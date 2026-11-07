"""Agents: copies of the model with a fresh context, each doing one part of a job in the background.

An agent lives in a session of its own (``agent-<id>``, after its first run) and works in runs of kind
``agent``, each on its own thread, while the run that started it (a turn or a task: the lead) goes on. An
agent has the lead's whole profile: its toolkits, MCP servers, app actions, rules and model. What it knows
is the task the lead wrote. Agents get no agent tools: the lead is the one orchestrator.

A message to a working agent reaches it at its next step (steering) and answers its question (ask_lead).
A message to one that finished is a new run in the same session, so it goes on with all it knew.

What agents send the lead goes through one mailbox (``agent_mail``): reports, questions and progress
updates. Each reaches the lead's session exactly once (claimed in one transaction): from agents_wait, as a
note before the lead's next model call, or, when no run of that session goes on, as a note with
``agent.finished`` or ``agent.asked``, so the app can start a turn. Updates never wake the lead. Stopping
an agent deletes it: its session and its mail. Apps hear ``agent.updated`` when one starts, ends or is
stopped. See docs/architecture.md, 5.5.
"""

import json
import re
import threading
import time
from pathlib import Path
from typing import List, Optional

from .exceptions import BrainError
from .loop import ACTIVE
from .toolkits import STOPPED_BY_USER, ToolError
from .toolkits.todo import render as render_todo

AGENT_PROMPT = """## YOU ARE AN AGENT
The you that talks with the user (the lead) started you to do one part of a bigger job: the task in the
first message. You have the lead's tools and rules, and the user approves your changes as they approve
the lead's. Nobody watches you live.
- Stay within the task: other agents may be working on the other parts at the same time. Change only
  what your task covers.
- If the task is unclear or you need a decision that is not yours, ask the lead with ask_lead: it knows
  the whole conversation and can ask the user. Find out what you can by yourself first.
- For long work, keep a todo list with todo_write and note progress with task_progress at milestones:
  the lead reads your notes, and your context may be summed up during long work.
- Verify what you did before you report it.
- End with a compact report, findings first (at most about 2,000 tokens): the exact paths, names, URLs,
  line numbers and results that are needed. Put long output (data, drafts, code) in files and name them."""
MESSAGE = "[A message from the lead]\n{text}"
STEPS = 200  # as a task's
MAX_WORKING = 5  # at once per lead session; Anthropic's lead agent starts 3-5
OPEN_HOURS = 24  # an idle agent is deleted after this (the next start or brain start), and its name is free
REPORT_CHARS = 8_000  # about 2,000 tokens; the whole report goes to a file
WAIT_DEFAULT, WAIT_MAX = 600, 1800
ASK_WAIT = 1800  # seconds an agent waits for the lead's answer before it goes on by itself
SHOWN_STEPS, TASK_CHARS, RESULT_CHARS = 15, 150, 160
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
# working, asking (waits for the lead), waiting (for the user's approval), done, failed, stopped
STATUS = {"queued": "working", "working": "working", "input_required": "waiting", "completed": "done",
          "failed": "failed", "cancelled": "stopped"}


def duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"


