"""Her body's chemistry: levels relax, push each other, habituate, and sleep has its own physiology."""

import math

from sentientmilk_framework.mind.body import DAY, HOUR, MINUTE, START, Body, Temperament

NOON = 1_763_294_400.0  # 2025-11-16 12:00 UTC; local hours differ, the rhythm only needs a fixed start


def body(seed=1, **levels):
    made = Body(Temperament.born(seed=seed), at=NOON)
    made.levels.update(levels)
    return made


def test_a_push_fades_back_toward_where_she_rests():
    her = body(cortisol=0.9)
    her.advance(NOON + 6 * HOUR)
    assert her["cortisol"] < 0.45
    her = body(reward=0.8)
    her.advance(NOON + 15 * MINUTE)
    assert abs(her["reward"]) < 0.05  # a burst lasts minutes


def test_lasting_stress_wears_down_her_serotonin_and_her_vigor():
    calm, stressed = body(), body()
    for hour in range(1, 13):
        stressed.apply({"cortisol": 0.25})
        calm.advance(NOON + hour * HOUR)
        stressed.advance(NOON + hour * HOUR)
    assert stressed["serotonin"] < calm["serotonin"] - 0.05
    assert stressed["dopamine"] < calm["dopamine"]


def test_the_same_kindness_again_and_again_moves_her_less_and_a_drought_restores_it():
    her = body()
    first = her.apply({"oxytocin": 0.1})["oxytocin"]
    for _ in range(8):
        last = her.apply({"oxytocin": 0.05})["oxytocin"]
    assert last < 0.05 * 0.8 and her.sensitivity["oxytocin"] < 0.95
    her.advance(NOON + 8 * HOUR)
    assert her.sensitivity["oxytocin"] > 0.97 and first > 0.09


def test_awake_she_builds_sleep_pressure_and_sleep_clears_it():
    her = body(adenosine=0.1)
    her.advance(NOON + 16 * HOUR)
    tired = her.fatigue()
    assert her["adenosine"] > 0.9 and tired > 0.5
    her.fall_asleep()
    her.advance(NOON + 24 * HOUR)
    assert her["adenosine"] < 0.05 and her.fatigue() < tired / 3


def test_work_spends_her_energy_and_rest_brings_it_back():
    her = body()
    her.exert(240_000)
    assert her["energy"] < 0.3
    spent = her["energy"]
    her.advance(NOON + HOUR)
    assert her["energy"] > spent + 0.4


def test_she_misses_the_user_and_misses_them_slower_when_they_are_there():
    alone, together = body(social=0.9), body(social=0.9)
    alone.advance(NOON + 8 * HOUR)
    together.advance(NOON + 8 * HOUR, present=True)
    assert alone["social"] < 0.4 < together["social"]


def test_days_lived_through_at_once_stay_in_range():
    her = body()
    her.advance(NOON + 3 * DAY)
    assert her.at == NOON + 3 * DAY
    assert all(-1.0 <= value <= 1.0 for value in her.levels.values())
    assert all(0.0 <= her[name] <= 1.0 for name in START if name != "reward")


def test_the_same_seed_lives_the_same_life():
    a, b = body(seed=7), body(seed=7)
    for her in (a, b):
        her.apply({"cortisol": 0.2, "reward": 0.5})
        her.advance(NOON + 5 * HOUR)
    assert a.levels == b.levels
    c = body(seed=8)
    c.apply({"cortisol": 0.2, "reward": 0.5})
    c.advance(NOON + 5 * HOUR)
    assert c.levels != a.levels  # her noise is her own


def test_her_persona_sets_her_gains_and_her_seed_makes_her_her_own():
    warm = Temperament.born({"warmth": 1.0, "stress": -1.0}, seed=3)
    assert warm.warmth > 1.3 and warm.stress < 0.75 and 0.85 < warm.vigor < 1.15
    assert Temperament.born({}, seed=3) != Temperament.born({}, seed=4)
    warm_her, cold_her = Body(warm, at=NOON), Body(Temperament.born({"warmth": -1.0}, seed=3), at=NOON)
    assert warm_her.apply({"oxytocin": 0.1})["oxytocin"] > cold_her.apply({"oxytocin": 0.1})["oxytocin"]


def test_she_is_kept_and_comes_back_as_she_was():
    her = body(seed=5)
    her.apply({"cortisol": 0.3, "oxytocin": 0.2})
    her.fall_asleep()
    again = Body.from_dict(her.to_dict())
    assert again.levels == her.levels and again.asleep and again.temperament == her.temperament


def test_woken_too_early_she_is_groggy_and_a_little_irritable():
    her = body(adenosine=0.8)
    her.fall_asleep()
    before = dict(her.levels)
    her.wake(startled=True)
    assert not her.asleep and her["energy"] < before["energy"] and her["cortisol"] > before["cortisol"]


def test_her_rhythm_follows_when_the_user_is_around():
    her = body()
    for _ in range(200):
        her.learn_rhythm(23.0)  # a night owl
    assert math.isclose(her.peak, 1.0, abs_tol=0.5)
