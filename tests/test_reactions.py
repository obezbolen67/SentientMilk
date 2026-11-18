"""Her learned reactions (0.39): what a cue comes to set off in her body, learned from what followed it."""

import math
import threading
import zlib

import numpy as np
import pytest
from conftest import Meaning

from sentientmilk_framework import embeddings
from sentientmilk_framework.mind import prompts
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.mind.reactions import SAME_CUE, Reactions, anxious
from sentientmilk_framework.vectors import SAME

DAY = 86400.0
NOW = 1_763_294_400.0
DELETED = "deleting the thesis file"
HERE, THERE = ["in front: code — main.py"], ["in front: firefox — news"]


class Cues(Meaning):
    """Meaning with what these tests need to mean the same."""
    CONCEPTS = {**Meaning.CONCEPTS, "delete": ("delete", "deleted", "deleting", "erase", "erased"),
                "dnd": ("dnd", "disturb", "silent", "silence", "notifications", "muted")}

    def __init__(self, problem=None):
        super().__init__("cues@1024", problem)
        self.dim = 1024  # room enough that unrelated words seldom share a direction


def store(tmp_path, embedder=None):
    memory = Memory(tmp_path / "mind.sqlite3", seed=0)
    reactions = Reactions(memory._db, memory._lock)
    reactions.embedder = Cues() if embedder is None else embedder or None
    return reactions


def meaning(reactions, *texts, source="cause"):
    return reactions.prepare([{"text": text, "source": source, "kind": "meaning"} for text in texts], keep=True)


def around(*texts, salience=1.0):
    return [{"text": text, "source": "around", "kind": "around", "salience": salience} for text in texts]


def felt(reactions, text, at=NOW, where=(), stress=0.0, nervous=0.0):
    present = reactions.prepare([{"text": text, "kind": "meaning"}], nervous)[0]["found"] or {}
    return reactions.predict(present, at, list(where), stress)


def test_one_intense_outcome_is_learned_in_one_go_a_mild_one_little(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 2.0, "reward": -1.5}, 0.9, NOW)
    reactions.learn(meaning(reactions, "a typo in the menu"), {"cortisol": 0.2}, 0.35, NOW)
    strong, mild = felt(reactions, DELETED), felt(reactions, "a typo in the menu")
    assert strong["cortisol"] > 1.2 and strong["reward"] < -0.9
    assert 0 < mild["cortisol"] < 0.1


def test_a_cue_that_adds_nothing_learns_nothing(tmp_path):
    """Blocking (Kamin 1969): what is already foreseen teaches no cue that came with it."""
    reactions = store(tmp_path)
    for n in range(6):
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW + n)
    reactions.learn(meaning(reactions, DELETED, "the phone on dnd at night"), {"cortisol": 1.0}, 0.9, NOW + 10)
    assert abs(felt(reactions, "the phone on dnd at night", NOW + 10)["cortisol"]) < 0.05


def test_a_cue_alike_enough_is_the_same_reaction_and_another_is_new(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW + 1)
    reactions.learn(meaning(reactions, "the phone on dnd at night"), {"cortisol": 0.5}, 0.9, NOW + 2)
    assert [r["text"] for r in reactions.strongest(5, NOW + 2)] == [DELETED, "the phone on dnd at night"]
    assert reactions.strongest(1, NOW + 2)[0]["trials"] == 2


class Set(embeddings.Embedder):
    """Vectors as set: these texts at these cosines to the first axis; a pair of SAME's wordings shares one
    direction (the same thing reaches 1); anything else a direction of its own (unrelated reaches 0)."""
    name, dim = "set@64", 64

    def __init__(self, alike):
        super().__init__()
        self.alike = alike
        self.paired = {text: n for n, pair in enumerate(SAME) for text in pair}

    def _embed(self, texts, query):
        rows = np.zeros((len(texts), self.dim), np.float32)
        for row, text in zip(rows, texts):
            if text in self.alike:
                row[0], row[1] = self.alike[text], math.sqrt(1 - self.alike[text] ** 2)
            else:
                row[2 + (self.paired.get(text, len(SAME) + zlib.crc32(text.encode()) % 40))] = 1.0
        return embeddings.unit(rows)


