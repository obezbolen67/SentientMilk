"""The one-off migration to data format 5 (scripts/migrate_format_5.py), on a home in format 4's shapes."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework import dataformat
from sentientmilk_framework.mind import workspace
from sentientmilk_framework.mind.feel import CHANNELS
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import Reactions
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store

_spec = importlib.util.spec_from_file_location(
    "migrate_format_5", Path(__file__).resolve().parents[1] / "scripts" / "migrate_format_5.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

NAMES = ("brain", "mind", "recall")
CALLED = {"noradrenaline": 28.7234, "cortisol": 0.5}  # what format 4 kept as reacted: what the reaction called for
NA, CORT = CHANNELS["noradrenaline"][1], CHANNELS["cortisol"][1]


def format_4_home(home: Path) -> dict:
    """A turn from before her push log, one after it (its reading's pushes logged, one channel pinned), one from
    before reactions were kept, and her latest reactions as format 4 kept them."""
    store = Store(home / "brain.sqlite3")
    old, turn, older = (store.add_run("milk", "main", "turn", {}, status="completed") for _ in range(3))
    came = store.run(turn)["created"]
    memory = Memory(home / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    workspace.Workspace(memory._db, memory._lock)
    memory.log_push(came - 1800, "a tool call failed", {"cortisol": 0.05}, "milk\nmain")  # the log begins
    # the turn's reading (logged on her body's clock, before her decision): the alarm moved what her pinned
    # alertness let it, the relief eased some strain; the message's own push and another chat's are not reactions
    memory.log_push(came + 2, "reacting to: the deploy alarm", {"noradrenaline": 0.1, "cortisol": 0.05}, "milk\nmain")
    memory.log_push(came + 2, "relief: putting it off", {"cortisol": -0.025}, "milk\nmain")
    memory.log_push(came + 2, 'The user said "the alarm"', {"reward": 0.04}, "milk\nmain")
    memory.log_push(came + 2, "reacting to: something else", {"cortisol": 0.2}, "milk\nother")
    decisions = {
        turn: {"at": came + 60, "way": {"noradrenaline": 0.6, "cortisol": 0.1, "reward": 0.1}, "reacted": dict(CALLED)},
        old: {"at": came - 3540, "way": {"cortisol": 0.4}, "reacted": {"cortisol": 1.0}},
        older: {"at": came - 7200, "way": {"cortisol": 0.2}},  # before reactions were kept: nothing of them
    }
    with sqlite3.connect(home / "brain.sqlite3") as db:
        db.execute("UPDATE runs SET created = ? WHERE id = ?", (came - 3600, old))
        db.execute("UPDATE runs SET created = ? WHERE id = ?", (came - 7260, older))
        for run, decision in decisions.items():
            db.execute("UPDATE runs SET options = ? WHERE id = ?", (json.dumps({"mind": decision}), run))
    each = [{"id": 1, "text": "the deploy alarm", "likeness": 1.0, "moved": dict(CALLED)}]
    memory.put("self", {
        "reacted": [{"at": came + 60, "text": "the deploy alarm", "by": "reading", "moved": dict(CALLED),
                     "pleasant": -0.1, "each": each},
                    {"at": came - 3540, "text": "the old one", "by": "reading", "moved": {"cortisol": 1.0},
                     "pleasant": -0.2, "each": [{"id": 2, "text": "the old one", "likeness": 1.0, "moved": {"cortisol": 1.0}}]}],
        "decided": {"run": turn, "app": "milk", "session": "main", "at": came + 60,
                    "path": {"reacted": {"text": "the deploy alarm", "moved": dict(CALLED)}}}})
    memory.close()
    Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), home / "recall.sqlite3").stop()
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        db.execute("PRAGMA user_version = 4")
        db.close()
    return {"turn": turn, "old": old, "older": older}


def formats(home: Path) -> dict:
    out = {}
    for name in NAMES:
        db = sqlite3.connect(home / f"{name}.sqlite3")
        out[name] = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()
    return out


def test_a_turn_keeps_what_its_reactions_called_for_apart_from_what_they_moved(tmp_path):
    runs = format_4_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert formats(tmp_path) == dict.fromkeys(NAMES, dataformat.FORMAT)
    assert Path(report["backup"]).is_dir() and report["turns measured"] == 1 and report["turns from before the push log"] == 1
    store = Store(tmp_path / "brain.sqlite3")
    measured = store.run(runs["turn"])["options"]["mind"]
    assert measured["called"] == CALLED
    # what the alarm and the relief moved in its chat, in lots: not the 28.7 called for, not the message's own push
    assert measured["reacted"] == {"noradrenaline": round(0.1 / NA, 4), "cortisol": round(0.025 / CORT, 4)}
    assert measured["external"] == {"noradrenaline": round(0.6 - 0.1 / NA, 4), "cortisol": round(0.1 - 0.025 / CORT, 4),
                                    "reward": 0.1}
    unmeasured = store.run(runs["old"])["options"]["mind"]
    assert unmeasured["called"] == {"cortisol": 1.0} and "reacted" not in unmeasured and "external" not in unmeasured
    assert store.run(runs["older"])["options"]["mind"] == {"at": measured["at"] - 7260, "way": {"cortisol": 0.2}}


def test_her_last_decision_keeps_what_its_reactions_called_for_and_moved_and_her_latest_are_let_go(tmp_path):
    format_4_home(tmp_path)
    report = migration.migrate(tmp_path)
    assert report["latest reactions let go"] == 2
    memory = Memory(tmp_path / "mind.sqlite3")
    me = memory.get("self")
    memory.close()
    assert me["reacted"] == []  # what each moved is not in the log as its own: her next ones are kept as they are
    path = me["decided"]["path"]["reacted"]
    assert path["predicted"] == CALLED and path["moved"] == {"noradrenaline": round(0.1 / NA, 4),
                                                             "cortisol": round(0.025 / CORT, 4)}


def test_it_refuses_a_running_brain_and_leaves_a_migrated_home_as_it_is(tmp_path):
    format_4_home(tmp_path)
    (tmp_path / "server.json").write_text("{}", encoding="utf-8")
    with pytest.raises(migration.Refused):
        migration.migrate(tmp_path)
    assert formats(tmp_path) == dict.fromkeys(NAMES, 4)
    (tmp_path / "server.json").unlink()
    migration.migrate(tmp_path)
    assert migration.migrate(tmp_path) == {"done": f"already at format {dataformat.FORMAT}"}
