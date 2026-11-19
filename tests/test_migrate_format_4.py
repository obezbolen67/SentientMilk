"""The one-off migration to data format 4 (scripts/migrate_format_4.py), on a home in format 3's shapes."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework import dataformat
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import Reactions
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store

_spec = importlib.util.spec_from_file_location(
    "migrate_format_4", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_4.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

NAMES = ("brain", "mind", "recall")


def format_3_home(home: Path) -> dict:
    """Things she put off as older versions kept them (no turn), and one as kept now."""
    store = Store(home / "brain.sqlite3")
    turn = store.add_run("milk", "main", "turn", {}, status="completed")
    begun = store.run(turn)["created"]
    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    memory.add("exchange", "The user said: write the report. I said: later.", 0.0, 0.5, 0.5, app="milk",
               session="main", at=begun + 8, run_id=turn)
    later = store.add_run("milk", "main", "turn", {}, status="completed")
    with sqlite3.connect(home / "brain.sqlite3") as db:  # the chat's next turn, twenty seconds on
        db.execute("UPDATE runs SET created = ? WHERE id = ?", (begun + 20, later))
    memory.add("exchange", "The user said: hi. I said: hi.", 0.0, 0.5, 0.5, app="milk", session="main",
               at=begun + 25, run_id=later)
    concerns = [{"what": "the report", "app": "milk", "session": "main", "at": begun + 1},  # its turn was kept
                {"what": "the taxes", "app": "milk", "session": "main", "at": begun + 19.5},
                {"what": "the plants", "app": "milk", "session": "elsewhere", "at": begun + 1},  # nothing kept there
                {"what": "the clock", "app": "milk", "session": "main", "at": begun + 2, "run": turn}]
    memory.put("self", {"concerns": concerns, "thoughts": []})
    memory.close()
    Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3").stop()
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        db.execute("PRAGMA user_version = 3")
        db.close()
    return {"turn": turn, "concerns": concerns}


def formats(home: Path) -> dict:
    out = {}
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        out[name] = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()
    return out


def test_each_thing_she_put_off_keeps_the_turn_she_put_it_off_in(tmp_path):
    made = format_3_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert formats(tmp_path) == {name: dataformat.FORMAT for name in NAMES} and dataformat.FORMAT == 4
    assert formats(Path(report["backup"])) == {name: 3 for name in NAMES}
    memory = Memory(tmp_path / "mind.sqlite3")
    concerns = memory.get("self")["concerns"]
    memory.close()
    # the next moment kept after "the taxes" is of a turn begun after it: not the turn it was put off in
    assert [c["run"] for c in concerns] == [made["turn"], None, None, made["turn"]]
    assert concerns[0] == {**made["concerns"][0], "run": made["turn"]}
    assert (report["concerns given their turn"], report["concerns whose turn was not kept"]) == (1, 2)
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    assert {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {
        "workspace", "workspace_vectors", "workspace_vector_revision"}  # what is on her mind, empty
    db.close()
    assert migration.migrate(tmp_path) == {"done": "already at format 4"}


def test_a_running_brain_and_data_of_another_format_are_left_as_they_were(tmp_path):
    format_3_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused, match="stop it first"):
        migration.migrate(tmp_path)
    (tmp_path / "server.json").unlink()
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    db.execute("PRAGMA user_version = 2")
    db.close()
    with pytest.raises(migration.Refused, match="format 3 only"):
        migration.migrate(tmp_path)
    assert formats(tmp_path) == {"brain": 3, "mind": 2, "recall": 3}
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    stored = json.loads(db.execute("SELECT value FROM state WHERE key = 'self'").fetchone()[0])
    db.close()
    assert "run" not in stored["concerns"][0] and not list(tmp_path.glob("before-format-4-*"))
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'workspace%'").fetchall()
    db.close()
