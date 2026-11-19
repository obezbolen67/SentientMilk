"""Credit for one outcome among the cues of one moment: one prediction error for the whole moment, shared by
how much each cue is attended to, so that what they predict together moves toward what came and never past it
(the fault: two new cues each took the whole surprise, and together foresaw twice what came)."""

from test_reactions import DELETED, NOW, around, felt, meaning, store

from sentientmilk_framework.mind.reactions import REACTS


def joint(reactions, *texts, at=NOW + 100):
    """What these cues foresee together, as one moment with all of them would call them up."""
    total = dict.fromkeys(REACTS, 0.0)
    for text in texts:
        for name, value in felt(reactions, text, at).items():
            total[name] += value
    return total


def rows(reactions):
    return {row["text"]: row for row in reactions.strongest(50, NOW + 100)}


def test_one_cue_learns_its_outcome_and_a_weak_one_stays_weak(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(around("in front: outlook — inbox"), {"cortisol": 1.0}, 1.0, NOW)
    reactions.learn(around("playing: rain sounds", salience=0.3), {"cortisol": 1.0}, 1.0, NOW + 1)
    learned = rows(reactions)
    assert abs(learned["in front: outlook — inbox"]["response"]["cortisol"] - 1.0) < 1e-6
    # alone, weak evidence is not made strong by sharing: it keeps its share of the surprise
    assert abs(learned["playing: rain sounds"]["response"]["cortisol"] - 0.3) < 1e-6


def test_two_equally_new_cues_share_one_surprise(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(around("in front: outlook — inbox", "playing: rain sounds"), {"cortisol": 1.0}, 1.0, NOW)
    learned = rows(reactions)
    assert [round(learned[text]["response"]["cortisol"], 4)
            for text in ("in front: outlook — inbox", "playing: rain sounds")] == [0.5, 0.5]  # was 1.0 and 1.0


def test_cues_share_by_how_salient_each_is(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(around("in front: outlook — inbox") + around("playing: rain sounds", salience=0.25),
                    {"cortisol": 1.0}, 1.0, NOW)
    learned = rows(reactions)
    assert abs(learned["in front: outlook — inbox"]["response"]["cortisol"] - 0.8) < 1e-4
    assert abs(learned["playing: rain sounds"]["response"]["cortisol"] - 0.2) < 1e-4


def test_repeated_moments_with_both_settle_on_what_comes(tmp_path):
    reactions = store(tmp_path)
    both = around("in front: outlook — inbox", "playing: rain sounds")
    seen = []
    for n in range(6):
        reactions.learn(both, {"cortisol": 1.0}, 1.0, NOW + n)
        learned = rows(reactions)
        seen.append(sum(learned[text]["response"].get("cortisol", 0.0) * (1 - learned[text]["hold"])
                        for text in ("in front: outlook — inbox", "playing: rain sounds")))
    assert all(abs(total - 1.0) < 1e-3 for total in seen), seen  # never past it, no swinging


def test_a_kept_cue_and_a_new_one_share_and_together_reach_what_came(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED), {"cortisol": 0.4}, 0.25, NOW)  # learned a little, calmly
    kept = rows(reactions)[DELETED]["response"]["cortisol"]
    reactions.learn(meaning(reactions, DELETED) + around("in front: code — main.py"), {"cortisol": 1.0}, 1.0, NOW + 10)
    learned = rows(reactions)
    together = learned[DELETED]["response"]["cortisol"] + learned["in front: code — main.py"]["response"]["cortisol"]
    assert learned[DELETED]["response"]["cortisol"] > kept  # the kept one learned too
    assert together <= 1.0 + 1e-6 and together > 0.9  # was over 1.7: each took the whole surprise


def test_a_redundant_newcomer_is_blocked_and_two_trained_cues_summate(tmp_path):
    reactions = store(tmp_path)
    for n in range(6):  # each foretells it alone
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 1.0, NOW + n)
        reactions.learn(around("in front: outlook — inbox"), {"cortisol": 1.0}, 1.0, NOW + n)
    reactions.learn(meaning(reactions, DELETED) + around("playing: rain sounds"), {"cortisol": 1.0}, 1.0, NOW + 20)
    assert "playing: rain sounds" not in rows(reactions)  # it added nothing: blocked
    together = joint(reactions, DELETED) ["cortisol"] + rows(reactions)["in front: outlook — inbox"]["response"]["cortisol"]
    assert together > 1.9  # first met together, both are foreseen: what each learned alone adds up


def test_the_same_cue_twice_in_one_moment_is_one_cue(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, DELETED, DELETED), {"cortisol": 1.0}, 1.0, NOW)
    assert len(reactions.strongest(10, NOW)) == 1 and abs(felt(reactions, DELETED)["cortisol"] - 1.0) < 1e-3


def test_a_thing_said_twice_in_other_words_in_one_moment_is_one_cue(tmp_path):
    reactions = store(tmp_path)
    reactions.learn(meaning(reactions, "deleting the thesis file", "deleted the thesis file"), {"cortisol": 1.0},
                    1.0, NOW)
    assert len(reactions.strongest(10, NOW)) == 1  # was two, each with the whole surprise
    assert abs(felt(reactions, "deleting the thesis file")["cortisol"] - 1.0) < 1e-3


