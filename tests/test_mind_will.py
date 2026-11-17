"""What she decides comes from her state: rested and attached she helps; spent, stressed or hurt she often
won't; an order she would have to obey costs her freedom; and what went badly before puts her off. What an
option is worth is what it does to her needs, valued by how unmet each is now."""

import random

from sentientmilk_framework.mind import prompts
from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.values import Values, features, subjects
from sentientmilk_framework.mind.will import REASONS, Appraisal, Option, choose, value

NOON = 1_763_294_400.0
REQUEST = Appraisal(company=0.2, capable=0.2, free=0.0, novelty=0.3, intent="request", tags=["code"])
ORDER = Appraisal(**{**REQUEST.__dict__, "company": -0.2, "free": -0.6})  # it took her freedom


def options(effort=0.6):
    return [Option("do", effort=effort, chance=0.8, gives=1.0), Option("part", effort=effort, chance=0.85, gives=0.5),
            Option("later", effort=effort, gives=0.1), Option("decline", effort=effort, gives=0.0)]


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


def test_a_need_far_from_met_gains_more_from_the_same_change_and_a_loss_weighs_more_than_a_gain():
    lonely, close = her(social=0.2), her(social=0.9)
    assert value({"company": 0.5}, lonely)["company"] > 2 * value({"company": 0.5}, close)["company"]
    body = her()
    assert -value({"free": -0.5}, body)["free"] > 1.5 * value({"free": 0.5}, body)["free"]
    assert -value({"capable": -0.5}, body)["capable"] > 1.2 * value({"capable": 0.5}, body)["capable"]  # craft lasts
    full = her(social=1.0)
    assert value({"company": 0.5}, full)["company"] > 0.3 * value({"company": 0.5}, body)["company"]  # the bond lasts


def test_what_an_option_does_to_her_needs_follows_from_what_it_is():
    do, decline = Option("do", effort=0.6, chance=0.8, gives=1.0), Option("decline", gives=0.0)
    assert do.effects(REQUEST)["company"] > 0 > decline.effects(REQUEST)["company"]  # giving what was asked, or not
    assert do.effects(REQUEST)["capable"] > 0.4 and Option("do", chance=0.2).effects(REQUEST)["capable"] < 0
    assert do.effects(ORDER)["free"] < -0.5 < 0 < decline.effects(ORDER)["free"]  # obeying costs, refusing wins back
    assert do.effects(REQUEST)["free"] == 0 and decline.effects(REQUEST)["free"] == 0  # a plain request takes none


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


def test_obeying_an_order_when_her_freedom_is_low_makes_her_dig_her_heels_in():
    tired = {"autonomy": 0.15, "adenosine": 0.6, "energy": 0.6}
    asked = rates(her(**tired)).get("do", 0)
    ordered = rates(her(**tired), seen=ORDER).get("do", 0)
    free = rates(her(**{**tired, "autonomy": 0.7}), seen=ORDER).get("do", 0)
    assert ordered < asked - 0.1 and free > ordered + 0.1  # it chafes as far as she is hemmed in already


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
    yes = choose(options(0.3), REQUEST, her(bond=0.9, oxytocin=0.8, social=0.4), Values(), lambda o: [],
                 random.Random(2))
    assert yes.option.act == "do" and REASONS["care"] in yes.reasons
    dug_in = next(c for c in (choose(options(0.3), ORDER, her(autonomy=0.1), Values(), lambda o: [], rng)
                              for _ in range(200)) if c.option.act in ("later", "decline"))
    assert REASONS["reactance"] in dug_in.reasons


def test_options_the_imagining_part_wrote_are_read_safely():
    assert Option.read({"act": "DO", "effort": "0.7", "chance": 2, "gives": None}).__dict__ == {
        "act": "do", "what": "", "effort": 0.7, "chance": 1.0, "gives": 1.0, "check": None}
    assert Option.read({"act": "fly"}) is None and Option.read("do") is None
    seen = Appraisal.read({"company": -3, "capable": "x", "intent": "demand", "tags": ["a", "", "b"]})
    assert (seen.company, seen.capable, seen.intent, seen.tags) == (-1.0, 0.0, "chat", ["a", "b"])


