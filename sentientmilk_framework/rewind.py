"""Returning to a message, like Claude Code's rewind: the chat goes back to just before the user sent it.

Undone with it:
- everything logged since (replies, tool calls, notes, and compactions and clearings made since);
- files changed with files_write and files_edit since, also by the agents she started since and the tasks
  her new reminders fired (each file goes back to the version kept before its first change, see
  Store.keep_version; a file made since is deleted);
- her todo list for the chat;
- work she started since that still runs: jobs, her agents' runs and those tasks are stopped, the agents she
  started since are deleted, and the reminders she set since are removed.

Not undone, and ``kept`` names those calls: what commands and app actions did, what went out to the web or
other services, memories (the app's, not the chat's) and the journal. ``preview`` is the dry run of
``rewind``; both refuse while a run of the chat goes on.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Tuple

from .exceptions import BrainError
from .loop import ACTIVE
from .toolkits import ToolError
from .toolkits.shell import stop as stop_job
from .toolkits.todo import clean as clean_todo

logger = logging.getLogger(__name__)

STOP_WAIT = 10  # seconds the work being stopped has to end before its files are restored
# Calls whose effects a return takes back, or that only touch the work it stops.
UNDONE = {"files_write", "files_edit", "skill_delete", "todo_write", "schedule_create", "agent_start", "agent_message",
          "task_progress"}
BUSY = "She is still working in this chat: stop her first, or wait."


def preview(brain, app: str, session: str, event: int) -> dict:
    """What returning to ``event`` (a message the user sent) would undo and what it keeps."""
    target, work = _plan(brain, app, session, event)
    files = _files(brain, app, session, target, work)[0]
    return {**_summary(brain, app, session, target, work), "files": _listed(files)}


def rewind(brain, app: str, session: str, event: int) -> dict:
    """Return to just before ``event``: the summary, with ``problems`` (files that could not be put back)."""
    _busy(brain, app, session)  # before the lock, which a running turn holds
    with brain.runs.session_lock(app, session):  # a turn sent meanwhile starts once this is done
        target, work = _plan(brain, app, session, event)
        summary = _summary(brain, app, session, target, work)  # before the stop: what it stops
        _stop(brain, app, work)
        changes, versions = _files(brain, app, session, target, work)  # after the stop: nothing writes now
        summary["files"] = _listed(changes)
        failed = set()
        for change in changes:
            try:
                path = Path(change["path"])
                if change["content"] is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(change["content"])
            except OSError as exc:
                failed.add(change["key"])
                summary["problems"].append(f"{change['path']}: {exc.strerror or exc}")
        todo = _todo(brain.store, app, session, target)
        last = brain.store.last_event(app, session, target["id"], "assistant")
        tokens = ((last or {}).get("usage") or {}).get("prompt_tokens") or 0

        def change_state(state: dict) -> dict:
            state["todo"] = todo
            state["context_tokens"] = tokens
            state.pop("read", None)  # files read since are unread again; she reads before she edits
            return state
        # a file that could not be put back keeps its versions: a later return can still restore it
        brain.store.rewind(app, session, target["id"], [v["id"] for v in versions if v["key"] not in failed],
                           list(work["runs"]), change_state)
        for reminder in work["reminders"]:
            brain.scheduler.delete(reminder["id"])
    logger.info("Returned %s/%s to before event %s", app, session, target["id"])
    return summary


def _busy(brain, app: str, session: str) -> None:
    if brain.session_busy(app, session):
        raise BrainError("busy", BUSY, http_status=409)


def _plan(brain, app: str, session: str, event: int) -> Tuple[dict, dict]:
    _busy(brain, app, session)
    store = brain.store
    target = store.event(event)
    if not target or (target["app"], target["session"], target["type"]) != (app, session, "input") or \
            not target.get("display"):
        raise ValueError(f"{event} is not a message the user sent in this chat")
    return target, _work(store, app, session, target)


def _work(store, app: str, session: str, target: dict) -> dict:
    """What she started since the message from other sessions: runs of her agents, of tasks her new reminders
    fired, and of what those started; her new agents, running jobs and new reminders."""
    since = target["at"]
    reminders = [s for s in store.schedules(app) if s["session"] == session and s["created_by"] == "model"
                 and s["created"] >= since]
    fired = {s["id"] for s in reminders}
    runs: Dict[int, dict] = {}
    for run in store.runs_since(app, since):  # the oldest first: a run's parent comes before it
        options = run["options"]
        if run["session"] != session and (
                (run["kind"] == "agent" and options.get("parent_session") == session) or
                (run["kind"] == "task" and options.get("schedule") in fired) or run["parent"] in runs):
            runs[run["id"]] = run
    agents = [(int(name.split("-", 1)[1]), settings["agent"]) for name, settings in store.child_sessions(app, session)
              if settings["agent"].get("created", 0) >= since and not settings["agent"].get("stopped")]
    jobs = [job for job in store.jobs(app, time.time(), limit=1000) if job["status"] == "running" and
            (job["run"] in runs or (job["session"] == session and job["started"] >= since))]
    return {"runs": runs, "agents": agents, "jobs": jobs, "reminders": reminders}


def _files(brain, app: str, session: str, target: dict, work: dict) -> Tuple[List[dict], List[dict]]:
    """(each file that changed since and what it goes back to, every version kept since). A file's first
    version since the message is how it was then: ``content`` None means it did not exist."""
    store, versions, first, gone = brain.store, [], {}, {}
    for version in store.versions(app, session):
        if version["session"] == session:
            ours = version["since"] >= target["id"]
        else:  # an agent's run may be gone with its agent: it still counts when it started since
            if version["run"] not in gone:
                gone[version["run"]] = store.run(version["run"]) is None
            ours = version["started"] >= target["at"] and (version["run"] in work["runs"] or gone[version["run"]])
        if ours:
            versions.append(version)
            first.setdefault(version["key"], version)
    changes = []
    for version in first.values():
        path = Path(version["path"])
        if not version["existed"]:
            if path.is_file():
                changes.append({**version, "content": None, "change": "delete"})
            continue
        content = store.version_content(version["id"])
        try:
            now = path.read_bytes() if path.is_file() else None
        except OSError:
            now = None  # unreadable now: put back all the same
        if now != content:
            changes.append({**version, "content": content, "change": "restore"})
    return changes, versions


def _listed(changes: List[dict]) -> List[dict]:
    return [{"path": c["path"], "change": c["change"]} for c in changes]


def _todo(store, app: str, session: str, target: dict) -> list:
    """Her todo list as the message found it: the last one she wrote before it."""
    last = store.last_event(app, session, target["id"], "tool", "todo_write")
    return clean_todo((last or {}).get("arguments", {}).get("items") or [])


def _summary(brain, app: str, session: str, target: dict, work: dict) -> dict:
    store = brain.store
    later = store.events(app, session, after=target["id"] - 1, types=("input", "tool"))
    found = store.find_session(app, session) or {"state": {}}
    agents = {agent_id for agent_id, _ in work["agents"]}
    running = [run for run in work["runs"].values() if (store.run(run["id"]) or {}).get("status") in ACTIVE]
    stopped = [{"kind": "job", "id": job["id"], "name": job["command"]} for job in work["jobs"]]
    stopped += [{"kind": "agent", "id": run["options"].get("agent"),
                 "name": brain.agents.record(app, run["session"]).get("name", "")}
                for run in running if run["kind"] == "agent" and run["options"].get("agent") not in agents]
    stopped += [{"kind": "task", "id": run["id"], "name": run["options"].get("goal", "")}
                for run in running if run["kind"] == "task"]
    return {
        "to": target["id"], "text": target["display"], "mentions": target.get("mentions") or [],
        "skills": target.get("skills") or [],
        "messages": sum(1 for e in later if e["type"] == "input" and e.get("display")),
        "todo": _todo(store, app, session, target) != found["state"].get("todo", []),
        "agents": [{"id": agent_id, "name": record["name"]} for agent_id, record in work["agents"]],
        "stopped": stopped,
        "reminders": [{"id": s["id"], "text": s["payload"]["text"]} for s in work["reminders"]],
        "kept": _kept(brain, app, session, later, work),
        "problems": [],
    }


def _kept(brain, app: str, session: str, later: List[dict], work: dict) -> List[dict]:
    """The calls since the message whose effects stay: those that change something and are not undone here."""
    profile = brain.profile(app, session)
    tools = {**brain.toolset(profile, "agent").by_name, **brain.toolset(profile, "turn").by_name}
    events = [e for e in later if e["type"] == "tool"]
    events += [e for run in work["runs"] for e in brain.store.run_events(run) if e["type"] == "tool"]
    counts: Dict[str, int] = {}
    for event in events:
        tool_ = tools.get(event["name"])
        if event["status"] == "ok" and event["name"] not in UNDONE and not (tool_ and tool_.readonly):
            counts[event["name"]] = counts.get(event["name"], 0) + 1
    return [{"name": name, "count": count} for name, count in counts.items()]


def _stop(brain, app: str, work: dict) -> None:
    """Stop the work, quietly (nobody is told it ended, no report waits), and give it STOP_WAIT to end."""
    for run_id in work["runs"]:  # first: a run that ends now already ends quietly
        brain.store.update_run_options(run_id, lambda options: {**options, "quiet": True})
    for job in work["jobs"]:
        stop_job(brain, job, quiet=True)
    for agent_id, _ in work["agents"]:
        try:
            brain.agents.stop(app, agent_id)
        except ToolError:
            pass  # deleted meanwhile
    for run_id in work["runs"]:
        brain.runs.cancel(run_id, "The user went back to before this work started.")
    deadline = time.monotonic() + STOP_WAIT
    while time.monotonic() < deadline and any((brain.store.run(r) or {}).get("status") in ACTIVE
                                              for r in work["runs"]):
        time.sleep(0.05)
