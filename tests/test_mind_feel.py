"""What she senses of her body (lagged and blurred, its channels in words, never numbers or a feeling's name), the
feelings she makes of it (the feeling words she said of herself, by body and situation) and a face for apps."""

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Concepts, Interoception, face, feel, moved
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
    assert all(word in good.words() for word in ("reward", "closeness", "comfort"))
    assert "more strain" in bad.words() and "soreness" in bad.words()


def test_she_senses_her_body_late():
    body, senses = her()
    body.levels["cortisol"] = 0.9
    assert "strain" not in feel(body, senses).words()  # not yet
    senses.follow(body, 600)
    assert "much more strain than you're used to" in feel(body, senses).words()


def test_she_notices_what_changes_and_gets_used_to_what_lasts():
    body, senses = her()
    body.levels["oxytocin"] = 0.9  # a warm chat
    senses.follow(body, 300)
    assert "much more closeness" in feel(body, senses).words()
    for _ in range(12):  # two hours of it
        senses.follow(body, 600)
    still = feel(body, senses)
    assert "more closeness" in still.words() and "much more closeness" not in still.words()  # there, no longer news
    assert dict(still.standing_out(20, 0.0, usual=True))["oxytocin"] > 1.5  # her body is as it was
    body.levels["oxytocin"] = 0.4  # back where it usually sits: after so much of it, that is felt as less
    senses.follow(body, 300)
    assert "less closeness" in feel(body, senses).words()
    body.levels["energy"] = 0.3  # what her body needs keeps calling, however long it lasts
    for _ in range(12):
        senses.follow(body, 600)
    assert "much less energy" in feel(body, senses).words()


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
    assert said.startswith("Your body: ") and "much less energy" in said and "more closeness" in said
    assert "called" not in said and "fond" not in said  # her body, never a feeling's name
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


def test_any_word_she_uses_becomes_a_feeling_that_comes_back_when_she_is_moved_that_way_again():
    concepts = Concepts()

    def blow(body, **change):  # the way a message moves her body
        before = dict(body.levels)
        body.levels.update({name: before[name] + by for name, by in change.items()})
        return moved(before, body.levels)
    body, _ = her()
    concepts.add("jealous", blow(body, cortisol=0.1, oxytocin=-0.05, grievance=0.08, reward=-0.15),
                 "they keep talking about another assistant", NOON)
    body, _ = her()
    concepts.add("touched", blow(body, oxytocin=0.08, reward=0.25, social=0.1), "they say they missed me", NOON)
    # moved the same way again, on another day and in another body (tired, lonely): the hour's body is not the feeling
    body, _ = her(seed=3, adenosine=0.8, energy=0.5, social=0.2)
    way = blow(body, cortisol=0.07, oxytocin=-0.03, grievance=0.05, reward=-0.1)
    assert [word for word, _ in concepts.recognize(way, "they mention that other assistant again")] == ["jealous"]
    unlike = dict(concepts.recognize(way, "the weather is nice")).get("jealous", 0.0)  # once said: less ready
    assert unlike < dict(concepts.recognize(way, "that other assistant"))["jealous"]
    assert concepts.recognize(blow(body, oxytocin=0.05, reward=0.2, social=0.08))[0][0] == "touched"
    assert concepts.recognize(blow(body, novelty=0.2, dopamine=0.05)) == []  # nothing she named is like wonder
    assert concepts.recognize(moved(body.levels, body.levels)) == []  # and unmoved, nothing comes back
    assert feel(*her()).noticed() == {}  # nor at rest, when nothing stands out in her body
    # between messages nothing moves her but what stands out in her body: a lasting hurt feels like one
    body, senses = her(cortisol=0.75, grievance=0.5, reward=-0.4)
    assert concepts.recognize(feel(body, senses).noticed())[0][0] == "jealous"
    concepts.add("jealous", way, "the other assistant", NOON + 60)
    before = dict(concepts.named[0]["moved"])
    concepts.came_back("jealous", NOON + 120)  # felt again in a moment she called something else: counted, not reshaped
    assert concepts.named[0]["moved"] == before
    shown = {f["word"]: f for f in concepts.shown(way)}
    assert (shown["jealous"]["count"], shown["jealous"]["back"]) == (2, 1)
    assert shown["jealous"]["strength"] > 0.8 and shown["touched"]["strength"] == 0.0
    assert shown["jealous"]["place"][0] < -0.3 < 0.3 < shown["touched"]["place"][0]  # unpleasant, pleasant
    assert shown["jealous"]["place"][2] < 0 < shown["touched"]["place"][2]  # apart from the user, toward them
    # drawn by what it moves, not by the tired and lonely body she felt it in the second time
    assert set(dict(shown["jealous"]["channels"])) == {"cortisol", "reward", "grievance"}


def test_the_imagine_answer_reads_by_shape_with_words_first_or_without():
    new = imagined('["they leave for a while", "less", "same", "same", "chat", "errand", "lonely", '
                   '["talk", "say bye", 0.1, 0.9, 0.6]]')
    assert new["appraisal"]["company"] == -0.5 and new["appraisal"]["free"] == 0.0
    assert new["happens"] == "they leave for a while" and "feeling" not in new  # nothing names her feelings
    assert new["appraisal"]["intent"] == "chat" and new["options"][0]["act"] == "talk"
    assert new["appraisal"]["theirs"] == 0.0  # nothing said of how things are for them
    bare = imagined('[0.3, 0.6, 0.5, "chat", "errand", ["talk", "ok", 0.1, 0.9, 0.6]]')  # parts left out
    assert bare["appraisal"]["company"] == -0.4 and bare["happens"] == "" and bare["options"][0]["act"] == "talk"
    assert bare["appraisal"]["theirs"] == 0.0 and bare["appraisal"]["intent"] == "chat"
    theirs = imagined('["they failed an exam", "more", "same", "same", "bad", "chat", "school", "fine"]')
    assert theirs["appraisal"]["theirs"] == -0.5 and theirs["appraisal"]["intent"] == "chat"
    assert theirs["appraisal"]["tags"] == ["school"]
