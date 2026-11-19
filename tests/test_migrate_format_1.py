"""The one-off migration to data format 1 (scripts/migrate_format_1.py), on a home in the shapes from before it."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import Reactions
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store

_spec = importlib.util.spec_from_file_location(
    "migrate_format_1", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_1.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

APP, CHAT = "milkchan", "chat-1"
HERS = {"word": "worn flat", "moved": {"cortisol": 0.4}, "about": {}, "count": 1, "back": 0, "at": 5.0,
        "said": [{"text": "I feel worn flat", "at": 5.0}]}


def call(store, session, run, name, arguments, status="ok"):
    return store.add_event(APP, session, run, "tool", {"name": name, "arguments": arguments, "status": status})


def old_home(home: Path) -> dict:
    """A home as SentientMilk kept it before the format stamp: what it holds, by name."""
    store = Store(home / "brain.sqlite3")
    turn = store.add_run(APP, CHAT, "turn", {"steer_user": True, "steer": [{"type": "text", "text": "x"}],
                                              "steer_batches": []}, status="completed")
    first = store.add_event(APP, CHAT, turn, "input", {"content": "first", "display": "first"})
    call(store, CHAT, turn, "memory_save", {"key": "lang", "value": "English"})
    call(store, CHAT, turn, "memory_save", {"key": "user", "value": "Tester", "scope": "everywhere"})
    call(store, CHAT, turn, "memory_save", {"category": "user", "key": "home", "value": "Riga"})  # lasting: its default
    call(store, CHAT, turn, "memory_save", {"key": "push", "value": "never", "scope": "session"})
    call(store, CHAT, turn, "memory_save", {"key": "bad", "value": "x"}, status="error")
    summary = store.add_run(APP, "summary-9", "summary", {"chat": CHAT, "upto": first["id"]}, status="completed")
    call(store, "summary-9", summary, "memory_save", {"key": "tone", "value": "short"})
    second = store.add_event(APP, CHAT, turn, "input", {"content": "second", "display": "second"})
    call(store, CHAT, turn, "memory_forget", {"key": "lang"})
    third = store.add_event(APP, CHAT, turn, "input", {"content": "third", "display": "third"})
    store.update_session(APP, CHAT, "state", lambda state: {**state, "journaled_upto": 3, "todo": []})
    # a return since 0.30 took a lasting save for the chat's own: the fact sat in the chat's memory since
    other = store.add_run(APP, "chat-2", "turn", {}, status="completed")
    hi = store.add_event(APP, "chat-2", other, "input", {"content": "hi", "display": "hi"})
    call(store, "chat-2", other, "memory_save", {"category": "projects", "key": "bot", "value": "Ferryman"})
    call(store, "chat-2", other, "memory_save", {"key": "push", "value": "never"})
    store.update_session(APP, "chat-2", "state", lambda state: {**state, "session_memory": {"bot": "Ferryman",
                                                                                          "push": "never"}})
    with sqlite3.connect(home / "brain.sqlite3") as db:
        db.executescript("""
            CREATE TABLE memory (app TEXT NOT NULL, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                                 updated REAL NOT NULL, PRIMARY KEY (category, key));
            CREATE TABLE memory_revisions (id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL,
                                           category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                                           why TEXT NOT NULL);
            CREATE TABLE journal (id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL, session TEXT NOT NULL,
                                  note TEXT NOT NULL);
        """)
        db.execute("INSERT INTO memory VALUES (?, 'user', 'name', ?, 100.0)", (APP, json.dumps("Tester")))
        db.execute("INSERT INTO journal VALUES (7, 50.0, ?, ?, 'We planned a platformer.')", (APP, CHAT))
        db.execute("INSERT INTO journal VALUES (8, 60.0, ?, 'gone', 'Of a chat deleted since.')", (APP,))

    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    episode = memory.add("exchange", "The user said hi.", 0.1, 0.2, 0.3)
    memory.put("concepts", [{**HERS, "hers": True}, {**HERS, "word": "permission", "said": [], "hers": False}])
    memory.put("self", {"logic": 3, "trust": 0.5})
    memory.put("people", {"known": [], "handles": {}, "met_past": True})
    memory.put("body", {"levels": {}, "entrained": True, "sleep": {"model": 2, "slept_at": 0.0}})
    memory._db.execute("ALTER TABLE episodes ADD COLUMN first_text TEXT")
    memory.close()

    recall = Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3")
    recall.add("fact", "user/old", APP, "", 10.0, "old: a fact taken out since")
    recall.stop()
    for name in ("brain", "mind", "recall"):
        with sqlite3.connect(home / f"{name}.sqlite3") as db:
            db.execute("PRAGMA user_version = 0")
    return {"first": first["id"], "second": second["id"], "third": third["id"], "hi": hi["id"], "turn": turn,
            "episode": episode}


def rows(path, query, *args):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute(query, args)]
    finally:
        db.close()


def test_an_old_home_is_brought_to_format_1_once(tmp_path):
    made = old_home(tmp_path)
    report = migration.migrate(tmp_path)
    brain, mind, recall = (tmp_path / f"{name}.sqlite3" for name in ("brain", "mind", "recall"))
    assert sorted(p.name for p in Path(report["backup"]).iterdir()) == ["brain.sqlite3", "mind.sqlite3", "recall.sqlite3"]
    assert rows(Path(report["backup"]) / "brain.sqlite3", "SELECT COUNT(*) AS n FROM journal")[0]["n"] == 2
    for path in (brain, mind, recall):
        assert rows(path, "PRAGMA user_version")[0]["user_version"] == 1

    found = {row["id"]: json.loads(row["data"])["memory"] for row in rows(brain, "SELECT id, data FROM events WHERE type = 'input'")}
    assert found == {made["first"]: {}, made["second"]: {"lang": "English", "push": "never", "tone": "short"},
                     made["third"]: {"push": "never", "tone": "short"}, made["hi"]: {}}  # the lasting facts and the failed save were never the chat's
    assert not rows(brain, "SELECT * FROM runs WHERE kind = 'summary'")
    assert not rows(brain, "SELECT * FROM events WHERE session = 'summary-9'")
    assert sorted(row["id"] for row in rows(brain, "SELECT id FROM sessions")) == [CHAT, "chat-2"]
    assert json.loads(rows(brain, "SELECT options FROM runs WHERE id = ?", made["turn"])[0]["options"]) == {}
    states = {row["id"]: json.loads(row["state"]) for row in rows(brain, "SELECT id, state FROM sessions")}
    assert states[CHAT] == {"todo": []} and states["chat-2"]["session_memory"] == {"push": "never"}
    assert not {"memory", "memory_revisions", "journal"} & {row["name"] for row in rows(brain, "SELECT name FROM sqlite_master")}

    units = {row["ref"]: row for row in rows(recall, "SELECT * FROM units")}
    assert units["user/name#0"]["text"] == "name: Tester" and units["user/name#0"]["at"] == 100.0
    assert units["7#0"]["session"] == CHAT and "user/old#0" not in units and "8#0" not in units

    state = {row["key"]: json.loads(row["value"]) for row in rows(mind, "SELECT key, value FROM state")}
    assert state["concepts"] == [HERS]
    assert state["self"] == {"trust": 0.5} and state["people"] == {"known": [], "handles": {}}
    assert state["body"] == {"levels": {}, "sleep": {"slept_at": 0.0}}
    assert "first_text" not in {row["name"] for row in rows(mind, "PRAGMA table_info(episodes)")}
    assert [row["id"] for row in rows(mind, "SELECT id FROM episodes")] == [made["episode"]]

    Store(brain).session(APP, CHAT)  # the current code opens it
    assert migration.migrate(tmp_path) == {"done": "already at format 1"}


def test_a_running_brain_or_a_shape_it_does_not_know_is_refused_and_nothing_changes(tmp_path):
    old_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused, match="stop it first"):
        migration.migrate(tmp_path)
    (tmp_path / "server.json").unlink()
    with sqlite3.connect(tmp_path / "mind.sqlite3") as db:
        db.execute("CREATE TABLE mystery (id INTEGER)")
    with pytest.raises(migration.Refused, match="mind: table mystery is not made now"):
        migration.migrate(tmp_path)
    for name in ("brain", "mind", "recall"):
        assert rows(tmp_path / f"{name}.sqlite3", "PRAGMA user_version")[0]["user_version"] == 0
    assert rows(tmp_path / "brain.sqlite3", "SELECT COUNT(*) AS n FROM journal")[0]["n"] == 2
    assert "first_text" in {row["name"] for row in rows(tmp_path / "mind.sqlite3", "PRAGMA table_info(episodes)")}
