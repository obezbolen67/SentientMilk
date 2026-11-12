"""Talk to the SentientMilk brain from an app.

    client = connect()                                  # the running brain, started if needed
    client.declare_app("jarvis", name="Jarvis", environment="...", toolkits=["web"])  # memory: every app
    result = client.turn("jarvis", "main", text="Hello!", on_event=print)
    result["reply"], result["signals"], result["tools"]

The brain runs as its own process (``sentientmilk serve``), announces its address and
token in ``<home>/server.json`` and exits after a while with nothing to do; the client
starts it again when it is gone, the way SentientMilk recorded in ``<home>/launch.json``.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import quote

import requests

from .exceptions import BrainError

DISCOVERY_FILE = "server.json"
LAUNCH_FILE = "launch.json"
COMPACT_TIMEOUT = 600
START_TIMEOUT = 30


def default_home() -> Path:
    """Where the brain keeps its settings, memory and discovery file."""
    return Path(os.environ.get("SENTIENTMILK_HOME") or Path.home() / ".sentientmilk")


def _unreachable(exc: Exception) -> BrainError:
    return BrainError("brain_unreachable", "Cannot reach the SentientMilk brain", str(exc))


def track_tool(tools: List[dict], event: dict) -> None:
    """Fold tool events into one entry per call: running, then completed or error."""
    if event["type"] == "tool.start":
        tools.append({"name": event["name"], "call_id": event["call_id"], "arguments": event.get("arguments", {}),
                      "status": "running", "result": None})
    elif event["type"] == "tool.end":
        for tool in reversed(tools):
            if tool["call_id"] == event["call_id"] and tool["status"] == "running":
                tool["status"] = "completed" if event["status"] == "ok" else "error"
                tool["result"] = event.get("result")
                return


class BrainClient:
    def __init__(self, url: str, token: str, timeout: float = 30.0, home: Optional[Path] = None,
                 command: Optional[List[str]] = None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.home, self.command = home, command  # set: a vanished brain is started again
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def discover(cls, home: Optional[Path] = None) -> Optional["BrainClient"]:
        """The brain announced in ``home``, if it is running."""
        try:
            info = json.loads((Path(home or default_home()) / DISCOVERY_FILE).read_text(encoding="utf-8"))
            client = cls(info["url"], info["token"])
            client.health()
        except (OSError, ValueError, KeyError, TypeError, BrainError):
            return None
        return client

    def _restart(self) -> bool:
        if not self.home:
            return False
        fresh = connect(self.home, self.command)
        self.url, self._headers = fresh.url, fresh._headers
        return True

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        for attempt in (1, 2):
            try:
                return requests.request(method, f"{self.url}/v1{path}", headers=self._headers, **kwargs)
            except requests.ConnectionError as exc:  # nothing reached the brain, so a retry is safe
                if attempt == 2 or not self._restart():
                    raise _unreachable(exc) from exc
            except requests.RequestException as exc:
                raise _unreachable(exc) from exc
        raise AssertionError("unreachable")

    def _call(self, method: str, path: str, payload: Optional[dict] = None, timeout: Optional[float] = None,
              params: Optional[dict] = None) -> dict:
        response = self._request(method, path, json=payload, params=params, timeout=timeout or self.timeout)
        return self._result(response)

    @staticmethod
    def _result(response: requests.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.ok and isinstance(data, dict):
            return data
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            raise BrainError(error.get("type", "error"), error.get("message", ""), error.get("details"),
                             error.get("http_status"))
        raise BrainError("brain_error", f"The brain answered {response.status_code}", response.text[:500])

    def _stream(self, method: str, path: str, payload: Optional[dict] = None,
                params: Optional[dict] = None) -> Iterator[dict]:
        response = self._request(method, path, json=payload, params=params, stream=True, timeout=(self.timeout, None))
        with response:
            if not response.ok:
                self._result(response)
            response.encoding = "utf-8"
            try:
                for line in response.iter_lines(chunk_size=None, decode_unicode=True):
                    if line.startswith("data: "):
                        yield json.loads(line[len("data: "):])
            except requests.RequestException as exc:
                raise _unreachable(exc) from exc

    # ============== Brain ==============

    def health(self) -> dict:
        return self._call("GET", "/health", timeout=3)

    def config(self) -> dict:
        """Settings without secrets; ``api_key_set`` and ``web_search_key_set`` tell if they are set."""
        return self._call("GET", "/config")

    def update_config(self, **changes: Any) -> dict:
        return self._call("PATCH", "/config", changes)

    def models(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> List[str]:
        payload = {key: value for key, value in (("base_url", base_url), ("api_key", api_key)) if value}
        return self._call("POST", "/models", payload)["models"]

    def stats(self) -> dict:
        return self._call("GET", "/stats")

    # ============== Apps and sessions ==============

    def declare_app(self, app: str, **declaration: Any) -> dict:
        """Who the brain is in this app: name, environment, persona, signals, toolkits, actions, rules, roots."""
        return self._call("PUT", f"/apps/{app}", declaration)

    def apps(self) -> List[str]:
        return self._call("GET", "/apps")["apps"]

    def app(self, app: str) -> dict:
        return self._call("GET", f"/apps/{app}")

    def memory(self) -> Dict[str, Dict[str, Any]]:
        """What the brain remembers for every app, {category: {key: value}}; ``memory_entries`` says which app
        saved each. A session's own memory is ``session(app, id)["session_memory"]``."""
        result: Dict[str, Dict[str, Any]] = {}
        for entry in self.memory_entries():
            result.setdefault(entry["category"], {})[entry["key"]] = entry["value"]
        return result

    def memory_entries(self) -> List[dict]:
        """Every memory entry: category, key, value, app (the one that saved it) and updated."""
        return self._call("GET", "/memory")["entries"]

    def update_app(self, app: str, **settings: Any) -> dict:
        """The user's settings for an app: persona ("" resets), model, rules, disabled_toolkits, roots, journal."""
        return self._call("PATCH", f"/apps/{app}/settings", settings)

    def sessions(self, app: str) -> List[dict]:
        return self._call("GET", f"/apps/{app}/sessions")["sessions"]

    def session(self, app: str, session: str) -> dict:
        """settings, todo, session_memory (the session's own, {key: value}), created and context use."""
        return self._call("GET", f"/apps/{app}/sessions/{session}")

    def update_session(self, app: str, session: str, **settings: Any) -> dict:
        """title, instructions, cwd, roots, rules, disabled_toolkits for one session."""
        return self._call("PATCH", f"/apps/{app}/sessions/{session}", settings)

    def delete_session(self, app: str, session: str) -> None:
        """The session and its history; refused (``busy``) while a turn of it goes on."""
        self._call("DELETE", f"/apps/{app}/sessions/{session}")

    def mentions(self, app: str, query: str = "", kind: Optional[str] = None, session: str = "main") -> List[dict]:
        """What an @ picker offers for ``query`` in ``session``: {kind, ref, label, note, time}; a query that
        looks like a path lists that folder. ``kind``: session, agent, plugin or file."""
        params = {"q": query, "session": session, **({"kind": kind} if kind else {})}
        return self._call("GET", f"/apps/{app}/mentions", params=params)["mentions"]

    def jobs(self, app: str, since: float = 0) -> List[dict]:
        """An app's background commands: the running ones and those that ended after ``since`` (epoch seconds),
        the newest first: ``id``, ``session``, ``command``, ``cwd``, ``status`` (running, stopping, finished,
        stopped), ``exit_code``, ``started``, ``ended`` and ``last``, its newest output line."""
        return self._call("GET", f"/apps/{app}/jobs", params={"since": since})["jobs"]

    def stop_job(self, job: int) -> dict:
        """Stop a running background command and everything it started; ``message`` says what happened."""
        return self._call("POST", f"/jobs/{job}/stop")

    def mention_card(self, app: str, kind: str, ref: str, session: str = "main") -> str:
        """The card the brain reads for a mention: what a picker shows as its preview."""
        return self._call("GET", f"/apps/{app}/mentions/{kind}", params={"ref": ref, "session": session})["card"]

    def summarize_session(self, app: str, session: str) -> dict:
        """The session ended: she goes over what is new in it in the background, and keeps what matters in her
        memory (memory_save). ``queued``: there was enough new for that; ``messages``: the user's since the
        last time. Nothing shows in the session."""
        return self._call("POST", f"/apps/{app}/sessions/{session}/summary", {})

    def summarize_sessions(self, app: str) -> dict:
        """At an app's start: she goes over each of its conversations with enough new in it (``queued``: their
        ids), one at a time, after the turns going on."""
        return self._call("POST", f"/apps/{app}/summaries", {})

    def compact_session(self, app: str, session: str) -> dict:
        """Sum up the whole session now: ``compacted`` (False when there was nothing to sum up), and the
        context in tokens ``before`` and ``after``. It takes a model call."""
        return self._call("POST", f"/apps/{app}/sessions/{session}/compact", {}, timeout=COMPACT_TIMEOUT)

    def history(self, app: str, session: str, tools: bool = False) -> List[dict]:
        """What the user said and the brain replied; ``tools`` adds each tool call between them."""
        return self._call("GET", f"/apps/{app}/sessions/{session}/history" + ("?tools=1" if tools else ""))["history"]

    def rewind_preview(self, app: str, session: str, event: int) -> dict:
        """What returning to a message the user sent (its history entry's ``id``) would undo: ``messages``,
        ``files`` ({path, change: restore or delete}), ``todo`` and ``session_memory`` (each: goes back or
        not), ``agents`` (deleted),
        ``stopped`` (jobs, agents' runs and tasks: {kind, id, name}), ``schedules`` (removed), and ``kept``
        ({name, count}: calls whose effects stay). ``text`` and ``mentions`` are the message's."""
        return self._call("GET", f"/apps/{app}/sessions/{session}/rewind", params={"to": event})

    def rewind(self, app: str, session: str, event: int) -> dict:
        """Return the chat to just before that message and undo the rest as previewed; ``problems`` lists the
        files that could not be put back. Refused (``busy``) while a turn of the chat goes on."""
        return self._call("POST", f"/apps/{app}/sessions/{session}/rewind", {"to": event}, timeout=60)

    def clear_history(self, app: str, session: str) -> None:
        self._call("DELETE", f"/apps/{app}/sessions/{session}/history")

    def import_history(self, app: str, session: str, messages: List[dict], memory: Dict[str, Dict[str, Any]],
                       transcript: Optional[List[dict]] = None) -> None:
        """History an app kept before it used the brain; ``transcript`` is what it showed, if that differs."""
        payload = {"messages": messages, "memory": memory}
        if transcript is not None:
            payload["transcript"] = transcript
        self._call("POST", f"/apps/{app}/sessions/{session}/import", payload)

    def turn(self, app: str, session: str, text: Optional[str] = None, *, image: Optional[str] = None,
             items: Optional[List[dict]] = None, context: Optional[Dict[str, str]] = None, reply: str = "required",
             max_steps: Optional[int] = None, on_event: Optional[Callable[[dict], None]] = None,
             on_approval: Optional[Callable[[dict], Any]] = None,
             on_action: Optional[Callable[[dict], Any]] = None, occurrence: Optional[int] = None) -> dict:
        """One turn. Events reach ``on_event`` as they happen. ``on_approval(event)`` answers approval
        requests with "allow", "always", "deny" or ("deny", reason); without it they are denied.
        ``on_action(event)`` runs a declared action (``event["name"]``, ``event["arguments"]``) and
        returns its result, or ``(result, [image data URLs])``; an exception becomes an error result.
        ``max_steps``: a limit on the turn's model calls, which has none otherwise (an eval's cap)."""
        inputs = list(items or [])
        if text:
            inputs.append({"type": "text", "text": text})
        if image:
            inputs.append({"type": "image", "url": image})
        payload = {"input": inputs, "context": context or {}, "reply": reply}
        if occurrence is not None:
            payload['occurrence'] = occurrence
        if max_steps:
            payload["max_steps"] = max_steps
        tools: List[dict] = []
        run = None
        for event in self._stream("POST", f"/apps/{app}/sessions/{session}/turns", payload):
            run = event.get("run", run)
            track_tool(tools, event)
            if on_event:
                on_event(event)
            if event["type"] == "approval.requested":
                answer = on_approval(event) if on_approval else ("deny", "This app cannot ask the user for approval.")
                decision, reason = answer if isinstance(answer, tuple) else (answer, "")
                self._answer_live(run, call_id=event["call_id"], decision=decision, reason=reason)
            elif event["type"] == "action.requested" and on_action:
                try:
                    result = on_action(event)
                    result, images = result if isinstance(result, tuple) else (result, [])
                    self._answer_live(run, call_id=event["call_id"], result=result, images=images)
                except BrainError:
                    raise
                except Exception as exc:
                    self._answer_live(run, call_id=event["call_id"], result=f"{type(exc).__name__}: {exc}",
                                      status="error")
            elif event["type"] == "done":
                return {"run": run, "reply": event["reply"], "signals": event["signals"], "silent": event["silent"],
                        "status": event["status"], "usage": event.get("usage"), "tools": tools,
                        "unread": event.get("unread", [])}
            elif event["type"] == "error":
                raise BrainError(**event["error"])
        raise BrainError("brain_unreachable", "The brain ended the turn without an answer")

    def _answer_live(self, run: int, **answer: Any) -> None:
        """Answer a turn being streamed. Stopped while the app asked the user, the run has ended: its end
        comes on the stream, so the answer is dropped."""
        try:
            self.answer(run, **answer)
        except BrainError:
            if self.run(run)["status"] not in ("completed", "failed", "cancelled"):
                raise

    # ============== Runs and tasks ==============

    def run(self, run: int) -> dict:
        return self._call("GET", f"/runs/{run}")

    def answer(self, run: int, **answer: Any) -> None:
        """call_id + decision (allow/always/deny) + reason; call_id + result for actions;
        question + action (accept/decline/cancel) + content for questions."""
        self._call("POST", f"/runs/{run}/answer", answer)

    def cancel(self, run: int) -> None:
        """Stop a run at once: waits end, calls still running are left behind, its helpers stop too."""
        self._call("POST", f"/runs/{run}/cancel", {})

    def steer(self, run: int, text: Optional[str], items: Optional[List[dict]] = None) -> None:
        """Send a message to a turn that works: it reaches the model at its next step. ``items``: more input
        with it, such as mentions, or instead of text (a skill the user started). Raises ``ended`` when the turn
        is over: send it as a new turn then."""
        inputs = ([{"type": "text", "text": text}] if text else []) + list(items or [])
        self._call("POST", f"/runs/{run}/steer", {"input": inputs})

    def detach(self, run: int) -> None:
        self._call("POST", f"/runs/{run}/detach", {})

    def start_task(self, app: str, goal: str, session: Optional[str] = None, **options: Any) -> dict:
        """toolkits, verify, allow (rules), context (compact/reset), max_steps, cwd."""
        return self._call("POST", "/tasks", {"app": app, "goal": goal, **({"session": session} if session else {}),
                                             **options})

    def tasks(self, app: Optional[str] = None, status: Optional[str] = None, kind: str = "task") -> List[dict]:
        """Background runs, the newest first: tasks, or with ``kind`` "agent" the runs of agents."""
        params = {key: value for key, value in (("app", app), ("status", status), ("kind", kind)) if value}
        return self._call("GET", "/tasks", params=params)["tasks"]

    def agents(self, app: str, session: str, all: bool = False) -> List[dict]:
        """The agents a session started, the newest first: ``id``, ``name``, ``access``, ``task``, ``status``
        (working, asking, waiting for the user, done, failed, interrupted: a message goes on; stopped: going),
        ``step``, ``seconds``, ``activity`` (what it does now), ``report``; only open ones unless ``all`` (stopped
        ones are closed)."""
        params = {"app": app, "session": session, **({"all": "1"} if all else {})}
        return self._call("GET", "/agents", params=params)["agents"]

    def agent(self, agent: int) -> dict:
        """One agent with its ``steps`` (``name``, ``arguments``, ``status``, ``result``), ``todo`` and ``progress``."""
        return self._call("GET", f"/agents/{agent}")

    def stop_agent(self, agent: int) -> dict:
        """Stop an agent at once and close it; the session that started it hears that the user stopped it."""
        return self._call("POST", f"/agents/{agent}/stop", {})

    def run_events(self, run: int) -> Iterator[dict]:
        """What a run did so far ("log" events), then live events until it ends."""
        return self._stream("GET", f"/runs/{run}/events")

    def events(self, app: str, after: int = 0) -> Iterator[dict]:
        """Notifications for an app (tasks, jobs, schedules), from ``after`` on, then live."""
        return self._stream("GET", "/events", params={"app": app, "after": after})

    # ============== Schedules, toolkits, journal ==============

    def schedules(self, app: Optional[str] = None) -> List[dict]:
        return self._call("GET", "/schedules", params={"app": app} if app else None)["schedules"]

    def create_schedule(self, app: str, when: str, text: str, session: str = "main",
                        catch_up: str = "once", timezone: Optional[str] = None, title: str = '') -> dict:
        """Work for later, once ('2026-11-06T17:00', 'in 20m') or repeating ('every 2h', cron): each run is a
        normal turn of ``app`` with ``text`` in the schedule's own conversation (``execution_session``)."""
        return self._call("POST", "/schedules", {"app": app, "session": session, "when": when, "text": text,
                          "catch_up": catch_up, 'timezone': timezone, 'title': title})

    def scheduled_occurrences(self, app: str, pending: bool = True) -> List[dict]:
        """App-owned deliveries: pending/recoverable by default, or the latest occurrence history."""
        return self._call('GET', f'/apps/{app}/scheduled', params={'pending': '1' if pending else '0'})['occurrences']

    def update_schedule(self, schedule: int, **changes: Any) -> dict:
        """Change when, text, title, timezone, catch_up or enabled; obsolete queued work is cancelled."""
        return self._call('PATCH', f'/schedules/{schedule}', changes)

    def enable_schedule(self, schedule: int, enabled: bool) -> dict:
        return self._call("PATCH", f"/schedules/{schedule}", {"enabled": enabled})

    def delete_schedule(self, schedule: int) -> None:
        self._call("DELETE", f"/schedules/{schedule}")

    def toolkits(self, app: Optional[str] = None) -> dict:
        return self._call("GET", "/toolkits", params={"app": app} if app else None)

    def plugins(self) -> List[dict]:
        """Every plugin: name, version, description, builtin, enabled, error, toolkits, tools, mcp, settings
        (secrets only as ``set``)."""
        return self._call("GET", "/plugins")["plugins"]

    def install_plugin(self, source: str) -> dict:
        """From a folder with a plugin.json, or a git URL; the plugin is on at once."""
        return self._call("POST", "/plugins", {"source": source}, timeout=330)["plugin"]

    def update_plugin(self, name: str, enabled: Optional[bool] = None, settings: Optional[Dict[str, str]] = None,
                      trusted: Optional[bool] = None) -> dict:
        """Turn a plugin on or off, change its settings ("<set>" keeps a secret, "" clears a setting), and
        trust it as its files are now (its tools then use their own policies, its MCP servers run) or no more."""
        changes = {key: value for key, value in (("enabled", enabled), ("settings", settings), ("trusted", trusted))
                   if value is not None}
        return self._call("PATCH", f"/plugins/{quote(name, safe='')}", changes)["plugin"]

    def reload_plugin(self, name: str) -> dict:
        """Bring in a plugin's changes from where it was installed from."""
        return self._call("POST", f"/plugins/{quote(name, safe='')}/reload", timeout=330)["plugin"]

    def remove_plugin(self, name: str) -> None:
        self._call("DELETE", f"/plugins/{quote(name, safe='')}")

    def skills(self) -> List[dict]:
        """Every skill: name, description, argument_hint, model_invocable (she may load it), user_invocable (the
        user may start it: a ``skill`` input item, {"type": "skill", "name", "arguments"}), builtin, path, error."""
        return self._call("GET", "/skills")["skills"]

    def remove_skill(self, name: str) -> None:
        """Delete one of the user's skills (its folder); a shipped one cannot be."""
        self._call("DELETE", f"/skills/{quote(name, safe='')}")

    def mcp(self) -> dict:
        return self._call("GET", "/mcp")

    def set_mcp(self, servers: Dict[str, dict]) -> dict:
        return self._call("PUT", "/mcp", {"servers": servers})

    def reconnect_mcp(self, name: str) -> None:
        self._call("POST", f"/mcp/{name}/reconnect")

    def browser(self) -> dict:
        """Her browser: ``command`` (the Chrome or Edge it uses; empty: none found), ``version``, ``mode`` (off,
        hidden: she uses it out of sight, shown: on the user's screen for a sign-in she asked for, user: opened
        from here), ``profile`` (its folder), ``has_profile``, ``tabs`` (all conversations')."""
        return self._call("GET", "/browser")

    def open_browser(self) -> dict:
        """Her browser's profile in a plain Chrome on the user's screen, nothing attached: they sign in to sites
        for her there. She cannot use it until they close it."""
        return self._call("POST", "/browser/open", timeout=60)

    def clear_browser(self) -> dict:
        """Forget what she signed in to (her browser's profile is deleted)."""
        return self._call("POST", "/browser/clear", timeout=60)

    def journal(self, query: str = "") -> List[dict]:
        return self._call("GET", "/journal", params={"q": query} if query else None)["notes"]

    def delete_note(self, note: int) -> None:
        self._call("DELETE", f"/journal/{note}")

    def forget(self, category: str, key: str) -> None:
        """Forget a memory entry in every app; sessions see it gone at their next request."""
        self._call("DELETE", f"/memory/{quote(category, safe='')}/{quote(key, safe='')}")

    def forget_session_memory(self, app: str, session: str, key: str) -> None:
        """Take one thing out of a session's memory."""
        self._call("DELETE", f"/apps/{app}/sessions/{session}/memory/{quote(key, safe='')}")

    def shutdown(self) -> None:
        """Stop the brain; the next connect() starts it again."""
        self._call("POST", "/shutdown")


