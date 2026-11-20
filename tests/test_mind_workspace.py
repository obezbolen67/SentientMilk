"""What is on her mind: one workspace every process writes and reads (docs/superpowers/specs/2026-11-19-workspace-design.md)."""

import json
import math
import sqlite3
import threading
import time

import numpy as np
import pytest
from conftest import Meaning, turn, use, wait_for

from sentientmilk_framework.mind.workspace import Workspace

T0 = 1_000_000.0


def new_space() -> Workspace:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    return Workspace(db, threading.RLock())


def test_more_uses_and_a_later_one_keep_an_item_more_active():
    space = new_space()
    space.enter("thought:1", "thought", "the cat", T0)
    space.enter("thought:2", "thought", "the deploy", T0)
    space.use(["thought:2"], T0 + 60)
    space.enter("thought:3", "thought", "rain", T0 + 3000)
    space.enter("thought:4", "thought", "the oven", T0)
    space.use(["thought:4"] * 4, T0)  # gone over five times at once: five traces of one age
    once, twice, fresh, burst = (space.items[f"thought:{n}"] for n in (1, 2, 3, 4))
    assert Workspace.activation(twice, T0 + 3600) > Workspace.activation(once, T0 + 3600)
    assert Workspace.activation(fresh, T0 + 3600) > Workspace.activation(once, T0 + 3600)
    assert Workspace.activation(once, T0 + 86400) < Workspace.activation(once, T0 + 3600)  # it fades unused
    assert Workspace.activation(burst, T0 + 3600) == pytest.approx(Workspace.activation(once, T0 + 3600) + math.log(5))


def test_what_she_means_to_do_and_what_the_cue_is_about_come_as_far_as_her_span_holds():
    space = new_space()
    space.enter("concern:5", "put off", "finish the clock widget", T0, episode=10)
    space.enter("thought:11", "thought", "rain on the window", T0 + 3500, episode=11)
    space.enter("thought:12", "thought", "the deploy went fine", T0 + 3400, episode=12)
    space.enter("urge", "intends", "you mean to tell them: hi", T0 + 3300, episode=13)
    now = T0 + 3600
    likeness = {"concern:5": 0.9, "thought:12": 0.3, "thought:11": 0.0}
    picked = space.before_her(now, 4, likeness)  # what she means to do, then what the cue is about, most alike first
    assert [item["key"] for item in picked] == ["urge", "concern:5", "thought:12"]  # nothing unrelated, however fresh
    assert [item["key"] for item in space.before_her(now, 1, likeness)] == ["urge"]  # a spent mind: one
    assert [i["key"] for i in space.before_her(now, 3, likeness, carried=["urge"])] == ["concern:5", "thought:12"]
    assert [i["key"] for i in space.before_her(now, 3, {})] == ["urge"]  # she cannot tell meaning now
    # no cue (looking inward): the most active, by their uses alone
    assert [item["key"] for item in space.before_her(now, 4)] == ["thought:11", "thought:12", "urge", "concern:5"]
    assert space.before_her(now, 0) == []


def test_items_leave_with_their_records_and_their_words_keep_their_meaning_until_they_change():
    space = new_space()
    space.enter("self", "self", "I sulk when ignored.", T0)
    space.enter("thought:1", "thought", "a", T0)
    space.enter("thought:2", "thought", "b", T0)
    space.leave_kind("thought", keep=["thought:2"])
    assert set(space.items) == {"self", "thought:2"}
    row = space.items["self"]["id"]
    space.vectors.put([(row, np.ones(3, np.float32) / np.sqrt(3))], "m")
    space.enter("self", "self", "I sulk  when ignored.", T0 + 5)  # the same words: a use, the same meaning
    assert space.items["self"]["n"] == 2 and space.vectors.vector(row, "m") is not None
    assert space.likeness(np.ones(3, np.float32) / np.sqrt(3), "m", lambda c: c) == {"self": pytest.approx(1.0)}
    space.enter("self", "self", "I sulk when ignored, and say so later.", T0 + 9)  # new words: meaning again
    assert space.vectors.vector(row, "m") is None and space.likeness(np.ones(3) / np.sqrt(3), "m", lambda c: c) == {}
    space.leave("self")
    assert list(space.items) == ["thought:2"]
    with pytest.raises(ValueError):
        space.enter("x", "a mood", "", T0)


class Garden(Meaning):
    CONCEPTS = {**Meaning.CONCEPTS, "clock": ("clock", "widget", "clocks"), "rain": ("rain", "window", "raining")}


LATER_CLOCK = '[0.5, 0.5, 0.4, "request", "clock", "tired", ["later", "the clock widget", 0.8, 0.7, 0.1]]'


