"""Memory that feels: a moment keeps how it moved her and what was around it; what comes back is called
by meaning, by what is around her now (a rare surrounding most) and by her mood; what just came back is held off;
a vivid memory comes back with its surroundings, a faint one without."""

import math
import time

from conftest import Meaning

from sentientmilk_framework.mind.memory import Memory, cue, intensity, line, moment_cues

DAY = 86400.0
NOW = 1_763_294_400.0
SONG = cue("playing", "Clair de Lune — Debussy")


def memory(tmp_path, embedder=None):
    mind = Memory(tmp_path / "mind.sqlite3", seed=0)
    mind.embedder = embedder
    return mind


def embedded(mind, embedder):
    mind.embedder = embedder
    found = mind.vectors.texts(mind.vectors.pending(embedder.name, 1000))
    mind.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))], embedder.name)
    return mind


def filler(mind, count, cues=(), at=NOW - 3 * DAY):
    for n in range(count):
        mind.add("exchange", f"An ordinary moment number {n} about invoices", 0.0, 0.3, 0.3, at=at + n, cues=cues)


def test_a_moment_keeps_how_it_moved_her_and_what_was_around_it(tmp_path):
    mind = memory(tmp_path)
    felt = {"cortisol": 1.2, "reward": -0.8}
    episode = mind.add("exchange", "They said the song was ours", -0.2, 0.6, 0.6, at=NOW - DAY, felt=felt,
                       cues=[SONG, cue("time", "late at night"), cue("time", "late at night")])
    row = mind.by_ids([episode])[0]
    assert mind.felt(row) == felt
    assert sorted(mind.cues([episode])[episode]) == sorted([SONG, "time: late at night"])
    assert SONG == "playing: clair de lune — debussy"
    assert math.isclose(intensity(felt), math.hypot(1.2, 0.8))
    assert mind.felt(mind.by_ids([mind.add("thought", "old style", 0.0, 0.2, 0.2, at=NOW)])[0]) == {}


def test_a_surrounding_is_as_strong_as_it_is_rare_among_her_memories(tmp_path):
    mind = memory(tmp_path)
    filler(mind, 9, cues=["user: plays"])
    mind.add("exchange", "They said the song was ours", 0.4, 0.6, 0.6, at=NOW - DAY, cues=["user: plays", SONG])
    strength = mind.cue_strength(["user: plays", SONG, "playing: never heard"])
    assert strength["user: plays"] == 0.0 and strength[SONG] == 1.0
    assert strength["playing: never heard"] == 1.0  # in none of them: rare as can be (it calls nothing up)


def test_what_a_moment_keeps_of_its_time_where_and_who(tmp_path):
    late = time.mktime((2026, 11, 17, 2, 30, 0, 0, 0, -1))
    assert moment_cues(late, app="milkchan", device="phone", actor="plays") == [
        "time: late at night", "app: milkchan", "device: phone", "with: plays"]
    assert moment_cues(time.mktime((2026, 11, 17, 18, 0, 0, 0, 0, -1)))[0] == "time: evening"
def test_a_rare_surrounding_brings_back_a_moment_unlike_in_meaning(tmp_path):
    """No embedder (the service is down): what is around her still calls her memories up."""
    mind = memory(tmp_path)
    filler(mind, 20, cues=["user: plays", "time: evening"])
    night = mind.add("exchange", "We stayed up and they told me about their grandmother", 0.5, 0.6, 0.6,
                     at=NOW - 10 * DAY, cues=["user: plays", SONG], felt={"oxytocin": 1.0})
    found = mind.recall("how do I file my taxes", 0.0, NOW, cues=["user: plays", "time: evening", SONG])
    assert [e["id"] for e in found] == [night]
    assert found[0]["through"] == SONG and found[0]["cued"] >= 0.9


def test_a_common_surrounding_brings_back_nothing_by_itself(tmp_path):
    mind = memory(tmp_path)
    filler(mind, 20, cues=["user: plays", "time: evening"])
    assert mind.recall("anything", 0.0, NOW, cues=["user: plays", "time: evening"]) == []


def test_a_memory_that_just_came_back_is_held_off_for_a_while(tmp_path):
    mind = memory(tmp_path)
    first = mind.add("exchange", "Our cat died last spring", -0.6, 0.5, 0.5, at=NOW - 5 * DAY)
    second = mind.add("exchange", "Our dog died last spring", -0.6, 0.5, 0.5, at=NOW - 5 * DAY)
    embedded(mind, Meaning())
    came = mind.recall("my pet died", -0.5, NOW, count=1)[0]["id"]
    later = [mind.recall("my pet died", -0.5, NOW + 60, count=1, strengthen=False)[0]["id"] for _ in range(5)]
    assert came in (first, second) and all(other != came for other in later)
    assert mind.recall("my pet died", -0.5, NOW + 3 * DAY, count=2, strengthen=False)


