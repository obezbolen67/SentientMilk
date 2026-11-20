"""The one-off migration to data format 6 (scripts/migrate_format_6.py), on a home in format 5's shapes."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework import dataformat
from sentientmilk_framework.mind import workspace
from sentientmilk_framework.mind.feel import Feelings
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import Reactions
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store

_spec = importlib.util.spec_from_file_location(
    "migrate_format_6", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_6.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

NAMES = ("brain", "mind", "recall")
FORESEEN = {"company": -0.4, "capable": 0.2, "free": 0.0}


def naming(words, text, at, how, named, episode=None, measure=None):
    """A naming as format 5 kept it (no ``reviewed``)."""
    return {"words": words, "text": text, "at": at, "how": how, "named": named, "run": None, "event": None,
            "call": None, "episode": episode, "asked": None, "measure": measure, "reminded": []}


def format_5_home(home: Path) -> dict:
    """A turn kept with its decision, a thought she leaned on, a moment from before decisions were kept, and her
    concepts as format 5 kept them: one only older software named, one named twice with numbers."""
    store = Store(home / "brain.sqlite3")
    turn = store.add_run("milk", "main", "turn", {}, status="completed")
    with sqlite3.connect(home / "brain.sqlite3") as db:
        db.execute("UPDATE runs SET options = ? WHERE id = ?",
                   (json.dumps({"mind": {"foreseen": FORESEEN, "act": "later", "what": "read it tonight"}}), turn))
    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    workspace.Workspace(memory._db, memory._lock)
    exchange = memory.add("exchange", "They asked me to read their essay.", 0.0, 0.3, 0.5, run_id=turn, at=1000.0)
    thought = memory.add("thought", "I should sort those photos.", 0.0, 0.3, 0.3, at=2000.0)
    older = memory.add("exchange", "Something from long ago.", 0.0, 0.3, 0.3, at=10.0)
    memory.put("self", {"thoughts": [{"episode": thought, "at": 2000.0, "leaned": {
        "act": "do", "considered": [{"act": "do", "what": "sort the photos", "picked": True},
                                    {"act": "let", "what": "", "picked": False}]}}]})
    memory.put("concepts", [
        {"word": "waiting to be useful", "moved": {"dopamine": -0.3}, "about": {"fourteen": 1.0}, "count": 1,
         "measured": 1, "back": 2, "back_at": 900.0, "back_run": 4, "at": 500.0,
         "said": [naming("waiting to be useful", "a spare part waiting to be useful", 500.0, "legacy", "legacy")]},
        {"word": "flat", "moved": {"dopamine": -0.5}, "about": {}, "count": 2, "measured": 2, "back": 0,
         "back_at": None, "back_run": None, "at": 1000.0,
         "said": [naming("Flat", "Flat, honestly.", 900.0, "speech", "now", exchange,
                         {"of": "message", "run": turn, "way": {"dopamine": -0.5}}),
                  naming("flat", "Still flat.", 1000.0, "thought", "now", thought,
                         {"of": "reading", "way": {"dopamine": -0.4}})]}])
    memory.close()
    Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3").stop()
    with sqlite3.connect(home / "mind.sqlite3") as db:  # format 5's episodes: no appraisal, no leaning
        db.execute("ALTER TABLE episodes DROP COLUMN appraisal")
        db.execute("ALTER TABLE episodes DROP COLUMN leaned")
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        db.execute("PRAGMA user_version = 5")
        db.close()
    return {"turn": turn, "exchange": exchange, "thought": thought, "older": older}


def test_moments_gain_what_they_meant_and_her_concepts_become_provisional_feelings(tmp_path):
    made = format_5_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert Path(report["backup"]).is_dir() and report["exchanges given what they meant and her leaning"] == 1
    assert report["thoughts given her leaning"] == 1 and report["older namings given their concept's mean"] == 1
    for name in NAMES:
        assert sqlite3.connect(tmp_path / f"{name}.sqlite3").execute("PRAGMA user_version").fetchone()[0] == \
            dataformat.FORMAT == 6
    memory = Memory(tmp_path / "mind.sqlite3")
    try:
        kept = {e["id"]: e for e in memory.by_ids([made["exchange"], made["thought"], made["older"]])}
        assert Memory.appraisal(kept[made["exchange"]]) == FORESEEN  # how things were for them: not kept then
        assert Memory.leaned(kept[made["exchange"]]) == {"act": "later", "what": "read it tonight"}
        assert Memory.leaned(kept[made["thought"]]) == {"act": "do", "what": "sort the photos"}
        assert Memory.appraisal(kept[made["older"]]) is None and Memory.leaned(kept[made["older"]]) is None
        assert memory.get("concepts") is None
        feelings = Feelings(memory.get("feelings"))
    finally:
        memory.close()
    useful, flat = feelings.known
    assert (useful["id"], flat["id"], feelings.next) == (1, 2, 3)
    assert {useful["standing"], flat["standing"]} == {"provisional"} and len(feelings.unreviewed()) == 3
    assert useful["said"][0]["measure"] == {"of": "legacy", "way": {"dopamine": -0.3}}  # the mean it had
    assert (useful["back"], useful["back_at"], useful["back_run"]) == (2, 900.0, 4)
    assert feelings.words(flat) == ["Flat"] and flat["said"][1]["measure"]["way"] == {"dopamine": -0.4}
    assert "moved" not in flat and "about" not in flat
    assert migration.migrate(tmp_path) == {"done": "already at format 6"}


def test_it_refuses_a_running_brain_and_a_home_of_another_format(tmp_path):
    format_5_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused, match="stop it first"):
        migration.migrate(tmp_path)
    (tmp_path / "server.json").unlink()
    with sqlite3.connect(tmp_path / "recall.sqlite3") as db:
        db.execute("PRAGMA user_version = 4")
    with pytest.raises(migration.Refused, match="knows format 5 only"):
        migration.migrate(tmp_path)
