"""What she senses of her body (lagged and blurred, its channels in words, never numbers or a feeling's name), the
feelings she makes of it (moments she sorted with her own words, come back by the whole situation) and a face for apps."""

import json

from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Feelings, Interoception, face, feel, moved, naming
from sentientmilk_framework.mind.prompts import imagined

NOON = 1_763_294_400.0
MILKCHAN = {"arms_crossed": ["neutral", "smile", "sad", "mad", "nervous", "confused", "playful", "zoned_out"],
            "arms_down": ["neutral", "smile", "sad", "mad", "nervous", "confused"]}


def her(seed=1, insight=1.0, **levels):
    body = Body(Temperament.born({"insight": insight}, seed=seed), at=NOON)
    body.levels.update({"adenosine": 0.4 + body.shift(), **levels})  # at rest: the pressure usual for the hour
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
    assert "much more strain than usual" in feel(body, senses).words()


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
    assert said.startswith("Body: ") and "much less energy" in said and "more closeness" in said
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


def felt_as(words, way, at, text=None, episode=None, run=None, named="now"):
    """A naming of a moment, its numbers a reading of her body."""
    return naming(words, text or words, at, "tool", named, episode=episode, run=run,
                  measure={"of": "reading", "way": way} if way is not None else None)


def blow(body, **change):  # the way a message moves her body
    before = dict(body.levels)
    body.levels.update({name: before[name] + by for name, by in change.items()})
    return moved(before, body.levels)


ENVY = {"cortisol": 0.1, "oxytocin": -0.05, "grievance": 0.08, "reward": -0.15}
WARM = {"oxytocin": 0.08, "reward": 0.25, "social": 0.1}
SLIGHTED = {"company": -0.6, "capable": 0.0, "free": 0.0, "theirs": 0.2}
PRAISED = {"company": 0.5, "capable": 0.6, "free": 0.0, "theirs": 0.5}


def now(way, appraisal=None):
    return {"way": way, "appraisal": appraisal}


def test_any_word_she_uses_sorts_a_moment_and_comes_back_when_a_moment_is_like_it():
    feelings = Feelings()
    body, _ = her()
    jealous, _ = feelings.sort(felt_as("jealous", blow(body, **ENVY), NOON, episode=1), now({}), {}, None)
    body, _ = her()
    feelings.sort(felt_as("touched", blow(body, **WARM), NOON, episode=2), now({}), {}, None)
    assert jealous["standing"] == "provisional" and feelings.word(jealous) == "jealous"
    # moved the same way again, on another day and in another body (tired, lonely): the hour's body is not the feeling
    body, _ = her(seed=3, adenosine=0.8, energy=0.5, social=0.2)
    way = blow(body, cortisol=0.07, oxytocin=-0.03, grievance=0.05, reward=-0.1)
    found = feelings.recognize(now(way), {}, None)
    assert [feelings.word(f) for f, _, _ in found] == ["jealous"] and found[0][2]["episode"] == 1  # and which moment
    assert feelings.word(feelings.recognize(now(blow(body, oxytocin=0.05, reward=0.2, social=0.08)), {}, None)[0][0]) \
        == "touched"
    assert feelings.recognize(now(blow(body, novelty=0.2, dopamine=0.05)), {}, None) == []  # nothing like wonder
    assert feelings.recognize(now(moved(body.levels, body.levels)), {}, None) == []  # unmoved, nothing comes back
    assert feel(*her()).noticed() == {}  # nor at rest, when nothing stands out in her body
    # between messages nothing moves her but what stands out in her body: a lasting hurt feels like one
    body, senses = her(cortisol=0.75, grievance=0.5, reward=-0.4)
    assert feelings.word(feelings.recognize(now(feel(body, senses).noticed()), {}, None)[0][0]) == "jealous"
    feelings.came_back(jealous["id"], NOON + 120, 7)  # felt again in a moment she called nothing: counted, sorts nothing
    shown = {f["word"]: f for f in feelings.shown(now(way), {}, None)}
    assert (shown["jealous"]["count"], shown["jealous"]["back"], shown["jealous"]["back_run"]) == (1, 1, 7)
    assert shown["jealous"]["strength"] > 0.6 and shown["touched"]["strength"] == 0.0
    assert shown["jealous"]["like"]["episode"] == 1 and shown["jealous"]["standing"] == "provisional"
    assert shown["jealous"]["place"][0] < -0.3 < 0.3 < shown["touched"]["place"][0]  # unpleasant, pleasant
    assert shown["jealous"]["place"][2] < 0 < shown["touched"]["place"][2]  # apart from the user, toward them
    assert set(dict(shown["jealous"]["channels"])) == {"cortisol", "reward", "grievance"}


