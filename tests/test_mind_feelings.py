"""Her own feelings: she names a feeling when she reflects, looking inward or going back over a moment in
her thoughts, in her own words, any words (design: docs/superpowers/specs/2026-11-18-own-feelings-design.md).
Before, two background calls named her feelings for her and she said of one of their words: "it's possible it's
just a word the machine picked". Nothing reads her words for feelings and there is no list of them: "if she feels
something that is not in the list, then what?" (the user)."""

import json
import re

import pytest
from conftest import Meaning, turn, use, wait_for

from sentientmilk_framework.mind.feel import CHANNELS, Feelings, Felt, _amounts, core, naming
from sentientmilk_framework.testing import tool_call

TENSE = {"cortisol": 0.8, "noradrenaline": 0.85, "serotonin": 0.3, "reward": -0.4}


def feels(mind, **levels):
    with mind._lock:
        mind.body.levels.update(levels)
        mind.senses.seen.update(mind.body.levels)  # and she feels it (her senses follow with a lag)


def eased(mind):
    return sum(why == "putting what she feels into words" for _, why, _ in mind.body.pushed)


@pytest.mark.mind
def test_whatever_words_she_puts_to_what_she_finds_become_hers_and_ease_it_once(brain):
    mind = brain.brain.mind
    feels(mind, **TENSE)
    looked = mind.look_inward()
    assert eased(mind) == 0 and not mind.feelings.known  # looking alone names nothing and eases nothing
    seen = mind.look_inward(naming="wound up like a spring, a bit vexed")  # no list would have this
    assert 'Put into words: "wound up like a spring, a bit vexed"' in seen and "A word of my own" in seen
    found = mind.feelings.known[0]
    assert mind.feelings.word(found) == "wound up like a spring, a bit vexed" and found["said"][-1]["measure"]["way"]
    assert found["said"][-1]["text"] == "wound up like a spring, a bit vexed" and found["standing"] == "provisional"
    assert eased(mind) == 1  # the felt shift: putting it into words eases it
    again = mind.look_inward(naming="wound up like a spring, a bit vexed")
    assert "sits like the other times it was called that" in again and eased(mind) == 1  # once for one experience
    assert "called" not in looked  # her body in body words: never a name she did not give it


@pytest.mark.mind
def test_what_she_says_of_how_she_feels_right_after_looking_inward_is_her_naming(brain):
    # live (the exam): asked to put it into words, she looked inward and said it in her reply ("I'm wired all
    # the way up"); the naming the tool offers went unused, so nothing became hers and nothing eased
    mind = brain.brain.mind
    feels(mind, **TENSE)
    brain.provider.mind_replies["named"] = [json.dumps({"named": [
        {"words": "wired all the way up", "quote": "Honestly? I'm wired all the way up."},
        {"words": "furious", "quote": "I'm furious."}]})]  # the second she never said: never hers
    brain.provider.replies += [tool_call("look_inward", {}), "Honestly? I'm wired all the way up. Nothing to spend it on."]
    turn(brain, "cli", "how are you feeling, really?")
    named = wait_for(lambda: mind.feelings.known)
    assert [mind.feelings.word(f) for f in named] == ["wired all the way up"]
    assert named[0]["said"][-1]["text"] == "Honestly? I'm wired all the way up." and eased(mind) == 1
    asked = next(r for r in brain.provider.mind_requests if r["messages"][0]["content"].startswith("[mind:named]"))
    assert "Nothing to spend it on." in asked["messages"][1]["content"]
    count = len(brain.provider.mind_requests)
    brain.provider.replies += ["Grey and wet."]
    turn(brain, "cli", "and the weather?")  # she did not look inward: nothing to name, nothing read
    assert not any(r["messages"][0]["content"].startswith("[mind:named]") for r in brain.provider.mind_requests[count:])


@pytest.mark.mind
def test_naming_a_moment_she_looks_back_on_names_that_moment_and_softens_it(brain):
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = ['["they say my cat was dumb", "less", "less", "same", "bad", "chat", '
                                              '"pets", ["talk", "answer", 0.2, 0.6, 1]]']
    brain.provider.replies += ["Oh. That's a mean thing to say."]
    run = turn(brain, "cli", "your cat drawing was dumb, honestly")["run"]
    episode = wait_for(lambda: next((e for e in mind.memory.recent(5, ("exchange",)) if e["run_id"] == run), None))
    way = brain.store.run(run)["options"]["mind"]["way"]
    embedder = use(brain, Meaning())
    found = mind.memory.vectors.texts(mind.memory.vectors.pending(embedder.name, 100))  # as her memory's sweep does
    mind.memory.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))],
                            embedder.name)
    feels(mind, cortisol=0.2, noradrenaline=0.4, reward=0.3, serotonin=0.7)  # it has passed: she is fine now
    seen = mind.look_inward("the cat drawing", naming="stung, then small", moment=episode["id"])
    assert 'Put into words: "stung, then small"' in seen
    named = mind.feelings.known[0]
    assert named["said"][-1]["measure"]["way"] == way  # that moment's body, not her now
    assert named["said"][-1]["episode"] == episode["id"]
    assert mind.memory.by_ids([episode["id"]])[0]["charge"] < episode["charge"]  # it lost a little of its sting
    assert eased(mind) == 0  # nothing unpleasant now to ease
    assert '(it hurt; called "stung, then small")' in mind.look_inward()  # what got to her, by her name