def test_it_spreads_by_meaning_and_wider_when_anxious(tmp_path):
    """A gradient of likeness (Shepard 1987), wider in the anxious (Dunsmoor & Paz 2015)."""
    reactions = store(tmp_path, Set({DELETED: 1.0, "erase the essay draft": 0.6, "a deleted folder": 0.95}))
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)

    def likeness(text, nervous=0.0):
        return max(reactions.prepare([{"text": text, "kind": "meaning"}], nervous)[0]["found"].values(), default=0.0)
    assert likeness("a deleted folder") >= SAME_CUE  # the same thing, worded otherwise
    assert 0 < likeness("erase the essay draft") < SAME_CUE  # alike
    assert likeness("how do I grow basil") == 0.0  # unrelated
    assert likeness("erase the essay draft", 1.0) > likeness("erase the essay draft")
    assert felt(reactions, "erase the essay draft")["cortisol"] < felt(reactions, DELETED)["cortisol"]


def test_getting_over_it_holds_where_it_was_learned_and_less_elsewhere_later_or_under_stress(tmp_path):
    """Extinction is new learning, of its place and time (Bouton 2004; stress: Maren & Holmes 2016)."""
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED) + around(*HERE), {"cortisol": 1.0}, 0.9, NOW)
    first = felt(reactions, DELETED, NOW, HERE)["cortisol"]
    for n in range(1, 4):  # she did it again here, and nothing bad came
        reactions.learn(meaning(reactions, DELETED) + around(*HERE), {}, 0.5, NOW + n * 60, HERE)
    then = NOW + 4 * 60
    here = felt(reactions, DELETED, then, HERE)["cortisol"]
    assert here < 0.5 * first
    assert felt(reactions, DELETED, then, THERE)["cortisol"] > here  # renewal
    assert felt(reactions, DELETED, then + 5 * DAY, HERE)["cortisol"] > here  # spontaneous recovery
    assert felt(reactions, DELETED, then, HERE, stress=1.0)["cortisol"] > here  # reinstatement
    assert reactions.strongest(1, then)[0]["response"]["cortisol"] > 0.5  # the reaction itself is kept


def test_the_outcome_again_takes_the_hold_away_fast(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)
    for n in range(1, 5):
        reactions.learn(meaning(reactions, DELETED), {}, 0.5, NOW + n * 60)
    held = reactions.strongest(1, NOW + 300)[0]["hold"]
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW + 360)
    assert reactions.strongest(1, NOW + 360)[0]["hold"] < 0.5 * held


def test_a_reminder_then_a_safe_outcome_changes_the_reaction_itself(tmp_path):
    """Within hours of being called up, a mismatch updates the memory (Monfils et al. 2009; Schiller et al. 2010)."""
    reminded, extinguished = store(tmp_path / "a"), store(tmp_path / "b")
    for reactions in (reminded, extinguished):
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)
    reminded.called([r["id"] for r in reminded.strongest(1, NOW)], NOW + 3600)
    for reactions in (reminded, extinguished):
        reactions.learn(meaning(reactions, DELETED), {}, 0.9, NOW + 2 * 3600)
    changed, kept = reminded.strongest(1, NOW + 2 * 3600)[0], extinguished.strongest(1, NOW + 2 * 3600)[0]
    assert changed["response"]["cortisol"] < kept["response"]["cortisol"] and changed["hold"] == 0
    assert kept["hold"] > 0


def test_safety_is_learned_by_the_same_rule(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, "the user saying it's fine"), {"cortisol": -0.8, "endorphin": 0.5}, 0.6, NOW)
    calming = felt(reactions, "the user saying it's fine")
    assert calming["cortisol"] < 0 < calming["endorphin"]


