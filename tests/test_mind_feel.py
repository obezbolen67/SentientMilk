"""What she senses of her body (lagged and blurred, its channels in words, never numbers), the feelings she
makes of it (any word she ever used, by body and situation) and a face for apps."""

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Concepts, Interoception, face, feel
from sentientmilk_framework.mind.prompts import imagined

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
    assert {"reward", "closeness", "comfort"} <= {n for n in ("reward", "closeness", "comfort")
                                                   if n in good.words()}
    assert "stress very high" in bad.words() and "hurt" in bad.words()


def test_she_senses_her_body_late():
    body, senses = her()
    body.levels["cortisol"] = 0.9
    assert "stress" not in feel(body, senses).words()  # not yet
    senses.follow(body, 600)
    assert "stress very high" in feel(body, senses).words()


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
    said = feel(body, senses).words([("fond", 0.8)])
    assert said.startswith("Your body: ") and "energy very low" in said and "closeness very high" in said
    assert said.endswith('It feels like what you have called "fond".')
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
    body, senses = her(adenosine=0.95)
    assert face(feel(body, senses), MILKCHAN, asleep=False)["eyes"] == "half"


def test_any_word_she_uses_becomes_a_feeling_that_comes_back_in_a_body_and_a_situation_like_its_own():
    concepts = Concepts()
    body, senses = her(cortisol=0.7, oxytocin=0.75, grievance=0.3, noradrenaline=0.6)
    concepts.add("jealous", feel(body, senses).reading, "they keep talking about another assistant", NOON)
    body, senses = her(cortisol=0.7, social=0.1, bond=0.9)
    concepts.add("homesick", feel(body, senses).reading, "they have been gone all day", NOON)
    # the same body again, in a situation like the one she named it in
    body, senses = her(seed=3, cortisol=0.68, oxytocin=0.72, grievance=0.32, noradrenaline=0.58)
    reading = feel(body, senses).reading
    assert concepts.recognize(reading, "they mention that other assistant again")[0][0] == "jealous"
    unlike = dict(concepts.recognize(reading, "the weather is nice"))["jealous"]
    assert unlike < dict(concepts.recognize(reading, "that other assistant"))["jealous"]
    body, senses = her(seed=4, cortisol=0.69, social=0.12, bond=0.88)
    assert concepts.recognize(feel(body, senses).reading)[0][0] == "homesick"
    body, senses = her(reward=0.9, oxytocin=0.9, endorphin=0.7)
    assert concepts.recognize(feel(body, senses).reading) == []  # nothing she named is like joy
    concepts.add("jealous", reading, "the other assistant", NOON + 60)
    shown = {f["word"]: f for f in concepts.shown(reading)}
    assert shown["jealous"]["count"] == 2 and shown["jealous"]["place"][0] < 0
    assert "cortisol" in dict(shown["jealous"]["channels"])
    old = Concepts([["relieved", [0.1] * 19]])  # a mind from before 0.22 keeps her words
    assert old.recognize(reading) == [] and old.shown(reading)[0]["word"] == "relieved"


def test_the_imagine_answer_reads_by_shape_with_words_first_or_without():
    new = imagined('["they leave for a while", "less", "same", "same", "chat", "errand", "lonely", '
                   '["talk", "say bye", 0.1, 0.9, 0.6]]')
    assert new["appraisal"]["company"] == -0.5 and new["appraisal"]["free"] == 0.0
    assert new["happens"] == "they leave for a while" and new["feeling"] == "lonely"
    assert new["appraisal"]["intent"] == "chat" and new["options"][0]["act"] == "talk"
    old = imagined('[0.3, 0.6, 0.5, "chat", "errand", "fine", ["talk", "ok", 0.1, 0.9, 0.6]]')
    assert old["appraisal"]["company"] == -0.4 and old["happens"] == "" and old["feeling"] == "fine"