def test_of_two_moments_called_up_alike_the_more_intense_comes_sooner(tmp_path):
    mind = memory(tmp_path)
    for n in range(20):  # other songs played in other moments: this one is rare among them
        mind.add("exchange", f"An ordinary moment number {n}", 0.0, 0.3, 0.3, at=NOW - 3 * DAY + n,
                 cues=[f"playing: another song {n}"])
    calm = mind.add("exchange", "We listened to it once", 0.1, 0.3, 0.4, at=NOW - DAY, cues=[SONG],
                    felt={"reward": 0.1})
    moving = mind.add("exchange", "We listened to it the night they cried", 0.1, 0.3, 0.4, at=NOW - DAY, cues=[SONG],
                      felt={"reward": 1.5, "oxytocin": 1.2})
    found = [mind.recall("", 0.0, NOW, count=1, cues=[SONG], strengthen=False)[0]["id"] for _ in range(10)]
    assert found.count(moving) >= 8 and calm != moving


def test_a_vivid_memory_comes_back_with_what_was_around_it_and_a_faint_one_without(tmp_path):
    mind = memory(tmp_path)
    filler(mind, 20, cues=["user: plays"])
    episode = mind.add("exchange", "They said the song was ours", 0.4, 0.6, 0.6, at=NOW - DAY,
                       cues=["user: plays", SONG])
    vivid = mind.recall("", 0.0, NOW, cues=[SONG], strengthen=False)[0]
    assert "playing: clair de lune — debussy" in line(vivid, NOW) and "user: plays" not in line(vivid, NOW)
    assert "What brings it back: playing: clair de lune — debussy." in line(vivid, NOW)
    faint = mind.recall("", 0.0, NOW + 200 * DAY, cues=[SONG], strengthen=False)[0]
    assert faint["id"] == episode and "; playing" not in line(faint, NOW + 200 * DAY)


def test_sleep_softens_an_unpleasant_moment_more_than_a_pleasant_one(tmp_path):
    """The fading affect bias (Walker, Skowronski & Thompson 2003): what hurt fades faster than what pleased."""
    mind = memory(tmp_path)
    hurt = mind.add("exchange", "They said my drawing was dumb", -0.5, 0.6, 0.6, at=NOW, sting=-0.4)
    glad = mind.add("exchange", "They loved my drawing", 0.6, 0.6, 0.6, at=NOW, sting=0.4)
    mind.soften([hurt, glad], 0.35)
    charge = {e["id"]: e["charge"] for e in mind.by_ids([hurt, glad])}
    assert math.isclose(charge[hurt], 1 - 0.35 * 1.4) and math.isclose(charge[glad], 1 - 0.35 * 0.6)


def test_a_night_s_moving_moment_strengthens_the_faint_memories_like_it(tmp_path):
    """Emotional learning reaches back to related memories kept weakly before (Dunsmoor et al. 2015)."""
    mind = memory(tmp_path)
    related = mind.add("exchange", "They mentioned their cat once, in passing", 0.0, 0.2, 0.1, at=NOW - 60 * DAY)
    unrelated = mind.add("exchange", "We went over the tax deadline", 0.0, 0.2, 0.1, at=NOW - 60 * DAY)
    flat = mind.add("exchange", "They said their dog likes walks", 0.0, 0.2, 0.2, at=NOW - 3600, felt={"reward": 0.1})
    moving = mind.add("exchange", "Their cat died tonight and they cried", -0.6, 0.8, 0.8, at=NOW - 3600,
                      felt={"cortisol": 1.6, "oxytocin": 1.2, "reward": -1.0})
    embedded(mind, Meaning())
    before = {e["id"]: mind.strength_now(e, NOW) for e in mind.by_ids([related, unrelated])}
    assert mind.tag_related(mind.related([flat, moving]), NOW) == 1
    after = {e["id"]: mind.strength_now(e, NOW) for e in mind.by_ids([related, unrelated])}
    assert after[related] > before[related] + 0.05 and math.isclose(after[unrelated], before[unrelated])


def test_a_surrounding_is_rare_only_among_the_moments_that_could_have_kept_its_kind(tmp_path):
    """Her moments from before kept who she was with only lately (10 of 217 in her real memory): "with: plays"
    in all 10 of them is as common as can be, not rare among 217."""
    mind = memory(tmp_path)
    filler(mind, 30, cues=["time: evening"])
    for n in range(5):
        mind.add("exchange", f"Lately {n}", 0.0, 0.3, 0.3, at=NOW - n, cues=["time: evening", "with: plays"])
    strength = mind.cue_strength(["with: plays", "time: evening"])
    assert strength["with: plays"] == 0.0 and strength["time: evening"] == 0.0
    assert mind.recall("", 0.0, NOW, cues=["with: plays", "time: evening"]) == []


def test_the_time_of_day_describes_a_moment_but_calls_nothing_up(tmp_path):
    """Every day has a morning: a time of day is never rare in a life, however few mornings she kept (three of
    217 in her real memory, which made "morning" look as rare as a song heard once)."""
    mind = memory(tmp_path)
    filler(mind, 30, cues=["time: evening"])
    morning = mind.add("exchange", "We talked over breakfast", 0.3, 0.4, 0.5, at=NOW - DAY,
                       cues=["time: morning", SONG])
    assert mind.recall("", 0.0, NOW, cues=["time: morning"]) == []
    came = mind.recall("", 0.0, NOW, cues=[SONG], strengthen=False)[0]
    assert came["id"] == morning and "time: morning" in line(came, NOW)
