"""The brain: one shared mind that several apps think with.

An app declares itself (name, environment, default persona, the signals it wants,
the toolkits it uses and the actions it runs itself). The user's choices for that
app (persona, model, rules, switched-off toolkits) are kept apart as its settings.
Every conversation is a session of an app; every piece of work is a run.
"""

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from . import context, permissions, transport
from . import signals as signal_format
from .config import BrainConfig, validate_rules, validate_setting
from .journal import Journal
from .loop import ACTIVE, Toolset, build_toolset
from .mcp_host import McpHost
from .provider import Provider
from .runs import Bus, Runs
from .scheduler import Scheduler
from .store import Store
from .toolkits import builtin, load_plugins
from .toolkits.shell import shell_name

logger = logging.getLogger(__name__)

NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
DEFAULT_PERSONA = "You are a helpful, capable assistant."
DEFAULT_TOOLKITS = ["memory", "todo", "journal", "web"]
DECLARATION = {"name": str, "environment": str, "persona": str, "signals": dict, "actions": list,
               "toolkits": list, "rules": dict, "roots": list, "journal": dict}
APP_SETTINGS = {"persona": (str, type(None)), "model": str, "disabled_toolkits": list, "rules": dict,
                "roots": list, "journal": dict}
SESSION_SETTINGS = {"instructions": str, "disabled_toolkits": list, "rules": dict, "roots": list, "cwd": str,
                    "title": str}
TITLE_CHARS = 80
ITEM_TYPES = ("text", "image", "event")


def validate_name(value: Any, what: str = "id") -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError(f"{what} must be 1-64 letters, digits, '.', '_' or '-'")
    return value


def _check_fields(data: Any, fields: dict, what: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"{what} must be an object")
    unknown = set(data) - set(fields)
    if unknown:
        raise ValueError(f"Unknown {what} fields: {sorted(unknown)}")
    for key, kind in fields.items():
        if key in data and not isinstance(data[key], kind):
            names = "/".join(k.__name__ for k in kind) if isinstance(kind, tuple) else kind.__name__
            raise ValueError(f"{what}.{key} must be a {names}")
    for key in ("toolkits", "disabled_toolkits", "roots"):
        if key in data and not all(isinstance(item, str) and item for item in data[key]):
            raise ValueError(f"{what}.{key} must be a list of names")
    if "rules" in data:
        data["rules"] = validate_rules(data["rules"])
    if "journal" in data and (set(data["journal"]) - {"read", "write"} or
                              not all(isinstance(v, bool) for v in data["journal"].values())):
        raise ValueError(f"{what}.journal must be {{read: bool, write: bool}}")
    return data


def validate_declaration(data: Any) -> dict:
    data = _check_fields(dict(data) if isinstance(data, dict) else data, DECLARATION, "declaration")
    if "signals" in data:
        signal_format.validate(data["signals"])
    for action in data.get("actions", []):
        if not isinstance(action, dict) or not TOOL_NAME.fullmatch(str(action.get("name", ""))):
            raise ValueError("each action needs a name of letters, digits, '_' or '-'")
        if not isinstance(action.get("description", ""), str) or not isinstance(action.get("parameters", {}), dict):
            raise ValueError(f"action {action['name']}: description must be a string, parameters a JSON schema")
        if action.get("policy", "auto") not in ("auto", "ask"):
            raise ValueError(f"action {action['name']}: policy must be auto or ask")
    return data


def validate_items(items: Any) -> List[dict]:
    """Turn input: text, image (data URL) and event items; images are stored at the size they are sent."""
    if not isinstance(items, list) or not items:
        raise ValueError("input must be a non-empty list of items")
    result = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in ITEM_TYPES:
            raise ValueError(f"each input item needs a type: {', '.join(ITEM_TYPES)}")
        if item["type"] == "text":
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                raise ValueError("text items need non-empty text")
            result.append({"type": "text", "text": item["text"]})
        elif item["type"] == "image":
            url = transport.validate_image(item.get("url") or item.get("data"))
            result.append({"type": "image", "url": transport.encode_image(url, transport.IMAGE)})
        else:
            if not isinstance(item.get("name"), str) or not item["name"].strip():
                raise ValueError("event items need a name")
            if not isinstance(item.get("text", ""), str) or not isinstance(item.get("data", {}), dict):
                raise ValueError("event text must be a string and data an object")
            result.append({"type": "event", "name": item["name"], "text": item.get("text", ""),
                           **({"data": item["data"]} if item.get("data") else {})})
    return result


