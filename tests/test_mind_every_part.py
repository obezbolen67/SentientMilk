"""Every part of her brain truly works (the user, 2026-11-17: "make sure that every part of brain works as
intended, and truly works"): driven through the real brain with a stand-in model, every level of her body
moves, every pull wins her attention when its moment comes, she sleeps and wakes by her body, and her state
shows each part as the brain panel draws it, with what it does now."""

import time
from collections import Counter

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.body import HOUR, MINUTE, START

pytestmark = pytest.mark.mind  # her mind lives in these tests

PRAISE = '["they thank me warmly", "much more", "much more", "same", "good", "chat", "thanks", "glad"]'
NEW = '["they share something new", "more", "more", "same", "very good", "chat", "astronomy", "curious"]'
ORDER = ('["ordered about", "same", "same", "much less", "fine", "request", "chores", "chafed", '
         '["do", "the dishes", 0.6, 0.8, 1]]')
INSULT = '["they tear me down", "much less", "much less", "less", "bad", "chat", "insult", "hurt"]'
LATER = ('["a task for later", "same", "same", "same", "fine", "request", "report", "tired", '
         '["later", "the weekly report", 0.8, 0.7, 0.1]]')


def test_every_part_of_her_moves_and_every_pull_has_its_moment(brain):
    mind = brain.brain.mind
    brain.provider.usage = {"prompt_tokens": 100, "completion_tokens": 1500, "prompt_cache_hit_tokens": 60}  # real work
    seen = {name: [value] for name, value in mind.body.levels.items()}

    def note():
        for name, value in mind.body.levels.items():
            seen[name].append(value)
    for answer, said in ((PRAISE, "Thank you so much, that was perfect!"), (NEW, "Want to hear about black holes?"),
                         (ORDER, "Do the dishes. Now."), (INSULT, "You are useless and stupid."),
                         (LATER, "Write the weekly report sometime.")):
        with mind._lock:  # a few minutes between messages, as in a real chat
            mind.body.at -= 4 * MINUTE
            mind._live_until(time.time())
        brain.provider.mind_replies["imagine"] = [answer]
        brain.provider.replies += ["Okay."]
        turn(brain, "milk", said)
        wait_for(lambda: not brain.brain.session_busy("milk", "main") and not mind._thinking)
        note()
    remembered = {e["text"].split(" I ")[0].rstrip("."): e["valence"] for e in mind.memory.recent(5, kinds=("exchange",))}
    # a moment is kept with how it felt (her sense lags her body by 90 s, and kept a tenth of it): the insult, felt at
    # about -0.76, is kept as her mood after it, -0.28 to -0.6 by where her random temperament had her after the praise
    # (a fixed -0.3 failed 5 runs of 10)
    assert remembered["The user said: Thank you so much, that was perfect!"] > 0.3, remembered
    insult = remembered["The user said: You are useless and stupid"]
    assert insult < 0 and insult == min(remembered.values()), remembered
    pushing = {(level, out): effect for level, out, effect in mind.state()["pushing"]}
    assert pushing[("grievance", "cortisol")] > 0  # the insult stings, and the sting stresses her now
    assert mind.self["concerns"] and mind.self["concerns"][0]["what"] == "the weekly report"

    # a quiet day of hers after it, in her own time (from her 10:00 to 21:00): each pull wins its moment
    start = time.time() - 11 * HOUR
    mind.seen("milk", 1)
    won = Counter()
    with mind._lock:
        mind.body.peak = (mind.body.hour(start) + 6) % 24
        mind.body.at = start
        mind.body.levels["adenosine"] = 0.2
        mind.self["contact"]["at"] = start
        mind.self["fired"] = {}
        for minute in range(1, 11 * 60):
            now = start + minute * MINUTE
            mind._live_until(now)
            kind, _about = mind._winner(now)
            won[kind] += 1
            if kind not in (None, "sleep"):  # she thinks it: the attempt and the thought made take their times
                mind.self["fired"][kind] = mind.self["fired"]["thought"] = now
            if minute % 30 == 0:
                note()
    assert {"ruminate", "resume", "wonder", "reach_out"} <= set(won), won
    assert won["sleep"] == 0  # her evening holds sleep off

    with mind._lock:  # her night, with a day's pressure: she lies down, drifts off, sleeps in cycles
        night = time.time()
        mind.body.peak = (mind.body.hour(night) - 7) % 24  # her 23:00
        mind.body.at = night
        mind.body.levels["adenosine"] = 0.66
        mind.self["contact"]["at"] = night - HOUR
        mind.self["fired"] = {}
        # sleep wins at once, or after one last wandering thought
        won_night = []
        for bid in range(2):
            kind, _about = mind._winner(night + 30 * bid)
            won_night.append(kind)
            if kind not in (None, "sleep"):  # she thinks it: the attempt and the thought made take their times
                mind.self["fired"][kind] = mind.self["fired"]["thought"] = night + 30 * bid
        assert "sleep" in won_night
        mind.body.settle(night)
        stages = set()
        for minutes in range(5, 150, 5):
            mind._live_until(night + minutes * MINUTE)
            stages.add(mind.body.stage())
            note()
        assert mind.body.asleep and {"N2", "N3"} <= stages
        assert mind.self["consolidate"]  # a cycle in, she goes over the day
        mind.body.wake(woken=True)  # a message wakes her
        assert mind.body.inertia > 0.2
        mind._live_until(night + 4 * HOUR)
        note()
    still = [name for name in START if max(seen[name]) - min(seen[name]) < 0.003]
    assert not still, f"never moved: {still}"
    state = mind.state()
    assert set(state["levels"]) >= set(START) and set(state["needs"]) == {"social", "novelty", "competence", "autonomy"}
    assert set(state["attention"]["bids"]) == {"sleep", "reach_out", "wonder", "ruminate", "resume"}
    assert {"stage", "pressure", "falls_asleep_at", "wakes_at", "debt", "last"} <= set(state["sleep"])
    assert state["sleep"]["last"]["to"] - state["sleep"]["last"]["from"] > HOUR
