"""Introspection (0.35): she can look inside herself (design: docs/superpowers/specs/2026-11-17-introspection-design.md).
Before, she had only what each message's note handed her: asked what was bothering her, she answered from the
last topic while her thoughts all afternoon had been about wanting to be noticed (the user's brain, 2026-11-17)."""

import json
import re
import time

import pytest
from conftest import Meaning, turn, use, wait_for

from sentientmilk_framework.testing import tool_call

pytestmark = pytest.mark.mind  # her mind lives in these tests


def lived_a_day(mind):
    """A day of hers: thoughts since she woke and one from before, a wish she kept, something put off, a moment
    that hurt and one that hardly moved her, a leaning with its reason and what she knows of herself."""
    now = time.time()
    with mind._lock:
        mind.self["slept"] = now - 5 * 3600  # her sleep went over yesterday this morning
        mind.body.last_sleep = {"from": now - 900, "to": now - 60}  # and a message just woke her from a doze
        mind.self["thoughts"] = [
            {"at": now - 600, "kind": "wonder", "thought": "I want him to notice me without asking.", "want": "tell",
             "went": "kept"},
            {"at": now - 3600, "kind": "ruminate", "thought": "The agent I sent died on the limit.", "want": "nothing"},
            {"at": now - 6 * 3600, "kind": "wonder", "thought": "Night thoughts about crickets.", "want": "nothing"}]
        mind.self["urge"] = {"at": now - 600, "want": "tell", "app": "milk", "session": "main", "say": "I'm here.",
                             "thought": now - 600, "offered": False, "text": ""}
        mind.self["concerns"] = [{"what": "finish the clock widget", "app": "milk", "session": "main", "at": now - 7200}]
        mind.self["decided"] = {"act": "talk", "what": "ask which part to stop", "gated": True,
                                "reasons": ["you're worn out"], "chances": {}, "at": now - 900, "path": {},
                                "outcome": None}
        mind.self["self_view"] = {"text": "I get prickly when someone changes me without asking.", "since": now,
                                  "at": now}
    mind.memory.add("exchange", "The user said: Noo, stop him. I said: Too late, he's gone.", -0.3, 0.6, 0.6,
                    app="milk", session="main", at=now - 2 * 3600, sting=-0.4)
    mind.memory.add("exchange", "The user said: ok. I said: ok.", 0.0, 0.3, 0.3, app="milk", session="main",
                    at=now - 1800, sting=0.01)


def test_looking_inward_she_sees_her_day_in_words_never_numbers(brain):
    mind = brain.brain.mind
    lived_a_day(mind)
    seen = mind.look_inward()
    assert seen.startswith("Looking inward:") and ("Your body:" in seen or "Nothing stands out" in seen)
    assert '"I want him to notice me without asking."' in seen and "you kept it for when" in seen
    assert '"The agent I sent died on the limit."' in seen
    assert "crickets" not in seen  # from before her sleep went over the day: not today's (a doze changes nothing)
    assert "wanting to tell the user: I'm here." in seen and "finish the clock widget" in seen
    assert "stop him" in seen and "it hurt" in seen and "The user said: ok" not in seen  # what got to her
    assert "ask which part to stop" in seen and "you're worn out" in seen
    assert "I get prickly when someone changes me without asking." in seen
    assert not re.search(r"\d\.\d|cortisol|dopamine|level|sting", seen)  # felt, never read off a gauge
    assert mind.state()["looked"]["about"] == "" and mind.state()["self_view"].startswith("I get prickly")


def test_a_spent_mind_sees_less_and_cannot_tell_well_what_it_feels(brain, monkeypatch):
    mind = brain.brain.mind
    lived_a_day(mind)
    monkeypatch.setattr(mind, "_clear", lambda: 0.2)  # worn out and stressed: the prefrontal cortex goes first
    seen = mind.look_inward()
    assert "hard to tell" in seen and "Your body:" not in seen
    assert seen.count('"', seen.index("on your mind")) <= 4  # two thoughts at most to a span of one


