"""Talk to the SentientMilk brain from an app.

    client = connect()                                  # the running brain, started if needed
    client.declare_app("jarvis", name="Jarvis", environment="...", toolkits=["memory", "web"])
    result = client.turn("jarvis", "main", text="Hello!", on_event=print)
    result["reply"], result["signals"], result["tools"]

The brain runs as its own process (``sentientmilk serve``), announces its address and
token in ``<home>/server.json`` and exits after a while with nothing to do; the client
starts it again when it is gone.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import requests

from .exceptions import BrainError

DISCOVERY_FILE = "server.json"
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

    def app(self, app: str) -> dict:
        return self._call("GET", f"/apps/{app}")

    def update_app(self, app: str, **settings: Any) -> dict:
        """The user's settings for an app: persona ("" resets), model, rules, disabled_toolkits, roots, journal."""
        return self._call("PATCH", f"/apps/{app}/settings", settings)

    def sessions(self, app: str) -> List[dict]:
        return self._call("GET", f"/apps/{app}/sessions")["sessions"]

    def session(self, app: str, session: str) -> dict:
        return self._call("GET", f"/apps/{app}/sessions/{session}")

    def update_session(self, app: str, session: str, **settings: Any) -> dict:
        """instructions, cwd, roots, rules, disabled_toolkits for one session."""
        return self._call("PATCH", f"/apps/{app}/sessions/{session}", settings)

    def history(self, app: str, session: str) -> List[dict]:
        return self._call("GET", f"/apps/{app}/sessions/{session}/history")["history"]

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
             on_event: Optional[Callable[[dict], None]] = None,
             on_approval: Optional[Callable[[dict], Any]] = None) -> dict:
        """One turn. Events reach ``on_event`` as they happen. ``on_approval(event)`` answers approval
        requests with "allow", "always", "deny" or ("deny", reason); without it they are denied."""
        inputs = list(items or [])
        if text:
            inputs.append({"type": "text", "text": text})
        if image:
            inputs.append({"type": "image", "url": image})
        payload = {"input": inputs, "context": context or {}, "reply": reply}
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
                self.answer(run, call_id=event["call_id"], decision=decision, reason=reason)
            elif event["type"] == "done":
                return {"run": run, "reply": event["reply"], "signals": event["signals"], "silent": event["silent"],
                        "status": event["status"], "usage": event.get("usage"), "tools": tools}
            elif event["type"] == "error":
                raise BrainError(**event["error"])
        raise BrainError("brain_unreachable", "The brain ended the turn without an answer")

    # ============== Runs and tasks ==============

    def run(self, run: int) -> dict:
        return self._call("GET", f"/runs/{run}")

    def answer(self, run: int, **answer: Any) -> None:
        """call_id + decision (allow/always/deny) + reason; call_id + result for actions;
        question + action (accept/decline/cancel) + content for questions."""
        self._call("POST", f"/runs/{run}/answer", answer)

    def cancel(self, run: int) -> None:
        self._call("POST", f"/runs/{run}/cancel", {})

    def detach(self, run: int) -> None:
        self._call("POST", f"/runs/{run}/detach", {})

    def start_task(self, app: str, goal: str, session: Optional[str] = None, **options: Any) -> dict:
        """toolkits, verify, allow (rules), context (compact/reset), max_steps, cwd."""
        return self._call("POST", "/tasks", {"app": app, "goal": goal, **({"session": session} if session else {}),
                                             **options})

    def tasks(self, app: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        params = {key: value for key, value in (("app", app), ("status", status)) if value}
        return self._call("GET", "/tasks", params=params)["tasks"]

    def run_events(self, run: int) -> Iterator[dict]:
        """What a run did so far ("log" events), then live events until it ends."""
        return self._stream("GET", f"/runs/{run}/events")

    def events(self, app: str, after: int = 0) -> Iterator[dict]:
        """Notifications for an app (tasks, jobs, schedules), from ``after`` on, then live."""
        return self._stream("GET", "/events", params={"app": app, "after": after})

    # ============== Schedules, toolkits, journal ==============

    def schedules(self, app: Optional[str] = None) -> List[dict]:
        return self._call("GET", "/schedules", params={"app": app} if app else None)["schedules"]

    def create_schedule(self, app: str, when: str, text: str, mode: str = "wake", session: str = "main",
                        catch_up: str = "once") -> dict:
        return self._call("POST", "/schedules", {"app": app, "session": session, "when": when, "text": text,
                                                 "mode": mode, "catch_up": catch_up})

    def enable_schedule(self, schedule: int, enabled: bool) -> dict:
        return self._call("PATCH", f"/schedules/{schedule}", {"enabled": enabled})

    def delete_schedule(self, schedule: int) -> None:
        self._call("DELETE", f"/schedules/{schedule}")

    def toolkits(self, app: Optional[str] = None) -> dict:
        return self._call("GET", "/toolkits", params={"app": app} if app else None)

    def mcp(self) -> dict:
        return self._call("GET", "/mcp")

    def set_mcp(self, servers: Dict[str, dict]) -> dict:
        return self._call("PUT", "/mcp", {"servers": servers})

    def journal(self, query: str = "") -> List[dict]:
        return self._call("GET", "/journal", params={"q": query} if query else None)["notes"]

    def delete_note(self, note: int) -> None:
        self._call("DELETE", f"/journal/{note}")


def brain_command(home: Path) -> List[str]:
    return [sys.executable, "-m", "sentientmilk_framework", "--home", str(home), "serve", "--log"]


def connect(home: Optional[Path] = None, command: Optional[List[str]] = None) -> BrainClient:
    """The brain running in ``home``; started as its own process when none runs.

    ``command`` starts it (default: this Python with ``-m sentientmilk_framework serve``); packaged
    apps pass their own executable. Two apps starting at once are fine: the brain lock lets one win.
    """
    home = Path(home or default_home())
    client = BrainClient.discover(home)
    if client is None:
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        subprocess.Popen(command or brain_command(home), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt",
                         close_fds=True)
        deadline = time.time() + START_TIMEOUT
        while client is None:
            if time.time() > deadline:
                raise BrainError("brain_unreachable", "The SentientMilk brain did not start",
                                 f"See {home / 'brain.log'}")
            time.sleep(0.2)
            client = BrainClient.discover(home)
    client.home, client.command = home, command
    return client