def packaged() -> bool:
    """A packaged app: PyInstaller's, or a folder made by scripts/bundle.py (its runtime holds bundle.json),
    run by the runtime's python.exe or by the folder's own NAME.exe beside the runtime."""
    here = Path(sys.executable).parent
    return bool(getattr(sys, "frozen", False)) or any((folder / "bundle.json").exists()
                                                      for folder in (here, here / "runtime"))


def _command(home: Path, *args: str) -> List[str]:
    program = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "sentientmilk_framework"]
    return [*program, "--home", str(home), *args]


def own_command(home: Path) -> List[str]:
    """How this program runs the brain: SentientMilk's own executable when packaged."""
    return _command(home, "serve", "--log")


def panel_command(home: Path) -> List[str]:
    """How this program opens its control panel."""
    return _command(home)


def start_command(home: Path) -> List[str]:
    """What Windows runs at sign-in (Start with Windows): no console; it starts the brain and exits."""
    from .autostart import windowless

    program, *rest = _command(home, "start")
    return [str(windowless(Path(program))), *rest]


def record_launch(home: Path) -> None:
    """SentientMilk notes how it is installed, so apps start it that way (it decides, not them)."""
    home.mkdir(parents=True, exist_ok=True)
    (home / LAUNCH_FILE).write_text(json.dumps({"command": own_command(home)}), encoding="utf-8")


