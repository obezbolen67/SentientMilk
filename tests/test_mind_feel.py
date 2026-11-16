"""What she senses of her body: lagged and blurred, sensations rather than numbers, and a face for apps."""

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Concepts, Interoception, face, feel

NOON = 1_763_294_400.0
MILKCHAN = {"arms_crossed": ["neutral", "smile", "sad", "mad", "nervous", "confused", "playful", "zoned_out"],
            "arms_down": ["neutral", "smile", "sad", "mad", "nervous", "confused"]}


def her(seed=1, insight=1.0, **levels):
    body = Body(Temperament.born({"insight": insight}, seed=seed), at=NOON)
    body.levels.update(levels)
    senses = Interoception(body, seed)
    return body, senses


def test_good_news_and_closeness_feel_pleasant_and_stress_does_not():
    body, senses = her(reward=0.7, oxytocin=0.75, endorphin=0.5)
    good = feel(body, senses)
    body, senses = her(cortisol=0.8, reward=-0.6, grievance=0.5, serotonin=0.35)
    bad = feel(body, senses)
    assert good.valence > 0.4 > -0.4 > bad.valence
    assert dict(good.strongest())["warm"] > 0.4 and "light" in dict(good.strongest())
    assert {"tense", "prickly", "sinking"} & set(dict(bad.strongest()))


def test_she_senses_her_body_late():
    body, senses = her()
    body.levels["cortisol"] = 0.9
    assert feel(body, senses).sensed["tense"] < 0.3  # not yet
    senses.follow(body, 600)
    assert feel(body, senses).sensed["tense"] > 0.6


def test_little_insight_misreads_her_body_more_and_a_moment_reads_the_same_twice():
    def spread(body, senses):
        errors = []
        for _ in range(200):
            senses.follow(body, 300)
            errors.append(abs(senses.reading(body)["cortisol"] - body["cortisol"]))
        return sum(errors) / len(errors)
    body, sharp = her(insight=1.0, seed=2)
    blurred_body, blurred = her(insight=-1.0, seed=2)
    assert spread(blurred_body, blurred) > 1.3 * spread(body, sharp)
    assert sharp.reading(body) == sharp.reading(body)  # no flicker between two looks


def test_she_hears_her_body_in_words_never_in_numbers():
    body, senses = her(energy=0.2, oxytocin=0.8)
    said = feel(body, senses).words()
    assert said.startswith("You feel ") and "drained" in said and "warm" in said
    assert not any(ch.isdigit() for ch in said)


def test_her_face_is_a_declared_mood_by_how_she_feels():
    body, senses = her(reward=0.8, oxytocin=0.8, endorphin=0.6, noradrenaline=0.6)
    happy = face(feel(body, senses), MILKCHAN, asleep=False)
    assert happy["mood"] in ("smile", "playful") and happy["stance"] == "open" and happy["eyes"] == "open"
    body, senses = her(cortisol=0.85, grievance=0.7, serotonin=0.3, noradrenaline=0.75, reward=-0.5)
    cross = face(feel(body, senses), MILKCHAN, asleep=False)
    assert cross["mood"] in ("mad", "nervous") and cross["stance"] == "closed"
    asleep = face(feel(body, senses), MILKCHAN, asleep=True)
    assert asleep == {"mood": "zoned_out", "stance": cross["stance"], "eyes": "closed", "asleep": True}
    assert face(feel(body, senses), {"pose": ["glee"]}, asleep=False) is None  # no mood she knows


def test_a_state_like_one_she_named_comes_back_with_its_name():
    body, senses = her(cortisol=0.7, social=0.1, bond=0.9)
    lonely = feel(body, senses)
    concepts = Concepts()
    concepts.add("homesick", lonely.vector())
    body2, senses2 = her(seed=3, cortisol=0.68, social=0.12, bond=0.88)
    assert concepts.like(feel(body2, senses2).vector()) == "homesick"
    assert "homesick" in feel(body2, senses2).words(like="homesick")
    body3, senses3 = her(reward=0.9, oxytocin=0.9, endorphin=0.7)
    assert concepts.like(feel(body3, senses3).vector()) is None
