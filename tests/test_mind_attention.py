"""Attention turned inward: an ordinary way for her to notice how she is, with no tool and no extra call
(docs/superpowers/specs/2026-11-19-attention-and-action-credit-design.md, part 1)."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind import life
from sentientmilk_framework.mind.feel import CHANNELS, USUAL
from sentientmilk_framework.mind.life import Mind

pytestmark = pytest.mark.mind  # her mind lives in these tests

CHAT = '["they say hi", 0.2, 0.1, 0.0, "fine", "chat", "greeting", ""]'
ASKED = '["they ask after them", 0.3, 0.1, 0.0, "fine", "question", "feelings", "", "how they feel"]'
HOLDING_UP = '["they check in", 0.3, 0.0, 0.0, "fine", "question", "feelings", "", "how they are holding up"]'


def settle(mind, **lots):
    """Her body, and her sense of it, settled where ``lots`` put each channel from where it usually sits (all
    others at usual), as if it had been so for a while."""
    with mind._lock:
        levels = {name: USUAL[name] + lots.get(name, 0.0) * CHANNELS[name][1] for name in CHANNELS}
        mind.body.levels.update(levels)
        sensed = mind.body.sensed()
        for name in CHANNELS:
            mind.senses.seen[name] = mind.senses.used[name] = sensed[name]
            mind.senses.bias[name] = 0.0
        if "adenosine" not in lots:  # the pressure usual for the hour, as felt
            mind.body.levels["adenosine"] += mind.body.shift()
            mind.senses.seen["adenosine"] = mind.senses.used["adenosine"] = USUAL["adenosine"]
        mind.body.asleep = False


def attend(mind, **kwargs):
    with mind._lock:
        return mind.attend(time.time(), kwargs.pop("of", "turn"), **kwargs)


def test_a_settled_body_in_a_quiet_moment_draws_nothing(brain):
    mind = brain.brain.mind
    settle(mind)
    assert attend(mind, free=1.0) is None and mind.self["attending"] is None
    brain.provider.mind_replies["imagine"] = [CHAT]
    result = turn(brain, "milk", "hi there")
    decision = brain.store.run(result["run"])["options"]["mind"]
    assert decision["attended"] is None and "You turn inward" not in decision.get("note", "")
    assert "You turn inward" not in brain.provider.sent[-1]["messages"][-1]["content"]


def test_her_body_far_from_usual_is_noticed_once_and_again_only_as_it_changes(brain):
    mind = brain.brain.mind
    settle(mind, dopamine=-2.2)
    episodes, named, levels = len(mind.memory.recent(100)), len(mind.concepts.named), dict(mind.body.levels)
    first = attend(mind, free=1.0)
    assert first["why"] == ["body"] and first["taken"] == {"dopamine": pytest.approx(-2.2, abs=0.05)}
    assert "For a while now: much less drive than usual." in first["text"]
    # noticing is not naming: no memory of its own, no name, nothing eased
    assert len(mind.memory.recent(100)) == episodes and len(mind.concepts.named) == named
    assert mind.body.levels == levels
    assert attend(mind, free=1.0) is None  # the same, known: it does not call again, tick after tick
    settle(mind, dopamine=-2.5)  # a little worse: too little to be news
    assert attend(mind, free=1.0) is None
    settle(mind, dopamine=-2.5, oxytocin=1.2)  # something new while she attends to herself: captured, same stretch
    more = attend(mind, free=1.0)
    assert more["key"] == first["key"] and list(more["taken"]) == ["oxytocin"]
    item = mind._in_mind(time.time()).items[first["key"]]
    assert item["kind"] == "noticed" and "closeness" in item["text"]  # on her mind, in what she took in
    settle(mind, dopamine=-2.5)  # it eased: no longer known, so it would be news again
    assert attend(mind, free=1.0) is None and "oxytocin" not in mind.self["attending"]["known"]


def test_focus_held_outward_keeps_off_what_an_idle_mind_would_notice(brain):
    mind = brain.brain.mind
    settle(mind, dopamine=-1.5)
    assert attend(mind, free=0.4) is None  # absorbed in a message or a task
    assert attend(mind, free=1.0)["why"] == ["body"]  # idle, the same state draws her


def test_being_torn_between_two_ways_turns_her_attention_to_both(brain):
    mind = brain.brain.mind
    settle(mind)
    considered = [{"act": "do", "what": "fix the clock", "parts": {"care": 0.3, "cost": -0.25}, "worth": 0.21,
                   "picked": True},
                  {"act": "later", "what": "fix the clock", "parts": {"care": 0.1, "cost": -0.02}, "worth": 0.18,
                   "picked": False}]
    found = attend(mind, free=0.5, considered=considered, temperature=0.1)
    assert found["why"] == ["torn"] and found["torn"] == "later" and found["text"].startswith("You are torn: ")
    clear = [dict(considered[0], worth=0.5), considered[1]]
    assert attend(mind, free=0.5, considered=clear, temperature=0.1) is None  # one clearly wins


def test_asleep_nothing_is_noticed_and_after_sleep_what_she_knew_is_gone(brain):
    mind = brain.brain.mind
    settle(mind, dopamine=-2.2)
    first = attend(mind, free=1.0)
    mind.body.asleep = True
    assert attend(mind, free=1.0) is None
    mind.body.asleep = False
    mind.self["slept"] = time.time()
    again = attend(mind, free=1.0)
    assert again["key"] != first["key"] and again["why"] == ["body"]  # a new day, noticed anew


def test_a_restart_goes_on_with_the_same_stretch_and_notices_nothing_twice(brain):
    mind = brain.brain.mind
    settle(mind, dopamine=-2.2)
    first = attend(mind, free=1.0)
    mind.save()
    restored = Mind(brain.brain)
    assert restored.self["attending"]["key"] == first["key"]
    with restored._lock:
        restored.body.levels.update(mind.body.levels)
        restored.senses.seen.update(mind.senses.seen)
        restored.senses.used.update(mind.senses.used)
        restored.senses.bias.update(mind.senses.bias)
        assert restored.attend(time.time(), "turn", free=1.0) is None


def test_a_vague_mind_notices_only_how_it_is_on_the_whole_and_a_mixed_one_both_ways(brain, monkeypatch):
    mind = brain.brain.mind
    settle(mind, dopamine=-2.2, oxytocin=1.6)
    mixed = attend(mind, free=1.0)
    assert "less drive" in mixed["text"] and "more closeness" in mixed["text"]  # both, and no name for either
    mind.self["attending"] = None
    monkeypatch.setattr(mind, "_clear", lambda: 0.2)
    vague = attend(mind, free=1.0)
    assert "you can't tell more than that" in vague["text"] and "drive" not in vague["text"]


def test_a_thought_of_hers_turns_to_herself_once_and_wandering_ends_the_stretch(brain, monkeypatch):
    mind = brain.brain.mind
    settle(mind, dopamine=-1.5)
    now = time.time()
    with mind._lock:
        assert mind._noticing(now, False) >= life.RESTING  # it pulls as a resting mind's wandering does
        assert mind._noticing(now, True) is None  # at work, as focused as she is, it does not
    brain.provider.mind_replies["think"] = ['{"thought": "I am so drained today.", "could": []}']
    mind._think("notice", None)
    asked = brain.provider.mind_requests[-1]["messages"][1]["content"]
    assert "Your attention turns to yourself. For a while now: much less drive than usual." in asked
    thought = mind.self["thoughts"][0]
    assert thought["kind"] == "notice" and thought["episode"] in mind.self["attending"]["episodes"]
    with mind._lock:
        assert mind._noticing(time.time(), False) is None  # known now: no second thought of it, tick after tick
    brain.provider.mind_replies["think"] = ['{"thought": "Rain on the window again.", "could": []}']
    mind._think("wonder", None)
    assert mind.self["attending"]["released"]  # her mind went elsewhere


def test_asked_how_she_is_in_any_words_she_turns_inward_and_names_it_with_the_tool_off(brain):
    mind = brain.brain.mind
    brain.client.update_app("milk", disabled_toolkits=["inward"])
    settle(mind, dopamine=-1.0)
    for question, reading in (("how are you feeling?", ASKED), ("you holding up ok?", HOLDING_UP)):
        brain.provider.mind_replies["imagine"] = [reading]
        brain.provider.mind_replies["named"] = ['{"named": [{"words": "wrung out", "quote": "Honestly, wrung out."}]}']
        brain.provider.replies += ["Honestly, wrung out."]
        result = turn(brain, "milk", question)
        sent = brain.provider.sent[-1]
        assert not any(t["function"]["name"] == "look_inward" for t in sent.get("tools") or [])
        note = sent["messages"][-1]["content"]
        assert "You turn inward: Looking inward: For a while now: less drive than usual." in note
        # a little of herself, not her day again: her note has her day, and her last decision, read again here,
        # was carried on in words as a shell command in 15 of 52 held-out answers (the 0.48 exam)
        assert not any(day in note for day in ("on your mind today", "What you did today", "Last time you weighed",
                                               "What got to you today", "What you have come to know"))
        assert question not in note.split("Inside you:")[1]  # said already
        decision = brain.store.run(result["run"])["options"]["mind"]
        assert decision["attended"]["why"][0] == "asked"
        wait_for(lambda: mind.memory.of_run(result["run"]))
    said = [one for concept in mind.concepts.named for one in concept["said"] if one["how"] == "speech"]
    assert len(said) == 2 and all(one["named"] == "now" and one["run"] for one in said)
    kept = mind.memory.of_run(result["run"])
    assert {"source": "inward", "kind": "noticed"}.items() <= json.loads(kept["attention"])[-1].items()
    assert mind.state()["looked"]["about"] == ""  # she looked inward, as the console tells


def test_looking_inward_on_purpose_is_the_same_attention_and_records_its_stretch(brain):
    mind = brain.brain.mind
    settle(mind, dopamine=-2.2)
    seen = mind.look_inward()
    assert seen.startswith("Looking inward:") and "For a while now: much less drive than usual." in seen
    state = mind.self["attending"]
    assert state["of"] == ["look"] and "deliberate" in state["why"] and state["known"]["dopamine"] < -2
    assert attend(mind, free=1.0) is None  # she knows it now