def test_a_word_said_once_is_provisional_and_a_second_like_moment_makes_it_hers():
    feelings = Feelings()
    episodes = {1: {"felt": ENVY, "appraisal": SLIGHTED}, 2: {"felt": ENVY, "appraisal": SLIGHTED}}
    first, _ = feelings.sort(felt_as("jealous", ENVY, NOON, episode=1), now(ENVY, SLIGHTED), episodes, None)
    again, alike = feelings.sort(felt_as("Jealous.", ENVY, NOON + 60, episode=2), now(ENVY, SLIGHTED), episodes, None)
    assert again is first and alike > 0.9 and first["standing"] == "hers"
    assert first["revisions"][-1]["did"] == "confirmed" and feelings.words(first) == ["jealous"]


def test_a_second_unlike_moment_leaves_it_provisional():
    feelings = Feelings()
    first, _ = feelings.sort(felt_as("weird", ENVY, NOON, episode=1), now(ENVY), {}, None)
    _, alike = feelings.sort(felt_as("weird", WARM, NOON + 60, episode=2), now(WARM), {}, None)
    assert alike < Feelings.FLOOR and first["standing"] == "provisional" and feelings.moments(first) == 2


def test_repeating_a_word_for_one_moment_counts_once():
    feelings = Feelings()
    first, _ = feelings.sort(felt_as("jealous", ENVY, NOON, episode=1), now(ENVY), {}, None)
    feelings.sort(felt_as("jealous", ENVY, NOON + 5, episode=1), now(ENVY), {}, None)
    assert feelings.moments(first) == 1 and first["standing"] == "provisional"  # one moment, however often said
    once = feelings.strength(first, now(ENVY), {}, None)[0]
    feelings.sort(felt_as("jealous", ENVY, NOON + 60, episode=2), now(ENVY), {}, None)
    assert feelings.strength(first, now(ENVY), {}, None)[0] > once  # a second moment: more established


def test_two_feelings_sharing_a_word_take_the_naming_most_like_their_moments():
    feelings = Feelings()
    tight, _ = feelings.sort(felt_as("tight", ENVY, NOON, episode=1), now(ENVY), {}, None)
    feelings.sort(felt_as("tight", ENVY, NOON + 1, episode=2), now(ENVY), {}, None)
    feelings.sort(felt_as("tight", WARM, NOON + 2, episode=3), now(WARM), {}, None)
    close = feelings.split(tight["id"], [tight["said"][2]], "close with someone, not jealous", NOON + 3)
    found, _ = feelings.sort(felt_as("tight", WARM, NOON + 9, episode=4), now(WARM), {}, None)
    assert found is close and feelings.moments(close) == 2 and feelings.moments(tight) == 2


def test_recognition_is_by_body_what_it_meant_and_what_it_was_about():
    feelings = Feelings()
    episodes = {1: {"felt": ENVY, "appraisal": SLIGHTED}, 2: {"felt": ENVY, "appraisal": SLIGHTED}}
    jealous, _ = feelings.sort(felt_as("jealous", ENVY, NOON, episode=1), now(ENVY, SLIGHTED), episodes, None)
    feelings.sort(felt_as("jealous", ENVY, NOON + 60, episode=2), now(ENVY, SLIGHTED), episodes, None)
    slighted = feelings.strength(jealous, now(ENVY, SLIGHTED), episodes, None)[0]
    praised = feelings.strength(jealous, now(ENVY, PRAISED), episodes, None)[0]
    assert slighted > praised  # the same body, meant otherwise: less like it
    about = feelings.strength(jealous, now(ENVY, SLIGHTED), episodes, {1: 1.0, 2: 0.9})[0]
    elsewhere = feelings.strength(jealous, now(ENVY, SLIGHTED), episodes, {1: 0.0, 2: 0.0})[0]
    assert about > elsewhere + 0.2  # about the same thing as its moments, or about something else


def test_without_meaning_likeness_is_body_and_what_it_meant():
    feelings = Feelings()
    one = felt_as("jealous", ENVY, NOON, episode=1)
    episodes = {1: {"felt": ENVY, "appraisal": SLIGHTED}}
    assert feelings.likeness(now(ENVY, SLIGHTED), one, episodes, None) == 1.0  # service down: no meaning part
    assert feelings.likeness(now(ENVY, SLIGHTED), one, episodes, {}) == 1.0  # that moment has no vector yet
    assert feelings.likeness(now({}, SLIGHTED), one, episodes, {1: 1.0}) is None  # nothing felt: nothing recognized


