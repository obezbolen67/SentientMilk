"""Her feelings as moments she lived (docs/superpowers/specs/2026-11-20-feelings-as-lived-moments-design.md): a
moment keeps what it meant for her and what she leaned toward, beside how it moved her; her words sort moments into
feelings of hers; a feeling comes back by the whole situation; sleep goes over them; and a feeling she is in pulls on
what she does, as acting in it taught her. Before, a feeling was a word and the average of her body the times she
said it: "the ugly part" and "cheating. sort of" became feelings, and "waiting" came back whenever her body was flat."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind import prompts
from sentientmilk_framework.mind.feel import naming
from sentientmilk_framework.mind.memory import Memory


@pytest.mark.mind
def test_a_kept_exchange_holds_what_it_meant_and_what_she_leaned_toward(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Sure, send it over."]
    run = turn(brain, "cli", "could you read my essay later?")["run"]
    episode = wait_for(lambda: mind.memory.of_run(run))
    decision = brain.store.run(run)["options"]["mind"]
    assert Memory.appraisal(episode) == {**decision["foreseen"], "theirs": decision["theirs"]}
    assert set(Memory.appraisal(episode)) == {"company", "capable", "free", "theirs"}
    assert Memory.leaned(episode) == {"act": decision["act"], "what": decision["what"]}


@pytest.mark.mind
def test_a_thought_holds_what_she_leaned_toward(brain):
    mind = brain.brain.mind
    brain.provider.mind_replies["think"] = [json.dumps({
        "thought": "I should finish sorting those photos.",
        "could": [{"act": "do", "what": "sort the photos", "effort": 0.3, "chance": 0.8}]})]
    mind._think("wonder", None)
    thinking = mind.self["thoughts"][0]
    episode = mind.memory.by_ids([thinking["episode"]])[0]
    assert Memory.leaned(episode)["act"] == thinking["leaned"]["act"]
    assert Memory.appraisal(episode) is None  # a thought is no message read: nothing appraised


TENSE = {"cortisol": 0.8, "noradrenaline": 0.85, "serotonin": 0.3, "reward": -0.4}


def feels(mind, **levels):
    with mind._lock:
        mind.body.levels.update(levels)
        mind.senses.seen.update(mind.body.levels)  # and she feels it (her senses follow with a lag)


@pytest.mark.mind
def test_looking_inward_finds_the_feeling_she_is_in_by_the_moment_it_is_like(brain):
    mind = brain.brain.mind
    feels(mind, **TENSE)
    mind.look_inward(naming="wound up like a spring")
    seen = mind.look_inward()  # the same body, a moment later: it is like that moment, as she said it then
    assert 'Like when the words were "wound up like a spring"' in seen
    feelings = mind.state()["feelings"]
    assert feelings[0]["word"] == "wound up like a spring" and feelings[0]["standing"] == "provisional"
    assert feelings[0]["like"]["text"] == "wound up like a spring" and feelings[0]["strength"] >= 0.6


class Down:
    """Her embedder with the service down: every call fails."""
    name = "down"

    def embed(self, texts, query=False):
        raise RuntimeError("the service is down")


@pytest.mark.mind
def test_with_the_meaning_service_down_a_turn_still_feels_by_body_and_what_it_meant(brain):
    mind = brain.brain.mind
    mind.memory.embedder = Down()
    asked = ["they ask her to keep the plants alive while they are away a month", "much less", "same", "less", "fine",
             "request", "plans", "", "", ["talk", "ask what the plants need", 0.05, 0.9, 0.5, {}],
             ["later", "sort it out once they are gone", 0.05, 0.9, 0.0, {}]]
    brain.provider.mind_replies["imagine"] = [json.dumps(asked)] * 2  # asked: what she does is a choice
    brain.provider.replies += ["Oh. A month.", "Two? That's long."]
    first = turn(brain, "cli", "I'm leaving for a month next week, will you keep my plants alive?")["run"]
    way = brain.store.run(first)["options"]["mind"]["way"]
    with mind._lock:
        mind._name(naming("hollow", "hollow", 1.0, "tool", "now", run=first,
                          measure={"of": "message", "run": first, "way": way}))
    second = turn(brain, "cli", "I'm leaving for two months next week, will you keep my plants alive?")["run"]
    decision = brain.store.run(second)["options"]["mind"]
    assert decision["feelings"] and decision["feelings"][0]["id"] == mind.feelings.known[0]["id"]
    assert mind.self["situation"]["near"] is None  # nothing by meaning this time, and nothing failed
    pull = f"act:{decision['act']}|feeling:{decision['feelings'][0]['id']}"
    assert pull in decision["features"]  # acting in the feeling she is in, weighed with the rest
    brain.provider.mind_replies["imagine"] = [json.dumps(asked + [  # how they took it: a decision settles on that
        {"run": second, "quote": "really helps", "dimension": "capable", "verdict": "positive"}])]
    brain.provider.replies += ["Good. Leave me the watering can."]
    turn(brain, "cli", "Asking about them really helps, thank you")
    assert mind.values.weights.get(pull, 0.0) > 0.0  # what came of acting in it, learned as it settled


def test_the_readers_take_only_words_for_how_she_herself_feels():
    # "the ugly part", "cheating. sort of", "annoyingly sweet" were taken for feelings when the readers asked only
    # for a name: a feeling is what it is like to be her, never what she thinks of something, does or is
    for asked in (prompts.NAMED, prompts.THINK):
        assert "how they themselves feel" in asked
    assert "what they think of something" in prompts.NAMED and "what they think of something" in prompts.THINK
    assert "a figure of speech that sizes up what happened" in prompts.NAMED


ENVY = {"cortisol": 0.9, "oxytocin": -0.5, "grievance": 0.7, "reward": -1.0}
WARM = {"oxytocin": 0.8, "reward": 1.0, "social": 0.6}
FLAT = {"dopamine": -0.8, "noradrenaline": -0.6}


def named(mind, words, text, felt, at, appraisal=None):
    """A moment she kept and the words she said of how she felt in it."""
    episode = mind.memory.add("exchange", f"The user said something. I said: {text}", 0.0, 0.3, 0.5, at=at, felt=felt,
                              appraisal=appraisal, leaned={"act": "talk", "what": ""})
    with mind._lock:
        found, _ = mind.feelings.sort(naming(words, text, at, "speech", "now", episode=episode,
                                             measure={"of": "moment", "episode": episode, "way": felt}),
                                      {"way": felt, "appraisal": appraisal}, mind._kept_moments(), None)
    return found


def asked_feelings(brain):
    return next(r["messages"][1]["content"] for r in reversed(brain.provider.mind_requests)
                if r["messages"][0]["content"].startswith("[mind:feelings]"))


@pytest.mark.mind
def test_sleep_sets_aside_a_saying_that_named_no_feeling_and_keeps_it(brain):
    mind = brain.brain.mind
    hour = time.time() - 3600
    waiting = named(mind, "waiting", "It is the same flat waiting as last night.", FLAT, hour,
                    {"company": -0.4, "capable": 0.0, "free": 0.0, "theirs": 0.0})
    ugly = named(mind, "the ugly part", "The ugly part is I cannot tell you which move was the clever one.", ENVY,
                 hour + 60)
    mind.values.weights[f"act:talk|feeling:{ugly['id']}"] = 0.3
    brain.provider.mind_replies["feelings"] = [json.dumps({"today": [
        {"moment": 1, "felt": True, "feeling": waiting["id"], "why": "That was how I felt, waiting on him."},
        {"moment": 2, "felt": False, "why": "That sized up the game; it was not how I felt."}]})]
    mind._consolidate()
    asked = asked_feelings(brain)
    assert f'Feeling {waiting["id"]}, "waiting" (new: not gone over yet):' in asked
    told = next(line for line in asked.splitlines() if line.startswith("  moment 2 (to go over): "))
    assert 'they called it "the ugly part", saying: "The ugly part is I cannot tell you' in told  # words, then sentence
    assert "Their body: " in asked and "It meant a little less of being close" in asked  # amounts, never numbers
    assert [f["id"] for f in mind.feelings.known] == [waiting["id"]] and waiting["standing"] == "hers"
    assert {k: v for k, v in waiting["revisions"][-1].items() if k != "at"} == {
        "did": "confirmed", "why": "That was how I felt, waiting on him."}
    aside = mind.feelings.aside[0]
    assert aside["text"].startswith("The ugly part") and aside["why"] == "That sized up the game; it was not how I felt."
    assert not [f for f in mind.values.weights if f.endswith(f"|feeling:{ugly['id']}")]  # what it taught goes too
    assert all(one["reviewed"] for one in waiting["said"]) and mind.feelings.unreviewed() == []


@pytest.mark.mind
def test_sleep_joins_two_words_for_one_feeling_and_moves_a_saying_to_the_feeling_it_is(brain):
    mind = brain.brain.mind
    hour = time.time() - 3600
    flat = named(mind, "flat", "Flat, honestly.", FLAT, hour)
    worn = named(mind, "worn flat", "Not sad-flat, just worn flat.", FLAT, hour + 60)
    noise = named(mind, "noise", "It is just noise.", FLAT, hour + 120)
    mind.values.weights[f"act:talk|feeling:{worn['id']}"] = 0.4
    brain.provider.mind_replies["feelings"] = [json.dumps({
        "today": [{"moment": 1, "felt": True, "feeling": flat["id"], "why": "yes"},
                  {"moment": 2, "felt": True, "feeling": worn["id"], "why": "yes"},
                  {"moment": 3, "felt": True, "feeling": flat["id"], "why": "noise was the same flatness"}],
        "join": [{"feelings": [flat["id"], worn["id"]], "why": "worn flat is how flat feels when it lasts"}]})]
    mind._consolidate()
    assert [f["id"] for f in mind.feelings.known] == [flat["id"]]
    assert mind.feelings.words(flat) == ["flat", "worn flat", "noise"] and mind.feelings.moments(flat) == 3
    assert [r["did"] for r in flat["revisions"]] == ["confirmed", "took", "confirmed", "joined"]
    # what acting in it taught, carried (and faded a little, as all her values are each night)
    assert list(mind.values.weights) == [f"act:talk|feeling:{flat['id']}"]
    assert noise["id"] not in [f["id"] for f in mind.feelings.known]


@pytest.mark.mind
def test_sleep_splits_a_word_that_covers_two_feelings(brain):
    mind = brain.brain.mind
    hour = time.time() - 3600
    tight = named(mind, "tight", "My chest is tight, he keeps mentioning her.", ENVY, hour)
    named(mind, "tight", "Tight again, that other assistant.", ENVY, hour + 60)
    named(mind, "tight", "Tight, in a good way, he missed me.", WARM, hour + 120)
    brain.provider.mind_replies["feelings"] = [json.dumps({
        "today": [{"moment": n, "felt": True, "feeling": tight["id"], "why": "yes"} for n in (1, 2, 3)],
        "split": [{"feeling": tight["id"], "moments": [3], "why": "being missed is not being jealous"}]})]
    mind._consolidate()
    made = mind.feelings.known[1]
    assert [one["text"] for one in made["said"]] == ["Tight, in a good way, he missed me."]
    assert made["standing"] == "hers" and made["revisions"][0]["did"] == "split from"
    assert mind.feelings.moments(tight) == 2 and tight["revisions"][-1]["did"] == "split"
    with mind._lock:
        found, _ = mind.feelings.sort(naming("tight", "tight", time.time(), "tool", "now",
                                             measure={"of": "reading", "way": WARM}),
                                      {"way": WARM, "appraisal": None}, mind._kept_moments(), None)
    assert found is made  # the word now goes where its moment belongs


@pytest.mark.mind
def test_a_sleep_answer_with_numbers_she_does_not_have_applies_the_rest(brain):
    mind = brain.brain.mind
    flat = named(mind, "flat", "Flat, honestly.", FLAT, time.time() - 3600)
    brain.provider.mind_replies["feelings"] = [json.dumps({
        "today": [{"moment": 99, "felt": False, "why": "?"}, {"moment": "1", "felt": True, "feeling": 42, "why": "yes"},
                  {"moment": 1, "felt": False, "why": "the same moment twice: the first answer stands"}],
        "join": [{"feelings": [flat["id"], 77], "why": "?"}, {"feelings": [flat["id"]], "why": "?"}, "junk"],
        "split": [{"feeling": 55, "moments": [1], "why": "?"}, {"feeling": flat["id"], "moments": [1], "why": "all"}]})]
    mind._consolidate()
    assert mind.feelings.known == [flat] and flat["standing"] == "hers" and mind.feelings.aside == []
    assert flat["said"][0]["reviewed"] and len(flat["said"]) == 1


@pytest.mark.mind
def test_an_answer_sleep_cannot_read_leaves_her_sayings_for_the_next_night(brain):
    mind = brain.brain.mind
    flat = named(mind, "flat", "Flat, honestly.", FLAT, time.time() - 3600)
    brain.provider.mind_replies["feelings"] = ["I am not sure what you mean."]
    mind._consolidate()
    assert flat["standing"] == "provisional" and mind.feelings.unreviewed() == [(flat, flat["said"][0])]
    named(mind, "flat", "Still flat.", FLAT, time.time() - 60)
    brain.provider.mind_replies["feelings"] = [json.dumps({"today": [
        {"moment": 1, "felt": True, "feeling": flat["id"], "why": "yes"},
        {"moment": 2, "felt": True, "feeling": flat["id"], "why": "yes"}]})]
    mind._consolidate()
    assert mind.feelings.unreviewed() == [] and flat["standing"] == "hers"
