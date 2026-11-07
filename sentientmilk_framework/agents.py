"""Agents: copies of the model with a fresh context, each doing one part of a job in the background.

An agent lives in a session of its own (``agent-<id>``, after its first run) and works in runs of kind
``agent``, each on its own thread, while the run that started it (a turn or a task: its parent) goes on.
A message to a working agent reaches it at its next step (steering). A message to one that finished is a
new run in the same session, so it goes on with all it knew. Read agents get the read-only tools and the
light model; write agents get the parent's tools and model, and their changes ask the user. Agents get
no agent tools (no nesting) and no app actions (the app's screen and input have one user at a time).

Each report reaches the parent session exactly once (``claim``, under one lock): from agents_wait, at
the parent's next model call (as a note), or, when no run of the parent session is going on, as a note
and an ``agent.finished`` notification, so the app can start a turn. See docs/architecture.md, 5.5.
"""

import json
import re
import threading
import time
from pathlib import Path
from typing import List, Optional

from .exceptions import BrainError
from .loop import ACTIVE
from .toolkits import ToolError
from .toolkits.todo import render as render_todo

AGENT_PROMPT = """## YOU ARE AN AGENT
The you that talks with the user started you to do one part of a bigger job: the task in the first
message. Nobody watches you live and nobody answers while you work, so work on your own with your tools.
- Stay within the task: other agents may be working on the other parts at the same time.
- {access}
- Verify what you did before you report it.
- For long work, keep a todo list with todo_write and record progress with task_progress: your context
  may be summed up during long work.
- End with a compact report, findings first (at most about 2,000 tokens): the exact paths, names, URLs,
  line numbers and results that are needed. Put long output (data, drafts, code) in files and name them.
- If something blocks you or the task is unclear, say so in your report and stop: a message may answer
  it, and then you go on."""
ACCESS = {"read": "You can only look, not change anything: investigate and report.",
          "write": "You can change things (files, commands); the user approves your changes the way they "
                   "approve the other you's. Change only what your task covers."}
STEPS = {"read": 60, "write": 200}
MESSAGE = "[A message from the you that started you]\n{text}"
MAX_WORKING = 5  # at once per parent session; Anthropic's lead agent starts 3-5
OPEN_HOURS = 24  # an idle agent closes after this, and its name is free again
REPORT_CHARS = 8_000  # about 2,000 tokens; the whole report goes to a file
WAIT_DEFAULT, WAIT_MAX = 600, 1800
SHOWN_STEPS, TASK_CHARS, RESULT_CHARS = 15, 150, 160
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
STATUS = {"queued": "working", "working": "working", "input_required": "waiting for the user",
          "completed": "done", "failed": "failed", "cancelled": "stopped"}


def duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"


