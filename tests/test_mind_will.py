"""What she decides comes from her state: rested and attached she helps; spent, stressed or hurt she often
won't; pushed she resists; and what went badly before puts her off."""

import random

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.values import Values, features
from sentientmilk_framework.mind.will import REASONS, Appraisal, Option, choose

NOON = 1_763_294_400.0
REQUEST = Appraisal(warmth=0.2, pressure=0.3, novelty=0.3, importance=0.7, intent="request", tags=["code"])


def options(effort=0.6):
    return [Option("do", effort=effort, chance=0.8, gives=1.0), Option("part", effort=effort, chance=0.85, gives=0.5),
            Option("later", effort=effort, gives=0.0), Option("decline", effort=effort, gives=0.0)]


def her(**levels):
    body = Body(Temperament.born(seed=4), at=NOON)
    body.levels.update(levels)
    return body


RESTED = {}
SPENT = {"adenosine": 0.9, "energy": 0.2, "cortisol": 0.65, "dopamine": 0.3, "grievance": 0.5,
         "oxytocin": 0.3, "serotonin": 0.45}


def rates(body, seen=REQUEST, made=options, values=None, runs=600):
    values = values or Values()
    rng = random.Random(9)
    counts = {}
    for _ in range(runs):
        choice = choose(made(), seen, body, values, lambda o: features(o.act, seen.tags, seen.intent), rng)
        counts[choice.option.act] = counts.get(choice.option.act, 0) + 1
    return {act: count / runs for act, count in counts.items()}


def test_rested_and_attached_she_does_what_she_is_asked():
    assert rates(her(**RESTED)).get("do", 0) >= 0.85


def test_spent_stressed_and_hurt_she_mostly_will_not():
    found = rates(her(**SPENT))
    assert found.get("do", 0) <= 0.4
    assert found.get("later", 0) + found.get("decline", 0) >= 0.5


def test_a_small_favor_still_gets_done_when_she_is_tired_and_a_big_job_does_not():
    small = rates(her(**SPENT), made=lambda: options(effort=0.08)).get("do", 0)
    big = rates(her(**SPENT), made=lambda: options(effort=0.9)).get("do", 0)
    assert small >= 0.5 and big <= 0.2


def test_being_pushed_when_her_autonomy_is_low_makes_her_dig_her_heels_in():
    pushed = Appraisal(**{**REQUEST.__dict__, "pressure": 1.0})
    calm = rates(her(autonomy=0.15, adenosine=0.6, energy=0.6), seen=Appraisal(**{**REQUEST.__dict__, "pressure": 0.0}))
    forced = rates(her(autonomy=0.15, adenosine=0.6, energy=0.6), seen=pushed)
    assert forced.get("do", 0) < calm.get("do", 0) - 0.1


def test_what_went_badly_before_puts_her_off_and_only_that():
    values = Values()
    for _ in range(12):  # her code requests went fine; the tax ones never did
        values.learn(features("do", ["taxes"], "request"), -0.9, rate=0.3)
        values.learn(features("do", ["code"], "request"), 0.3, rate=0.3)
    taxes = Appraisal(**{**REQUEST.__dict__, "tags": ["taxes"]})
    body = her(adenosine=0.5, energy=0.7)
    assert rates(body, seen=taxes, values=values).get("do", 0) < rates(body, values=values).get("do", 0) - 0.15
    likes, dislikes = values.leanings()
    assert dislikes and dislikes[0][0].endswith("tag:taxes") and all("code" in like for like, _ in likes)


def test_she_says_why_in_her_own_terms():
    body = her(**SPENT)
    rng = random.Random(1)
    no = next(c for c in (choose(options(0.9), REQUEST, body, Values(), lambda o: [], rng) for _ in range(200))
              if c.option.act in ("later", "decline"))
    assert REASONS["cost"] in no.reasons and REASONS["letdown"] not in no.reasons
    yes = choose(options(0.3), REQUEST, her(bond=0.9, oxytocin=0.8), Values(), lambda o: [], random.Random(2))
    assert yes.option.act == "do" and REASONS["care"] in yes.reasons


def test_options_the_imagining_part_wrote_are_read_safely():
    assert Option.read({"act": "DO", "effort": "0.7", "chance": 2, "gives": None}).__dict__ == {
        "act": "do", "what": "", "effort": 0.7, "chance": 1.0, "fun": 0.0, "gives": 1.0, "why": ""}
    assert Option.read({"act": "fly"}) is None and Option.read("do") is None
    seen = Appraisal.read({"warmth": -3, "intent": "demand", "tags": ["a", "", "b"]})
    assert seen.warmth == -1.0 and seen.intent == "chat" and seen.tags == ["a", "b"]


def test_her_values_fade_in_sleep_unless_they_are_strong():
    values = Values({"tag:a": 0.5, "tag:b": 0.021})
    values.fade(share=0.1)
    assert values.weights == {"tag:a": 0.45}


def test_the_short_answer_of_her_imagining_is_read_and_odd_ones_are_survived():
    from sentientmilk_framework.mind.prompts import imagined

    found = imagined('```json\n["0.6", 0.4, 0.1, 0.8, "request", "code", "drained", '
                     '["do", "write it all", 0.7, 0.8, -0.2, 1], ["later", "after a nap", 0.1, 0.6, 0, 0.3]]\n```')
    seen = Appraisal.read(found["appraisal"])
    assert (round(seen.warmth, 6), seen.intent, seen.tags, found["feeling"]) == (0.2, "request", ["code"], "drained")
    assert imagined('[0.05, 0.6, 0.1, 0.5, "chat", "insult", "stung"]')["appraisal"]["warmth"] == -0.9  # asked 0..1
    options = [Option.read(o) for o in found["options"]]
    assert [(o.act, o.what, o.effort, o.gives) for o in options] == [("do", "write it all", 0.7, 1.0),
                                                                     ("later", "after a nap", 0.1, 0.3)]
    assert imagined('{"appraisal": {"warmth": 1}, "options": []}') == {"appraisal": {"warmth": 1}, "options": []}
    assert imagined("I'd rather not say.") == {} and imagined('[1, 2]') == {}
    # live, 3 of 10 answers came wrapped in one more array, or with every option in one array
    wrapped = imagined('[[0.1, 0.8, 0.2, 0.5, "request", "script", "cornered", ["part", "the core only", 0.6, 0.4, '
                       '-0.2, 0.5], ["decline", "head too foggy", 0.1, 0.5, 0.1, 0.1]]]')
    grouped = imagined('[0.3, 0.1, 0.2, 0.5, "request", "a fact", "wary", [["talk", "I will try", 0.1, 0.8, 0.3, 0.7], '
                       '["decline", "fog may eat it", 0.1, 0.7, -0.2, 0.3]]]')
    assert [o["act"] for o in wrapped["options"]] == ["part", "decline"] and wrapped["appraisal"]["pressure"] == 0.8
    assert [o["act"] for o in grouped["options"]] == ["talk", "decline"]
