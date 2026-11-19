"""Sleepiness, effort and interest stay apart, from what she senses before an offer to how she weighs the task once
she knows it (docs/superpowers/specs/2026-11-19-attention-and-action-credit-design.md, part 2)."""

import random

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Interoception, feel
from sentientmilk_framework.mind.values import Values, features
from sentientmilk_framework.mind.will import REASONS, Appraisal, Option, choose

NOON = 1_763_294_400.0
TIRED = {"adenosine": 0.72, "energy": 0.35, "dopamine": 0.4, "noradrenaline": 0.25}
RESTED = {"adenosine": 0.3, "energy": 1.0}


def her(levels, bond=0.8):
    body = Body(Temperament.born(seed=4), at=NOON + 3 * 3600)
    body.levels.update({"bond": bond, **levels})
    return body


WHAT = "tidy the notes for the clock widget"


def task(seen):
    """The same task each time: asked of her, done now, later or not at all; her own idea, done or let be."""
    if seen.intent == "own":
        return [Option("do", what=WHAT, effort=0.5, chance=0.8), Option("let", effort=0.0)]
    return [Option("do", what=WHAT, effort=0.5, chance=0.8, gives=1.0), Option("later", what=WHAT, effort=0.5,
                                                                                chance=0.8),
            Option("decline", what=WHAT, effort=0.5, chance=0.8)]


def weigh(body, seen, values=None, runs=400):
    """How often she does it now, and her reasons each time she does or does not."""
    values, rng, did, why = values or Values(), random.Random(3), 0, {"do": [], "not": []}
    for _ in range(runs):
        choice = choose(task(seen), seen, body, values, lambda o: features(o.act, seen.tags, seen.intent, 15.0, "milk"),
                        rng)
        did += choice.option.act == "do"
        why["do" if choice.option.act == "do" else "not"] += choice.reasons
    return did / runs, why


def bored_of_it():
    values = Values()
    doing = [f for f in features("do", ["tidying"], "own", 15.0, "milk") if f.startswith("act:")]
    for _ in range(30):  # doing it has felt dull every time (after: what she did is what she learns from)
        values.reinforce(doing, -0.8 - values.predict(doing), 0.3)
    return values


ASKED = Appraisal(company=0.4, capable=0.3, novelty=0.3, intent="request", tags=["tidying"])  # the user asks it
OWN_IDEA = Appraisal(novelty=0.0, intent="own", tags=["tidying"])  # her own idea, nothing new in it


def test_before_the_offer_sleepiness_and_spent_energy_are_sensed_apart_and_neither_is_the_task():
    def sensed(levels):
        body = her(levels)
        senses = Interoception(body, 1)
        for _ in range(30):
            senses.follow(body, 90)
        return feel(body, senses).words()
    sleepy, spent = sensed({"adenosine": 0.75}), sensed({"energy": 0.3})
    assert "more sleep pressure" in sleepy and "energy" not in sleepy
    assert "less energy" in spent and "sleep pressure" not in spent
    assert "clock widget" not in sleepy + spent  # the task is not known yet: nothing of it is felt


def test_a_tired_milk_still_does_what_she_cares_about_for_them():
    rested = weigh(her(RESTED), ASKED)[0]
    done, why = weigh(her(TIRED), ASKED)
    assert rested > done > 0.5  # tired, less often, and still mostly done
    assert REASONS["care"] in why["do"]  # done for them, against how she feels


def test_a_rested_milk_lets_an_uninteresting_task_go_and_not_for_want_of_energy():
    done, why = weigh(her(RESTED), OWN_IDEA, bored_of_it())
    fresh = Appraisal(novelty=0.8, intent="own", tags=["tidying"])  # the same, new to her and not yet dull
    assert done < 0.5 < weigh(her(RESTED), fresh)[0]
    assert REASONS["cost"] not in why["not"]  # not for want of energy: rested, the work is not what holds her back
    assert REASONS["learned-"] in why["not"]  # what holds her back: doing it has felt dull before


def test_the_same_tired_feeling_leads_to_doing_one_task_and_putting_off_another():
    cared, _ = weigh(her(TIRED), ASKED)
    dull, why = weigh(her(TIRED), OWN_IDEA, bored_of_it())
    assert cared > 0.5 > dull
    assert REASONS["cost"] in why["not"]  # tired: the work weighs, as it did not when rested