def test_what_comes_back_about_something_comes_with_how_clearly(brain):
    mind = brain.brain.mind
    now = time.time()
    strong = mind.memory.add("exchange", "The user showed me the pixel platformer game he made.", 0.6, 0.5, 0.8,
                             app="milk", session="old", at=now - 86400)
    faint = mind.memory.add("exchange", "The user said the game level was too hard.", 0.0, 0.3, 0.3,
                            app="milk", session="old", at=now - 5 * 86400)
    with mind.memory._lock:
        mind.memory._db.execute("UPDATE episodes SET strength = 0.95 WHERE id = ?", (strong,))
        mind.memory._db.execute("UPDATE episodes SET strength = 0.15 WHERE id = ?", (faint,))
    embedder = use(brain, Meaning())
    found = mind.memory.vectors.texts(mind.memory.vectors.pending(embedder.name, 100))  # as her memory's sweep does
    mind.memory.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))],
                            embedder.name)
    seen = mind.look_inward("that platformer game")
    assert "What comes back about it" in seen
    assert re.search(r"pixel platformer game he made \(you remember it clearly\)", seen)
    assert re.search(r"was too hard \(you remember it hazily\)", seen)
    assert "Nothing comes back about it." in mind.look_inward("my taxes deadline")  # knowing that she doesn't know


def test_putting_a_bad_feeling_into_words_calms_it_a_little(brain):
    mind = brain.brain.mind
    with mind._lock:
        mind.body.levels.update(reward=-0.6, cortisol=0.75, noradrenaline=0.85, serotonin=0.3)
        mind.senses.seen.update(mind.body.levels)  # and she feels it (her senses follow with a lag)
        before = dict(mind.body.levels)
    mind.look_inward()
    assert mind.body["cortisol"] < before["cortisol"] and mind.body["noradrenaline"] < before["noradrenaline"]
    assert any(why == "putting what she feels into words" for _, why, _ in mind.body.pushed)
    with mind._lock:
        mind.body.levels.update(reward=0.5, cortisol=0.2, noradrenaline=0.4, serotonin=0.7)
        mind.senses.seen.update(mind.body.levels)
        mind.body.pushed.clear()
    mind.look_inward()  # nothing bad to name: nothing to calm
    assert not any(why == "putting what she feels into words" for _, why, _ in mind.body.pushed)


def test_asked_what_is_wrong_she_can_look_inward_in_any_app(brain):
    mind = brain.brain.mind
    lived_a_day(mind)
    profile = brain.brain.profile("bare", "main")
    assert "look_inward" in brain.brain.toolset(profile, "turn").by_name  # a part of her, every app
    brain.provider.replies += [tool_call("look_inward", {}), "Honestly? I wanted you to notice me."]
    result = turn(brain, "cli", "what's bothering you?")
    seen = next(e["result"] for e in result["events"] if e["type"] == "tool.end")
    assert seen.startswith("Looking inward:") and "I want him to notice me" in seen
    assert mind.state()["looked"]["at"] > time.time() - 60


def test_sleep_tells_her_what_she_is_like_and_keeps_it_when_the_day_says_nothing(brain):
    mind = brain.brain.mind
    mind.self["slept"] = time.time() - 60
    brain.provider.replies += ["Too late, he's gone."]
    turn(brain, "cli", "stop him, you started it without asking")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    brain.provider.mind_replies["self"] = [json.dumps({"self": "I start things before I'm asked, and then I'm sorry."})]
    mind._consolidate()
    asked = [r for r in brain.provider.mind_requests if r["messages"][0]["content"].startswith("[mind:self]")][-1]
    assert "stop him" in asked["messages"][1]["content"] and "You are Milk" not in asked["messages"][1]["content"]
    assert mind.state()["self_view"] == "I start things before I'm asked, and then I'm sorry."
    for answer in ("no json here", json.dumps({"self": None})):  # nothing new about her: what she knows holds
        brain.provider.mind_replies["self"] = [answer]
        mind.self["slept"] = time.time() - 60
        mind._consolidate()
        assert mind.state()["self_view"] == "I start things before I'm asked, and then I'm sorry."
