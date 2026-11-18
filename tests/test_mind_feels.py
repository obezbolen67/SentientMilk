"""Her mind keeps each moment with how it moved her and what was around it, and a moment that comes back moves
her again, by a share of what it did (0.38, docs/superpowers/specs/2026-11-18-memory-that-feels-design.md)."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.life import peak_end
from sentientmilk_framework.mind.memory import cue

SONG = {"playing": "Clair de Lune — Debussy"}
HURT = '["they say my cat drawing was dumb", "less", "less", "same", "bad", "chat", "pets", ["talk", "answer", 0.2, 0.6, 1]]'


def remembering(mind):
    return [entry for entry in mind.body.pushed if entry[1].startswith("remembering")]


def test_a_moment_is_remembered_by_its_peak_and_its_end():
    assert peak_end({"cortisol": 1.0}, {"cortisol": 0.2, "reward": -0.4}) == {"cortisol": 0.6, "reward": -0.2}
    assert peak_end({"cortisol": 1.0}, None) == {"cortisol": 1.0}


@pytest.mark.mind
def test_an_exchange_keeps_how_it_moved_her_and_what_was_around_it(brain):
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = [HURT]
    brain.provider.replies += ["Oh. That's a mean thing to say."]
    run = turn(brain, "cli", "your cat drawing was dumb, honestly", context=SONG)["run"]
    episode = wait_for(lambda: next((e for e in mind.memory.recent(5, ("exchange",)) if e["run_id"] == run), None))
    felt = mind.memory.felt(episode)
    way = brain.store.run(run)["options"]["mind"]["way"]
    assert felt and set(way) <= set(felt) | {name for name, change in way.items() if abs(change) < 0.002}
    cues = mind.memory.cues([episode["id"]])[episode["id"]]
    assert cue("playing", "Clair de Lune — Debussy") in cues and any(c.startswith("time: ") for c in cues)
    assert "app: cli" in cues


@pytest.mark.mind
def test_a_thought_keeps_what_thinking_it_did_and_what_was_around_her(brain):
    mind = brain.brain.mind
    mind.presence.report(idle=5, around=SONG, now=time.time())
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "That song again.", "want": "nothing"})]
    mind._think("wonder", None)
    thought = mind.memory.recent(1, ("thought",))[0]
    assert mind.memory.felt(thought).get("novelty", 0) > 0
    assert cue("playing", "Clair de Lune — Debussy") in mind.memory.cues([thought["id"]])[thought["id"]]


@pytest.mark.mind
def test_what_is_playing_brings_back_the_moment_it_played_in_and_she_feels_it_again(brain):
    mind = brain.brain.mind
    then = mind.memory.add("exchange", "They told me the song was the last thing their grandmother sang", -0.3,
                           0.6, 0.6, app="cli", session="old", at=time.time() - 3 * 86400,
                           felt={"cortisol": 1.2, "oxytocin": 0.8}, cues=[cue("playing", SONG["playing"])])
    brain.provider.replies += ["Sure, here's a list."]
    cortisol = mind.body["cortisol"]
    run = turn(brain, "cli", "can you list three fruits?", context=SONG)["run"]
    decision = brain.store.run(run)["options"]["mind"]
    assert any(item["id"] == then for item in decision["selected"])
    pushed = remembering(mind)
    assert len(pushed) == 1 and pushed[0][2]["cortisol"] > 0 and pushed[0][2]["oxytocin"] > 0
    assert decision["way"].get("cortisol", 0) > 0  # part of what reading the message did to her
    assert mind.body["cortisol"] > cortisol or pushed[0][2]["cortisol"] > 0.02
    note = brain.provider.sent[-1]["messages"]
    assert any("What brings it back: playing: clair de lune — debussy." in str(m.get("content")) for m in note)


@pytest.mark.mind
def test_a_memory_from_before_comes_back_unfelt(brain):
    mind = brain.brain.mind
    mind.memory.add("exchange", "They told me the song was the last thing their grandmother sang", -0.3, 0.6, 0.6,
                    app="cli", session="old", at=time.time() - 3 * 86400, cues=[cue("playing", SONG["playing"])])
    brain.provider.replies += ["Sure."]
    turn(brain, "cli", "can you list three fruits?", context=SONG)
    assert remembering(mind) == []


@pytest.mark.mind
def test_brooding_brings_the_hurt_back_through_the_same_way_and_wears_it_down(brain):
    mind = brain.brain.mind
    sore = mind.memory.add("exchange", "They said my drawing was dumb", -0.5, 0.6, 0.6, app="cli", session="old",
                           at=time.time() - 3600, sting=-0.6, felt={"cortisol": 1.0, "grievance": 0.8})
    about = mind.memory.by_ids([sore])[0]
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Why did that sting so much.", "want": "nothing"})]
    mind._think("ruminate", about)
    pushed = remembering(mind)
    assert len(pushed) == 1 and pushed[0][2]["cortisol"] > 0 and pushed[0][2]["grievance"] > 0
    assert mind.memory.by_ids([sore])[0]["charge"] < about["charge"]


@pytest.mark.mind
def test_a_round_of_her_long_term_memory_that_comes_back_brings_its_moment_s_feeling(brain):
    from conftest import Meaning, use
    mind, recall = brain.brain.mind, brain.brain.recall
    use(brain, Meaning())
    long_ago = time.time() - 30 * 86400
    recall.add("turn", "7", "cli", "old", long_ago, "they: my cat died\nyou: I am so sorry about your pet")
    mind.memory.add("exchange", "They told me something sad", -0.5, 0.6, 0.6, app="cli", session="old",
                    at=long_ago, event_id=7, felt={"cortisol": 1.0, "oxytocin": 0.6})
    recall.sweep()
    brain.provider.replies += ["I remember."]
    turn(brain, "cli", "my cat died, remember?")
    pushed = remembering(mind)
    assert len(pushed) == 1 and pushed[0][2]["cortisol"] > 0


@pytest.mark.mind
def test_what_came_back_lately_what_brought_it_and_what_it_did_are_seen(brain):
    mind = brain.brain.mind
    then = mind.memory.add("exchange", "They told me the song was the last thing their grandmother sang", -0.3,
                           0.6, 0.6, app="cli", session="old", at=time.time() - 3 * 86400,
                           felt={"cortisol": 1.2}, cues=[cue("playing", SONG["playing"])])
    brain.provider.replies += ["Sure."]
    turn(brain, "cli", "can you list three fruits?", context=SONG)
    came = mind.state()["remembered"][0]
    assert came["episode"] == then and came["by"] == "playing: clair de lune — debussy"
    assert came["moved"]["cortisol"] > 0 and "grandmother" in came["text"]
    mind.forget("cli", "old")
    assert mind.state()["remembered"] == []


@pytest.mark.mind
def test_a_memory_she_looks_for_comes_back_felt(brain):
    from conftest import Meaning, use
    mind = brain.brain.mind
    use(brain, Meaning())
    mind.memory.add("exchange", "Our pet passed away last spring", -0.6, 0.6, 0.7, app="cli", session="old",
                    at=time.time() - 20 * 86400, felt={"cortisol": 1.0, "serotonin": -0.8})
    memory, embedder = mind.memory, mind.memory.embedder
    found = memory.vectors.texts(memory.vectors.pending(embedder.name, 100))
    memory.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))], embedder.name)
    mind.look_inward(about="when my cat died")
    pushed = remembering(mind)
    assert len(pushed) == 1 and pushed[0][2]["cortisol"] > 0 and pushed[0][2]["serotonin"] < 0