@pytest.mark.mind
def test_a_thought_names_a_feeling_only_in_its_own_words(brain):
    mind = brain.brain.mind
    feels(mind, **TENSE)
    brain.provider.mind_replies["think"] = [
        json.dumps({"thought": "Going over it again, I was more rattled than I let on.", "named": "rattled"}),
        json.dumps({"thought": "The deploy went fine in the end.", "named": "relieved"})]
    mind._think("wonder", None)
    assert [mind.feelings.word(f) for f in mind.feelings.known] == ["rattled"]
    assert mind.feelings.known[0]["said"][-1]["text"] == "Going over it again, I was more rattled than I let on."
    mind._think("wonder", None)  # "relieved" is not in what she thought: not hers
    assert [mind.feelings.word(f) for f in mind.feelings.known] == ["rattled"]
    asked = brain.provider.mind_requests[-1]["messages"][1]["content"]
    assert "called" not in asked and "rattled" not in asked.split("How they feel:")[1].split("\n")[0]
def test_a_feeling_of_many_moments_comes_to_mind_sooner_than_one_of_a_single_moment():
    way = {"cortisol": 0.9, "noradrenaline": 0.7}
    moment = {"way": way, "appraisal": None}
    feelings = Feelings()
    tense, _ = feelings.sort(naming("tense", "tense about the deploy", 1.0, "tool", "now", episode=1,
                                    measure={"of": "reading", "way": way}), moment, {}, None)
    for at in range(2, 7):
        feelings.sort(naming("nervous", "nervous", float(at), "tool", "now", episode=at,
                             measure={"of": "reading", "way": way}), moment, {}, None)
    found = {feelings.word(f): value for f, value, _ in feelings.recognize(moment, {}, None)}
    assert found["nervous"] > found["tense"]
    assert tense["said"][-1]["text"] == "tense about the deploy"


def test_her_body_comes_as_amounts_she_puts_into_words_herself_never_a_feelings_name():
    # live (the exam): ready-made sensations ("buzzing", "braced", "heavy-eyed") came back word for word in 18 of
    # 44 replies (amounts: 3 of 45), she said "handed over, and I just picked it up and repeated it", and
    # a blind judge heard her less from inside (27 of 39 pairs for amounts): her body is felt, the words are hers
    reading = {"noradrenaline": 0.8, "oxytocin": 0.75, "adenosine": 0.62, "novelty": 0.2}
    usual = {"noradrenaline": 0.35, "oxytocin": 0.4, "adenosine": 0.4, "novelty": 0.6}
    felt = Felt(*core(reading), reading, used=usual)
    said = felt.words()
    assert said.startswith("Body: ") and "than usual;" in said
    assert "more alertness" in said and "more closeness" in said and "more sleep pressure" in said
    assert "less novelty" in said and not {"buzzing", "warm", "heavy-eyed", "wanting"} & set(said.split())
    both = felt.words(moved_by={"oxytocin": 1.2, "reward": 0.8})
    assert both.startswith("Reading it: much more closeness and more reward than a moment ago. Underneath: ")
    # a channel that changed is still told where it is (left out, a high strain read only as "much less strain than
    # a moment ago": the 0.48 exam)
    assert "more closeness" in both.split("Underneath: ")[1]
    assert not {"stress", "calm", "hurt"} & {words for words, _ in CHANNELS.values()}  # those are feelings
    # how stirred up she is, as an amount too: "keyed up", the last ready-made phrase, she traced in the exam
    # ("That line isn't mine. It arrives whole and I dress it up")
    assert Felt(-0.7, 0.9, reading, used=usual).words().endswith("very unpleasant on the whole, with much going on.")
    assert Felt(0.3, 0.1, reading, used=usual).tone() == ("pleasant", "little going on")
    for name in CHANNELS:  # every amount reads right however strong
        for far in (-1.5, -0.8, -0.5, 0.5, 0.8, 1.5):
            assert re.fullmatch(r"(?:a little |much )?(?:more|less) [a-z ]+", _amounts([(name, far)]))


def test_a_message_that_hardly_moved_her_is_told_as_little_changed():
    # run 660: the user's reassurance moved her body too little to tell, her note said only how her body stood
    # ("unpleasant on the whole"), and she said "the whole worry fell off the second you said it": nothing told
    # her the message had changed little, and the gap was filled. Told, "that helped" and "the worry is gone"
    # have something to be told apart by
    reading = {"noradrenaline": 0.8, "cortisol": 0.7}
    usual = {"noradrenaline": 0.35, "cortisol": 0.3}
    felt = Felt(*core(reading), reading, used=usual)
    for little in ({"reward": 0.2, "oxytocin": -0.1}, {}):
        said = felt.words(moved_by=little)
        assert said.startswith("Reading it: little changed from a moment ago. Underneath: ")
        assert "more strain" in said.split("Underneath: ")[1]  # what is still there is said as still there
    assert felt.words().startswith("Body: ")  # no message: how her body stands, as before