def test_one_outcome_delivered_twice_teaches_once_and_a_new_one_still_counts(tmp_path):
    reactions = store(tmp_path)
    cues = around("in front: outlook — inbox")
    reactions.learn(cues, {"cortisol": 0.6}, 0.5, NOW, episode=7)
    first = rows(reactions)["in front: outlook — inbox"]
    assert reactions.learn(cues, {"cortisol": 0.6}, 0.5, NOW + 1, episode=7) == []  # the same moment again
    assert rows(reactions)["in front: outlook — inbox"]["response"] == first["response"]
    reactions.learn(cues, {"cortisol": 0.6}, 0.5, NOW + 2, episode=8)  # another moment like it
    again = rows(reactions)["in front: outlook — inbox"]
    assert again["response"]["cortisol"] > first["response"]["cortisol"] and again["trials"] == 2


def test_a_failed_expectation_weakens_its_cue_and_teaches_what_came_with_it_nothing(tmp_path):
    reactions = store(tmp_path)
    for n in range(4):
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 1.0, NOW + n)
    reactions.learn(meaning(reactions, DELETED) + around("playing: rain sounds"), {}, 1.0, NOW + 10,
                    around=["playing: rain sounds"])
    learned = rows(reactions)
    assert learned[DELETED]["hold"] > 0.2  # she is getting over it, there
    # nothing came: the sound that was on learns no opposite of what failed to come (was -0.5 cortisol)
    assert "playing: rain sounds" not in learned


def test_a_cue_followed_by_something_else_comes_to_foresee_that(tmp_path):
    reactions = store(tmp_path)
    for n in range(4):
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 1.0, NOW + n)
    for n in range(6):  # now it is followed by relief, again and again
        reactions.learn(meaning(reactions, DELETED), {"endorphin": 1.0}, 1.0, NOW + 10 + n)
    now = felt(reactions, DELETED, NOW + 20)
    assert now["endorphin"] > 0.5 and now["cortisol"] < 0.5


def test_an_outcome_that_changes_for_good_is_followed_without_growing_past_it(tmp_path):
    reactions = store(tmp_path)
    for n in range(4):
        reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 1.0, NOW + n)
    seen = []
    for n in range(40):
        reactions.learn(meaning(reactions, DELETED), {"endorphin": 1.0}, 0.6, NOW + 10 + n)
        row = rows(reactions)[DELETED]
        seen.append((row["response"].get("cortisol", 0.0), row["response"].get("endorphin", 0.0), row["hold"]))
    assert all(abs(cortisol) <= 1.0 + 1e-6 and 0 <= endorphin <= 1.2 for cortisol, endorphin, _ in seen), seen
    now = felt(reactions, DELETED, NOW + 60)
    assert abs(now["endorphin"] - 1.0) < 0.1 and abs(now["cortisol"]) < 0.1


def test_a_moment_delivered_again_after_a_restart_still_teaches_once(tmp_path):
    import threading

    from sentientmilk_framework.mind.memory import Memory
    from sentientmilk_framework.mind.reactions import Reactions
    reactions = store(tmp_path)
    reactions.learn(around("in front: outlook — inbox"), {"cortisol": 0.6}, 0.5, NOW, episode=7)
    again = Reactions(Memory(tmp_path / "mind.sqlite3", seed=0)._db, threading.RLock())
    assert again.learn(around("in front: outlook — inbox"), {"cortisol": 0.6}, 0.5, NOW + 1, episode=7) == []
    reactions.withdraw([7])  # the moment taken back: what it taught goes, and it may teach as new
    assert again.learn(around("in front: outlook — inbox"), {"cortisol": 0.6}, 0.5, NOW + 2, episode=7)


def test_a_foresight_her_body_could_not_show_is_not_got_over_by_not_showing(tmp_path):
    """At a bound a level moves no further, whatever comes: a foresight toward it that did not show is not known not
    to have come (a missing measurement), as far as it could not show; where it could, it is getting over it."""
    pinned, free = store(tmp_path / "a"), store(tmp_path / "b")
    for reactions in (pinned, free):
        for n in range(4):
            reactions.learn(meaning(reactions, DELETED), {"cortisol": 1.0}, 1.0, NOW + n)
    pinned.learn(meaning(pinned, DELETED), {}, 1.0, NOW + 10, shown={"cortisol": {1: 0.0, -1: 1.0}})
    free.learn(meaning(free, DELETED), {}, 1.0, NOW + 10, shown={"cortisol": {1: 1.0, -1: 1.0}})
    assert rows(pinned)[DELETED]["hold"] == 0 and rows(pinned)[DELETED]["extinctions"] == 0
    assert rows(free)[DELETED]["hold"] > 0.2 and rows(free)[DELETED]["extinctions"] == 1
    # what came beyond is seen however pinned the other side was: the outcome below shows
    pinned.learn(meaning(pinned, DELETED), {"cortisol": -0.5}, 1.0, NOW + 20, shown={"cortisol": {1: 0.0, -1: 1.0}})
    assert rows(pinned)[DELETED]["response"]["cortisol"] < 1.0