def short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Agents:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self._lock = threading.Lock()  # starts (names and the cap) and report claims

    # ============== Reading ==============

    def record(self, app: str, session: str) -> dict:
        return ((self.store.find_session(app, session) or {}).get("settings") or {}).get("agent") or {}

    def summary(self, app: str, session: str, record: Optional[dict] = None, only_open: bool = False) -> Optional[dict]:
        """What an agent is and does now; None for a session that is not an agent's (or, with ``only_open``,
        for a closed one: a chat of many months has many, and they are left unread)."""
        record = record if record is not None else self.record(app, session)
        runs = self.store.runs(app=app, session=session, limit=1)
        if not record or not runs:
            return None
        latest = runs[0]
        working = latest["status"] in ACTIVE
        is_open = not record.get("stopped") and (working or time.time() - latest["updated"] < OPEN_HOURS * 3600)
        if only_open and not is_open:
            return None
        events = self.store.run_events(latest["id"])
        reply = (latest["result"] or {}).get("reply", "") if latest["status"] == "completed" else ""
        return {
            "id": int(session.split("-", 1)[1]), "name": record["name"], "access": record["access"],
            "task": record["task"], "session": session, "parent": record["parent"], "run": latest["id"],
            "status": STATUS.get(latest["status"], latest["status"]), "working": working,
            "open": is_open,
            "step": sum(1 for e in events if e["type"] == "assistant"),
            "seconds": (time.time() if working else latest["updated"]) - latest["created"],
            "activity": self._activity(latest, events) if working else "",
            "report": reply, "error": (latest["error"] or {}).get("message", ""),
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
                            f"closed). Your agents: {names}.")
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

    def _activity(self, run: dict, events: List[dict]) -> str:
        if run["status"] == "input_required":
            names = ", ".join(request["name"] for request in self.brain.runs.waiting(run["id"]))
            return f"waiting for the user to allow {names}" if names else "waiting for the user"
        done = {e["call_id"] for e in events if e["type"] == "tool"}
        running = [e for e in events if e["type"] == "tool_start" and e["call_id"] not in done]
        if not running:
            return "thinking"
        assistant = next((e for e in reversed(events) if e["type"] == "assistant"), None)
        arguments = {c["id"]: (c.get("function") or {}).get("arguments", "")
                     for c in ((assistant or {}).get("message") or {}).get("tool_calls") or []}
        return "; ".join(f"{e['name']} {short(arguments.get(e['call_id'], ''), 120)}".strip() for e in running)

    def describe(self, agent: dict) -> str:
        """One line about an agent, for the model."""
        head = f"- {agent['name']} (#{agent['id']}, {agent['access']}): {agent['status']}"
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

    # ============== Starting, messages, stopping ==============

    def start(self, parent_run: dict, name, task, access="read", toolkits=None) -> dict:
        name, task, access = str(name or "").strip(), str(task or "").strip(), str(access or "read").strip()
        if not NAME.fullmatch(name):
            raise ToolError("The name must be 1-32 letters, digits, '-', '_' or '.', starting with a letter or "
                            "digit, e.g. tests or docs-research.")
        if not task:
            raise ToolError("The task is empty: say what the agent must do, with everything it needs.")
        if access not in STEPS:
            raise ToolError("access must be read or write.")
        app, parent = parent_run["app"], parent_run["session"]
        base = (parent_run["options"].get("profile") or {}).get("from_session") or parent  # a task works for a chat
        if toolkits is not None:
            have = self.brain.profile(app, base)["toolkits"]
            if not isinstance(toolkits, list) or any(kit not in have or kit == "agents" for kit in toolkits):
                raise ToolError(f"toolkits must be a list of yours: {', '.join(k for k in have if k != 'agents')}.")
        record = {"name": name, "parent": parent, "base": base, "access": access, "toolkits": toolkits,
                  "task": task, "created": time.time()}
        with self._lock:
            self._check_room(app, parent, name)
            run_id = self.store.add_run(app, "pending", "agent", {}, parent=parent_run["id"])
            session = f"agent-{run_id}"
            self.store.update_session(app, session, "settings", lambda s: {**s, "title": name, "agent": record})
            self.store.update_run(run_id, session=session, options=self._options(record, run_id, task))
        self.brain.runs.spawn(run_id)
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
        read = record["access"] == "read"
        options = {"input": [{"type": "text", "text": text}], "agent": agent_id, "parent_session": record["parent"],
                   "goal": f"agent {record['name']}: {text}",  # what lists of background work show
                   "max_steps": STEPS[record["access"]], "delivered": False,
                   "profile": {"instructions": AGENT_PROMPT.format(access=ACCESS[record["access"]]),
                               "toolkits": record["toolkits"], "mode": "readonly" if read else None,
                               "from_session": record.get("base") or record["parent"], "signals": False}}
        if read:
            options["model"] = self.brain.config.values()["light_model"]
        return options

    def message(self, parent_run: dict, ref, text) -> str:
        text = str(text or "").strip()
        if not text:
            raise ToolError("The message is empty.")
        app, parent = parent_run["app"], parent_run["session"]
        agent = self.find(app, parent, ref)
        item = [{"type": "text", "text": MESSAGE.format(text=text)}]
        if agent["working"]:
            try:  # its approvals wait for the user still: a message from you is not their answer
                self.brain.runs.steer(agent["run"], item, refuse_approvals=False)
                return f"Sent: {agent['name']} reads it at its next step."
            except BrainError:
                pass  # it ended just now: the message is a new request then
        with self._lock:
            self._check_room(app, parent)
            record = self.record(app, agent["session"])
            run_id = self.store.add_run(app, agent["session"], "agent",
                                        self._options(record, agent["id"], item[0]["text"]), parent=parent_run["id"])
        self.brain.runs.spawn(run_id)
        return f"Sent: {agent['name']} goes on with it, with all it knew. Collect its answer with agents_wait."

    def stop(self, app: str, agent_id: int, by_user: bool = False) -> dict:
        """Stop an agent at once and close it; it reports nothing more."""
        session = f"agent-{int(agent_id)}"
        record = self.record(app, session)
        if not record:
            raise ToolError(f"There is no agent {agent_id}.")
        self.store.update_session(app, session, "settings",
                                  lambda s: {**s, "agent": {**s.get("agent", {}), "stopped": True}}, create=False)
        for run in self.store.runs(app=app, session=session, statuses=ACTIVE, limit=10):
            self.brain.runs.cancel(run["id"], "The agent was stopped.")
        if by_user:
            self.brain.note(app, record["parent"], f"The user stopped your agent {record['name']} (#{agent_id}).")
        return self.summary(app, session)

    def wait(self, ctx, refs=None, timeout=WAIT_DEFAULT) -> str:
        """Until the named agents (or all working ones) are done, the timeout passes or the user writes;
        then every report not delivered yet."""
        app, parent = ctx.app, ctx.session
        refs = refs if isinstance(refs, list) else ([refs] if refs else [])
        targets = [self.find(app, parent, ref) for ref in refs] or [a for a in self.open(app, parent) if a["working"]]
        sessions = {a["session"]: a["name"] for a in targets}
        deadline = time.time() + max(1, min(int(timeout or WAIT_DEFAULT), WAIT_MAX))
        interrupted = ""

        def working() -> List[str]:
            return [name for session, name in sessions.items()
                    if self.store.runs(app=app, session=session, limit=1)[0]["status"] in ACTIVE]
        while working() and time.time() < deadline:
            if ctx.pause(min(0.5, max(0.0, deadline - time.time()))):
                interrupted = ctx.interruption()
                break
        parts = [f"{interrupted} The wait ended early."] if interrupted else []
        parts += [self.report(run) for run in self.claim(app, parent)]
        still = working()
        if still:
            parts.append(f"Still working: {', '.join(still)}. Wait again, or go on: their reports come to you "
                         "when they finish.")
        if not parts:
            return "None of your agents is working, and no report is waiting." if not targets else "No new reports."
        return "\n\n".join(parts)

    # ============== Reports ==============

    def claim(self, app: str, parent: str) -> List[dict]:
        """The finished agent runs of this session whose reports have not reached it yet; each only once.
        Agents that were stopped report nothing."""
        with self._lock:
            runs = self.store.undelivered_agent_runs(app, parent)
            for run in runs:
                self.store.update_run_options(run["id"], lambda options: {**options, "delivered": True})
        return [run for run in runs if not self.record(app, run["session"]).get("stopped")]

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

    def take_reports(self, run: dict) -> None:
        """Before a model call of a run: reports of its session's agents that came meanwhile, as a note."""
        reports = [self.report(r) for r in self.claim(run["app"], run["session"])]
        if reports:
            self.brain.note(run["app"], run["session"], "\n\n".join(reports))

    def hand_over(self, app: str, parent: str) -> None:
        """Reports nobody collected while no run of the session goes on: a note, and news for the app."""
        claimed = self.claim(app, parent)
        if not claimed:
            return
        self.brain.note(app, parent, "\n\n".join(self.report(run) for run in claimed))
        news = [run for run in claimed if run["status"] != "cancelled"]  # a stop is no news to tell
        if news:
            self.brain.notify(app, parent, "agent.finished", {"agents": [
                {"agent": run["options"].get("agent"), "name": self.record(app, run["session"]).get("name", ""),
                 "status": run["status"], "run": run["id"]} for run in news]})

    def run_ended(self, run: dict) -> None:
        if run["kind"] == "agent":
            parent = run["options"].get("parent_session")
            if not parent:
                return
            if not self.store.has_session(run["app"], parent):  # the chat was deleted meanwhile
                self.store.delete_session(run["app"], run["session"])
                return
            if not self.brain.session_busy(run["app"], parent):  # else its next step or its end takes it
                self.hand_over(run["app"], parent)
        elif run["kind"] in ("turn", "task"):
            self.hand_over(run["app"], run["session"])

    def recover(self) -> None:
        """After a restart: reports that ended with no run of their session going on to take them."""
        for app, parent in self.store.undelivered_parents():
            if not self.brain.session_busy(app, parent):
                self.hand_over(app, parent)

    def delete_for(self, app: str, parent: str) -> None:
        """Its chat was deleted (first): idle agents go now; working ones stop and go when their run ends
        (run_ended), so no run loses its row while it still works."""
        for session, settings in self.store.child_sessions(app, parent):
            working = self.store.runs(app=app, session=session, statuses=ACTIVE, limit=10)
            for run in working:
                self.brain.runs.cancel(run["id"], "Its chat was deleted.")
            if not working:
                self.store.delete_session(app, session)
