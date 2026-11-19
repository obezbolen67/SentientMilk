"""Her wandering mind: it knows when its last thought was and what it can tell of the user and of what is
around her; what comes up is cued by the moment and comes in chains; going round one thing leaves her bored; what
she finds out on her own satisfies her curiosity; and a task of hers reports in words, without a face.

In her real mind (2026-11-17) every thought from 15:15 to 19:01 had the user eating ("He's still chewing", four
hours on): each was given the last one with no word of when it was, and nothing of whether he was even there."""

import json
import random
import time

import pytest
from conftest import Meaning, use, wait_for

from sentientmilk_framework.mind.memory import cue

SONG = {"playing": "Clair de Lune — Debussy"}


def asked(brain):
    return [r["messages"][1]["content"] for r in brain.provider.mind_requests
            if r["messages"][0]["content"].startswith("[mind:think]")][-1]


def think(brain, words, kind="wonder", about=None):
    brain.provider.mind_replies["think"] = [json.dumps({"thought": words, "want": "nothing"})]
    brain.brain.mind._think(kind, about)


def embed(brain):
    memory, embedder = brain.brain.mind.memory, brain.brain.mind.memory.embedder
    found = memory.vectors.texts(memory.vectors.pending(embedder.name, 1000))
    if found:
        memory.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))], embedder.name)


def wandered(mind):
    return [moved for _, why, moved in mind.body.pushed if why == "her mind wandered"]


@pytest.mark.mind
def test_her_last_thought_comes_with_when_it_was_and_what_she_can_tell_of_the_user(brain):
    mind = brain.brain.mind
    now = time.time()
    mind.self["thoughts"] = [{"at": now - 3 * 3600, "kind": "wonder", "thought": "He's still eating.", "want": "nothing"}]
    mind.presence.report(idle=2 * 3600, locked=False, busy=False, now=now, around=SONG)
    think(brain, "It's gone quiet.")
    seen = asked(brain)
    assert 'Your last thought, 3 hours ago: "He\'s still eating."' in seen
    # what the computer shows, not where the user is: a computer nobody touches cannot tell someone away from
    # someone reading or on their phone, and her thoughts made "he's just gone" of it (the audit, finding 7)
    assert "What they can tell of the user: nobody has touched the computer for 2 hours" in seen
    assert "away" not in seen.split("What they can tell of the user: ")[1].split("\n")[0]
    assert "Around them: playing: Clair de Lune — Debussy" in seen


@pytest.mark.mind
def test_going_round_one_thing_leaves_her_bored_and_a_new_thought_does_not(brain):
    mind = brain.brain.mind
    use(brain, Meaning())
    mind.memory.add("thought", "I keep thinking about the platformer level he showed me", 0.0, 0.3, 0.3,
                    at=time.time() - 3600)
    embed(brain)
    think(brain, "I keep thinking about the platformer level he showed me")
    repeat = (wandered(mind)[-1:] or [{}])[0].get("novelty", 0.0)  # an exact repeat: nothing new at all
    mind.body.pushed.clear()  # pushes of one reason within seconds are told as one
    think(brain, "Taxes are due before the deadline, I wonder if he filed his invoice")
    new = wandered(mind)[-1]["novelty"]
    assert new > 0.05 and new > 1.5 * repeat


@pytest.mark.mind
def test_what_is_around_her_calls_up_the_moment_it_was_around_and_not_what_is_before_her(brain):
    mind = brain.brain.mind
    then = mind.memory.add("exchange", "They told me the song was the last thing their grandmother sang", -0.2, 0.6,
                           0.6, app="cli", session="old", at=time.time() - 5 * 86400,
                           cues=[cue("playing", SONG["playing"])])
    mind.presence.report(idle=30, now=time.time(), around=SONG)
    think(brain, "That song.")
    seen = asked(brain)
    assert "the last thing their grandmother sang" in seen
    assert "What brings it back: playing: clair de lune — debussy." in seen
    thought = mind.memory.recent(1, ("thought",))[0]
    assert then in json.loads(thought["origin_ids"])


