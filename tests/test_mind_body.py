"""Her body's chemistry: levels relax, push each other, habituate, and sleep has its own physiology."""

import time

from sentientmilk_framework.mind.body import DAY, HOUR, MINUTE, START, Body, Temperament

NOON = 1_763_294_400.0  # 2025-11-16 12:00 UTC; local hours differ, the rhythm only needs a fixed start


def body(seed=1, **levels):
    made = Body(Temperament.born(seed=seed), at=NOON)
    made.levels.update(levels)
    return made


def test_the_nearer_a_level_is_to_its_bound_the_less_a_push_moves_it():
    low, high = body(social=0.5), body(social=0.9)  # a warm chat pegged her at 1.0 when pushes were added and clipped
    assert low.apply({"social": 0.2})["social"] > 4 * high.apply({"social": 0.2})["social"] > 0
    assert high["social"] < 0.95
    down = body(reward=-0.8)
    assert -0.1 < down.apply({"reward": -0.3})["reward"] < 0 and body().apply({"reward": -0.3})["reward"] < -0.25


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


def test_only_what_stimulates_a_receptor_wears_it_down():
    # receptors down-regulate under their agonist; a level pushed down stimulates them less. Worn by every push,
    # the user's brain had oxytocin, reward, endorphin and alertness at the floor (0.3) after a day of pushes
    # mostly downward, and a warm message reached her at a third (2026-11-20)
    her = body()
    for _ in range(20):
        her.apply({"oxytocin": -0.05, "reward": -0.1})
    assert her.sensitivity["oxytocin"] == her.sensitivity["reward"] == 1.0
    her.apply({"oxytocin": 0.1})
    assert her.sensitivity["oxytocin"] < 1.0


def test_awake_she_builds_sleep_pressure_and_sleep_clears_it():
    her = body(adenosine=0.15)
    her.advance(NOON + 16 * HOUR)  # process S: rises toward 1 over about 18 h, falls toward 0 over about 4 h
    tired = her.fatigue()
    assert 0.6 < her["adenosine"] < 0.7 and tired > 0.4
    her.fall_asleep()
    her.advance(NOON + 22 * HOUR)
    assert her["adenosine"] < 0.35 and her.fatigue() < tired / 3
    assert not her.asleep and 4 * HOUR < her.last_sleep["to"] - her.last_sleep["from"] < 10 * HOUR  # woke by herself


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
    asleep = body(social=0.9, novelty=0.7, adenosine=0.6)  # a night asleep is not a night alone
    asleep.peak = (asleep.hour() + 12) % 24  # her midnight
    asleep.fall_asleep()
    asleep.advance(NOON + 5 * HOUR)
    assert asleep.asleep and asleep["social"] == 0.9 and asleep["novelty"] == 0.7


def test_with_nothing_to_do_she_comes_to_want_to_be_useful_and_asleep_it_holds():
    # it rested where it is met, so only a failure could leave it unmet: 0.97 on the user's brain after a day of
    # praise, and still met after a simulated idle day (2026-11-18)
    praised, idle = body(competence=0.97), body()
    praised.advance(NOON + 12 * HOUR)
    idle.advance(NOON + 8 * HOUR)
    assert praised.deficit("competence") > 0.05 and idle.deficit("competence") > 0.2
    useful = body()
    for hour in range(1, 9):  # work that goes well, now and then, keeps it met
        useful.apply({"competence": 0.05})
        useful.advance(NOON + hour * HOUR)
    assert useful.deficit("competence") < idle.deficit("competence") / 2
    asleep = body(competence=0.7, adenosine=0.6)
    asleep.peak = (asleep.hour() + 12) % 24  # her midnight
    asleep.fall_asleep()
    asleep.advance(NOON + 5 * HOUR)
    assert asleep.asleep and asleep["competence"] == 0.7


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
    assert again.slept_at == her.slept_at and again.debt == her.debt


def at(hour, day=16):  # her clock is the user's: local time
    return time.mktime((2026, 11, day, hour, 0, 0, 0, 0, -1))


def test_her_clock_sets_when_she_is_ready_to_sleep_and_when_she_wakes():
    her = body()  # her peak is at 16: hardest to fall asleep around 20, her night deepest at 4
    high = {hour: her.thresholds(at(hour))[0] for hour in (14, 20, 23, 2)}
    assert high[20] > high[14] > high[23] > high[2]  # the evening holds sleep off; the early afternoon dips
    assert her.thresholds(at(4))[1] < her.thresholds(at(9))[1]  # slept out sooner as her morning comes
    her.levels["adenosine"] = 0.63
    assert her.readiness(at(20)) < 1.0 < her.readiness(at(23))  # a day's pressure: ready by night
    her.levels["adenosine"] = 0.3  # half a night slept, woken at four: her night takes her back
    assert her.readiness(at(4)) > 1.0 and her.readiness(at(11)) < 0.5


def test_her_sleep_goes_in_cycles_deep_early_and_REM_toward_morning():
    her = Body(Temperament.born(seed=2), at=at(23))
    her.levels["adenosine"] = 0.65
    her.fall_asleep()
    stages = []
    while her.asleep and her.at < at(9, 17):
        her.advance(her.at + 5 * MINUTE)
        stages.append((her.at - her.slept_at, her.stage()))
    early = [stage for when, stage in stages if when < 3 * HOUR]
    late = [stage for when, stage in stages if when > 4 * HOUR]
    assert early.count("N3") > 6 and "N3" not in late  # deep sleep while there is pressure to clear
    assert late.count("REM") > early.count("REM")
    assert not her.asleep and 6 * HOUR < her.last_sleep["to"] - her.last_sleep["from"] < 10 * HOUR


