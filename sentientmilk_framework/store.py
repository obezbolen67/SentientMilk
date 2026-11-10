"""Everything the brain keeps, in one SQLite file (WAL, one connection per call).

The ``events`` table is the single source of truth for every conversation: model
messages and the transcript apps show are both projections of it.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id TEXT PRIMARY KEY, declaration TEXT NOT NULL DEFAULT '{}', settings TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    app TEXT NOT NULL, id TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, PRIMARY KEY (app, id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, app TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL,
    parent INTEGER, status TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}', result TEXT,
    error TEXT, usage TEXT, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_status ON runs(status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, app TEXT NOT NULL, session TEXT NOT NULL, run INTEGER,
    at REAL NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_session ON events(app, session, id);
CREATE INDEX IF NOT EXISTS events_by_run ON events(run, id);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, run INTEGER, app TEXT NOT NULL, session TEXT NOT NULL,
    command TEXT NOT NULL, cwd TEXT, pid INTEGER, status TEXT NOT NULL, exit_code INTEGER,
    log TEXT NOT NULL, started REAL NOT NULL, ended REAL
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY, app TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL,
    spec TEXT NOT NULL, payload TEXT NOT NULL, next_at REAL, last_at REAL,
    catch_up TEXT NOT NULL, created_by TEXT NOT NULL, enabled INTEGER NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_ids (id INTEGER PRIMARY KEY AUTOINCREMENT);
INSERT OR IGNORE INTO schedule_ids(id) SELECT id FROM schedules;
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL, session TEXT,
    type TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notifications_by_app ON notifications(app, id);
CREATE TABLE IF NOT EXISTS schedule_occurrences (
    id INTEGER PRIMARY KEY, schedule INTEGER NOT NULL, app TEXT NOT NULL, session TEXT NOT NULL,
    scheduled_at REAL NOT NULL, queued_at REAL NOT NULL, payload TEXT NOT NULL, late INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending', run INTEGER, finished_at REAL,
    UNIQUE(schedule, scheduled_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS occurrence_active ON schedule_occurrences(schedule)
    WHERE status IN ('pending', 'started');
CREATE INDEX IF NOT EXISTS occurrences_by_app ON schedule_occurrences(app, status, id);
CREATE TABLE IF NOT EXISTS memory (
    app TEXT NOT NULL, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
    updated REAL NOT NULL, PRIMARY KEY (app, category, key)
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL, session TEXT NOT NULL, note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_mail (
    id INTEGER PRIMARY KEY, app TEXT NOT NULL, parent TEXT NOT NULL, agent INTEGER NOT NULL, run INTEGER,
    kind TEXT NOT NULL, text TEXT NOT NULL, data TEXT NOT NULL, at REAL NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS agent_mail_by_parent ON agent_mail(app, parent, delivered);
CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY, app TEXT NOT NULL, chat TEXT NOT NULL, session TEXT NOT NULL, run INTEGER,
    started REAL NOT NULL, key TEXT NOT NULL, path TEXT NOT NULL, since INTEGER NOT NULL, content BLOB,
    at REAL NOT NULL, UNIQUE (app, session, key, since)
);
CREATE INDEX IF NOT EXISTS file_versions_by_chat ON file_versions(app, chat);
"""
NOTIFICATION_DAYS = 7
NOTIFICATIONS_PER_APP = 1000
PREVIEW_CHARS = 120  # of a session's first message, shown until it has a title


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(text: Optional[str]) -> Any:
    return json.loads(text) if text else None


def _event(row) -> dict:
    return {"id": row[0], "app": row[1], "session": row[2], "run": row[3], "at": row[4], "type": row[5],
            **json.loads(row[6])}


def _run(row) -> Optional[dict]:
    if not row:
        return None
    keys = ("id", "app", "session", "kind", "parent", "status", "options", "result", "error", "usage",
            "created", "updated")
    run = dict(zip(keys, row))
    for key in ("options", "result", "error", "usage"):
        run[key] = _load(run[key])
    run["options"] = run["options"] or {}
    return run


_RUN_COLUMNS = "id, app, session, kind, parent, status, options, result, error, usage, created, updated"
_EVENT_COLUMNS = "id, app, session, run, at, type, data"


JOB_KEYS = ("id", "run", "app", "session", "command", "cwd", "pid", "status", "exit_code", "log", "started",
            "ended")

