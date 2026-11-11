"""SentientMilk as a local server: apps talk to the brain over HTTP on 127.0.0.1.

Every request needs the bearer token from ``<home>/server.json`` (readable by the user
only). One brain per home: ``brain.lock`` is held while it runs. Streams are server-sent
events. See README.md for the full API.
"""

import hmac
import json
import logging
import logging.handlers
import os
import queue
import secrets
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

from . import mentions, rewind
from .brain import Brain, validate_items, validate_name
from .client import DISCOVERY_FILE, default_home
from .exceptions import BrainError, classify
from .loop import TERMINAL
from .tray import Tray

logger = logging.getLogger(__name__)

API_VERSION = 2
MAX_BODY = 32 * 1024 * 1024
HEARTBEAT = 15
LOCK_FILE = "brain.lock"


class AlreadyRunning(RuntimeError):
    """Another brain holds this home."""


def _json(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


def _number(value, what: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")


def _short(event: dict) -> dict:
    """A logged event for streaming: big contents cut, images left out."""
    shown = {}
    for key, value in event.items():
        if isinstance(value, str) and len(value) > 2000:
            value = value[:2000] + " [...]"
        elif key == "content" and isinstance(value, list):
            value = [b if b.get("type") == "text" else {"type": "image"} for b in value]
        shown[key] = value
    return shown


class _Handler(BaseHTTPRequestHandler):
    server: "BrainServer"
    protocol_version = "HTTP/1.1"  # chunked responses deliver each event as it happens

    def log_message(self, format, *args):
        logger.debug("%s %s", self.address_string(), format % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    # ============== Plumbing ==============

    def _send(self, status: int, data) -> None:
        body = _json(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, kind: str, message: str) -> None:
        self._send(status, {"error": {"type": kind, "message": message, "details": None, "http_status": None}})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= MAX_BODY:
            raise OverflowError
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _dispatch(self, method: str) -> None:
        self.close_connection = True
        expected = f"Bearer {self.server.token}"
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            return self._fail(401, "unauthorized", "Missing or wrong token")
        try:
            url = urlsplit(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p]
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            body = self._body() if method in ("POST", "PATCH", "PUT") else {}
            if not parts or parts[0] != "v1" or not self._route(method, parts[1:], body, query):
                self._fail(404, "not_found", f"No {method} {url.path}")
        except OverflowError:
            self._fail(413, "bad_request", f"Request body is over {MAX_BODY} bytes")
        except (ValueError, KeyError, TypeError) as exc:
            self._fail(400, "bad_request", str(exc))
        except BrokenPipeError:
            pass
        except Exception as exc:
            error = classify(exc)
            if error.type == "unknown":
                logger.exception("%s %s failed", method, self.path)
            self._send(502, {"error": error.as_dict()})

    def _stream_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()

    def _stream(self, event: Optional[dict]) -> bool:
        """Send one event (None: a heartbeat); False when the app has gone away."""
        data = b": ping\n\n" if event is None else b"data: " + _json(event) + b"\n\n"
        try:
            self.wfile.write(b"%X\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()
            return True
        except OSError:
            return False

    def _stream_end(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass

    def _follow(self, key: tuple, listener: queue.Queue, until=lambda event: False, skip=lambda event: False) -> None:
        try:
            while True:
                try:
                    event = listener.get(timeout=HEARTBEAT)
                except queue.Empty:
                    if not self._stream(None) or self.server.closing:
                        return
                    continue
                if skip(event):
                    continue
                if not self._stream(event) or until(event):
                    return
        finally:
            self.server.brain.bus.unsubscribe(key, listener)
            self._stream_end()

    # ============== Routes ==============

    def _route(self, method: str, route: list, body: dict, query: dict) -> bool:
        brain = self.server.brain
        head, rest = route[0] if route else "", route[1:]
        if route == ["health"] and method == "GET":
            from . import __version__

            self._send(200, {"status": "ok", "api": API_VERSION, "pid": os.getpid(), "version": __version__,
                             "home": str(self.server.home), "started": self.server.started})
        elif route == ["shutdown"] and method == "POST":
            self._send(200, {"status": "ok"})
            threading.Thread(target=self.server.close, name="sentientmilk-shutdown", daemon=True).start()
        elif route == ["config"] and method == "GET":  # with the Claude Code that runs super agents
            self._send(200, {**brain.config.public(), "super": brain.superagents.status()})
        elif route == ["config"] and method == "PATCH":
            self._send(200, {**brain.config.update(body), "super": brain.superagents.status()})
        elif route == ["models"] and method == "POST":
            if not all(isinstance(body.get(key, ""), str) for key in ("base_url", "api_key")):
                raise ValueError("base_url and api_key must be strings")
            self._send(200, {"models": brain.models(body.get("base_url"), body.get("api_key"))})
        elif route == ["stats"] and method == "GET":
            self._send(200, brain.stats())
        elif route == ["apps"] and method == "GET":
            self._send(200, {"apps": brain.store.apps()})
        elif head == "apps" and rest:
            return self._app_route(method, validate_name(rest[0], "app id"), rest[1:], body, query)
        elif route == ["events"] and method == "GET":
            self._notifications(validate_name(query.get("app", ""), "app"), _number(query.get("after", 0), "after"))
        elif head == "tasks":
            return self._task_route(method, rest, body, query)
        elif head == "agents":
            return self._agent_route(method, rest, query)
        elif head == "runs" and len(rest) >= 1:
            return self._run_route(method, _number(rest[0], "run id"), rest[1:], body)
        elif head == "schedules":
            return self._schedule_route(method, rest, body, query)
        elif route == ["toolkits"] and method == "GET":
            app = query.get("app")
            self._send(200, {"toolkits": brain.toolkit_names(), "mcp": brain.mcp.status(),
                             **({"enabled": brain.profile(validate_name(app), "main")["toolkits"]} if app else {})})
        elif route == ["plugins"] and method == "GET":
            self._send(200, {"plugins": brain.plugins.public()})
        elif route == ["plugins"] and method == "POST":
            self._send(200, {"plugin": brain.install_plugin(body.get("source", ""))})
        elif head == "plugins" and len(rest) == 1 and method == "PATCH":
            unknown = set(body) - {"enabled", "settings", "trusted"}
            if unknown:
                raise ValueError(f"Unknown plugin fields: {sorted(unknown)}")
            self._send(200, {"plugin": brain.update_plugin(rest[0], body.get("enabled"), body.get("settings"),
                                                           body.get("trusted"))})
        elif head == "plugins" and len(rest) == 2 and rest[1] == "reload" and method == "POST":
            self._send(200, {"plugin": brain.reload_plugin(rest[0])})
        elif head == "plugins" and len(rest) == 1 and method == "DELETE":
            brain.remove_plugin(rest[0])
            self._send(200, {"status": "ok"})
        elif route == ["skills"] and method == "GET":
            self._send(200, {"skills": brain.skills.public()})
        elif head == "skills" and len(rest) == 1 and method == "DELETE":
            brain.skills.remove(rest[0])
            self._send(200, {"status": "ok"})
        elif route == ["mcp"] and method == "GET":
            from .mcp_host import public

            self._send(200, {**public(brain.mcp.config()), "status": brain.mcp.status()})
        elif route == ["mcp"] and method == "PUT":
            self._send(200, brain.mcp.set_config(body))
        elif head == "mcp" and len(rest) == 2 and rest[1] == "reconnect" and method == "POST":
            brain.mcp.reconnect(rest[0])
            self._send(200, {"status": "ok"})
        elif route == ["journal"] and method == "GET":
            self._send(200, {"notes": brain.store.notes(query.get("q", ""), _number(query.get("limit", 200), "limit"))})
        elif route == ["memory"] and method == "GET":
            self._send(200, {"entries": brain.store.memory_entries()})
        elif head == "memory" and len(rest) == 2 and method == "DELETE":
            found = brain.forget_memory(rest[0], rest[1])
            self._send(200 if found else 404, {"status": "ok" if found else "not found"})
        elif head == "journal" and len(rest) == 1 and method == "DELETE":
            self._send(200 if brain.store.delete_note(_number(rest[0], "note id")) else 404, {"status": "ok"})
        elif head == "jobs" and len(rest) == 1 and method == "GET":
            job = brain.store.job(_number(rest[0], "job id"))
            if not job:
                return False
            from .toolkits.shell import _lines

            self._send(200, {**job, "tail": _lines(job["log"])[-50:]})
        elif head == "jobs" and len(rest) == 2 and rest[1] == "stop" and method == "POST":
            job = brain.store.job(_number(rest[0], "job id"))
            if not job:
                return False
            from .toolkits.shell import stop

            self._send(200, {"job": job["id"], "message": stop(brain, job)})
        else:
            return False
        return True

    def _app_route(self, method: str, app: str, rest: list, body: dict, query: dict) -> bool:
        brain = self.server.brain
        if not rest and method == "PUT":
            self._send(200, brain.declare_app(app, body))
        elif not rest and method == "GET":
            self._send(200, brain.app_info(app))
        elif rest == ["settings"] and method == "PATCH":
            self._send(200, brain.update_app_settings(app, body))
        elif rest == ["sessions"] and method == "GET":
            self._send(200, {"sessions": brain.store.sessions(app)})
        elif rest == ['scheduled'] and method == 'GET':
            found = brain.runs.scheduled_pending(app) if query.get('pending', '1') == '1' else brain.store.occurrences(app)
            self._send(200, {'occurrences': found})
        elif rest == ["jobs"] and method == "GET":
            from .toolkits.shell import last_line

            try:
                since = float(query.get("since", 0))
            except ValueError:
                raise ValueError("since must be a time in seconds since the epoch")
            shown = ("id", "session", "command", "cwd", "status", "exit_code", "started", "ended")
            self._send(200, {"jobs": [{**{key: job[key] for key in shown}, "last": last_line(job["log"])}
                                      for job in brain.store.jobs(app, since)]})
        elif rest == ["mentions"] and method == "GET":
            session = validate_name(query.get("session", "main"), "session id")
            self._send(200, {"mentions": mentions.candidates(brain, app, session, query.get("q", ""),
                                                             query.get("kind") or None)})
        elif len(rest) == 2 and rest[0] == "mentions" and method == "GET":
            session = validate_name(query.get("session", "main"), "session id")
            self._send(200, {"card": mentions.card(brain, app, session, rest[1], query.get("ref", ""))})
        elif len(rest) >= 2 and rest[0] == "sessions":
            return self._session_route(method, app, validate_name(rest[1], "session id"), rest[2:], body, query)
        else:
            return False
        return True

    def _session_route(self, method: str, app: str, session: str, rest: list, body: dict, query: dict) -> bool:
        brain = self.server.brain
        if not rest and method == "GET":
            self._send(200, brain.session_info(app, session))
        elif not rest and method == "PATCH":
            self._send(200, brain.update_session_settings(app, session, body))
        elif not rest and method == "DELETE":
            if brain.session_busy(app, session):
                return self._fail(409, "busy", "A turn of this session is still going on; stop it first") or True
            brain.delete_session(app, session)
            self._send(200, {"status": "ok"})
        elif len(rest) == 2 and rest[0] == "memory" and method == "DELETE":
            found = brain.forget_session_memory(app, session, rest[1])
            self._send(200 if found else 404, {"status": "ok" if found else "not found"})
        elif rest == ["compact"] and method == "POST":
            self._send(200, brain.runs.compact(app, session))
        elif rest == ["history"] and method == "GET":
            self._send(200, {"history": brain.history(app, session, tools=query.get("tools") in ("1", "true"))})
        elif rest == ["history"] and method == "DELETE":
            brain.store.clear_session(app, session)
            self._send(200, {"status": "ok"})
        elif rest == ["rewind"] and method in ("GET", "POST"):
            if method == "POST" and set(body) - {"to"}:
                raise ValueError(f"Unknown rewind fields: {sorted(set(body) - {'to'})}")
            event = _number((query if method == "GET" else body).get("to"), "to (the id of a message the user sent)")
            try:
                self._send(200, (rewind.preview if method == "GET" else rewind.rewind)(brain, app, session, event))
            except BrainError as exc:
                if exc.http_status != 409:
                    raise
                return self._fail(409, exc.type, exc.message) or True
        elif rest == ["import"] and method == "POST":
            brain.import_history(app, session, body)
            self._send(200, {"status": "ok"})
        elif rest == ["turns"] and method == "POST":
            self._turn(app, session, body)
        else:
            return False
        return True

    def _turn(self, app: str, session: str, body: dict) -> None:
        unknown = set(body) - {"input", "context", "reply", "max_steps", 'occurrence'}
        if unknown:
            raise ValueError(f"Unknown turn fields: {sorted(unknown)}")
        occurrence = body.get('occurrence')
        if occurrence is not None and (type(occurrence) is not int or occurrence < 1):
            raise ValueError('occurrence must be a positive whole number')
        items = validate_items(body.get("input")) if occurrence is None else []
        context = body.get("context") or {}
        if not isinstance(context, dict) or not all(isinstance(v, str) for v in context.values()):
            raise ValueError("context must map names to strings")
        reply = body.get("reply", "required")
        if reply not in ("required", "optional"):
            raise ValueError("reply must be required or optional")
        steps = body.get("max_steps")
        if steps is not None and (not isinstance(steps, int) or isinstance(steps, bool) or steps < 1):
            raise ValueError("max_steps must be a whole number from 1")
        runs = self.server.brain.runs
        if occurrence is not None:
            # The durable owner/session check precedes claiming a live action consumer.
            found = self.server.brain.store.occurrence(app, occurrence)
            if found is None or found['session'] != session:
                raise BrainError('not_found', 'No scheduled occurrence belongs to this app and session', http_status=404)
            runs.claim_scheduled_stream(occurrence)
            try:
                run_id, listener, replay = runs.start_scheduled_turn(app, session, occurrence, context, steps)
                self._stream_turn(run_id, listener, replay)
            finally:
                runs.release_scheduled_stream(app, occurrence)
            return
        run_id, listener = runs.start_turn(app, session, items, context, reply, max_steps=steps)
        self._stream_turn(run_id, listener)

    def _stream_turn(self, run_id: int, listener, replay: bool = False) -> None:
        brain = self.server.brain
        replayed = set()
        self._stream_start()
        if self._stream({"type": "run.started", "run": run_id}):
            if replay:
                run = brain.store.run(run_id)
                logged_events = brain.store.run_events(run_id)
                for logged in logged_events:
                    if logged['type'] == 'tool':
                        common = {'run': run_id, 'call_id': logged['call_id'], 'name': logged['name'],
                                  'arguments': logged.get('arguments') or {}}
                        self._stream({'type': 'tool.start', **common})
                        self._stream({'type': 'tool.end', **common, 'status': logged['status'],
                                      'result': (logged.get('content') or '')[:2000]})
                        replayed.update((kind, logged['call_id']) for kind in ('tool.start', 'tool.end'))
                if run['status'] in TERMINAL:
                    if run['error']:
                        self._stream({'type': 'error', 'run': run_id, 'status': run['status'], 'error': run['error']})
                    else:
                        self._stream({'type': 'done', 'run': run_id, 'status': run['status'],
                                      **(run['result'] or {}), 'usage': run['usage']})
                    brain.bus.unsubscribe(('run', run_id), listener)
                    self._stream_end()
                    return
                for logged in logged_events:
                    if logged['type'] in ('action_result', 'tool'):
                        replayed.add(('action.requested', logged['call_id']))
                    if logged['type'] in ('approval', 'tool'):
                        replayed.add(('approval.requested', logged['call_id']))
                for waiting in brain.runs.waiting(run_id):
                    self._stream({'type': waiting['kind'] + '.requested', 'run': run_id,
                                  **{key: value for key, value in waiting.items() if key != 'kind'}})
                    replayed.add((waiting['kind'] + '.requested', waiting['call_id']))
            self._follow(("run", run_id), listener, until=lambda e: e["type"] in ("done", "error"),
                         skip=lambda event: (event['type'], event.get('call_id')) in replayed)
        else:
            self.server.brain.bus.unsubscribe(("run", run_id), listener)

    def _notifications(self, app: str, after: int) -> None:
        brain = self.server.brain
        listener = brain.bus.subscribe(("app", app))
        if after < 0:  # from now on
            after = brain.store.last_notification(app)
        self._stream_start()
        sent = after
        for notification in brain.store.notifications(app, after):
            if not self._stream(notification):
                brain.bus.unsubscribe(("app", app), listener)
                return
            sent = notification["id"]
        self._follow(("app", app), listener, skip=lambda n: n["id"] <= sent)

    def _task_route(self, method: str, rest: list, body: dict, query: dict) -> bool:
        brain = self.server.brain
        if not rest and method == "POST":
            unknown = set(body) - {"app", "session", "goal", "toolkits", "verify", "allow", "context", "max_steps", "cwd"}
            if unknown:
                raise ValueError(f"Unknown task fields: {sorted(unknown)}")
            if not isinstance(body.get("goal"), str) or not body["goal"].strip():
                raise ValueError("goal must be a non-empty string")
            app = validate_name(body.get("app", ""), "app")
            session = validate_name(body["session"], "session") if body.get("session") else None
            run_id = brain.runs.start_task(app, session, body["goal"].strip(), toolkits=body.get("toolkits"),
                                           verify=bool(body.get("verify")), allow=body.get("allow"),
                                           context=body.get("context", "compact"), max_steps=body.get("max_steps"),
                                           cwd=body.get("cwd"))
            self._send(200, brain.store.run(run_id))
        elif not rest and method == "GET":
            statuses = tuple(query["status"].split(",")) if query.get("status") else None
            kind = query.get("kind", "task")
            if kind not in ("task", "agent"):
                raise ValueError("kind must be task or agent")
            self._send(200, {"tasks": brain.store.runs(app=query.get("app"), kind=kind, statuses=statuses,
                                                       limit=_number(query.get("limit", 50), "limit"))})
        elif len(rest) >= 1:
            run = brain.store.run(_number(rest[0], "task id"))
            if not run or run["kind"] != "task":
                return False
            return self._run_route(method, run["id"], rest[1:], body)
        else:
            return False
        return True

    def _agent_route(self, method: str, rest: list, query: dict) -> bool:
        agents = self.server.brain.agents
        if not rest and method == "GET":
            app, session = validate_name(query.get("app", ""), "app"), validate_name(query.get("session", ""), "session")
            found = agents.all(app, session)
            self._send(200, {"agents": found if query.get("all") in ("1", "true") else [a for a in found if a["open"]]})
            return True
        if not rest:
            return False
        agent_id = _number(rest[0], "agent id")
        app = next((run["app"] for run in self.server.brain.store.runs(session=f"agent-{agent_id}", limit=1)), None)
        agent = agents.summary(app, f"agent-{agent_id}") if app else None
        if agent is None:
            return False
        if len(rest) == 1 and method == "GET":
            self._send(200, agents.details(app, agent))
        elif rest[1:] == ["stop"] and method == "POST":
            self._send(200, agents.stop(app, agent_id, by_user=True))
        else:
            return False
        return True

    def _run_route(self, method: str, run_id: int, rest: list, body: dict) -> bool:
        brain = self.server.brain
        run = brain.store.run(run_id)
        if not run:
            return False
        if not rest and method == "GET":
            waiting = brain.runs.waiting(run_id) if run["status"] == "input_required" else []
            self._send(200, {**run, "waiting": waiting})
        elif rest == ["events"] and method == "GET":
            listener = brain.bus.subscribe(("run", run_id))
            self._stream_start()
            for event in brain.store.run_events(run_id):
                if not self._stream({"type": "log", "event": _short(event)}):
                    brain.bus.unsubscribe(("run", run_id), listener)
                    return True
            if brain.store.run(run_id)["status"] in TERMINAL:
                brain.bus.unsubscribe(("run", run_id), listener)
                self._stream_end()
            else:
                self._follow(("run", run_id), listener, until=lambda e: e["type"] in ("done", "error"))
        elif rest == ["answer"] and method == "POST":
            unknown = set(body) - {"call_id", "decision", "reason", "result", "status", "question", "action", "content",
                                   "images"}
            if unknown:
                raise ValueError(f"Unknown answer fields: {sorted(unknown)}")
            brain.runs.answer(run_id, body.get("call_id", ""), body.get("decision"), body.get("reason", ""),
                              body.get("result"), body.get("status", "ok"), body.get("question"),
                              body.get("action", "decline"), body.get("content"), body.get("images"))
            self._send(200, {"status": "ok"})
        elif rest == ["cancel"] and method == "POST":
            brain.runs.cancel(run_id, body.get("reason") or "Cancelled.")
            self._send(200, {"status": "ok"})
        elif rest == ["steer"] and method == "POST":
            try:
                brain.runs.steer(run_id, validate_items(body.get("input")))
            except BrainError as exc:
                return self._fail(409, exc.type, exc.message) or True
            self._send(200, {"status": "ok"})
        elif rest == ["detach"] and method == "POST":
            brain.runs.detach(run_id)
            self._send(200, {"status": "ok"})
        else:
            return False
        return True

    def _schedule_route(self, method: str, rest: list, body: dict, query: dict) -> bool:
        brain = self.server.brain
        if not rest and method == "GET":
            self._send(200, {"schedules": brain.store.schedules(query.get("app"))})
        elif not rest and method == "POST":
            unknown = set(body) - {"app", "session", "when", "text", "mode", "catch_up", 'timezone', 'title'}
            if unknown:
                raise ValueError(f"Unknown schedule fields: {sorted(unknown)}")
            if body.get('mode', 'app') != 'app':  # 0.6 clients still say which; reminders are schedules now
                raise ValueError('There is one kind of schedule now: leave mode out (reminders are schedules too)')
            schedule = brain.scheduler.create(validate_name(body.get("app", ""), "app"),
                                              validate_name(body.get("session", "main"), "session"),
                                              body.get("when", ""), body.get("text", ""), created_by="app",
                                              catch_up=body.get("catch_up", "once"),
                                              timezone=body.get('timezone'), title=body.get('title', ''))
            self._send(200, schedule)
        elif len(rest) == 1 and method == "PATCH":
            self._send(200, brain.scheduler.update(_number(rest[0], "schedule id"), **body))
        elif len(rest) == 1 and method == "DELETE":
            found = brain.scheduler.delete(_number(rest[0], "schedule id"))
            self._send(200 if found else 404, {"status": "ok" if found else "not found"})
        else:
            return False
        return True


def _take_lock(home: Path):
    home.mkdir(parents=True, exist_ok=True)
    handle = open(home / LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise AlreadyRunning(f"Another brain is running in {home}")
    return handle


class BrainServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets a second socket take over a port with SO_REUSEADDR.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, home: Path, port: int = 0):
        self.home = Path(home)
        self._lock_handle = _take_lock(self.home)
        try:
            super().__init__(("127.0.0.1", port), _Handler)
        except BaseException:
            self._lock_handle.close()
            raise
        self.brain = Brain(self.home)
        self.token = secrets.token_urlsafe(32)
        self.started = time.time()
        self.closing = False
        self._close_lock = threading.Lock()
        self._closed = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def announce(self) -> None:
        """Write the discovery file atomically, readable by the user only."""
        fd, temporary = tempfile.mkstemp(prefix=".server-", suffix=".json", dir=self.home)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"url": self.url, "token": self.token, "pid": os.getpid(), "api": API_VERSION}, output)
        os.chmod(temporary, 0o600)
        _while_read(lambda: os.replace(temporary, self.home / DISCOVERY_FILE))

    def close(self) -> None:
        """Stop serving, stop the brain's threads and withdraw the discovery file if it is ours.
        A second caller waits for the first to finish (serve() exits the process right after)."""
        self.closing = True  # streams and the serve() loop end now
        with self._close_lock:
            if self._closed:
                return
            self.shutdown()
            self.server_close()
            self.brain.close()
            path = self.home / DISCOVERY_FILE
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("token") == self.token:
                    _while_read(path.unlink)
            except (OSError, ValueError):
                pass
            self._lock_handle.close()
            self._closed = True


def _while_read(change, tries: int = 40) -> None:
    """Windows refuses to delete or replace a file another process has open, as an app discovering the brain
    does for a moment: try again for up to 2 s."""
    for attempt in range(tries):
        try:
            return change()
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


def start(home: Optional[Path] = None, port: int = 0) -> BrainServer:
    """Serve from background threads and announce the address."""
    home = Path(home or default_home())
    server = BrainServer(home, port)
    threading.Thread(target=server.serve_forever, name="sentientmilk-server", daemon=True).start()
    server.brain.start()
    server.announce()
    logger.info("SentientMilk brain listening on %s (home %s)", server.url, home)
    return server


def serve(home: Optional[Path] = None, port: int = 0, log_file: bool = False) -> None:
    """Serve until stopped: from the tray icon, the control panel (POST /v1/shutdown) or Ctrl+C. The brain is
    a background service and never stops on its own."""
    home = Path(home or default_home())
    if log_file:
        home.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(home / "brain.log", maxBytes=1_000_000, backupCount=2,
                                                       encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
    try:
        server = start(home, port)
    except AlreadyRunning as exc:
        print(exc, flush=True)
        return
    print(f"SentientMilk brain on {server.url}; token in {server.home / DISCOVERY_FILE}", flush=True)
    tray = Tray(server.home, stop=lambda: threading.Thread(target=server.close, name="sentientmilk-shutdown",
                                                           daemon=True).start())
    tray.show(server.brain.config.values()["model"])
    try:
        while not server.closing:  # closed by POST /v1/shutdown or the tray
            time.sleep(0.5)  # Ctrl+C interrupts this on Windows too, unlike Event.wait()
            tray.update(server.brain.busy(), server.brain.config.values()["model"])
    except KeyboardInterrupt:
        pass
    finally:
        tray.close()
        server.close()


__all__ = ["AlreadyRunning", "BrainError", "BrainServer", "serve", "start"]