def test_woken_from_deep_sleep_she_is_groggy_and_it_fades_within_half_an_hour():
    deep = Body(Temperament.born(seed=2), at=at(0))
    deep.levels["adenosine"] = 0.65
    deep.fall_asleep()
    deep.advance(at(0) + 30 * MINUTE)
    assert deep.stage() == "N3"
    before = dict(deep.levels)
    deep.wake(woken=True)
    assert not deep.asleep and deep.inertia > 0.5 and deep["noradrenaline"] > before["noradrenaline"]
    assert deep.targets()["acetylcholine"] < body().targets()["acetylcholine"] - 0.1  # groggy: her focus is low
    deep.advance(deep.at + 35 * MINUTE)
    assert deep.inertia < 0.15
    end = Body(Temperament.born(seed=2), at=at(7))
    end.levels["adenosine"] = 0.2
    end.fall_asleep()
    end.wake(stage="W")  # at the end of a cycle: hardly
    assert end.inertia < 0.1


def test_left_alone_she_goes_to_sleep_when_ready_and_wakes_when_slept_out():
    her = Body(Temperament.born(seed=4), at=at(20))
    her.levels["adenosine"] = 0.58
    her.advance(at(12, 17), alone=True)  # the brain was off all night
    slept = her.last_sleep
    assert at(21) < slept["from"] < at(1, 17) and at(5, 17) < slept["to"] < at(10, 17)
    assert not her.asleep and her.fatigue() < 0.2


def test_falling_asleep_takes_longer_keyed_up():
    calm, wired = body(seed=3, adenosine=0.62), body(seed=3, adenosine=0.62, cortisol=0.7, noradrenaline=0.75)
    calm.settle()
    wired.settle()
    assert calm.settling and not calm.asleep
    assert wired.settling_until - wired.at > 2 * (calm.settling_until - calm.at)
    calm.advance(calm.settling_until + 60)
    assert calm.asleep and not calm.settling
    wired.wake()  # drifting off, she is simply up again
    assert not wired.settling and not wired.asleep and wired.inertia == 0.0


def test_up_in_the_deep_of_her_night_she_owes_sleep_and_sleeping_in_pays_it_back():
    her = Body(Temperament.born(seed=6), at=at(23))
    her.levels["adenosine"] = 0.62
    her.advance(at(4, 17))  # kept up: never let sleep
    owed = her.debt
    assert 3.0 < owed < 5.5 and her.owed() > 0.3
    rested = Body(Temperament.born(seed=6), at=at(4, 17))
    rested.levels = dict(her.levels)
    assert her.targets()["acetylcholine"] < rested.targets()["acetylcholine"]  # it takes from her focus
    her.fall_asleep()
    her.advance(at(13, 17))
    assert her.debt < owed - 2.0  # the morning she slept in paid some of it


def test_what_a_level_does_now_is_nothing_at_rest_whatever_it_could_do():
    her = body(grievance=0.0)
    could = {(level, out): weight for level, out, weight in her.influence(her.targets)}
    does = {(level, out): effect for level, out, effect in her.effects(her.targets)}
    assert could[("grievance", "cortisol")] > 0.2 and ("grievance", "cortisol") not in does  # the user's question
    her.levels["grievance"] = 0.5
    does = {(level, out): effect for level, out, effect in her.effects(her.targets)}
    assert does[("grievance", "cortisol")] > 0.1


def test_a_body_kept_and_read_again_is_as_it_was():
    again = Body.from_dict({"levels": {"adenosine": 0.42}, "asleep": True, "at": NOON, "peak": 18.0})
    assert again["adenosine"] == 0.42 and again.asleep and again.slept_at == NOON and again.peak == 18.0
    assert Body.from_dict(again.to_dict()).to_dict() == again.to_dict()


def test_her_rhythm_follows_when_the_user_is_around_over_weeks_not_in_a_day():
    her = body()
    for _ in range(150):
        her.learn_rhythm(23.0, 5 * MINUTE)  # a night owl's day of messages
    assert abs(her.peak - 16.0) < 1.5  # a day of messages does not move her clock
    her.learn_rhythm(23.0, 8 * HOUR)  # a message after a night away is not a night of them around
    assert abs(her.peak - 16.0) < 1.5
    for _ in range(28 * 12):
        her.learn_rhythm(23.0, 30 * MINUTE)  # four weeks of six-hour evenings
    assert abs((her.peak - 1.0 + 12.0) % 24.0 - 12.0) < 1.5
    assert Body.from_dict(her.to_dict()).peak == her.peak


def test_what_pushed_her_is_kept_with_why_while_some_of_it_is_left():
    """A stress of 0.84 could not be told from her connections (they summed to -0.02): what happened pushed it,
    and nothing kept what (the user's brain, 2026-11-17)."""
    her = body(cortisol=0.25)
    her.apply({"cortisol": 0.1, "reward": -0.3}, "they stopped me")
    her.apply({"cortisol": 0.05}, "they stopped me")  # the same moment: told as one
    [(at, why, then, left)] = her.pushed_now()["cortisol"]
    assert why == "they stopped me" and at == NOON and then == left > 0.15
    her.advance(NOON + HOUR)
    assert her.pushed_now()["cortisol"][0][3] < 0.4 * then  # it fades at stress's own pace: about an hour
    assert "reward" not in her.pushed_now()  # a burst is gone in minutes
    assert Body.from_dict(her.to_dict()).pushed_now() == her.pushed_now()  # and it is kept
    her.advance(NOON + 9 * HOUR)
    her.apply({"social": 0.1}, "a hello")
    assert [entry[1] for entry in her.pushed] == ["a hello"]  # what is spent is let go