class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")  # readers never wait for a running turn
            db.executescript(_SCHEMA)
        finally:
            db.close()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")  # writers queue up instead of losing each other's updates
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    # ============== Apps and sessions ==============

    def app(self, app: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT declaration, settings FROM apps WHERE id = ?", (app,)).fetchone()
        return {"declaration": json.loads(row[0]), "settings": json.loads(row[1])} if row else None

    def apps(self) -> List[str]:
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT id FROM apps ORDER BY id")]

    def put_app(self, app: str, declaration: Optional[dict] = None, settings: Optional[dict] = None) -> None:
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO apps(id) VALUES (?)", (app,))
            if declaration is not None:
                db.execute("UPDATE apps SET declaration = ? WHERE id = ?", (dump(declaration), app))
            if settings is not None:
                db.execute("UPDATE apps SET settings = ? WHERE id = ?", (dump(settings), app))

    def session(self, app: str, session: str) -> dict:
        """Settings and state of a session; a new session is created on first use."""
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO sessions(app, id, created) VALUES (?, ?, ?)",
                       (app, session, time.time()))
            row = db.execute("SELECT settings, state, created FROM sessions WHERE app = ? AND id = ?",
                             (app, session)).fetchone()
        return {"app": app, "id": session, "settings": json.loads(row[0]), "state": json.loads(row[1]),
                "created": row[2]}

    def sessions(self, app: str) -> List[dict]:
        """Each session with its ``title`` (None until named) and ``preview``, the start of the first message."""
        with self._db() as db:
            rows = db.execute(
                "SELECT s.id, s.created, s.settings, MAX(e.at) FROM sessions s LEFT JOIN events e "
                "ON e.app = s.app AND e.session = s.id WHERE s.app = ? GROUP BY s.id ORDER BY s.id",
                (app,)).fetchall()
            inputs = db.execute("SELECT session, data FROM events WHERE app = ? AND type = 'input' ORDER BY id",
                                (app,)).fetchall()
        previews: Dict[str, str] = {}
        for session, data in inputs:
            if session not in previews:
                display = json.loads(data).get("display")
                if display:
                    previews[session] = " ".join(display.split())[:PREVIEW_CHARS]
        return [{"id": sid, "created": created, "last_active": last, "title": json.loads(settings).get("title"),
                 "preview": previews.get(sid, "")} for sid, created, settings, last in rows]

    def has_session(self, app: str, session: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM sessions WHERE app = ? AND id = ?", (app, session)).fetchone() is not None

    def find_session(self, app: str, session: str) -> Optional[dict]:
        """Like ``session`` but never creates one: None when there is no such session (a reader that comes
        late, after the user deleted it, must not bring it back)."""
        with self._db() as db:
            row = db.execute("SELECT settings, state, created FROM sessions WHERE app = ? AND id = ?",
                             (app, session)).fetchone()
        return {"app": app, "id": session, "settings": json.loads(row[0]), "state": json.loads(row[1]),
                "created": row[2]} if row else None

    def child_sessions(self, app: str, parent: str) -> List[tuple]:
        """(session, settings) of the agents ``parent`` started, the oldest first."""
        return [(session, settings) for _, session, settings in self.agent_sessions(app, parent)]

    def agent_sessions(self, app: Optional[str] = None, parent: Optional[str] = None) -> List[tuple]:
        """(app, session, settings) of every agent, or of an app's, or of those ``parent`` started."""
        query, params = "SELECT app, id, settings FROM sessions WHERE json_extract(settings, '$.agent') IS NOT NULL", []
        if app is not None:
            query, params = query + " AND app = ?", params + [app]
        if parent is not None:
            query, params = query + " AND json_extract(settings, '$.agent.parent') = ?", params + [parent]
        with self._db() as db:
            rows = db.execute(query + " ORDER BY created", params).fetchall()
        return [(app_, session, json.loads(settings)) for app_, session, settings in rows]

    def delete_session(self, app: str, session: str) -> None:
        """An agent's versions stay with the chat they were made for: a return there still restores them."""
        with self._db() as db:
            db.execute("UPDATE schedules SET enabled = 0, next_at = NULL WHERE app = ? "
                       "AND json_extract(payload, '$.mode') = 'app' AND json_extract(payload, '$.session') = ?",
                       (app, session))
            db.execute("UPDATE schedule_occurrences SET status = 'cancelled', finished_at = ? "
                       "WHERE app = ? AND session = ? AND status = 'pending'", (time.time(), app, session))
            db.execute("DELETE FROM events WHERE app = ? AND session = ?", (app, session))
            db.execute("DELETE FROM runs WHERE app = ? AND session = ?", (app, session))
            db.execute("DELETE FROM sessions WHERE app = ? AND id = ?", (app, session))
            db.execute("DELETE FROM file_versions WHERE app = ? AND chat = ?", (app, session))

    def update_session(self, app: str, session: str, field: str, change: Callable[[dict], dict],
                       create: bool = True) -> Optional[dict]:
        """Read-modify-write ``settings`` or ``state`` in one transaction. ``create`` False: only a session that
        still exists (None otherwise), for work that finishes after the user may have deleted it."""
        assert field in ("settings", "state")
        if create:
            self.session(app, session)
        with self._db() as db:
            row = db.execute(f"SELECT {field} FROM sessions WHERE app = ? AND id = ?", (app, session)).fetchone()
            if row is None:
                return None
            value = change(json.loads(row[0]))
            db.execute(f"UPDATE sessions SET {field} = ? WHERE app = ? AND id = ?", (dump(value), app, session))
        return value

    def clear_session(self, app: str, session: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM events WHERE app = ? AND session = ?", (app, session))
            db.execute("UPDATE sessions SET state = '{}' WHERE app = ? AND id = ?", (app, session))
            db.execute("DELETE FROM file_versions WHERE app = ? AND chat = ?", (app, session))

    def rewind(self, app: str, session: str, event: int, versions: List[int], mail_runs: List[int],
               change: Callable[[dict], dict]) -> None:
        """One transaction: the session's events from ``event`` on go, a ``rewound`` mark takes the last one's id
        (SQLite gives a deleted top id out again, and saved ids such as file versions' must never point at a
        later message), the restored ``versions`` and the waiting mail of ``mail_runs`` go, ``change`` its state."""
        with self._db() as db:
            last = db.execute("SELECT MAX(id) FROM events WHERE app = ? AND session = ? AND id >= ?",
                              (app, session, event)).fetchone()[0]
            db.execute("DELETE FROM events WHERE app = ? AND session = ? AND id >= ?", (app, session, event))
            if last is not None:
                db.execute("INSERT INTO events(id, app, session, run, at, type, data) VALUES (?, ?, ?, NULL, ?, "
                           "'rewound', ?)", (last, app, session, time.time(), dump({"to": event})))
            db.executemany("DELETE FROM file_versions WHERE id = ?", [(v,) for v in versions])
            db.executemany("DELETE FROM agent_mail WHERE app = ? AND run = ? AND delivered = 0",
                           [(app, run) for run in mail_runs])
            row = db.execute("SELECT state FROM sessions WHERE app = ? AND id = ?", (app, session)).fetchone()
            if row is not None:
                db.execute("UPDATE sessions SET state = ? WHERE app = ? AND id = ?",
                           (dump(change(json.loads(row[0]))), app, session))

    # ============== File versions: a file as it was before its first change after a message ==============

    def keep_version(self, app: str, chat: str, session: str, run: int, started: float, path: str,
                     read: Callable[[], Optional[bytes]]) -> None:
        """Before a file tool changes ``path``: its content (``read()``, None when it does not exist), unless a
        version was kept since the session's latest message. ``chat`` is the conversation the work is for."""
        key = os.path.normcase(path)
        with self._db() as db:
            since = db.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE app = ? AND session = ? AND "
                               "type = 'input'", (app, session)).fetchone()[0]
            if db.execute("SELECT 1 FROM file_versions WHERE app = ? AND session = ? AND key = ? AND since = ?",
                          (app, session, key, since)).fetchone():
                return
            db.execute("INSERT INTO file_versions(app, chat, session, run, started, key, path, since, content, at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (app, chat, session, run, started, key, path, since, read(), time.time()))

    def versions(self, app: str, chat: str) -> List[dict]:
        """Every version kept for a conversation (its own and its agents' and tasks'), the oldest first, without
        its content (``version_content``); ``existed`` False: the file did not exist then."""
        keys = ("id", "session", "run", "started", "key", "path", "since", "at", "existed")
        with self._db() as db:
            rows = db.execute("SELECT id, session, run, started, key, path, since, at, content IS NOT NULL FROM "
                              "file_versions WHERE app = ? AND chat = ? ORDER BY id", (app, chat)).fetchall()
        return [{**dict(zip(keys, row)), "existed": bool(row[-1])} for row in rows]

    def version_content(self, version: int) -> Optional[bytes]:
        with self._db() as db:
            row = db.execute("SELECT content FROM file_versions WHERE id = ?", (version,)).fetchone()
        return row[0] if row else None

    # ============== Events ==============

    def add_event(self, app: str, session: str, run: Optional[int], type: str, data: dict) -> dict:
        """Committed before returning: a step is durable before the next one starts."""
        at = time.time()
        with self._db() as db:
            cursor = db.execute("INSERT INTO events(app, session, run, at, type, data) VALUES (?, ?, ?, ?, ?, ?)",
                                (app, session, run, at, type, dump(data)))
        return {"id": cursor.lastrowid, "app": app, "session": session, "run": run, "at": at, "type": type,
                **data}

    def events(self, app: str, session: str, after: int = 0, types: Optional[tuple] = None) -> List[dict]:
        query = f"SELECT {_EVENT_COLUMNS} FROM events WHERE app = ? AND session = ? AND id > ?"
        params: list = [app, session, after]
        if types:
            query += f" AND type IN ({','.join('?' * len(types))})"
            params += list(types)
        with self._db() as db:
            return [_event(row) for row in db.execute(query + " ORDER BY id", params)]

    def event(self, event: int) -> Optional[dict]:
        with self._db() as db:
            row = db.execute(f"SELECT {_EVENT_COLUMNS} FROM events WHERE id = ?", (event,)).fetchone()
        return _event(row) if row else None

    def last_event(self, app: str, session: str, before: int, type: str, name: str = "") -> Optional[dict]:
        """The session's newest event of ``type`` before event ``before``; with ``name``, a call of that tool
        that went well."""
        query = f"SELECT {_EVENT_COLUMNS} FROM events WHERE app = ? AND session = ? AND id < ? AND type = ?"
        params: list = [app, session, before, type]
        if name:
            query += " AND json_extract(data, '$.name') = ? AND json_extract(data, '$.status') = 'ok'"
            params.append(name)
        with self._db() as db:
            row = db.execute(query + " ORDER BY id DESC LIMIT 1", params).fetchone()
        return _event(row) if row else None

    def run_events(self, run: int, after: int = 0) -> List[dict]:
        with self._db() as db:
            return [_event(row) for row in db.execute(
                f"SELECT {_EVENT_COLUMNS} FROM events WHERE run = ? AND id > ? ORDER BY id", (run, after))]

    def last_compaction(self, app: str, session: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute(f"SELECT {_EVENT_COLUMNS} FROM events WHERE app = ? AND session = ? AND "
                             "type = 'compaction' ORDER BY id DESC LIMIT 1", (app, session)).fetchone()
        return _event(row) if row else None

    def quiet_sessions(self, before: float) -> List[tuple]:
        """(app, session, last event id) of sessions whose last event is older than ``before``."""
        with self._db() as db:
            return db.execute("SELECT app, session, MAX(id) FROM events GROUP BY app, session "
                              "HAVING MAX(at) < ?", (before,)).fetchall()

    # ============== Runs ==============

    def add_run(self, app: str, session: str, kind: str, options: dict, parent: Optional[int] = None,
                status: str = "queued") -> int:
        now = time.time()
        with self._db() as db:
            return db.execute("INSERT INTO runs(app, session, kind, parent, status, options, created, updated) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (app, session, kind, parent, status, dump(options), now, now)).lastrowid

    def runs_since(self, app: str, since: float) -> List[dict]:
        """An app's runs created at ``since`` or later, the oldest first (a run comes after the run that started it)."""
        with self._db() as db:
            return [_run(row) for row in db.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE app = ? AND created >= ? "
                                                    "ORDER BY id", (app, since))]

    def run(self, run: int) -> Optional[dict]:
        with self._db() as db:
            return _run(db.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run,)).fetchone())

    def runs(self, app: Optional[str] = None, kind: Optional[str] = None, statuses: Optional[tuple] = None,
             limit: int = 100, session: Optional[str] = None) -> List[dict]:
        """The newest first."""
        query, params = f"SELECT {_RUN_COLUMNS} FROM runs WHERE 1=1", []
        for column, value in (("app", app), ("kind", kind), ("session", session)):
            if value:
                query += f" AND {column} = ?"
                params.append(value)
        if statuses:
            query += f" AND status IN ({','.join('?' * len(statuses))})"
            params += list(statuses)
        with self._db() as db:
            return [_run(row) for row in db.execute(query + " ORDER BY id DESC LIMIT ?", params + [limit])]

    # ============== Agent mail: what agents send the session that started them ==============

    def post_mail(self, app: str, parent: str, agent: int, run: Optional[int], kind: str, text: str,
                  data: Optional[dict] = None) -> None:
        """An agent's ``report``, ``question`` or ``update`` for ``parent``. Only an agent's latest update
        waits; a report also makes its waiting question moot."""
        stale = {"update": ("update",), "report": ("update", "question")}.get(kind, ())
        with self._db() as db:
            if stale:
                db.execute(f"UPDATE agent_mail SET delivered = 1 WHERE app = ? AND agent = ? AND delivered = 0 "
                           f"AND kind IN ({','.join('?' * len(stale))})", (app, agent, *stale))
            db.execute("INSERT INTO agent_mail(app, parent, agent, run, kind, text, data, at) VALUES "
                       "(?, ?, ?, ?, ?, ?, ?, ?)", (app, parent, agent, run, kind, text, dump(data or {}), time.time()))

    def claim_mail(self, app: str, parent: str) -> List[dict]:
        """The mail waiting for ``parent``, the oldest first, marked delivered in the same transaction: each
        piece is handed out once, whichever thread asks first."""
        with self._db() as db:
            rows = db.execute("SELECT id, agent, run, kind, text, data FROM agent_mail WHERE app = ? AND parent = ? "
                              "AND delivered = 0 ORDER BY id", (app, parent)).fetchall()
            db.execute("UPDATE agent_mail SET delivered = 1 WHERE app = ? AND parent = ? AND delivered = 0 "
                       "AND id <= ?", (app, parent, rows[-1][0] if rows else 0))
        return [{"id": i, "agent": agent, "run": run, "kind": kind, "text": text, "data": json.loads(data)}
                for i, agent, run, kind, text, data in rows]

    def has_mail(self, app: str, parent: str, kind: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM agent_mail WHERE app = ? AND parent = ? AND kind = ? AND delivered = 0 "
                              "LIMIT 1", (app, parent, kind)).fetchone() is not None

    def mail_parents(self) -> List[tuple]:
        """(app, parent) of every session with a report or question waiting (updates never wake one)."""
        with self._db() as db:
            return db.execute("SELECT DISTINCT app, parent FROM agent_mail WHERE delivered = 0 AND kind IN "
                              "('report', 'question')").fetchall()

    def delete_mail(self, app: str, agent: Optional[int] = None, parent: Optional[str] = None) -> None:
        with self._db() as db:
            if agent is not None:
                db.execute("DELETE FROM agent_mail WHERE app = ? AND agent = ?", (app, agent))
            if parent is not None:
                db.execute("DELETE FROM agent_mail WHERE app = ? AND parent = ?", (app, parent))

    def count_events(self, run: int, type: str) -> int:
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM events WHERE run = ? AND type = ?", (run, type)).fetchone()[0]

    def run_tail(self, run: int) -> List[dict]:
        """A run's last model step and what came after it: what it is doing now, without reading its
        whole log."""
        with self._db() as db:
            return [_event(row) for row in db.execute(
                f"SELECT {_EVENT_COLUMNS} FROM events WHERE run = ? AND id >= coalesce((SELECT MAX(id) FROM events "
                "WHERE run = ? AND type = 'assistant'), 0) ORDER BY id", (run, run))]

    def update_run_options(self, run: int, change: Callable[[dict], dict]) -> dict:
        """Read-modify-write a run's options in one transaction: runs, steering, stops and agents change
        them from different threads, and writing back a copy read earlier lost the others' changes."""
        with self._db() as db:
            row = db.execute("SELECT options FROM runs WHERE id = ?", (run,)).fetchone()
            options = change(json.loads(row[0]) if row else {})
            db.execute("UPDATE runs SET options = ?, updated = ? WHERE id = ?", (dump(options), time.time(), run))
        return options

    def update_run(self, run: int, **fields: Any) -> None:
        columns = {key: dump(value) if key in ("options", "result", "error", "usage") else value
                   for key, value in fields.items()}
        columns["updated"] = time.time()
        with self._db() as db:
            db.execute(f"UPDATE runs SET {', '.join(f'{key} = ?' for key in columns)} WHERE id = ?",
                       (*columns.values(), run))
            if fields.get('status') in ('completed', 'failed', 'cancelled'):
                db.execute('UPDATE schedule_occurrences SET status = ?, finished_at = ? WHERE run = ?',
                           (fields['status'], time.time(), run))

    # ============== Jobs ==============

    def add_job(self, run: Optional[int], app: str, session: str, command: str, cwd: str, log: str) -> int:
        with self._db() as db:
            return db.execute("INSERT INTO jobs(run, app, session, command, cwd, status, log, started) "
                              "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                              (run, app, session, command, cwd, log, time.time())).lastrowid

    def job(self, job: int) -> Optional[dict]:
        with self._db() as db:
            row = db.execute(f"SELECT {', '.join(JOB_KEYS)} FROM jobs WHERE id = ?", (job,)).fetchone()
        return dict(zip(JOB_KEYS, row)) if row else None

    def jobs(self, app: str, since: float, limit: int = 50) -> List[dict]:
        """An app's running jobs and those that ended after ``since``, the newest first."""
        with self._db() as db:
            rows = db.execute(f"SELECT {', '.join(JOB_KEYS)} FROM jobs WHERE app = ? AND (ended IS NULL OR ended >= ?) "
                              "ORDER BY id DESC LIMIT ?", (app, since, limit)).fetchall()
        return [dict(zip(JOB_KEYS, row)) for row in rows]

    def update_job(self, job: int, **fields: Any) -> None:
        with self._db() as db:
            db.execute(f"UPDATE jobs SET {', '.join(f'{key} = ?' for key in fields)} WHERE id = ?",
                       (*fields.values(), job))

    def running_jobs(self) -> List[int]:
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT id FROM jobs WHERE status = 'running'")]

    # ============== Schedules ==============

    _SCHEDULE_KEYS = ("id", "app", "session", "kind", "spec", "payload", "next_at", "last_at", "catch_up",
                      "created_by", "enabled", "created")

    def add_schedule(self, **fields: Any) -> int:
        fields = {**fields, "payload": dump(fields["payload"]), "created": time.time()}
        with self._db() as db:
            # Deleted recurrences retain conversations and audit records, so their ids cannot be recycled.
            fields['id'] = db.execute('INSERT INTO schedule_ids DEFAULT VALUES').lastrowid
            schedule_id = db.execute(f"INSERT INTO schedules({', '.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                                     tuple(fields.values())).lastrowid
            payload = json.loads(fields['payload'])
            if payload['mode'] == 'app':
                payload['session'] = f'schedule-{schedule_id}'
                source = db.execute('SELECT settings FROM sessions WHERE app = ? AND id = ?',
                                    (fields['app'], fields['session'])).fetchone()
                settings = {k: v for k, v in json.loads(source[0] if source else '{}').items()
                            if k in ('instructions', 'cwd', 'roots', 'rules', 'disabled_toolkits')}
                settings.update(title=payload['title'], schedule=schedule_id)
                db.execute('UPDATE schedules SET payload = ? WHERE id = ?', (dump(payload), schedule_id))
                db.execute('INSERT INTO sessions(app, id, settings, created) VALUES (?, ?, ?, ?)',
                           (fields['app'], payload['session'], dump(settings), time.time()))
            return schedule_id

    def schedules(self, app: Optional[str] = None, enabled_only: bool = False) -> List[dict]:
        query, params = f"SELECT {', '.join(self._SCHEDULE_KEYS)} FROM schedules WHERE 1=1", []
        if app:
            query += " AND app = ?"
            params.append(app)
        if enabled_only:
            query += " AND enabled = 1"
        with self._db() as db:
            rows = db.execute(query + " ORDER BY id", params).fetchall()
        result = []
        for row in rows:
            schedule = dict(zip(self._SCHEDULE_KEYS, row))
            schedule["payload"] = json.loads(schedule["payload"])
            schedule["enabled"] = bool(schedule["enabled"])
            if schedule['payload']['mode'] == 'app':
                schedule['execution_session'] = schedule['payload']['session']
                schedule['timezone'] = schedule['payload']['timezone']
            result.append(schedule)
        return result

    def schedule(self, schedule: int) -> Optional[dict]:
        return next((s for s in self.schedules() if s["id"] == schedule), None)

    def update_schedule(self, schedule: int, *, cancel_pending: bool = False, **fields: Any) -> None:
        if "payload" in fields:
            fields["payload"] = dump(fields["payload"])
        with self._db() as db:
            db.execute(f"UPDATE schedules SET {', '.join(f'{key} = ?' for key in fields)} WHERE id = ?",
                       (*fields.values(), schedule))
            if cancel_pending:
                db.execute("UPDATE schedule_occurrences SET status = 'cancelled', finished_at = ? "
                           "WHERE schedule = ? AND status = 'pending'", (time.time(), schedule))

    def delete_schedule(self, schedule: int) -> bool:
        with self._db() as db:
            db.execute("UPDATE schedule_occurrences SET status = 'cancelled', finished_at = ? "
                       "WHERE schedule = ? AND status = 'pending'", (time.time(), schedule))
            return db.execute("DELETE FROM schedules WHERE id = ?", (schedule,)).rowcount > 0

    _OCCURRENCE_KEYS = ('id', 'schedule', 'app', 'session', 'scheduled_at', 'queued_at', 'payload',
                        'late', 'status', 'run', 'finished_at')

    @classmethod
    def _occurrence(cls, row) -> Optional[dict]:
        if row is None:
            return None
        found = dict(zip(cls._OCCURRENCE_KEYS, row))
        found['payload'] = json.loads(found['payload'])
        found['late'] = bool(found['late'])
        return found

    def occurrences(self, app: str, pending: bool = False, limit: int = 100) -> List[dict]:
        clause = " AND status IN ('pending', 'started')" if pending else ''
        with self._db() as db:
            return [self._occurrence(row) for row in db.execute(
                f"SELECT {', '.join(self._OCCURRENCE_KEYS)} FROM schedule_occurrences WHERE app = ?{clause} " +
                ('ORDER BY id DESC' if pending else 'ORDER BY id DESC LIMIT ?'),
                (app,) if pending else (app, limit))]

    def occurrence(self, app: str, occurrence: int) -> Optional[dict]:
        with self._db() as db:
            return self._occurrence(db.execute(f"SELECT {', '.join(self._OCCURRENCE_KEYS)} FROM "
                                              'schedule_occurrences WHERE app = ? AND id = ?',
                                              (app, occurrence)).fetchone())

    def start_scheduled_run(self, app: str, session: str, occurrence: int, context: dict,
                            max_steps: Optional[int]) -> tuple:
        with self._db() as db:
            found = self._occurrence(db.execute(f"SELECT {', '.join(self._OCCURRENCE_KEYS)} FROM "
                'schedule_occurrences WHERE app = ? AND session = ? AND id = ?', (app, session, occurrence)).fetchone())
            if found is None:
                raise ValueError('No scheduled occurrence belongs to this app and session')
            if found['run'] is not None:
                if not db.execute('SELECT 1 FROM runs WHERE id = ?', (found['run'],)).fetchone():
                    raise ValueError('The original scheduled run was removed')
                return found['run'], False
            if found['status'] != 'pending':
                raise ValueError('This scheduled occurrence is no longer pending')
            if db.execute("SELECT 1 FROM runs WHERE app = ? AND session = ? AND status IN "
                          "('queued', 'working', 'input_required') LIMIT 1", (app, session)).fetchone():
                raise ValueError('The scheduled conversation is busy; this occurrence remains queued')
            payload = found['payload']
            options = {'input': [{'type': 'event', 'name': 'scheduled',
                'text': f"Scheduled instructions: {payload['title']}. Complete them and report the result here.",
                'data': {'schedule': found['schedule'], 'occurrence': occurrence,
                         'scheduled_at': found['scheduled_at'], 'timezone': payload['timezone'], 'late': found['late']}},
                {'type': 'text', 'text': payload['text']}], 'context': context, 'reply': 'required',
                'occurrence': occurrence, 'schedule': found['schedule']}
            if max_steps is not None:
                options['max_steps'] = max_steps
            now = time.time()
            run = db.execute("INSERT INTO runs(app, session, kind, status, options, created, updated) "
                             "VALUES (?, ?, 'turn', 'queued', ?, ?, ?)",
                             (app, session, dump(options), now, now)).lastrowid
            db.execute("UPDATE schedule_occurrences SET status = 'started', run = ? WHERE id = ?", (run, occurrence))
            return run, True

    def queue_schedule(self, schedule: int, expected: float, now: float, next_at: Optional[float],
                       late: bool = False, skip: bool = False) -> Optional[dict]:
        """The due claim, occurrence, wakeup and next time commit together; retries cannot lose or duplicate work."""
        with self._db() as db:
            row = db.execute('SELECT app, payload, next_at, enabled FROM schedules WHERE id = ?',
                             (schedule,)).fetchone()
            if row is None or not row[3] or row[2] != expected:
                return None
            app, payload = row[0], json.loads(row[1])
            active = db.execute("SELECT id, status, payload FROM schedule_occurrences WHERE schedule = ? "
                                "AND status IN ('pending', 'started')", (schedule,)).fetchone()
            state = 'skipped' if skip or (active and active[1] == 'started') else 'pending'
            if active and active[1] == 'pending' and not skip:
                occurrence = active[0]
                payload['coalesced'] = json.loads(active[2]).get('coalesced', 0) + 1
                db.execute('UPDATE schedule_occurrences SET scheduled_at = ?, payload = ?, late = 1 WHERE id = ?',
                           (expected, dump(payload), occurrence))
            else:
                if state == 'skipped':
                    payload['reason'] = 'missed while stopped' if skip else 'previous occurrence still running'
                occurrence = db.execute('INSERT INTO schedule_occurrences(schedule, app, session, scheduled_at, '
                    'queued_at, payload, late, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (schedule, app, payload['session'], expected, now, dump(payload), int(late), state)).lastrowid
            db.execute('UPDATE schedules SET last_at = ?, next_at = ?, enabled = ? WHERE id = ?',
                       (now, next_at, int(next_at is not None), schedule))
            if state == 'pending':
                return self._notify(db, app, payload['session'], 'schedule.ready', {'occurrence': occurrence,
                                    'schedule': schedule, 'session': payload['session']})
            return None

    # ============== Notifications ==============

    def notify(self, app: str, session: Optional[str], type: str, data: dict) -> dict:
        with self._db() as db:
            return self._notify(db, app, session, type, data)

    @staticmethod
    def _notify(db, app: str, session: Optional[str], type: str, data: dict) -> dict:
        at = time.time()
        nid = db.execute("INSERT INTO notifications(at, app, session, type, data) VALUES (?, ?, ?, ?, ?)",
                         (at, app, session, type, dump(data))).lastrowid
        db.execute("DELETE FROM notifications WHERE at < ? OR (app = ? AND id <= ?)",
                   (at - NOTIFICATION_DAYS * 86400, app, nid - NOTIFICATIONS_PER_APP))
        return {"id": nid, "at": at, "app": app, "session": session, "type": type, "data": data}

    def notifications(self, app: str, after: int = 0) -> List[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id, at, app, session, type, data FROM notifications WHERE app = ? AND id > ? "
                              "ORDER BY id", (app, after)).fetchall()
        return [{"id": i, "at": at, "app": a, "session": s, "type": t, "data": json.loads(d)}
                for i, at, a, s, t, d in rows]

    def last_notification(self, app: str) -> int:
        with self._db() as db:
            return db.execute("SELECT COALESCE(MAX(id), 0) FROM notifications WHERE app = ?", (app,)).fetchone()[0]

    # ============== Memory (per app) ==============

    def remember(self, app: str, category: str, key: str, value: Any, *, replace: bool = True) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
        with self._db() as db:
            db.execute(f"{verb} INTO memory(app, category, key, value, updated) VALUES (?, ?, ?, ?, ?)",
                       (app, category, key, dump(value), time.time()))

    def recall(self, app: str, category: str, key: str) -> Optional[Any]:
        with self._db() as db:
            row = db.execute("SELECT value FROM memory WHERE app = ? AND category = ? AND key = ?",
                             (app, category, key)).fetchone()
        return json.loads(row[0]) if row else None

    def forget(self, app: str, category: str, key: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM memory WHERE app = ? AND category = ? AND key = ?",
                              (app, category, key)).rowcount > 0

    def memories(self, app: str) -> Dict[str, Dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT category, key, value FROM memory WHERE app = ? ORDER BY category, key",
                              (app,)).fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for category, key, value in rows:
            result.setdefault(category, {})[key] = json.loads(value)
        return result

    # ============== Journal (shared by every app) ==============

    def add_note(self, app: str, session: str, note: str) -> int:
        with self._db() as db:
            return db.execute("INSERT INTO journal(at, app, session, note) VALUES (?, ?, ?, ?)",
                              (time.time(), app, session, note)).lastrowid

    def notes(self, query: str = "", limit: int = -1, app: Optional[str] = None,
              session: Optional[str] = None) -> List[dict]:
        """Journal notes, newest first (``limit`` -1: all of them), of one session when given."""
        where, params = [], []
        if query:
            where.append("note LIKE ? ESCAPE '\\'")
            params.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if app is not None and session is not None:
            where.append("app = ? AND session = ?")
            params += [app, session]
        sql = "SELECT id, at, app, session, note FROM journal" + (" WHERE " + " AND ".join(where) if where else "")
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY at DESC, id DESC LIMIT ?", params + [limit]).fetchall()
        return [{"id": i, "at": at, "app": a, "session": s, "note": n} for i, at, a, s, n in rows]

    def delete_note(self, note: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM journal WHERE id = ?", (note,)).rowcount > 0