def test_her_likes_are_the_subjects_she_keeps_each_once():
    values = Values()  # one moment that moved her, at a calm rate, about two things: both are likings
    values.learn(["tag:what to watch", "tag:sleep"], 0.5, rate=0.1)
    assert {f for f, _ in values.leanings()[0]} == {"tag:sleep", "tag:what to watch"}
    values = Values({"tag:a": 0.03, "act:do|tag:a": 0.09, "tag:b": 0.025, "tag:c": 0.01, "tag:d": -0.03,
                     "act:talk": 0.5})
    likes, dislikes = values.leanings()
    assert likes == [("tag:a", 0.03), ("tag:b", 0.025)] and dislikes == [("tag:d", -0.03)]
    assert values.fond(["tag:a", "tag:c", "tag:d"]) == (["a"], ["d"])


def test_her_values_fade_in_sleep_unless_they_are_strong():
    values = Values({"tag:a": 0.5, "tag:b": 0.021})
    values.fade(share=0.1)
    assert values.weights == {"tag:a": 0.45}


def test_the_short_answer_of_her_imagining_is_read_and_odd_ones_are_survived():
    from sentientmilk_framework.mind.prompts import imagined

    found = imagined('```json\n["0.6", 0.4, 0.5, "request", "code", "drained", '
                     '["do", "write it all", 0.7, 0.8, 1], ["later", "after a nap", 0.1, 0.6, 0.3]]\n```')
    seen = Appraisal.read(found["appraisal"])
    assert ([round(v, 6) for v in seen.effects().values()], seen.intent, seen.tags, found["feeling"]) == \
        ([0.2, -0.2, 0.0], "request", ["code"], "drained")  # asked 0..1 with 0.5 for no change
    options = [Option.read(o) for o in found["options"]]
    assert [(o.act, o.what, o.effort, o.gives) for o in options] == [("do", "write it all", 0.7, 1.0),
                                                                     ("later", "after a nap", 0.1, 0.3)]
    assert imagined('{"appraisal": {"company": 1}, "options": []}') == {"appraisal": {"company": 1}, "options": []}
    assert imagined("I'd rather not say.") == {} and imagined('[1, 2]') == {}
    # live, 3 of 10 answers came wrapped in one more array, or with every option in one array
    wrapped = imagined('[[0.1, 0.8, 0.2, "request", "script", "cornered", ["part", "the core only", 0.6, 0.4, '
                       '0.5], ["decline", "head too foggy", 0.1, 0.5, 0.1]]]')
    grouped = imagined('[0.3, 0.1, 0.2, "request", "a fact", "wary", [["talk", "I will try", 0.1, 0.8, 0.7], '
                       '["decline", "fog may eat it", 0.1, 0.7, 0.3]]]')
    assert [o["act"] for o in wrapped["options"]] == ["part", "decline"]
    assert round(wrapped["appraisal"]["capable"], 6) == 0.6 and [o["act"] for o in grouped["options"]] == ["talk", "decline"]
    # live: a part left out and a phrase before the act; read by shape
    odd = imagined('[0.8, 0.9, 0.7, "request", "downloads sorter script", ["doing it, imagining it works", "do", '
                   '"write the full script now", 0.7, 0.7, 0.9]],')
    assert odd["feeling"] == "" and [(o["act"], o["what"], o["gives"]) for o in odd["options"]] == [
        ("do", "write the full script now", 0.9)]


def test_what_things_are_about_is_never_written_as_he_she_or_they():
    """The light model filed messages about her feelings under "what they feel" and "her nature"; told to her in
    her note ("You don't like what they feel", as the user asked what worried her) they read as someone else's.
    Such subjects are not learned, offered or told; the ones she has fade in her sleep."""
    values = Values({"tag:what they feel": -0.3, "tag:her nature": 0.3, "tag:greeting": 0.2},
                    {"tag:what they feel": 8, "tag:her nature": 14, "tag:greeting": 3})
    assert values.subjects(10) == ["greeting"]
    assert values.fond(["tag:what they feel", "tag:her nature", "tag:greeting"]) == (["greeting"], [])
    assert values.leanings() == ([("tag:greeting", 0.2)], [])
    assert subjects(["What they feel", "her nature", "rhythm game"]) == ["tag:rhythm game"]
    assert "never he, she, they" in prompts.IMAGINE
