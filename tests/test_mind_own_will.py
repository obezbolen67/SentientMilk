"""Her own acts are chosen by her will, as a turn's are; a thought survives a model that is not there
(docs/superpowers/specs/2026-11-19-own-acts-by-will-design.md).

Between conversations the model's ``want`` was acted on as given: exhausted, stressed or once ignored, she reached
out and took up work as readily as rested, and nothing that came of it taught her choosing."""

import json
import random
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind import life
from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.values import Values, features
from sentientmilk_framework.mind.will import Option, choose, mine

NOON = 1_763_294_400.0
SPENT = {"adenosine": 0.9, "energy": 0.2, "cortisol": 0.65, "dopamine": 0.3, "oxytocin": 0.3, "serotonin": 0.45}


def her(**levels):
    body = Body(Temperament.born(seed=4), at=NOON)
    body.levels.update(levels)
    return body


def imagined():
    return [Option("tell", say="the seedlings sprouted", effort=0.1, chance=0.7),
            Option("do", what="sort the photos of the garden", effort=0.6, chance=0.7), Option("let")]


def rates(body, made=imagined, values=None, reacting=None, runs=600):
    values, rng, counts = values or Values(), random.Random(9), {}
    for _ in range(runs):
        choice = choose(made(), mine(0.5), body, values, lambda o: features(o.act, (), "own", 12.0, "milk"), rng,
                        reacting)
        counts[choice.option.act] = counts.get(choice.option.act, 0) + 1
    return {act: counts.get(act, 0) / runs for act in ("tell", "do", "let")}


def reaching_out():
    return [Option("tell", say="the seedlings sprouted", effort=0.1, chance=0.7), Option("let")]


def test_her_state_moves_what_she_does_on_her_own():
    rested, spent = rates(her()), rates(her(**SPENT))
    assert rested["do"] > spent["do"] and spent["let"] > rested["let"]
    # tired and low, she reaches out less too, against letting it be (beside work she can't face, a small
    # message takes the share the work had)
    assert rates(her(), made=reaching_out)["tell"] > rates(her(**SPENT), made=reaching_out)["tell"]


def test_letting_it_be_is_always_open_and_nothing_is_ruled_out():
    hopeless = [Option("do", what="rewrite the whole project", effort=1.0, chance=0.1), Option("let")]
    choice = choose(hopeless, mine(0.2), her(**SPENT), Values(), lambda o: [], random.Random(1))
    assert choice.option.act == "let" or choice.chances["let"] > 0.5
    assert 0.0 < choice.chances["do"] < choice.chances["let"]  # less likely, never impossible


def test_a_learned_dread_of_reaching_out_makes_it_less_likely():
    dread = rates(her(), reacting=lambda option: -0.3 if option.act == "tell" else 0.0)
    assert dread["tell"] < rates(her())["tell"]


def test_what_her_own_acts_brought_before_weighs():
    values = Values()
    values.learn(features("tell", (), "own", 12.0, "milk"), -1.0, 0.6)  # reaching out on her own went badly
    assert rates(her(), values=values)["tell"] < rates(her())["tell"]


def test_with_nothing_between_them_no_hidden_rule_picks():
    def twins():
        return [Option("tell", say="first", effort=0.1, chance=0.7), Option("tell", say="second", effort=0.1, chance=0.7)]
    rng, first = random.Random(3), 0
    for _ in range(800):
        choice = choose(twins(), mine(0.5), her(), Values(), lambda o: [], rng)
        first += choice.option.say == "first"
    assert 0.44 < first / 800 < 0.56