def launch_command(home: Path) -> List[str]:
    try:
        command = json.loads((home / LAUNCH_FILE).read_text(encoding="utf-8"))["command"]
        if Path(command[0]).exists():
            return command
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    if packaged():  # a packaged app cannot run the brain itself
        raise BrainError("brain_unreachable", "SentientMilk is not set up on this computer",
                         "Install SentientMilk and open it once (run sentientmilk); apps start it from then on.")
    return own_command(home)


def open_panel(home: Optional[Path] = None) -> None:
    """Open SentientMilk's control panel in its own window, run the way SentientMilk recorded (the panel
    starts the brain when none runs)."""
    home = Path(home or default_home())
    command = launch_command(home)
    if command[-2:] == ["serve", "--log"]:
        command = command[:-2]
    env = {key: value for key, value in os.environ.items() if not key.startswith("_PYI_")}
    subprocess.Popen(command, cwd=home, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)


def _spawn(command: List[str], home: Path) -> None:
    """Start the brain on its own: no console, its home as working folder, and none of a packaged
    caller's PyInstaller state, which would make it run from (and lock) the caller's temp folder."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    if frozen_windows:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)  # children inherit the bootloader's DLL folder
    try:
        subprocess.Popen(command, cwd=home, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt",
                         close_fds=True)
    finally:
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))


def connect(home: Optional[Path] = None, command: Optional[List[str]] = None) -> BrainClient:
    """The brain running in ``home``; started as its own process when none runs, with ``command``
    or the way SentientMilk recorded. Two apps starting at once are fine: the brain lock lets one win."""
    home = Path(home or default_home())
    client = BrainClient.discover(home)
    if client is None:
        home.mkdir(parents=True, exist_ok=True)
        _spawn(command or launch_command(home), home)
        deadline = time.time() + START_TIMEOUT
        while client is None:
            if time.time() > deadline:
                raise BrainError("brain_unreachable", "The SentientMilk brain did not start",
                                 f"See {home / 'brain.log'}")
            time.sleep(0.2)
            client = BrainClient.discover(home)
    client.home, client.command = home, command
    return client