def short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Agents:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self._lock = threading.Lock()  # starts: names and the cap

    # ============== Reading ==============

    def record(self, app: str, session: str) -> dict:
        return ((self.store.find_session(app, session) or {}).get("settings") or {}).get("agent") or {}

    def summary(self, app: str, session: str, record: Optional[dict] = None, only_open: bool = False) -> Optional[dict]:
        """What an agent is and does now; None for a session that is not an agent's (or, with ``only_open``,
        for one closed: stopped, or idle for a day)."""
        record = record if record is not None else self.record(app, session)
        runs = self.store.runs(app=app, session=session, limit=1)
        if not record or not runs:
            return None
        latest = runs[0]
        working = latest["status"] in ACTIVE
        is_open = not record.get("stopped") and (working or time.time() - latest["updated"] < OPEN_HOURS * 3600)
        if only_open and not is_open:
            return None
        status, activity = self._state(latest) if working else (STATUS.get(latest["status"], latest["status"]), "")
        reply = (latest["result"] or {}).get("reply", "") if latest["status"] == "completed" else ""
        return {
            "id": int(session.split("-", 1)[1]), "name": record["name"], "task": record["task"], "session": session,
            "parent": record["parent"], "run": latest["id"], "status": status, "working": working, "open": is_open,
            "step": self.store.count_events(latest["id"], "assistant"),
            "seconds": (time.time() if working else latest["updated"]) - latest["created"],
            "activity": activity, "report": reply, "error": (latest["error"] or {}).get("message", ""),
            "created": record.get("created"), "updated": latest["updated"],
        }

    def all(self, app: str, parent: str, only_open: bool = False) -> List[dict]:
        """The agents a session started, the newest first."""
        found = [self.summary(app, session, settings.get("agent") or {}, only_open)
                 for session, settings in self.store.child_sessions(app, parent)]
        return sorted([a for a in found if a], key=lambda a: a["id"], reverse=True)

    def open(self, app: str, parent: str) -> List[dict]:
        return self.all(app, parent, only_open=True)

    def find(self, app: str, parent: str, ref) -> dict:
        """An open agent of this session by name or id."""
        text = str(ref or "").strip().lstrip("#")
        mine = self.open(app, parent)
        found = next((a for a in mine if a["name"] == text or str(a["id"]) == text), None)
        if found is None:
            names = ", ".join(a["name"] for a in mine) or "none"
            raise ToolError(f"You have no agent {ref!r} (stopped agents and ones idle for {OPEN_HOURS} h are "
                            f"gone). Your agents: {names}.")
        return found

    def details(self, app: str, agent: dict) -> dict:
        """An agent's todo list, latest progress note and recent steps (call, arguments, status, result)."""
        session = agent["session"]
        steps = [{"name": e["name"], "arguments": e.get("arguments") or {}, "status": e["status"],
                  "result": short(e.get("content", ""), RESULT_CHARS)}
                 for e in self.store.events(app, session, types=("tool",))]
        progress = ""
        for run in self.store.runs(app=app, session=session, limit=20):
            path = Path(self.brain.home) / "runs" / str(run["id"]) / "progress.md"
            if path.exists():
                progress = path.read_text(encoding="utf-8").strip().split("\n## ")[-1].lstrip("# ")
                break
        todo = ((self.store.find_session(app, session) or {}).get("state") or {}).get("todo") or []
        return {**agent, "steps": steps, "progress": progress, "todo": todo}

    def _state(self, run: dict) -> tuple:
        """(status, what it does now) of a working run."""
        if run["status"] == "input_required":
            waiting = self.brain.runs.waiting(run["id"])
            asked = [request["name"] for request in waiting if request["kind"] == "approval"]
            if asked:
                return "waiting", f"waits for the user to allow {', '.join(asked)}"
            return "working", "the app runs " + (", ".join(request["name"] for request in waiting) or "an action")
        tail = self.store.run_tail(run["id"])
        done = {e["call_id"] for e in tail if e["type"] == "tool"}
        running = [e for e in tail if e["type"] == "tool_start" and e["call_id"] not in done]
        if not running:
            return "working", "thinking"
        assistant = next((e for e in tail if e["type"] == "assistant"), None)
        arguments = {c["id"]: (c.get("function") or {}).get("arguments", "")
                     for c in ((assistant or {}).get("message") or {}).get("tool_calls") or []}
        for event in running:
            if event["name"] == "ask_lead":
                try:
                    question = json.loads(arguments.get(event["call_id"]) or "{}").get("question", "")
                except ValueError:
                    question = ""
                return "asking", f"asks you: {short(question, 300)}"
        return "working", "; ".join(f"{e['name']} {short(arguments.get(e['call_id'], ''), 120)}".strip()
                                    for e in running)

    def describe(self, agent: dict) -> str:
        """One line about an agent, for the model."""
        head = f"- {agent['name']} (#{agent['id']}): {agent['status']}"
        if agent["working"]:
            head += f", step {agent['step']}, {duration(agent['seconds'])}. Now: {agent['activity']}"
        else:
            head += f" after {agent['step']} steps, {duration(agent['seconds'])}"
        return head + f". Task: {short(agent['task'], TASK_CHARS)}"

    def describe_details(self, app: str, agent: dict) -> str:
        found = self.details(app, agent)
        lines = [self.describe(agent)[2:], "Task: " + short(agent["task"], 1500)]
        if found["todo"]:
            lines.append("Todo:\n" + render_todo(found["todo"]))
        if found["progress"]:
            lines.append("Latest progress note: " + short(found["progress"], 1000))
        steps = found["steps"][-SHOWN_STEPS:]
        if steps:
            lines.append(f"Steps (the last {len(steps)} of {len(found['steps'])}):")
            lines += [f"- {s['name']} {short(json.dumps(s['arguments'], ensure_ascii=False), 120)} -> {s['status']}: "
                      f"{s['result']}" for s in steps]
        if agent["report"]:
            lines.append("Its report: " + short(agent["report"], 1500))
        elif agent["error"]:
            lines.append("Problem: " + agent["error"])
        return "\n".join(lines)

    # ============== Starting, messages, questions, stopping ==============

    def start(self, parent_run: dict, name, task) -> dict:
        name, task = str(name or "").strip(), str(task or "").strip()
        if not NAME.fullmatch(name):
            raise ToolError("The name must be 1-32 letters, digits, '-', '_' or '.', starting with a letter or "
                            "digit, e.g. tests or docs-research.")
        if not task:
            raise ToolError("The task is empty: say what the agent must do, with everything it needs.")
        app, parent = parent_run["app"], parent_run["session"]
        base = (parent_run["options"].get("profile") or {}).get("from_session") or parent  # a task works for a chat
        record = {"name": name, "parent": parent, "base": base, "task": task, "created": time.time()}
        with self._lock:
            self.sweep(app, parent)
            self._check_room(app, parent, name)
            run_id = self.store.add_run(app, "pending", "agent", {}, parent=parent_run["id"])
            session = f"agent-{run_id}"
            self.store.update_session(app, session, "settings", lambda s: {**s, "title": name, "agent": record})
            self.store.update_run(run_id, session=session, options=self._options(record, run_id, task))
        self.brain.runs.spawn(run_id)
        self._updated(app, parent, run_id, name, "working", run_id)
        return self.summary(app, session)

    def _check_room(self, app: str, parent: str, name: Optional[str] = None) -> None:
        mine = self.open(app, parent)
        if name and any(a["name"] == name for a in mine):
            raise ToolError(f"You have an agent called {name} already: send it a message with agent_message, "
                            "or pick another name.")
        working = [a for a in mine if a["working"]]
        if len(working) >= MAX_WORKING:
            raise ToolError(f"{len(working)} agents are working already (at most {MAX_WORKING} at once): wait "
                            "for one with agents_wait, or stop one.")

    def _options(self, record: dict, agent_id: int, text: str) -> dict:
        return {"input": [{"type": "text", "text": text}], "agent": agent_id, "parent_session": record["parent"],
                "goal": f"agent {record['name']}: {text}",  # what lists of background work show
                "max_steps": STEPS,
                "profile": {"instructions": AGENT_PROMPT, "from_session": record.get("base") or record["parent"],
                            "signals": False}}

    def message(self, parent_run: dict, ref, text) -> str:
        text = str(text or "").strip()
        if not text:
            raise ToolError("The message is empty.")
        app, parent = parent_run["app"], parent_run["session"]
        agent = self.find(app, parent, ref)
        item = [{"type": "text", "text": MESSAGE.format(text=text)}]
        if agent["working"]:
            try:  # its approvals wait for the user still: a message from the lead is not their answer
                self.brain.runs.steer(agent["run"], item, refuse_approvals=False)
                return f"Sent: {agent['name']} reads it at its next step (it answers its question, if it asked one)."
            except BrainError:
                pass  # it ended just now: the message is a new request then
        with self._lock:
            self._check_room(app, parent)
            record = self.record(app, agent["session"])
            run_id = self.store.add_run(app, agent["session"], "agent",
                                        self._options(record, agent["id"], item[0]["text"]), parent=parent_run["id"])
        self.brain.runs.spawn(run_id)
        self._updated(app, parent, agent["id"], agent["name"], "working", run_id)
        return f"Sent: {agent['name']} goes on with it, with all it knew. Collect its answer with agents_wait."

    def ask(self, ctx, question) -> str:
        """An agent asks the lead and waits for its message: the lead's next step (or agents_wait) has the
        question, or, with no run of the lead going on, the app hears agent.asked and starts one."""
        question = str(question or "").strip()
        if not question:
            raise ToolError("The question is empty.")
        run, app = ctx.run, ctx.app
        parent, agent = run["options"].get("parent_session"), run["options"].get("agent")
        name = self.record(app, ctx.session).get("name", "")
        self.store.post_mail(app, parent, agent, run["id"], "question",
                             f"Agent {name} (#{agent}) asks:\n{question}\nAnswer with agent_message; it waits for you.",
                             {"name": name, "question": question})
        self._updated(app, parent, agent, name, "asking", run["id"])
        if not self.brain.session_busy(app, parent):
            self.hand_over(app, parent)
        if ctx.pause(ASK_WAIT):
            stop = ctx.interruption()
            return stop if stop == STOPPED_BY_USER else "The lead answered: its message comes next."
        return (f"No answer came in {duration(ASK_WAIT)}: go on with your best judgment, and say in your report "
                "what you assumed.")

    def update(self, run: dict, note: str) -> None:
        """An agent's progress note, for the lead's next step; only its latest one waits."""
        record = self.record(run["app"], run["session"])
        agent = run["options"].get("agent")
        self.store.post_mail(run["app"], run["options"]["parent_session"], agent, run["id"], "update",
                             f"Update from agent {record.get('name', '?')} (#{agent}): {short(note, 1000)}",
                             {"name": record.get("name", "")})

    def stop(self, app: str, agent_id: int, by_user: bool = False) -> dict:
        """Stop an agent at once and delete it (its session and mail; a working one when its run ends)."""
        session = f"agent-{int(agent_id)}"
        record = self.record(app, session)
        if not record:
            raise ToolError(f"There is no agent {agent_id}.")
        self.store.update_session(app, session, "settings",
                                  lambda s: {**s, "agent": {**s.get("agent", {}), "stopped": True}}, create=False)
        self.store.delete_mail(app, agent=int(agent_id))
        working = self.store.runs(app=app, session=session, statuses=ACTIVE, limit=10)
        for run in working:
            self.brain.runs.cancel(run["id"], "The agent was stopped.")
        if not working:
            self._delete(app, session, int(agent_id))
        if by_user:
            self.brain.note(app, record["parent"], f"The user stopped your agent {record['name']} (#{agent_id}).")
        self._updated(app, record["parent"], int(agent_id), record["name"], "stopped", None)
        return {"id": int(agent_id), "name": record["name"], "status": "stopped"}

    def _delete(self, app: str, session: str, agent_id: int) -> None:
        self.store.delete_session(app, session)
        self.store.delete_mail(app, agent=agent_id)

    def sweep(self, app: Optional[str] = None, parent: Optional[str] = None) -> None:
        """Delete agents idle for a day (and stopped ones left behind): their names are free again."""
        cutoff = time.time() - OPEN_HOURS * 3600
        for app_, session, settings in self.store.agent_sessions(app, parent):
            latest = self.store.runs(app=app_, session=session, limit=1)
            if latest and latest[0]["status"] in ACTIVE:
                continue
            if not latest or latest[0]["updated"] < cutoff or (settings.get("agent") or {}).get("stopped"):
                self._delete(app_, session, int(session.split("-", 1)[1]))

    def wait(self, ctx, refs=None, timeout=WAIT_DEFAULT) -> str:
        """Until the named agents (or all working ones) are done, one asks something, the timeout passes or
        the user writes; then all the mail that came."""
        app, parent = ctx.app, ctx.session
        refs = refs if isinstance(refs, list) else ([refs] if refs else [])
        targets = [self.find(app, parent, ref) for ref in refs] or [a for a in self.open(app, parent) if a["working"]]
        sessions = {a["session"]: a["name"] for a in targets}
        deadline = time.time() + max(1, min(int(timeout or WAIT_DEFAULT), WAIT_MAX))
        interrupted = ""

        def working() -> List[str]:
            return [name for session, name in sessions.items()
                    if (self.store.runs(app=app, session=session, limit=1) or [{"status": "gone"}])[0]["status"]
                    in ACTIVE]
        while working() and not self.store.has_mail(app, parent, "question") and time.time() < deadline:
            if ctx.pause(min(0.5, max(0.0, deadline - time.time()))):
                interrupted = ctx.interruption()
                break
        parts = [f"{interrupted} The wait ended early."] if interrupted else []
        parts += [mail["text"] for mail in self.claim(app, parent)]
        still = working()
        if still:
            parts.append(f"Still working: {', '.join(still)}. Wait again, or go on: their reports come to you "
                         "when they finish.")
        if not parts:
            return "None of your agents is working, and no report is waiting." if not targets else "No new reports."
        return "\n\n".join(parts)

    # ============== Mail to the lead ==============

    def claim(self, app: str, parent: str) -> List[dict]:
        """The mail waiting for this session; each piece only once. A stopped agent's says nothing more."""
        mail = self.store.claim_mail(app, parent)
        alive = {}
        for piece in mail:
            if piece["agent"] not in alive:
                record = self.record(app, f"agent-{piece['agent']}")
                alive[piece["agent"]] = bool(record) and not record.get("stopped")
        return [piece for piece in mail if alive[piece["agent"]]]

    def report(self, run: dict) -> str:
        record = self.record(run["app"], run["session"])
        who = f"Agent {record.get('name', '?')} (#{run['options'].get('agent')})"
        if run["status"] == "cancelled":
            return f"{who} was stopped before it finished."
        if run["status"] != "completed":
            return f"{who} failed: {(run['error'] or {}).get('message', 'unknown error')}"
        text = (run["result"] or {}).get("reply", "").strip() or "(It finished without a report.)"
        if len(text) > REPORT_CHARS:
            path = Path(self.brain.home) / "runs" / str(run["id"]) / "report.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            text = text[:REPORT_CHARS] + f"\n[Report cut. The whole report is in {path}.]"
        return f"{who} finished:\n{text}"

    def take_mail(self, run: dict) -> None:
        """Before a model call of a run: what its session's agents sent meanwhile, as a note."""
        mail = self.claim(run["app"], run["session"])
        if mail:
            self.brain.note(run["app"], run["session"], "\n\n".join(piece["text"] for piece in mail))

    def hand_over(self, app: str, parent: str) -> None:
        """Mail nobody collected while no run of the session goes on: a note, and news for the app."""
        mail = self.claim(app, parent)
        if not mail:
            return
        self.brain.note(app, parent, "\n\n".join(piece["text"] for piece in mail))
        news = [p for p in mail if p["kind"] == "report" and p["data"].get("status") != "cancelled"]  # a stop is no news
        if news:
            self.brain.notify(app, parent, "agent.finished", {"agents": [
                {"agent": p["agent"], "name": p["data"].get("name", ""), "status": p["data"]["status"], "run": p["run"]}
                for p in news]})
        for piece in mail:
            if piece["kind"] == "question":
                self.brain.notify(app, parent, "agent.asked", {"agent": piece["agent"], "run": piece["run"],
                                                               "name": piece["data"].get("name", ""),
                                                               "question": piece["data"].get("question", "")})

    def _updated(self, app: str, parent: str, agent: int, name: str, status: str, run: Optional[int]) -> None:
        self.brain.notify(app, parent, "agent.updated", {"agent": agent, "name": name, "status": status, "run": run})

    # ============== Lifecycle ==============

    def run_ended(self, run: dict) -> None:
        if run["kind"] == "agent":
            app, parent, agent = run["app"], run["options"].get("parent_session"), run["options"].get("agent")
            if not parent:
                return
            record = self.record(app, run["session"])
            if record.get("stopped") or not self.store.has_session(app, parent):  # stopped, or its chat was deleted
                if not self.store.runs(app=app, session=run["session"], statuses=ACTIVE, limit=1):
                    self._delete(app, run["session"], agent)
                return
            self.store.post_mail(app, parent, agent, run["id"], "report", self.report(run),
                                 {"name": record.get("name", ""), "status": run["status"]})
            self._updated(app, parent, agent, record.get("name", ""), STATUS.get(run["status"], run["status"]),
                          run["id"])
            if not self.brain.session_busy(app, parent):  # else its next step or its end takes it
                self.hand_over(app, parent)
        elif run["kind"] in ("turn", "task"):
            self.hand_over(run["app"], run["session"])

    def recover(self) -> None:
        """After a restart: old agents go; mail that came with no run of its session going on is handed over."""
        self.sweep()
        for app, parent in self.store.mail_parents():
            if not self.brain.session_busy(app, parent):
                self.hand_over(app, parent)

    def delete_for(self, app: str, parent: str) -> None:
        """Its chat was deleted (first): idle agents go now; working ones stop and go when their run ends
        (run_ended), so no run loses its row while it still works."""
        self.store.delete_mail(app, parent=parent)
        for session, settings in self.store.child_sessions(app, parent):
            working = self.store.runs(app=app, session=session, statuses=ACTIVE, limit=10)
            for run in working:
                self.brain.runs.cancel(run["id"], "Its chat was deleted.")
            if not working:
                self._delete(app, session, int(session.split("-", 1)[1]))