@pytest.mark.mind
def test_a_thought_does_what_her_will_chose_and_keeps_why(brain):
    mind = brain.brain.mind
    brain.client.mind("milk", idle=5)
    brain.provider.replies += ["Hi.", "Sorted them."]
    turn(brain, "milk", "the garden photos are a mess")
    for seed in range(40):  # until she lets one be and takes one up: both happen, by her will
        brain.provider.mind_replies["think"] = [json.dumps({
            "thought": "Those garden photos need sorting.",
            "could": [{"act": "do", "what": "sort the garden photos", "effort": 0.5, "chance": 0.8}]})]
        mind.rng.seed(seed)
        mind._think("wonder", None)
        went = {t.get("went") for t in mind.self["thoughts"]}
        if {"task", "let be"} <= went:
            break
    leaned = mind.self["thoughts"][0]["leaned"]
    assert set(leaned["chances"]) == {"do", "let"} and abs(sum(leaned["chances"].values()) - 1.0) < 1e-6
    assert {"task", "let be"} <= went
    tasks = brain.store.runs(app="milk", kind="task")
    assert len(tasks) == sum(t.get("went") == "task" for t in mind.self["thoughts"])
    assert all(t["options"]["own"]["leaned"]["features"] for t in tasks)
    let_be = next(t for t in mind.self["thoughts"] if t.get("went") == "let be")
    assert let_be["want"] == "nothing" and let_be["leaned"]["act"] == "let"
    assert "let it be" in mind.look_inward()


@pytest.mark.mind
def test_what_came_of_reaching_out_teaches_her(brain):
    mind = brain.brain.mind
    found = features("tell", (), "own", 12.0, "milk")
    with mind._lock:
        before = mind.values.predict(found)
        mind._credit(found, {"company": 0.6})  # they answered warmly
        warmer = mind.values.predict(found)
        mind._credit(found, {"company": -0.5})  # nobody answered while they could have
    assert warmer > before and mind.values.predict(found) < warmer


@pytest.mark.mind
def test_an_answer_to_what_she_said_on_her_own_teaches_her_choosing(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello")
    found = features("tell", (), "own", mind.body.hour(time.time()), "milk")
    with mind._lock:  # she said something on her own here, and it waits on an answer
        mind.self["urge"] = {"at": time.time(), "mark": mind.presence.now(), "want": "tell", "app": "milk",
                             "session": "main", "say": "the seedlings sprouted", "actor": mind.self["contact"]["actor"],
                             "thought": None,
                             "offered": True, "text": "", "features": found, "credited": False}
        before = mind.values.predict(found)
    brain.provider.mind_replies["imagine"] = [
        '["they are glad to hear it", "much more", "same", "same", "good", "chat", "garden"]']
    brain.provider.replies += ["Yes!"]
    turn(brain, "milk", "oh that's lovely, show me!")
    assert mind.self["urge"] is None and mind.values.predict(found) > before  # answered: taken in, and taught


@pytest.mark.mind
def test_a_failed_call_costs_the_attempt_and_the_wish_comes_back(brain):
    mind = brain.brain.mind
    brain.provider.mind_replies["think"] = [429]
    with mind._lock:
        mind.self["fired"].clear()
    mind._attempt("wonder", None, time.time())
    wait_for(lambda: not mind._thinking)
    fired = mind.self["fired"]
    assert "thought" in fired and "wonder" not in fired  # her readiness to wander is not used up
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Rain again."})]
    with mind._lock:
        fired["thought"] -= life.REFRACTORY["thought"]  # the 10 minutes between two thoughts have passed
    mind._attempt("wonder", None, time.time())
    wait_for(lambda: not mind._thinking)
    assert mind.self["thoughts"][0]["thought"] == "Rain again." and "wonder" in fired


@pytest.mark.mind
def test_a_thought_survives_an_edit_elsewhere_and_goes_with_what_it_stood_on(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Oh no."]
    turn(brain, "milk", "the cat is sick", session="cats")
    cat = wait_for(lambda: (mind.memory.recent(1, kinds=("exchange",)) or [None])[0])

    def edited_elsewhere(payload):
        mind.invalidate("milk", "elsewhere", delete=True)  # a chat with nothing of this thought in it
        return json.dumps({"thought": "I hope the cat is all right."})
    brain.provider.mind_replies["think"] = [edited_elsewhere]
    mind._think("ruminate", cat)
    assert mind.self["thoughts"][0]["thought"] == "I hope the cat is all right."

    def taken_back(payload):
        mind.invalidate("milk", "cats", delete=True)  # what the thought dwells on is taken back
        return json.dumps({"thought": "Poor cat, still."})
    brain.provider.mind_replies["think"] = [taken_back]
    mind._think("ruminate", cat)
    assert all(t["thought"] != "Poor cat, still." for t in mind.self["thoughts"])