def test_a_naming_without_a_moment_takes_no_part_in_likeness():
    feelings = Feelings()
    lost, _ = feelings.sort(felt_as("homesick", None, NOON, named="unresolved"), now(ENVY), {}, None)
    assert feelings.moments(lost) == 0 and feelings.strength(lost, now(ENVY), {}, None) == (0.0, None)
    assert feelings.unreviewed() == [(lost, lost["said"][0])]  # still hers to go over in her sleep


def test_join_moves_namings_and_keeps_a_revision():
    feelings = Feelings()
    flat, _ = feelings.sort(felt_as("flat", ENVY, NOON, episode=1), now(ENVY), {}, None)
    worn, _ = feelings.sort(felt_as("worn flat", ENVY, NOON + 9, episode=2), now(ENVY), {}, None)
    assert feelings.join(flat["id"], worn["id"], "worn flat is how flat feels when it lasts", NOON + 99)
    assert [f["id"] for f in feelings.known] == [flat["id"]] and feelings.words(flat) == ["flat", "worn flat"]
    assert flat["standing"] == "hers" and flat["revisions"][-1] == {
        "at": NOON + 99, "did": "joined", "with": worn["id"], "words": ["worn flat"],
        "why": "worn flat is how flat feels when it lasts"}


def test_join_with_itself_or_an_unknown_feeling_does_nothing():
    feelings = Feelings()
    flat, _ = feelings.sort(felt_as("flat", ENVY, NOON, episode=1), now(ENVY), {}, None)
    assert not feelings.join(flat["id"], flat["id"], "same", NOON) and not feelings.join(flat["id"], 99, "?", NOON)
    assert feelings.known == [flat] and flat["revisions"] == []


def test_split_taking_every_moment_or_none_does_nothing():
    feelings = Feelings()
    flat, _ = feelings.sort(felt_as("flat", ENVY, NOON, episode=1), now(ENVY), {}, None)
    feelings.sort(felt_as("flat", ENVY, NOON + 1, episode=2), now(ENVY), {}, None)
    assert feelings.split(flat["id"], list(flat["said"]), "all", NOON) is None
    assert feelings.split(flat["id"], [felt_as("flat", ENVY, NOON)], "not one of its", NOON) is None
    assert len(feelings.known) == 1 and len(flat["said"]) == 2


def test_set_aside_keeps_the_saying_and_removes_an_empty_feeling():
    feelings = Feelings()
    ugly, _ = feelings.sort(felt_as("the ugly part", ENVY, NOON, text="The ugly part is I can't tell you which move."),
                            now(ENVY), {}, None)
    gone = feelings.set_aside(ugly["said"][0], "that sized up the game, it wasn't how I felt", NOON + 5)
    assert gone == ugly["id"] and feelings.known == []
    assert feelings.aside[0]["text"] == "The ugly part is I can't tell you which move." and \
        feelings.aside[0]["why"] == "that sized up the game, it wasn't how I felt" and feelings.aside[0]["feeling"] == gone


def test_saved_round_trips():
    feelings = Feelings()
    flat, _ = feelings.sort(felt_as("flat", ENVY, NOON, episode=1), now(ENVY), {}, None)
    feelings.sort(felt_as("noise", WARM, NOON + 1, episode=2), now(WARM), {}, None)
    feelings.set_aside(feelings.known[1]["said"][0], "not a feeling", NOON + 2)
    feelings.came_back(flat["id"], NOON + 3, 4)
    again = Feelings(json.loads(json.dumps(feelings.saved())))
    assert again.saved() == feelings.saved() and again.next == 3


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


def test_sleep_pressure_is_felt_against_her_clock_and_what_she_owes():
    """The same adenosine is felt as more sleep pressure in her night than in her afternoon, and more with sleep
    owed: what she senses is how near sleep it puts her (both processes, as sleepiness is reported), not the
    amount; spent energy stays its own channel."""
    def sensed(hour, debt=0.0, energy=1.0):
        body = Body(Temperament.born({}, seed=1), at=NOON + (hour - 12) * 3600)
        body.levels.update(adenosine=0.45, energy=energy)
        body.debt = debt
        senses = Interoception(body, 1)
        for _ in range(40):
            senses.follow(body, 90)
        return dict(feel(body, senses).standing_out(20, 0.0, usual=True)), body

    afternoon, day = sensed(15)
    night, late = sensed(3)
    owing, _ = sensed(15, debt=8.0)
    assert night["adenosine"] - afternoon["adenosine"] > 0.5 and late.sleepiness() > day.sleepiness()
    assert owing["adenosine"] > afternoon["adenosine"]
    spent, _ = sensed(15, energy=0.4)
    assert abs(spent["adenosine"] - afternoon["adenosine"]) < 0.05 and spent["energy"] < -1.0
