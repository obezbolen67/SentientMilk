"""Starting, pausing, answering and recovering runs: turns, background tasks and subagents.

Turns run on their own thread, one at a time per session. Tasks queue for a small
pool of workers and live in their own session (``task-<id>``), so they never mix with
the chat that started them. One brain per home (brain.lock), so any run still marked
working at startup was interrupted by a crash or a restart.
"""

import concurrent.futures
import logging
import queue
import secrets
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from . import titles, transport
from .exceptions import BrainError
from .loop import ACTIVE, TERMINAL, VERIFY_PROMPT, Loop
from .toolkits import Attention

logger = logging.getLogger(__name__)

MAX_ACTION_IMAGES = 4
SUBAGENT_REPORT = 8_000  # characters, about 2,000 tokens
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
SUBAGENT_PROMPT = """## HELPER
You are a helper of another assistant, which gave you the goal below. You can only read. Investigate on
your own with your tools, then answer with a compact report (at most about 2,000 tokens): findings first,
with the exact paths, names, URLs and line numbers the other assistant needs. Do not ask questions."""


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

    def _lock(self, app: str, session: str) -> threading.Lock:
        with self._locks_guard:
            return self._session_locks.setdefault((app, session), threading.Lock())

    def _execute(self, run_id: int) -> None:
        run = self.store.run(run_id)
        with self._lock(run["app"], run["session"]):
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

    def _spawn(self, run_id: int) -> None:
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
        self._spawn(run_id)
        return run_id, listener

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
        self._spawn(run_id)
        return run_id

    def subagent(self, parent: dict, goal: str, toolkits: Optional[list] = None, mode: str = "readonly",
                 instructions: str = SUBAGENT_PROMPT) -> str:
        """Run a helper to the end on this thread and return its report."""
        options = {"input": [{"type": "text", "text": goal}], "goal": goal,
                   "profile": {"instructions": instructions, "toolkits": toolkits, "mode": mode,
                               "from_session": parent["session"], "signals": False}}
        model = self.brain.config.values()["light_model"]
        options["model"] = model
        run_id = self.store.add_run(parent["app"], "pending", "subagent", options, parent=parent["id"],
                                    status="working")
        self.store.update_run(run_id, session=f"agent-{run_id}")
        self.loop.execute(run_id)
        run = self.store.run(run_id)
        if run["status"] != "completed":
            message = (run["error"] or {}).get("message", run["status"])
            return f"The helper did not finish ({message})."
        report = run["result"]["reply"]
        return report if len(report) <= SUBAGENT_REPORT else report[:SUBAGENT_REPORT] + "\n[report cut]"

    def review(self, task: dict, report: str) -> str:
        """A separate, skeptical helper checks a task before it counts as done."""
        prompt = VERIFY_PROMPT.format(goal=task["options"]["goal"], report=report or "(no report)")
        toolkits = task["options"]["profile"].get("toolkits")
        return self.subagent(task, prompt, toolkits, mode="review", instructions="## REVIEWER\nCheck, do not fix.")

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
        if ctx.run["kind"] == "task":
            self.brain.notify(ctx.app, ctx.run["options"].get("parent_session") or ctx.session,
                              "task.input_required", {"task": ctx.run["id"], "question": question, "message": message})
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
            if not isinstance(images or [], list) or len(images or []) > MAX_ACTION_IMAGES:
                raise ValueError(f"images must be a list of at most {MAX_ACTION_IMAGES} data URLs")
            # stored at the size they are sent, like the images of a turn's input
            images = [transport.encode_image(transport.validate_image(url), transport.IMAGE) for url in images or []]
            self.store.add_event(run["app"], run["session"], run_id, "action_result",
                                 {"call_id": call_id, "result": result, "status": status, "images": images})
        if len(waiting) == 1 and run["status"] == "input_required":  # the last answer of a paused run
            self._spawn(run_id)  # a run still working sees the answer before it would pause

    def waiting(self, run_id: int) -> List[dict]:
        """The approvals and app actions a paused run still waits for."""
        events = self.store.run_events(run_id)
        done = {e["call_id"] for e in events if e["type"] == "tool"}
        # an action that asks first has two requests with one call id: the approval, then the action
        answered = {(e["call_id"], "approval" if e["type"] == "approval" else "action")
                    for e in events if e["type"] in ("approval", "action_result")}
        requests = [{"call_id": e["call_id"], "kind": e["type"].removesuffix("_request"), "name": e["name"],
                     "arguments": e["arguments"]}
                    for e in events if e["type"] in ("approval_request", "action_request") and e["call_id"] not in done]
        return [r for r in requests if (r["call_id"], r["kind"]) not in answered]

    def attention(self, run_id: int) -> Attention:
        """How a run hears at once that it is stopped or has a message (until it ends)."""
        with self._attention_lock:
            return self._attention.setdefault(run_id, Attention())

    def cancel(self, run_id: int, reason: str = "Cancelled.", now: bool = False) -> None:
        """Stop a run at once, its helpers with it: waits end, calls still running are left behind."""
        with self.pause_lock:  # a run about to wait for answers sees the flag, or is waiting already
            run = self.store.run(run_id)
            if not run or run["status"] in TERMINAL:
                return
            self.store.update_run(run_id, options={**run["options"], "cancel": reason})
        self.attention(run_id).stop()
        for helper in self.store.runs(app=run["app"], statuses=ACTIVE, limit=1000):
            if helper["parent"] == run_id:
                self.cancel(helper["id"], reason, now)
        if run["status"] == "input_required":  # the loop sees the flag and ends the run
            self._execute(run_id) if now else self._spawn(run_id)

    def steer(self, run_id: int, items: list) -> None:
        """A message for a run that works: it reaches the model at the next step, and waits inside tools end
        early. Approvals the run waits for are refused, as the user answered with a message. A run that has
        ended refuses it (``ended``): send it as a new turn."""
        with self.steer_lock:
            run = self.store.run(run_id)
            if not run or run["status"] in TERMINAL:
                raise BrainError("ended", "This turn has ended; send the message as a new turn", http_status=409)
            self.store.update_run(run_id, options={**run["options"], "steer": run["options"].get("steer", []) + items})
        self.attention(run_id).message()
        if run["status"] == "input_required":
            for request in self.waiting(run_id):
                if request["kind"] == "approval":
                    self.answer(run_id, call_id=request["call_id"], decision="deny",
                                reason="The user sent a message instead of answering.")

    def detach(self, run_id: int) -> None:
        """The app stops waiting for this turn; it reports through notifications like a task."""
        run = self.store.run(run_id)
        if not run or run["kind"] != "turn":
            raise ValueError(f"Run {run_id} is not a turn")
        self.store.update_run(run_id, options={**run["options"], "detached": True})

    # ============== Lifecycle ==============

    def compact(self, app: str, session: str) -> dict:
        """Sum up the whole session now, as a run of its own (after a turn of the session that runs)."""
        run_id = self.store.add_run(app, session, "compact", {})
        listener = self.brain.bus.subscribe(("run", run_id))
        try:
            self._spawn(run_id)
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

    def paused(self, run: dict) -> None:
        if run["kind"] == "task" or run["options"].get("detached"):
            self.brain.notify(run["app"], run["options"].get("parent_session") or run["session"],
                              "task.input_required", {"task": run["id"], "session": run["session"]})

    def finished(self, run: dict) -> None:
        with self._attention_lock:
            self._attention.pop(run["id"], None)
        if run["kind"] == "task":
            options, result = run["options"], run["result"] or {}
            parent = options.get("parent_session")
            message = (run["error"] or {}).get("message", "")
            if parent:
                self.brain.note(run["app"], parent,
                                f"Background task {run['id']} {run['status']}: {options['goal'][:300]}\n"
                                + (f"Report: {result.get('reply', '')[:3000]}" if run["status"] == "completed"
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

    def recover(self) -> None:
        for run in self.store.runs(statuses=("working", "queued"), limit=1000):
            if run["kind"] == "task":
                logger.info("Resuming task %s after a restart", run["id"])
                self.brain.note(run["app"], run["session"], "The brain restarted while you worked; continue.")
                self._spawn(run["id"])
            elif run["kind"] == "turn" and run["options"].get("input") is not None and \
                    not self.store.run_events(run["id"]):
                self._spawn(run["id"])  # never started: nothing was lost
            else:
                self.store.add_event(run["app"], run["session"], run["id"], "end",
                                     {"status": "failed", "reply": "", "signals": {}, "silent": False,
                                      "error": {"type": "interrupted", "message": "The brain stopped during this run"}})
                self.store.update_run(run["id"], status="failed",
                                      error={"type": "interrupted", "message": "The brain stopped during this run",
                                             "details": None, "http_status": None})

    def busy(self) -> bool:
        return bool(self.store.runs(statuses=("working", "queued"), limit=1))