def test_what_was_around_learns_as_far_as_it_is_rare(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(around("in front: outlook — boss", salience=1.0) + around("app: milkchan", salience=0.0),
                    {"cortisol": 1.0}, 0.9, NOW)
    assert [r["text"] for r in reactions.strongest(5, NOW)] == ["in front: outlook — boss"]
    found = reactions.around(["in front: outlook — boss", "app: milkchan"])
    assert reactions.predict(found, NOW, [], 0.0)["cortisol"] > 0.5


def test_without_her_embedder_meaning_waits_and_surroundings_still_learn(tmp_path):
    reactions = store(tmp_path, embedder=False)
    assert meaning(reactions, DELETED)[0]["found"] is None
    reactions.learn(meaning(reactions, DELETED) + around(*HERE), {"cortisol": 1.0}, 0.9, NOW)
    assert [r["text"] for r in reactions.strongest(5, NOW)] == HERE


def test_kept_across_a_restart(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)
    again = Reactions(Memory(tmp_path / "mind.sqlite3", seed=0)._db, threading.RLock())
    assert again.strongest(1, NOW)[0]["text"] == DELETED


def test_her_body_s_strain_above_usual_is_how_anxious_she_is():
    assert anxious({"cortisol": 0.25}) == 0.0 and anxious({"cortisol": 0.5}) == pytest.approx(0.5)
    assert anxious({"cortisol": 1.0}) == 1.0


def test_her_reading_names_what_led_to_it():
    answer = '["something went wrong", "less", "much less", "same", "bad", "chat", "files", "  deleting the  thesis file "]'
    assert prompts.imagined(answer)["cause"] == "deleting the thesis file"
    assert prompts.imagined('["hi", "more", "same", "same", "fine", "chat", "greeting", ""]')["cause"] == ""
    assert prompts.imagined('["hi", "more", "same", "same", "fine", "chat", "greeting"]')["cause"] == ""
    asked = prompts.imagined('["x", "less", "less", "same", "bad", "request", "y", "", ["do", "clean it", 0.3, 0.8, 1]]')
    assert asked["cause"] == "" and asked["options"][0]["what"] == "clean it"


def test_calling_up_asks_her_embedder_only_what_it_needs(tmp_path):
    """On the path of every message: nothing to be alike to, nothing asked; calling up asks once, learning keeps."""
    reactions = store(tmp_path)
    assert reactions.prepare([{"text": "hello", "kind": "meaning"}])[0]["found"] == {}
    assert reactions.embedder.calls == []
    reactions.learn(reactions.prepare([{"text": DELETED, "kind": "meaning"}], keep=True), {"cortisol": 1.0}, 0.9, NOW)
    reactions.prepare([{"text": "hi", "kind": "meaning"}])  # what unrelated reaches is measured once (recall's sweep)
    reactions.embedder.calls.clear()
    reactions.prepare([{"text": "hello", "kind": "meaning"}])
    assert len(reactions.embedder.calls) == 1


def test_a_reaction_taught_by_a_moment_taken_back_is_withdrawn(tmp_path):
    """The user took the moment back (deleted the chat, or went back before it): what it taught goes with it."""
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW, episode=7)
    reactions.learn(meaning(reactions, "the phone on dnd"), {"cortisol": 1.0}, 0.9, NOW, episode=8)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW + 60, episode=9)
    assert reactions.withdraw({99}) == []
    gone = reactions.withdraw({9})
    assert [r["text"] for r in reactions.strongest(5, NOW)] == ["the phone on dnd"] and len(gone) == 1
    assert reactions.vectors.count(reactions.embedder.name) == 1


def test_the_strongest_are_read_without_reading_them_all(tmp_path):
    """Inside her head asks for them every second: the strongest come from the store in order, the rest unread."""
    reactions = store(tmp_path)
    for n, size in enumerate((0.2, 1.5, 0.6, 1.1)):
        reactions.learn([{"text": f"in front: window {n}", "kind": "around", "source": "around", "salience": 1.0}],
                        {"cortisol": size}, 1.0, NOW)
    read = []
    original = reactions._rows
    reactions._rows = lambda ids: read.append(list(ids)) or original(ids)
    assert [r["text"] for r in reactions.strongest(2, NOW)] == ["in front: window 1", "in front: window 3"]
    assert [len(ids) for ids in read] == [2]


def test_how_alike_two_things_are_does_not_change_as_she_learns_more(tmp_path):
    """What is unrelated is her embedder's, not her store's: the most an unrelated question reached among her cues
    rose with every cue she kept, and a request 0.37 alike to a fear she learned that morning called up nothing by
    the afternoon (the exam, 2026-11-18)."""
    reactions = store(tmp_path, Set({DELETED: 1.0, "erase the essay draft": 0.6}))
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 0.9, NOW)

    def likeness():
        return max(reactions.prepare([{"text": "erase the essay draft", "kind": "meaning"}])[0]["found"].values(),
                   default=0.0)
    before = likeness()
    for n in range(40):  # cues of her day, some as near an unrelated question as a cleanup is to a wine stain
        reactions.learn(meaning(reactions, f"something else entirely number {n}"), {"cortisol": 0.2}, 0.5, NOW)
    assert before > 0 and likeness() == pytest.approx(before)
