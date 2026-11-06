"""Everything the brain keeps, in one SQLite file (WAL, one connection per call).

The ``events`` table is the single source of truth for every conversation: model
messages and the transcript apps show are both projections of it.
"""

import json
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
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL, session TEXT,
    type TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notifications_by_app ON notifications(app, id);
CREATE TABLE IF NOT EXISTS memory (
    app TEXT NOT NULL, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
    updated REAL NOT NULL, PRIMARY KEY (app, category, key)
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL, session TEXT NOT NULL, note TEXT NOT NULL
);
"""
NOTIFICATION_DAYS = 7
NOTIFICATIONS_PER_APP = 1000


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
        with self._db() as db:
            rows = db.execute(
                "SELECT s.id, s.created, MAX(e.at) FROM sessions s LEFT JOIN events e "
                "ON e.app = s.app AND e.session = s.id WHERE s.app = ? GROUP BY s.id ORDER BY s.id",
                (app,)).fetchall()
        return [{"id": sid, "created": created, "last_active": last} for sid, created, last in rows]

    def update_session(self, app: str, session: str, field: str, change: Callable[[dict], dict]) -> dict:
        """Read-modify-write ``settings`` or ``state`` in one transaction."""
        assert field in ("settings", "state")
        self.session(app, session)
        with self._db() as db:
            row = db.execute(f"SELECT {field} FROM sessions WHERE app = ? AND id = ?", (app, session)).fetchone()
            value = change(json.loads(row[0]))
            db.execute(f"UPDATE sessions SET {field} = ? WHERE app = ? AND id = ?", (dump(value), app, session))
        return value

    def clear_session(self, app: str, session: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM events WHERE app = ? AND session = ?", (app, session))
            db.execute("UPDATE sessions SET state = '{}' WHERE app = ? AND id = ?", (app, session))

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

    def run(self, run: int) -> Optional[dict]:
        with self._db() as db:
            return _run(db.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run,)).fetchone())

    def runs(self, app: Optional[str] = None, kind: Optional[str] = None, statuses: Optional[tuple] = None,
             limit: int = 100) -> List[dict]:
        query, params = f"SELECT {_RUN_COLUMNS} FROM runs WHERE 1=1", []
        for column, value in (("app", app), ("kind", kind)):
            if value:
                query += f" AND {column} = ?"
                params.append(value)
        if statuses:
            query += f" AND status IN ({','.join('?' * len(statuses))})"
            params += list(statuses)
        with self._db() as db:
            return [_run(row) for row in db.execute(query + " ORDER BY id DESC LIMIT ?", params + [limit])]

    def update_run(self, run: int, **fields: Any) -> None:
        columns = {key: dump(value) if key in ("options", "result", "error", "usage") else value
                   for key, value in fields.items()}
        columns["updated"] = time.time()
        with self._db() as db:
            db.execute(f"UPDATE runs SET {', '.join(f'{key} = ?' for key in columns)} WHERE id = ?",
                       (*columns.values(), run))

    # ============== Jobs ==============

    def add_job(self, run: Optional[int], app: str, session: str, command: str, cwd: str, log: str) -> int:
        with self._db() as db:
            return db.execute("INSERT INTO jobs(run, app, session, command, cwd, status, log, started) "
                              "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                              (run, app, session, command, cwd, log, time.time())).lastrowid

    def job(self, job: int) -> Optional[dict]:
        keys = ("id", "run", "app", "session", "command", "cwd", "pid", "status", "exit_code", "log", "started",
                "ended")
        with self._db() as db:
            row = db.execute(f"SELECT {', '.join(keys)} FROM jobs WHERE id = ?", (job,)).fetchone()
        return dict(zip(keys, row)) if row else None

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
            return db.execute(f"INSERT INTO schedules({', '.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                              tuple(fields.values())).lastrowid

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
            result.append(schedule)
        return result

    def schedule(self, schedule: int) -> Optional[dict]:
        return next((s for s in self.schedules() if s["id"] == schedule), None)

    def update_schedule(self, schedule: int, **fields: Any) -> None:
        if "payload" in fields:
            fields["payload"] = dump(fields["payload"])
        with self._db() as db:
            db.execute(f"UPDATE schedules SET {', '.join(f'{key} = ?' for key in fields)} WHERE id = ?",
                       (*fields.values(), schedule))

    def delete_schedule(self, schedule: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM schedules WHERE id = ?", (schedule,)).rowcount > 0

    # ============== Notifications ==============

    def notify(self, app: str, session: Optional[str], type: str, data: dict) -> dict:
        at = time.time()
        with self._db() as db:
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

    def add_note(self, app: str, session: str, note: str, capacity: int) -> int:
        """Add a note, then delete the oldest notes until all of them fit ``capacity`` characters."""
        with self._db() as db:
            nid = db.execute("INSERT INTO journal(at, app, session, note) VALUES (?, ?, ?, ?)",
                             (time.time(), app, session, note)).lastrowid
            rows = db.execute("SELECT id, LENGTH(note) FROM journal ORDER BY at DESC, id DESC").fetchall()
            total, doomed = 0, []
            for row_id, length in rows:
                total += length
                if total > capacity and row_id != nid:
                    doomed.append(row_id)
            db.executemany("DELETE FROM journal WHERE id = ?", [(row_id,) for row_id in doomed])
        return nid

    def notes(self, query: str = "", limit: int = 1000) -> List[dict]:
        sql, params = "SELECT id, at, app, session, note FROM journal", []
        if query:
            sql += " WHERE note LIKE ? ESCAPE '\\'"
            params.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY at DESC, id DESC LIMIT ?", params + [limit]).fetchall()
        return [{"id": i, "at": at, "app": a, "session": s, "note": n} for i, at, a, s, n in rows]

    def delete_note(self, note: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM journal WHERE id = ?", (note,)).rowcount > 0
