"""The one-off migration to data format 2 (scripts/migrate_format_2.py), on a home in format 1's shapes."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework import dataformat
from sentientmilk_framework.mind.feel import Concepts
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import Reactions
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store

_spec = importlib.util.spec_from_file_location(
    "migrate_format_2", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_2.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

NAMES = ("brain", "mind", "recall")
# as format 1 kept them: the last three sentences, the moment taken as the one named (first thing retrieval gave
# when she looked for one), and one mean of every naming
WARM = {"word": "something warm", "moved": {"reward": 0.231, "oxytocin": 0.1}, "about": {"seedlings": 1.0},
        "count": 4, "back": 2, "at": 50.0,
        "said": [{"text": "something warm", "at": 30.0, "episode": 341},
                 {"text": "Something warm, I think.", "at": 40.0, "episode": None},
                 {"text": "still something warm", "at": 50.0}]}


def format_1_home(home: Path) -> None:
    Store(home / "brain.sqlite3")
    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    memory.put("concepts", [WARM])
    memory.close()
    Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3").stop()
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        db.execute("PRAGMA user_version = 1")
        db.close()


def formats(home: Path) -> dict:
    out = {}
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        out[name] = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()
    return out


def test_her_namings_from_before_become_legacy_records_and_her_feelings_keep_what_they_learned(tmp_path):
    format_1_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert formats(tmp_path) == {name: dataformat.FORMAT for name in NAMES} and dataformat.FORMAT == 2
    assert formats(Path(report["backup"])) == {name: 1 for name in NAMES}  # the copy from before, untouched
    memory = Memory(tmp_path / "mind.sqlite3")
    concept = Concepts(memory.get("concepts")).named[0]
    memory.close()
    assert {key: concept[key] for key in ("word", "moved", "about", "count", "back", "at")} == {
        key: WARM[key] for key in ("word", "moved", "about", "count", "back", "at")}
    # the mean was moved by every naming then: the next measured one weighs one in five, as it would have
    assert (concept["measured"], concept["back_at"], concept["back_run"]) == (4, None, None)
    assert concept["said"] == [
        {"words": "something warm", "text": text, "at": at, "how": "legacy", "named": "legacy", "run": None,
         "event": None, "call": None, "episode": episode, "asked": None, "measure": None, "reminded": []}
        for text, at, episode in (("something warm", 30.0, 341), ("Something warm, I think.", 40.0, None),
                                  ("still something warm", 50.0, None))]
    assert report["namings kept as stored by older software"] == 3
    assert migration.migrate(tmp_path) == {"done": "already at format 2"}


def test_a_running_brain_and_data_of_another_format_are_left_as_they_were(tmp_path):
    format_1_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused, match="stop it first"):
        migration.migrate(tmp_path)
    (tmp_path / "server.json").unlink()
    db = sqlite3.connect(tmp_path / "mind.sqlite3")
    db.execute("PRAGMA user_version = 0")
    db.close()
    with pytest.raises(migration.Refused, match="format 1 only"):
        migration.migrate(tmp_path)
    assert formats(tmp_path) == {"brain": 1, "mind": 0, "recall": 1}
    memory_db = sqlite3.connect(tmp_path / "mind.sqlite3")
    stored = json.loads(memory_db.execute("SELECT value FROM state WHERE key = 'concepts'").fetchone()[0])
    memory_db.close()
    assert stored == [WARM] and not list(tmp_path.glob("before-format-2-*"))