@pytest.mark.mind
def test_a_memory_that_came_up_brings_its_neighbour_in_time_in_the_next_thought(brain):
    mind = brain.brain.mind
    mind.rng = random.Random(1)
    day = time.time() - 4 * 86400
    first = mind.memory.add("exchange", "We set up the aquarium together", 0.4, 0.5, 0.5, app="cli", session="old", at=day)
    mind.memory.add("exchange", "The fish we named Captain hid behind the rock all evening", 0.3, 0.4, 0.4,
                    app="cli", session="old", at=day + 600)
    for n in range(30):
        mind.memory.add("event", f"Some other day, number {n}", 0.0, 0.2, 0.1, at=day - (n + 2) * 86400)
    episode = mind.memory.add("thought", "That aquarium day was nice.", 0.3, 0.3, 0.3, at=time.time() - 60,
                              origins=[first])
    mind.self["thoughts"] = [{"at": time.time() - 60, "kind": "wonder", "thought": "That aquarium day was nice.",
                              "want": "nothing", "episode": episode}]
    think(brain, "Captain, hiding all evening.")
    seen = asked(brain)
    assert "Captain hid behind the rock" in seen and "We set up the aquarium together" not in seen


@pytest.mark.mind
def test_what_she_finds_out_on_her_own_satisfies_her_curiosity(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["The sicilian defence starts with c5 against e4."]
    task = brain.brain.runs.start_task("cli", "main", "Out of your own curiosity, look this up for yourself: "
                                       "chess openings for beginners.", quiet=True)
    wait_for(lambda: mind.memory.recent(1, ("event",)) and brain.client.run(task)["status"] == "completed")
    found = [moved for _, why, moved in mind.body.pushed if why.startswith("new to her: ")]
    assert found and found[-1]["novelty"] > 0
    event = mind.memory.recent(1, ("event",))[0]
    assert mind.memory.felt(event).get("novelty", 0) > 0


@pytest.mark.mind
def test_a_task_of_hers_reports_in_words_without_a_face(brain):
    brain.client.declare_app("pet", name="Pet", environment="A desk.", toolkits=["memory"], signals={
        "expression": {"description": "how you look", "options": ["mad", "smile"]}})
    brain.provider.replies += ['{"expression": "smile"}\nI read it all.']
    task = brain.brain.runs.start_task("pet", "main", "Out of your own curiosity, look this up for yourself: "
                                       "chess openings.", quiet=True)
    wait_for(lambda: brain.client.run(task)["status"] == "completed")
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert '"expression"' not in system  # never told to start its report with a face
    brain.provider.replies += ['{"expression": "smile"}\nHi.']
    assert brain.client.turn("pet", "main", "hi")["signals"] == {"expression": "smile"}  # a turn still has one


@pytest.mark.mind
def test_a_focused_mind_holds_off_what_only_the_surroundings_call_up(brain):
    """High acetylcholine favours what is attended over associative retrieval (Hasselmo 2006); memories come
    by themselves when attention is diffuse (Berntsen 2009). What meaning calls up is not held off."""
    mind = brain.brain.mind
    cued = {"relevance": 0.0, "cued": 1.0}
    meant = {"relevance": 0.7, "cued": 0.0}
    mind.body.levels["acetylcholine"] = 0.8
    focused = mind._quality(cued)
    mind.body.levels["acetylcholine"] = 0.2
    assert focused < mind._quality(cued) and mind._quality(meant) == 0.7


@pytest.mark.mind
def test_what_happened_within_the_hour_does_not_come_back_unbidden(brain):
    mind = brain.brain.mind
    mind.memory.add("exchange", "We listened to it a minute ago", 0.2, 0.4, 0.5, app="cli", session="old",
                    at=time.time() - 120, cues=[cue("playing", SONG["playing"])])
    mind.presence.report(idle=30, now=time.time(), around=SONG)
    think(brain, "Still that song.")
    assert "What brings it back" not in asked(brain)