def busy(mind, about, count, at):
    """Thoughts of hers about something else, which she has gone over again and again (more active than what the
    test is about)."""
    with mind._lock:
        mind.self["thoughts"] = [{"episode": 9000 + n, "at": at, "kind": "wonder", "thought": f"{about} {n}",
                                  "want": "nothing", "leaned": None} for n in range(count)] + mind.self["thoughts"]
        mind._in_mind(at)
        for _ in range(5):
            mind.workspace.use([f"thought:{9000 + n}" for n in range(count)], at)


def part(text, head):
    return text.split(head)[1].split("\n")[0] if head in text else ""


def put_off_an_hour_ago(brain):
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = [LATER_CLOCK]
    brain.provider.replies += ["Later, okay?"]
    turn(brain, "milk", "could you make me a clock widget?", session="widgets")
    with mind._lock:
        mind.self["concerns"][0]["at"] -= 3600
    brain.brain.recall.sweep()
    busy(mind, "the bread rising in the oven", 6, time.time())
    brain.provider.replies += ["Oh, the clocks."]
    turn(brain, "milk", "the clocks in the hallway stopped again", session="other")
    return part(brain.provider.last_user_text(), "Also in mind:")


@pytest.mark.mind
def test_something_she_put_off_that_the_message_is_about_reaches_her_note(brain):
    use(brain, Garden())
    also = put_off_an_hour_ago(brain)
    assert any(item.startswith(" put off an hour ago") and "the clock widget" in item
               for item in also.split(";")), also
    assert "the bread rising" not in also  # what the message is not about stays out, however fresh


class Down(Garden):
    def _embed(self, texts, query):
        raise RuntimeError("the embeddings service is down")


@pytest.mark.mind
def test_with_nothing_to_tell_meaning_by_nothing_comes_by_meaning(brain):
    use(brain, Down())  # the negative control: she cannot tell meaning now
    assert put_off_an_hour_ago(brain) == ""  # and not what is most active in its place


@pytest.mark.mind
def test_a_thought_sees_what_she_is_doing_and_means_to_say(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    now = time.time()
    brain.store.add_run("milk", "main", "task", {"goal": "sort the garden photos"}, status="working")
    with mind._lock:
        mind.self["urge"] = {"at": now - 300, "want": "tell", "app": "milk", "session": "main",
                             "say": "the seedlings sprouted", "actor": "", "thought": now - 300, "offered": False,
                             "text": "", "features": None}
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Quiet."})]
    mind._think("wonder", None)
    also = part(brain.provider.mind_requests[-1]["messages"][1]["content"], "Also on their mind:")
    assert "doing sort the garden photos" in also and "meaning to tell the user: the seedlings sprouted" in also
    assert '"hello"' not in also  # the talk it goes over is before it already


@pytest.mark.mind
def test_her_self_view_comes_to_a_turn_about_it_and_not_to_an_unrelated_one(brain):
    mind = brain.brain.mind
    use(brain, Garden())
    brain.provider.replies += ["It rains."]
    turn(brain, "milk", "the rain on the window is loud")
    rainy = wait_for(lambda: (mind.memory.recent(1, kinds=("exchange",)) or [None])[0])
    brain.brain.recall.sweep()
    now = time.time()
    with mind._lock:
        mind.self["self_view"] = {"text": "I go quiet when the rain is on the window.", "since": now - 3600,
                                  "at": now - 3600,
                                  "kind": "self-inference", "origins": [rainy["id"]], "against": [],
                                  "confidence": "supported"}
    busy(mind, "a thought about bread", 6, now)
    brain.provider.replies += ["Hm.", "Yes."]
    turn(brain, "milk", "is it raining at your window too?")
    assert "known of myself by now: I go quiet when the rain" in brain.provider.last_user_text()
    turn(brain, "milk", "how do I bake bread?")
    assert "I go quiet when the rain" not in brain.provider.last_user_text()


@pytest.mark.mind
def test_looking_inward_she_sees_what_else_is_on_her_mind(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Oh!"]
    turn(brain, "milk", "my seedlings sprouted", session="garden")
    seen = mind.look_inward()
    assert "my seedlings sprouted" in part(seen, "Also here now:")


@pytest.mark.mind
def test_her_sleep_ends_what_was_before_her_and_what_she_means_to_do_stays(brain):
    mind = brain.brain.mind
    now = time.time()
    with mind._lock:
        mind.self["thoughts"] = [{"episode": 901, "at": now - 7200, "kind": "wonder", "thought": "crickets at night",
                                  "want": "nothing", "leaned": None}]
        mind.self["concerns"] = [{"what": "finish the clock widget", "app": "milk", "session": "main", "at": now - 7200,
                                  "run": None}]
        mind.workspace.enter("asked:milk\nmain", "asked", 'the user said: "goodnight"', now - 7200)
        assert {"thought:901", "asked:milk\nmain", f"concern:{now - 7200}"} <= set(mind._in_mind(now).items)
        mind.self["slept"] = now - 3600  # she slept on it since
        assert set(mind._in_mind(now).items) == {f"concern:{now - 7200}"}
