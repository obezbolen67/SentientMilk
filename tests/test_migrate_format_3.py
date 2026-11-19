"""The one-off migration to data format 3 (scripts/migrate_format_3.py), on a home in format 2's shapes."""

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
    "migrate_format_3", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_3.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

NAMES = ("brain", "mind", "recall")
# as format 2 kept them: a thought with the model's want, the wish it left, a task it started
THOUGHT = {"episode": 7, "at": 50.0, "kind": "wonder", "thought": "Those photos need sorting.", "want": "do",
           "went": "task"}
URGE = {"at": 60.0, "want": "tell", "app": "milk", "session": "main", "say": "hi", "actor": "user",
        "thought": 60.0, "offered": True, "text": "You want to tell them: hi", "mark": 3.0}
OWN = {"want": "do", "what": "sort the photos", "thought": "Those photos need sorting.", "episode": 7}


def format_2_home(home: Path) -> int:
    store = Store(home / "brain.sqlite3")
    task = store.add_run("milk", "task-1", "task", {"goal": "sort", "own": OWN}, status="completed")
    asked = store.add_run("milk", "task-2", "task", {"goal": "asked"}, status="completed")
    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    memory.put("self", {"thoughts": [THOUGHT], "urge": URGE, "usual": 0.2})
    memory.close()
    Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3").stop()
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        db.execute("PRAGMA user_version = 2")
        db.close()
    return task, asked


def formats(home: Path) -> dict:
    out = {}
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        out[name] = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()
    return out


def test_what_her_thoughts_did_before_her_will_chose_is_marked_so(tmp_path):
    task, asked = format_2_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert formats(tmp_path) == {name: dataformat.FORMAT for name in NAMES} and dataformat.FORMAT == 3
    assert formats(Path(report["backup"])) == {name: 2 for name in NAMES}
    memory = Memory(tmp_path / "mind.sqlite3")
    me = memory.get("self")
    memory.close()
    assert me["thoughts"] == [{**THOUGHT, "leaned": None}]  # the model's want, not her will's choice
    assert me["urge"] == {**URGE, "features": None} and me["usual_own"] == 0.0 and me["usual"] == 0.2
    store = Store(tmp_path / "brain.sqlite3")
    assert store.run(task)["options"]["own"] == {**OWN, "leaned": None}
    assert "own" not in store.run(asked)["options"]  # a task she was asked for is not hers
    assert (report["thoughts"], report["tasks of her own"]) == (1, 1)
    assert migration.migrate(tmp_path) == {"done": "already at format 3"}


def test_a_running_brain_and_data_of_another_format_are_left_as_they_were(tmp_path):
    format_2_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused, match="stop it first"):
        migration.migrate(tmp_path)
    (tmp_path / "server.json").unlink()
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    db.execute("PRAGMA user_version = 1")
    db.close()
    with pytest.raises(migration.Refused, match="format 2 only"):
        migration.migrate(tmp_path)
    assert formats(tmp_path) == {"brain": 2, "mind": 1, "recall": 2}
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    stored = json.loads(db.execute("SELECT value FROM state WHERE key = 'self'").fetchone()[0])
    db.close()
    assert stored["thoughts"] == [THOUGHT] and not list(tmp_path.glob("before-format-3-*"))
