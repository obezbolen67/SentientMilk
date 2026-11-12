"""Starting, pausing, answering and recovering runs: turns, background tasks, agents and reviewers.

Turns and agents run on their own thread, one run at a time per session. Tasks queue for
a small pool of workers. Tasks and agents live in their own sessions (``task-<id>``,
``agent-<id>``), so they never mix with the chat that started them; agents.py has the rest
of agents. One brain per home (brain.lock), so any run still marked working at startup was
interrupted by a crash or a restart.
"""

import concurrent.futures
import logging
import queue
import secrets
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import context, mentions, titles, transport
from . import signals as signal_format
from .exceptions import BrainError
from .loop import ACTIVE, TERMINAL, VERIFY_PROMPT, Loop
from .toolkits import Attention

logger = logging.getLogger(__name__)

REPORT_CHARS = 8_000  # about 2,000 tokens; a longer report is shown in part, the whole of it in a file


def _stored(items: List[dict]) -> dict:
    """What an input event keeps for apps besides its text: its mentions, and the skills the user started."""
    started = [item["name"] for item in items if item["type"] == "skill"]
    return {**mentions.stored(items), **({"skills": started} if started else {})}


def whole_report(home, run_id: int, text: str) -> str:
    """A report as it is, or when long its start and the file with all of it."""
    if len(text) <= REPORT_CHARS:
        return text
    path = Path(home) / "runs" / str(run_id) / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text[:REPORT_CHARS] + f"\n[Report cut. The whole report is in {path}.]"


TASK_PROMPT = """## BACKGROUND TASK
You work on this task on your own: nobody watches live and nobody can answer questions until you finish.
Goal:
{goal}

How to work:
- For work with several parts, write a plan with todo_write first; then do one item at a time and mark it.
- After each meaningful step, record what you did and what comes next with task_progress. Your context may
  be summarized or reset during long work: the plan and the progress notes are what you see then.
- Verify each part (run it, test it, read the result) before you mark it done.
- Do not stop until the goal is met or you are truly blocked.
- Finish with a short report: what you did, what you verified, and anything left open."""