class Brain:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.config = BrainConfig(self.home / "config.json")
        self.store = Store(self.home / "brain.sqlite3")
        self.bus = Bus()
        self.jobs: Dict[int, Any] = {}
        self.plugins = load_plugins(self.home / "toolkits")
        self.mcp = McpHost(self)
        self.runs = Runs(self)
        self.scheduler = Scheduler(self)
        self.journal = Journal(self)
        self._started = False
        self._stopping = threading.Event()

    def start(self) -> None:
        """Recover interrupted work and start the background threads."""
        if self._started:
            return
        self._started = True
        for job in self.store.running_jobs():  # their processes ended with the last brain
            self.store.update_job(job, status="lost", ended=time.time())
        self.runs.start()
        self.scheduler.start()
        self.journal.start()
        self.mcp.start()

    def close(self) -> None:
        self._stopping.set()
        self.scheduler.stop()
        self.journal.stop()
        self.runs.stop()
        self.mcp.stop()

    # ============== Apps ==============

    def declare_app(self, app: str, declaration: dict) -> dict:
        validate_name(app, "app id")
        self.store.put_app(app, declaration=validate_declaration(declaration))
        return self.app_info(app)

    def app_info(self, app: str) -> dict:
        record = self.store.app(validate_name(app, "app id")) or {"declaration": {}, "settings": {}}
        profile = self.profile(app, "main")
        return {"id": app, "declaration": record["declaration"], "settings": record["settings"],
                "persona": profile["persona"], "persona_custom": bool(record["settings"].get("persona")),
                "toolkits": profile["toolkits"]}

    def update_app_settings(self, app: str, changes: dict) -> dict:
        changes = _check_fields(changes, APP_SETTINGS, "settings")
        record = self.store.app(validate_name(app, "app id")) or {"declaration": {}, "settings": {}}
        settings = {**record["settings"], **changes}
        if "persona" in changes:
            settings["persona"] = (changes["persona"] or "").strip() or None
        if "model" in changes:
            settings["model"] = changes["model"].strip()
        self.store.put_app(app, settings={k: v for k, v in settings.items() if v not in (None, "")})
        return self.app_info(app)

    def allow_always(self, app: str, rule: str) -> None:
        record = self.store.app(app) or {"declaration": {}, "settings": {}}
        rules = permissions.merge(record["settings"].get("rules"))
        if rule not in rules["allow"]:
            rules["allow"].append(rule)
        self.store.put_app(app, settings={**record["settings"], "rules": rules})

    def toolkit_names(self) -> List[str]:
        return list(builtin()) + list(self.plugins) + [f"mcp:{name}" for name in self.mcp.servers()]

    def profile(self, app: str, session: str, overrides: Optional[dict] = None) -> dict:
        """Everything a run of this session needs to know about who it is and what it may do."""
        overrides = overrides or {}
        record = self.store.app(app) or {"declaration": {}, "settings": {}}
        declaration, settings = record["declaration"], record["settings"]
        # Tasks and helpers work with the settings of the session that started them.
        base_session = overrides.get("from_session") or session
        session_settings = self.store.session(app, base_session)["settings"]
        if base_session != session:
            own = self.store.session(app, session)["settings"]
            session_settings = {**session_settings, **{k: v for k, v in own.items() if k == "instructions"}}
        values = self.config.values()
        disabled = set(values["disabled_toolkits"]) | set(settings.get("disabled_toolkits", [])) | \
            set(session_settings.get("disabled_toolkits", []))
        journal = {"read": True, "write": True, **declaration.get("journal", {}), **settings.get("journal", {})}
        known = self.toolkit_names()
        wanted = []
        for name in declaration.get("toolkits", DEFAULT_TOOLKITS):
            wanted += [k for k in known if k.startswith("mcp:")] if name == "mcp:*" else [name]
        toolkits = [k for k in dict.fromkeys(wanted) if k in known and k not in disabled
                    and not (k == "journal" and not journal["read"])]
        if overrides.get("toolkits"):
            toolkits = [k for k in toolkits if k in overrides["toolkits"]]
        instructions = "\n\n".join(filter(None, [session_settings.get("instructions", ""),
                                                 overrides.get("instructions", "")]))
        rules = permissions.merge(values["rules"], declaration.get("rules"), settings.get("rules"),
                                  session_settings.get("rules"), {"allow": overrides.get("allow", [])})
        roots = [str(Path(r).expanduser().resolve()) for r in
                 declaration.get("roots", []) + settings.get("roots", []) + session_settings.get("roots", [])]
        return {
            "app": app, "session": session, "name": declaration.get("name") or app,
            "environment": declaration.get("environment", ""),
            "persona": settings.get("persona") or declaration.get("persona") or DEFAULT_PERSONA,
            "instructions": instructions,
            "signals": {} if overrides.get("signals") is False else signal_format.validate(declaration.get("signals", {})),
            "actions": [] if overrides.get("mode") else declaration.get("actions", []),
            "toolkits": toolkits, "rules": rules, "roots": list(dict.fromkeys(roots)),
            "cwd": overrides.get("cwd") or session_settings.get("cwd"), "journal": journal,
            "mode": overrides.get("mode"),
            "model": settings.get("model") or values["model"], "light_model": values["light_model"],
            "context_window": values["context_window"],
        }

    def toolset(self, profile: dict, kind: str) -> Toolset:
        kits = {**builtin(), **self.plugins, **self.mcp.toolkits()}
        return build_toolset(kits, profile, kind, self.shell_label())

    def shell_label(self) -> str:
        return {"powershell": "Windows PowerShell 5.1", "pwsh": "PowerShell 7", "bash": "bash", "sh": "sh",
                "cmd": "cmd.exe"}[shell_name(self.config.values()["shell"])]

    def provider(self, model: str) -> Provider:
        values = self.config.values()
        return Provider(values["base_url"], values["api_key"], model, thinking_mode=values["thinking_mode"],
                        thinking_tokens=values["thinking_tokens"], stream=values["stream"])

    # ============== Sessions ==============

    def session_snapshot(self, profile: dict) -> dict:
        state = self.store.session(profile["app"], profile["session"])["state"]
        return state.get("snapshot") or self.refresh_snapshot(profile)

    def refresh_snapshot(self, profile: dict) -> dict:
        taken = context.snapshot(self.store, profile)

        def change(state):
            state["snapshot"] = taken
            return state
        self.store.update_session(profile["app"], profile["session"], "state", change)
        return taken

    def session_info(self, app: str, session: str) -> dict:
        record = self.store.session(validate_name(app, "app id"), validate_name(session, "session id"))
        state = record["state"]
        return {"app": app, "id": session, "settings": record["settings"], "todo": state.get("todo", []),
                "created": record["created"],
                "context": {"used": state.get("context_tokens", 0), "window": self.config.values()["context_window"],
                            "clear_at": context.CLEAR_AT, "compact_at": context.COMPACT_AT}}

    def update_session_settings(self, app: str, session: str, changes: dict) -> dict:
        changes = _check_fields(changes, SESSION_SETTINGS, "session settings")
        if "title" in changes:
            changes["title"] = " ".join(changes["title"].split())
            if len(changes["title"]) > TITLE_CHARS:
                raise ValueError(f"session title must be at most {TITLE_CHARS} characters")
        if "cwd" in changes and changes["cwd"]:
            changes["cwd"] = str(Path(changes["cwd"]).expanduser().resolve())

        def change(settings):
            settings.update(changes)
            return {k: v for k, v in settings.items() if v not in ("", None)}
        self.store.update_session(validate_name(app, "app id"), validate_name(session, "session id"), "settings", change)
        return self.session_info(app, session)

    def session_busy(self, app: str, session: str) -> bool:
        """A run of this session is going on or waits for answers."""
        return any(run["session"] == session for run in self.store.runs(app=app, statuses=ACTIVE, limit=1000))

    def history(self, app: str, session: str, tools: bool = False) -> List[dict]:
        """The conversation as apps show it: what the user said and what the brain replied; with
        ``tools`` also each tool call between them (its output capped as in live tool events)."""
        entries, started = [], {}
        types = ("input", "end", "shown") + (("tool_start", "action_request", "tool") if tools else ())
        for event in self.store.events(app, session, types=types):
            if event["type"] in ("tool_start", "action_request"):
                started[event["call_id"]] = event["at"]
            elif event["type"] == "tool":
                start = started.get(event["call_id"])
                entries.append({"role": "tool", "call_id": event["call_id"], "name": event["name"],
                                "arguments": event.get("arguments") or {}, "status": event["status"],
                                "text": event["content"][:2000], "time": event["at"],
                                "seconds": None if start is None else round(event["at"] - start, 3)})
            elif event["type"] == "shown":
                entries.append({"role": event["role"], "text": event["text"], "time": event["at"]})
            elif event["type"] == "input" and event.get("display"):
                entries.append({"role": "user", "text": event["display"], "time": event["at"]})
            elif event["type"] == "end" and event.get("reply"):
                entries.append({"role": "assistant", "text": event["reply"], "signals": event.get("signals") or {},
                                "time": event["at"]})
        return entries

    def import_history(self, app: str, session: str, data: dict) -> None:
        """History and memories an app kept before it used the brain; history only into an empty session."""
        messages, memory, shown = data.get("messages", []), data.get("memory", {}), data.get("transcript")
        if not isinstance(messages, list) or not all(isinstance(m, dict) and m.get("role") in
                                                     ("user", "assistant", "tool", "system") for m in messages):
            raise ValueError("messages must be a list of chat messages")
        if shown is not None and not (isinstance(shown, list) and all(
                isinstance(e, dict) and e.get("role") in ("user", "assistant") and isinstance(e.get("text"), str)
                for e in shown)):
            raise ValueError("transcript must be a list of {role: user|assistant, text}")
        if not isinstance(memory, dict) or not all(isinstance(items, dict) for items in memory.values()):
            raise ValueError("memory must be {category: {key: value}}")
        for category, items in memory.items():
            for key, value in items.items():
                self.store.remember(app, category, key, value, replace=False)
        if not messages and not shown:
            return
        if self.store.events(app, session):
            raise ValueError(f"Session {app}/{session} already has history")
        for entry in shown or []:  # what the app showed, kept apart from what the model sees
            self.store.add_event(app, session, None, "shown", {"role": entry["role"], "text": entry["text"]})
        names = {}
        for message in messages:
            role = message["role"]
            if role == "user":
                content = message.get("content") or ""
                display = None if shown is not None else message.get(
                    "display", content if isinstance(content, str) else None)
                self.store.add_event(app, session, None, "input", {"content": content, "display": display})
            elif role == "assistant":
                self.store.add_event(app, session, None, "assistant", {"message": message, "usage": {}})
                for call in message.get("tool_calls") or []:
                    names[call.get("id")] = (call.get("function") or {}).get("name", "")
                if not message.get("tool_calls") and shown is None:
                    reply = message.get("reply")
                    if reply is None:
                        reply = signal_format.split(message.get("content") or "")[1]
                    self.store.add_event(app, session, None, "end", {"status": "completed", "reply": reply,
                                                                     "signals": {}, "silent": False})
            elif role == "tool":
                call_id = message.get("tool_call_id", "")
                self.store.add_event(app, session, None, "tool", {
                    "call_id": call_id, "name": names.get(call_id, ""), "arguments": {},
                    "content": str(message.get("content") or ""), "status": "ok"})
            else:
                self.store.add_event(app, session, None, "note", {"text": str(message.get("content") or "")})

    # ============== Telling ==============

    def note(self, app: str, session: str, text: str) -> None:
        """Something the model should know at its next step in that session (a task ended, a job finished)."""
        self.store.add_event(app, session, None, "note", {"text": text})

    def notify(self, app: str, session: Optional[str], type: str, data: dict) -> None:
        notification = self.store.notify(app, session, type, data)
        self.bus.publish(("app", app), notification)

    # ============== Provider ==============

    def models(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> list:
        """Model ids the provider offers; the stored key is only ever sent to the stored URL."""
        values = self.config.values()
        url = validate_setting("base_url", base_url or "") or values["base_url"]
        key = api_key or (values["api_key"] if url == values["base_url"] else "")
        response = requests.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"} if key else {},
                                timeout=15)
        response.raise_for_status()
        data = response.json()
        entries = data.get("data", []) if isinstance(data, dict) else data
        return sorted({entry["id"] for entry in entries
                       if isinstance(entry, dict) and isinstance(entry.get("id"), str)}, key=str.lower)

    def busy(self) -> bool:
        """Work going on now: runs, and background commands (jobs)."""
        return self.runs.busy() or bool(self.jobs)

    def stats(self) -> dict:
        totals: Dict[str, Dict[str, int]] = {}
        for run in self.store.runs(limit=100000):
            usage = run["usage"] or {}
            entry = totals.setdefault(run["app"], {"runs": 0, "calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
                                                   "completion_tokens": 0})
            entry["runs"] += 1
            for key in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens"):
                entry[key] += usage.get(key) or 0
        for entry in totals.values():
            entry["cache_hit_rate"] = round(entry["cached_tokens"] / entry["prompt_tokens"], 3) \
                if entry["prompt_tokens"] else None
        return {"apps": totals}