class Bus:
    """Live events for whoever listens: a run's progress, an app's notifications."""

    def __init__(self):
        self._listeners: Dict[tuple, List[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, key: tuple) -> queue.Queue:
        listener: queue.Queue = queue.Queue()
        with self._lock:
            self._listeners[key].append(listener)
        return listener

    def unsubscribe(self, key: tuple, listener: queue.Queue) -> None:
        with self._lock:
            if listener in self._listeners.get(key, []):
                self._listeners[key].remove(listener)
            if not self._listeners.get(key):
                self._listeners.pop(key, None)

    def publish(self, key: tuple, event: dict) -> None:
        with self._lock:
            listeners = list(self._listeners.get(key, []))
        for listener in listeners:
            listener.put(event)


class Runs:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self.loop = Loop(brain)
        self._session_locks: Dict[Tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._scheduled_followers = set()  # one live action consumer per occurrence, within this single brain
        self._tasks: queue.Queue = queue.Queue()
        self._workers: List[threading.Thread] = []
        self._questions: Dict[Tuple[int, str], concurrent.futures.Future] = {}
        # An app may answer while the run still runs the step's other tools; deciding to pause and
        # taking an answer under one lock means an answer is never lost and never resumes a run twice.
        self.pause_lock = threading.Lock()
        self.steer_lock = threading.Lock()  # messages for a run, and its end
        self._attention: Dict[int, Attention] = {}
        self._attention_lock = threading.Lock()

    def start(self) -> None:
        self.recover()
        for index in range(self.brain.config.values()["task_workers"]):
            worker = threading.Thread(target=self._work, name=f"task-worker-{index}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def stop(self) -> None:
        for _ in self._workers:
            self._tasks.put(None)

    def session_lock(self, app: str, session: str) -> threading.Lock:
        """Held while a run of the session runs (and while it is rewound): one at a time."""
        with self._locks_guard:
            return self._session_locks.setdefault((app, session), threading.Lock())

    def _execute(self, run_id: int) -> None:
        run = self.store.run(run_id)
        with self.session_lock(run["app"], run["session"]):
            self.loop.execute(run_id)

    def _work(self) -> None:
        while True:
            run_id = self._tasks.get()
            if run_id is None:
                return
            try:
                self._execute(run_id)
            except Exception:
                logger.exception("Task %s crashed its worker step", run_id)

    def spawn(self, run_id: int) -> None:
        run = self.store.run(run_id)
        self.store.update_run(run_id, status="queued")
        if run["kind"] == "task":
            self._tasks.put(run_id)
        else:
            threading.Thread(target=self._execute, args=(run_id,), name=f"run-{run_id}", daemon=True).start()

    # ============== Starting ==============

    def start_turn(self, app: str, session: str, items: list, context: dict, reply: str = "required",
                   subscribe: bool = True, max_steps: Optional[int] = None):
        """A new turn; a turn of this session still waiting for answers is given up first."""
        for waiting in self.store.runs(app=app, kind="turn", statuses=("input_required",)):
            if waiting["session"] == session:  # ended here, so its end is logged before the new turn
                self.cancel(waiting["id"], reason="The user moved on without answering.", now=True)
        options = {"input": items, "context": context, "reply": reply}
        if max_steps:
            options["max_steps"] = int(max_steps)
        run_id = self.store.add_run(app, session, "turn", options)
        listener = self.brain.bus.subscribe(("run", run_id)) if subscribe else None
        self.spawn(run_id)
        return run_id, listener

    def claim_scheduled_stream(self, occurrence: int) -> None:
        with self._locks_guard:
            if occurrence in self._scheduled_followers:
                raise BrainError('busy', 'This scheduled occurrence already has an app connection', http_status=409)
            self._scheduled_followers.add(occurrence)

    def release_scheduled_stream(self, app: str, occurrence: int) -> None:
        with self._locks_guard:
            self._scheduled_followers.discard(occurrence)
        found = self.store.occurrence(app, occurrence)
        if found and found['status'] == 'started' and not self.brain.stopping.is_set():
            self.brain.notify(app, found['session'], 'schedule.ready', {'occurrence': occurrence,
                              'schedule': found['schedule'], 'session': found['session']})

    def scheduled_pending(self, app: str) -> list:
        with self._locks_guard:
            busy = set(self._scheduled_followers)
        return [item for item in self.store.occurrences(app, pending=True) if item['id'] not in busy
                and (item['status'] == 'started' or not self.brain.session_busy(app, item['session']))]

    def start_scheduled_turn(self, app: str, session: str, occurrence: int, context: dict,
                             max_steps: Optional[int] = None):
        found = self.store.occurrence(app, occurrence)
        if found is None or found['session'] != session:
            raise BrainError('not_found', 'No scheduled occurrence belongs to this app and session', http_status=404)
        try:
            run_id, created = self.store.start_scheduled_run(app, session, occurrence, context, max_steps)
        except ValueError as exc:
            raise BrainError('schedule_unavailable', str(exc), http_status=409) from exc
        listener = self.brain.bus.subscribe(('run', run_id))
        try:
            run = self.store.run(run_id)
            if created or run['status'] == 'queued':
                self.spawn(run_id)
            elif run['status'] in ('working', 'input_required'):
                actions = {a['name']: a for a in self.brain.profile(app, session)['actions']}
                for waiting in self.waiting(run_id):
                    if waiting['kind'] == 'action' and not actions.get(waiting['name'], {}).get('readonly'):
                        self.answer(run_id, waiting['call_id'], result='The app connection ended before this action '
                            'returned a result. It may or may not have happened. Inspect its effect before repeating it.',
                            status='error')
        except Exception:
            self.brain.bus.unsubscribe(('run', run_id), listener)
            raise
        return run_id, listener, not created

    def start_task(self, app: str, parent_session: Optional[str], goal: str, *, toolkits: Optional[list] = None,
                   verify: bool = False, allow: Optional[list] = None, context: str = "compact",
                   max_steps: Optional[int] = None, parent: Optional[int] = None, cwd: Optional[str] = None) -> int:
        if context not in ("compact", "reset"):
            raise ValueError("context must be compact or reset")
        options = {"goal": goal, "parent_session": parent_session, "verify": verify, "context_mode": context,
                   "input": [{"type": "text", "text": goal}],
                   "profile": {"instructions": TASK_PROMPT.format(goal=goal), "toolkits": toolkits,
                               "allow": allow or [], "from_session": parent_session, "cwd": cwd}}
        if max_steps:
            options["max_steps"] = int(max_steps)
        run_id = self.store.add_run(app, "pending", "task", options, parent=parent)
        self.store.update_run(run_id, session=f"task-{run_id}")
        self.brain.notify(app, parent_session, "task.updated", {"task": run_id, "status": "queued", "goal": goal})
        self.spawn(run_id)
        return run_id

    def subagent(self, parent: dict, goal: str, toolkits: Optional[list], instructions: str) -> str:
        """Run a helper to its end and return its report (the reviewer of a task). It has its parent's tools,
        folders and permissions: what needs approval is asked (in bypass the app allows it), and this waits.
        shortcut: the parent's worker waits with it; review on its own if waits for answers starve the workers."""
        own = parent["options"].get("profile") or {}  # it works where its parent does: folders and allowed calls
        options = {"input": [{"type": "text", "text": goal}], "goal": goal,
                   "profile": {"instructions": instructions, "toolkits": toolkits, "signals": False,
                               "from_session": own.get("from_session") or parent["session"], "cwd": own.get("cwd"),
                               "allow": own.get("allow") or []}}
        model = self.brain.config.values()["light_model"]
        options["model"] = model
        run_id = self.store.add_run(parent["app"], "pending", "subagent", options, parent=parent["id"],
                                    status="working")
        self.store.update_run(run_id, session=f"agent-{run_id}")
        self.loop.execute(run_id)
        while (run := self.store.run(run_id))["status"] not in TERMINAL:  # it waits for answers, then goes on
            time.sleep(0.2)
        if run["status"] != "completed":
            message = (run["error"] or {}).get("message", run["status"])
            return f"The helper did not finish ({message})."
        return whole_report(self.brain.home, run_id, run["result"]["reply"])

    def review(self, task: dict, report: str) -> str:
        """A separate, skeptical helper checks a task before it counts as done."""
        prompt = VERIFY_PROMPT.format(goal=task["options"]["goal"], report=report or "(no report)")
        toolkits = task["options"]["profile"].get("toolkits")
        return self.subagent(task, prompt, toolkits, instructions="## REVIEWER\nCheck, do not fix.")

    # ============== Answers and cancelling ==============

    def ask_question(self, ctx, source: str, message: str, schema) -> concurrent.futures.Future:
        """A tool (an MCP server) asks the user something while it runs; answered through answer()."""
        question = "q" + secrets.token_hex(4)
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._questions[(ctx.run["id"], question)] = future
        schema = schema.model_dump(exclude_none=True) if hasattr(schema, "model_dump") else schema
        data = {"question": question, "call_id": ctx.call_id, "source": source, "message": message, "schema": schema}
        self.store.add_event(ctx.app, ctx.session, ctx.run["id"], "question_request", data)
        ctx.emit({"type": "question.requested", **data})
        if ctx.run["kind"] in ("task", "agent"):
            self.paused(ctx.run, {"question": question, "message": message})
        return future

    def answer(self, run_id: int, call_id: str = "", decision: Optional[str] = None, reason: str = "",
               result=None, status: str = "ok", question: Optional[str] = None, action: str = "decline",
               content: Optional[dict] = None, images: Optional[list] = None) -> None:
        if question:
            future = self._questions.pop((run_id, question), None)
            if future is None:
                raise ValueError(f"Run {run_id} is not waiting for question {question}")
            if action not in ("accept", "decline", "cancel"):
                raise ValueError("action must be accept, decline or cancel")
            run = self.store.run(run_id)
            self.store.add_event(run["app"], run["session"], run_id, "question_answer",
                                 {"question": question, "action": action, "content": content})
            future.set_result({"action": action, "content": content})
            return
        with self.pause_lock:
            self._answer(run_id, call_id, decision, reason, result, status, images)

    def _answer(self, run_id: int, call_id: str, decision: Optional[str], reason: str, result, status: str,
                images: Optional[list]) -> None:
        run = self.store.run(run_id)
        if not run or run["status"] not in ("working", "input_required"):
            raise ValueError(f"Run {run_id} is not waiting for an answer")
        waiting = {request["call_id"]: request for request in self.waiting(run_id)}
        if call_id not in waiting:
            raise ValueError(f"Run {run_id} is not waiting for call {call_id}")
        if waiting[call_id]["kind"] == "approval":
            if decision not in ("allow", "always", "deny"):
                raise ValueError("decision must be allow, always or deny")
            self.store.add_event(run["app"], run["session"], run_id, "approval",
                                 {"call_id": call_id, "decision": decision, "reason": str(reason or "")[:2000]})
        else:
            if status not in ("ok", "error"):
                raise ValueError("status must be ok or error")
            if not isinstance(images or [], list):
                raise ValueError("images must be a list of data URLs")
            # stored as the model sees them, like the images of a turn's input: an app that fits them to
            # image_pixels (the action request says it) has them kept as it sent them, so its points stay exact
            pixels = self.brain.config.values()["image_pixels"]
            images = [transport.encode_image(transport.validate_image(url), pixels) for url in images or []]
            self.store.add_event(run["app"], run["session"], run_id, "action_result",
                                 {"call_id": call_id, "result": result, "status": status, "images": images})
        attention = self.attention(run_id)
        attention.answer()  # a run that waits in its own thread (await_answer) goes on there
        if len(waiting) == 1 and run["status"] == "input_required" and not attention.held:
            self.spawn(run_id)  # the last answer of a paused run; a run still working sees it before it pauses

    def waiting(self, run_id: int) -> List[dict]:
        """The approvals and app actions a paused run still waits for."""
        events = self.store.run_events(run_id)
        done = {e["call_id"] for e in events if e["type"] == "tool"}
        # an action that asks first has two requests with one call id: the approval, then the action
        answered = {(e["call_id"], "approval" if e["type"] == "approval" else "action")
                    for e in events if e["type"] in ("approval", "action_result")}
        requests = [{"call_id": e["call_id"], "kind": e["type"].removesuffix("_request"), "name": e["name"],
                     "arguments": e["arguments"], **({"always_ask": True} if e.get("always_ask") else {})}
                    for e in events if e["type"] in ("approval_request", "action_request") and e["call_id"] not in done]
        return [r for r in requests if (r["call_id"], r["kind"]) not in answered]

    def attention(self, run_id: int) -> Attention:
        """How a run hears at once that it is stopped or has a message (until it ends)."""
        with self._attention_lock:
            return self._attention.setdefault(run_id, Attention())

    def cancel(self, run_id: int, reason: str = "Cancelled.", now: bool = False) -> None:
        """Stop a run at once, and its helpers with it (a task's reviewer): waits end, calls still running are
        left behind. Not the agents it started or messaged: they are work of their own that goes on and reports
        to the session (Agents.stop stops one)."""
        with self.pause_lock:  # a run about to wait for answers sees the flag, or is waiting already
            run = self.store.run(run_id)
            if not run or run["status"] in TERMINAL:
                return
            self.store.update_run_options(run_id, lambda options: {**options, "cancel": reason})
        attention = self.attention(run_id)
        attention.stop()
        for helper in self.store.runs(app=run["app"], statuses=ACTIVE, limit=1000):
            if helper["parent"] == run_id and helper["kind"] != "agent":
                self.cancel(helper["id"], reason, now)
        if run["status"] == "input_required" and not attention.held:  # the loop sees the flag and ends the run
            self._execute(run_id) if now else self.spawn(run_id)  # (one waiting in its thread just woke)

    def steer(self, run_id: int, items: list, refuse_approvals: bool = True) -> None:
        """A message for a run that works: it reaches the model at the next step, and waits inside tools end
        early. Approvals the run waits for are refused, as the user answered with a message (not when the
        message is from the run that started an agent: the user has yet to answer). A run that has ended
        refuses it (``ended``): send it as a new turn."""
        with self.steer_lock:
            run = self.store.run(run_id)
            if not run or run["status"] in TERMINAL or run["options"].get("sealed"):  # sealed: it is ending
                raise BrainError("ended", "This turn has ended; send the message as a new turn", http_status=409)
            self.store.update_run_options(run_id, lambda options: {**options, "steer": options.get("steer", []) + items})
        self.attention(run_id).message()
        if run["status"] == "input_required" and refuse_approvals:
            for request in self.waiting(run_id):
                if request["kind"] == "approval":
                    self.answer(run_id, call_id=request["call_id"], decision="deny",
                                reason="The user sent a message instead of answering.")

    def detach(self, run_id: int) -> None:
        """The app stops waiting for this turn; it reports through notifications like a task."""
        run = self.store.run(run_id)
        if not run or run["kind"] != "turn":
            raise ValueError(f"Run {run_id} is not a turn")
        self.store.update_run_options(run_id, lambda options: {**options, "detached": True})

    # ============== The run protocol: what every engine keeps (Loop; a super agent's Claude Code) ==============

    def emitter(self, run_id: int) -> Callable[[dict], None]:
        def emit(event: dict) -> None:
            self.brain.bus.publish(("run", run_id), {"run": run_id, **event})
        return emit

    def log_input(self, run: dict, profile: dict, emit) -> None:
        """The run's input, logged once; apps hear its event id (``input``), the place to return to (rewind.py)."""
        options = run["options"]
        if options.get("input") is None or any(e["type"] == "input" for e in self.store.run_events(run["id"])):
            return
        reminders = []
        if profile["signals"] and run["kind"] == "turn":
            reminders.append(signal_format.FORMAT_REMINDER)
        if options.get("reply") == "optional":
            reminders.append(signal_format.OPTIONAL_REPLY)
        items = self.brain.skills.expand(mentions.resolve(self.brain, run["app"], run["session"], options["input"]))
        content, display = context.input_content(items, options.get("context") or {}, reminders=reminders)
        logged = self.store.add_event(run["app"], run["session"], run["id"], "input",
                                      {"content": content, "display": display, **_stored(items)})
        self.store.update_run_options(run["id"], lambda now: {**now, "input": None})  # the event keeps it
        emit({"type": "input", "id": logged["id"], "text": display})

    def take_messages(self, run: dict, emit) -> List[dict]:
        """Messages sent while the run worked (steering), logged as its input before it goes on: the input
        events logged (none when nothing came)."""
        with self.steer_lock:
            items = self.store.run(run["id"])["options"].get("steer") or []
            if items:
                self.store.update_run_options(run["id"], lambda options: {**options, "steer": []})
            self.attention(run["id"]).settle()
        if not items:
            return []
        items = self.brain.skills.expand(mentions.resolve(self.brain, run["app"], run["session"], items))
        content, display = context.input_content(items, {}, reminders=[])
        logged = self.store.add_event(run["app"], run["session"], run["id"], "input",
                                      {"content": content, "display": display, **_stored(items)})
        emit({"type": "steered", "text": display or "", "id": logged["id"]})
        return [logged]

    def ask(self, run: dict, kind: str, call_id: str, name: str, arguments: dict, emit,
            always_ask: bool = False) -> None:
        """Ask for a call: the user's ``approval`` or the app's ``action``. ``always_ask``: the user must answer,
        even in an app that allows everything on its own."""
        request = {"call_id": call_id, "name": name, "arguments": arguments,
                   **({"always_ask": True} if always_ask else {}),
                   # an app's pictures fitted to what the model sees reach it as they are: their points stay exact
                   **({"image_pixels": self.brain.config.values()["image_pixels"]} if kind == "action" else {})}
        self.store.add_event(run["app"], run["session"], run["id"], f"{kind}_request", request)
        emit({"type": f"{kind}.requested", **request})

    def await_answer(self, run: dict, call_id: str, emit) -> Optional[dict]:
        """For an engine that cannot leave its thread while it waits (a super agent: its Claude Code lives on):
        the answer to the approval asked for ``call_id``, or None once the run is stopped. The run shows as
        waiting meanwhile and the app hears it as it hears any paused run; the answer wakes it here (no thread
        is started for it), and nothing is read until something comes."""
        attention, paused, answer = self.attention(run["id"]), False, None
        attention.held = True
        try:
            while not attention.stopped.is_set():
                attention.answered.clear()  # first: an answer from now on wakes the wait below
                with self.pause_lock:  # an answer and the pause never cross
                    answer = next((e for e in self.store.run_events(run["id"])
                                   if e["type"] == "approval" and e["call_id"] == call_id), None)
                    if answer is None and not paused:
                        self.store.update_run(run["id"], status="input_required")
                if answer is not None:
                    break
                if not paused:
                    emit({"type": "paused", "status": "input_required"})
                    self.paused(self.store.run(run["id"]))
                    paused = True
                attention.answered.wait()
        finally:
            attention.held = False
        if attention.stopped.is_set():
            return None
        if paused:
            self.store.update_run(run["id"], status="working")
        return answer

    def seal(self, run: dict) -> bool:
        """The run is about to end: from now on a message to it is refused (``ended``: it starts anew, as an
        agent's next run or the next turn). False, and nothing sealed, when messages came that a run other than
        a turn must read first (an app sends a turn's own again: they come back in its result, unread)."""
        with self.steer_lock:
            if run["kind"] != "turn" and self.store.run(run["id"])["options"].get("steer"):
                return False
            self.store.update_run_options(run["id"], lambda options: {**options, "sealed": True})
        return True

    def end(self, run: dict, status: str, emit, reply: str = "", signals: Optional[dict] = None,
            silent: bool = False, error: Optional[BrainError] = None, extra: Optional[dict] = None) -> None:
        store = self.store
        if error and run['options'].get('occurrence'):
            reply = 'This scheduled task could not finish: ' + error.message
        result = {"reply": reply, "signals": signals or {}, "silent": silent, **(extra or {})}
        with self.steer_lock:  # a message that came too late goes back to the app, unread
            unread = store.run(run["id"])["options"].get("steer") or []
            if unread:
                result["unread"] = unread
            store.add_event(run["app"], run["session"], run["id"], "end",
                            {"status": status, **result, "error": error.as_dict() if error else None})
            self.brain.agents.ending({**run, "status": status, "result": result,
                                      "error": error.as_dict() if error else None})
            store.update_run(run["id"], status=status, result=result, error=error.as_dict() if error else None)
        final = store.run(run["id"])
        if error:
            emit({"type": "error", "status": status, "error": error.as_dict()})
        else:
            emit({"type": "done", "status": status, **result, "usage": final["usage"]})
        self.finished(final)

    # ============== Lifecycle ==============

    def compact(self, app: str, session: str) -> dict:
        """Sum up the whole session now, as a run of its own (after a turn of the session that runs)."""
        run_id = self.store.add_run(app, session, "compact", {})
        listener = self.brain.bus.subscribe(("run", run_id))
        try:
            self.spawn(run_id)
            while True:
                event = listener.get()
                if event["type"] in ("done", "error"):
                    break
        finally:
            self.brain.bus.unsubscribe(("run", run_id), listener)
        if event["type"] == "error":
            error = event["error"]
            raise BrainError(error["type"], error["message"], error.get("details"), error.get("http_status"))
        return {"run": run_id, "compacted": event["compacted"], "before": event["before"], "after": event["after"]}

    def paused(self, run: dict, extra: Optional[dict] = None) -> None:
        """A run nobody watches waits for the user: the app hears it (and asks)."""
        parent = run["options"].get("parent_session") or run["session"]
        if run["kind"] == "agent":
            name = self.brain.agents.record(run["app"], run["session"]).get("name", "")
            self.brain.notify(run["app"], parent, "agent.input_required",
                              {"agent": run["options"].get("agent"), "name": name, "run": run["id"],
                               "session": run["session"], **(extra or {})})
        elif run["kind"] == "subagent":  # a task's reviewer: the app answers it like the task
            self.brain.notify(run["app"], run["options"]["profile"].get("from_session") or run["session"],
                              "task.input_required", {"task": run["parent"], "run": run["id"],
                                                      "session": run["session"], "name": "reviewer"})
        elif run["kind"] == "task" or run["options"].get("detached"):
            self.brain.notify(run["app"], parent, "task.input_required",
                              {"task": run["id"], "session": run["session"], **(extra or {})})

    def finished(self, run: dict) -> None:
        with self._attention_lock:
            self._attention.pop(run["id"], None)
        for key in [key for key in list(self._questions) if key[0] == run["id"]]:  # nobody is left to answer
            future = self._questions.pop(key, None)
            if future and not future.done():
                future.set_result({"action": "cancel", "content": None})
        if run["kind"] == "task" and not run["options"].get("quiet"):  # quiet: a return stopped it
            options, result = run["options"], run["result"] or {}
            parent = options.get("parent_session")
            message = (run["error"] or {}).get("message", "")
            if parent:
                self.brain.note(run["app"], parent,
                                f"Background task {run['id']} {run['status']}: {options['goal'][:300]}\n"
                                + (f"Report: {whole_report(self.brain.home, run['id'], result.get('reply', ''))}"
                                   if run["status"] == "completed"
                                   else f"Problem: {message}"))
            self.brain.notify(run["app"], parent, f"task.{run['status']}",
                              {"task": run["id"], "goal": options["goal"], "reply": result.get("reply", ""),
                               "error": run["error"]})
            self.brain.journal.request(run["app"], run["session"])
        elif run["kind"] == "turn" and run["options"].get("detached"):
            self.brain.notify(run["app"], run["session"], f"task.{run['status']}",
                              {"run": run["id"], "reply": (run["result"] or {}).get("reply", ""),
                               "error": run["error"]})
        if run["kind"] == "turn" and run["status"] == "completed":
            titles.request(self.brain, run["app"], run["session"])
        if run['options'].get('occurrence'):
            self.brain.notify(run['app'], run['session'], 'schedule.updated', {
                'schedule': run['options']['schedule'], 'occurrence': run['options']['occurrence'],
                'status': run['status']})
        for pending in self.scheduled_pending(run['app']):
            if pending['session'] == run['session'] and pending['status'] == 'pending':
                self.brain.notify(run['app'], run['session'], 'schedule.ready', {'occurrence': pending['id'],
                                  'schedule': pending['schedule'], 'session': run['session']})
                self.brain.scheduler.wake()  # the brain starts it itself for an app that does not call back
        self.brain.agents.run_ended(run)

    def recover(self) -> None:
        waiting_reviewers = self.store.runs(kind="subagent", statuses=("input_required",), limit=1000)
        waiting_supers = [run for run in self.store.runs(kind="agent", statuses=("input_required",), limit=1000)
                          if run["options"].get("super")]
        for run in waiting_supers:  # its Claude Code went with the brain: what it asked goes too (it asks again)
            for request in self.waiting(run["id"]):
                self.store.add_event(run["app"], run["session"], run["id"], "tool", {
                    "call_id": request["call_id"], "name": request["name"], "arguments": request["arguments"],
                    "content": "The brain restarted before the user answered; Claude asks again.", "status": "error"})
        for run in self.store.runs(statuses=("working", "queued"), limit=1000) + waiting_reviewers + waiting_supers:
            if run["kind"] in ("task", "agent") or run['options'].get('occurrence'):
                logger.info("Resuming %s %s after a restart", run["kind"], run["id"])
                self.brain.note(run["app"], run["session"], "The brain restarted while you worked; continue.")
                self.spawn(run["id"])
            elif run["kind"] == "turn" and run["options"].get("input") is not None and \
                    not self.store.run_events(run["id"]):
                self.spawn(run["id"])  # never started: nothing was lost
            else:
                self.store.add_event(run["app"], run["session"], run["id"], "end",
                                     {"status": "failed", "reply": "", "signals": {}, "silent": False,
                                      "error": {"type": "interrupted", "message": "The brain stopped during this run"}})
                self.store.update_run(run["id"], status="failed",
                                      error={"type": "interrupted", "message": "The brain stopped during this run",
                                             "details": None, "http_status": None})
        self.brain.agents.recover()  # reports that ended with nobody there to take them

    def busy(self) -> bool:
        return bool(self.store.runs(statuses=("working", "queued"), limit=1))
