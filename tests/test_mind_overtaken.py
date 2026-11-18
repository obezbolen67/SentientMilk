"""In her sleep she goes over what she had in mind against what happened since (0.43; the audit of 2026-11-18,
findings 3 and 9).

Her guess that the user buys 2% milk came back twice and the user's "it's 3.2%" never; a thought of hers had an
essay skeleton still in its folder hours after she deleted it as asked; a question about a dead watcher came back
a day after the user said to forget it. A correction set a memory right only when it quoted it in the same chat.
And every insight of a night carried the same twelve moments, whatever it came from; a nap at 14:06 made nothing
of thirteen moments and said nothing."""

import json
import logging
import time

import pytest
from conftest import Meaning, use

pytestmark = pytest.mark.mind  # her mind lives in these tests

OTHER = ["We talked about taxes and the deadline in April", "The user showed me a platformer level they built",
         "Their cat knocked a glass off the desk", "They asked how to keep basil alive on a windowsill",
         "We planned a walk to the river on Sunday", "They said the new keyboard clicks too loudly",
         "I read about how bread rises overnight", "They were annoyed that the train was late again",
         "We argued about which film to watch tonight", "They fixed the wobbly chair with a folded card"]


def asked(brain, kind):
    return next(r for r in reversed(brain.provider.mind_requests)
                if r["messages"][0]["content"].startswith(f"[mind:{kind}]"))["messages"][1]["content"]


def numbered(listing: str, text: str) -> int:
    """The number a moment has in what her sleep was shown."""
    return next(int(row.split(".")[0]) for row in listing.splitlines() if text in row and row.split(".")[0].isdigit())


def test_sleep_sets_right_what_the_day_overtook_and_lets_go_of_what_was_settled(brain):
    mind = brain.brain.mind
    use(brain, Meaning())
    now = time.time()
    for index, text in enumerate(OTHER):
        mind.memory.add("exchange", text, 0.0, 0.3, 0.3, at=now - 5 * 86400 + index)
    old = mind.memory.add("exchange", "They said the interpreter job starts in May", 0.1, 0.3, 0.5,
                          at=now - 2 * 86400, app="cli", session="main")
    new = mind.memory.add("exchange", "They said: the interpreter job starts in June, not May", 0.2, 0.4, 0.6,
                          at=now - 3600, app="cli", session="main")
    brain.brain.recall.sweep()
    with mind._lock:
        mind.self["slept"] = now - 2 * 3600
        mind.self["concerns"] = [{"what": "get the May interpreter job notes ready", "app": "cli", "session": "main",
                                  "at": now - 2 * 86400 + 10, "run": None}]
    brain.provider.mind_replies["updates"] = [json.dumps({"outdated": [{"old": "O1", "by": "T1"}], "settled": ["P1"]})]
    mind._consolidate()
    shown = asked(brain, "updates")
    assert "T1 (" in shown and "June, not May" in shown.split("T1 (")[1].split("\n")[0]
    assert "O1 (" in shown and "starts in May" in shown.split("O1 (")[1].split("\n")[0]
    assert "P1 (" in shown and "May interpreter job notes" in shown
    assert mind.memory.by_ids([old])[0]["superseded_by"] == new  # set right, across a night, with no quote
    assert mind.self["concerns"] == []  # settled: nothing left to nag her
    back = mind.memory.recall("when does the interpreter job start", 0.0, time.time(), count=4, strengthen=False)
    assert old not in [e["id"] for e in back] and "starts in May" in next(e for e in back if e["id"] == new)["was"]


def test_nothing_alike_from_before_and_nothing_put_off_asks_nothing(brain):
    mind = brain.brain.mind
    use(brain, Meaning())
    mind.memory.add("exchange", "We planned a walk to the river on Sunday", 0.2, 0.3, 0.5, at=time.time() - 60)
    brain.brain.recall.sweep()
    mind._consolidate()
    assert not any(r["messages"][0]["content"].startswith("[mind:updates]") for r in brain.provider.mind_requests)
    assert mind.self["review"] is None


def test_insights_and_dreams_keep_the_moments_they_come_from(brain):
    mind = brain.brain.mind
    now = time.time()
    fixed = mind.memory.add("exchange", "The user thanked me for fixing their game", 0.8, 0.7, 0.8, at=now - 300)
    walk = mind.memory.add("exchange", "We planned a walk to the river", 0.4, 0.4, 0.5, at=now - 200)
    rain = mind.memory.add("exchange", "It rained on the window all evening", 0.1, 0.2, 0.4, at=now - 100)
    with mind._lock:
        mind.self["slept"] = now - 3600

    def answer(payload):
        listing = payload["messages"][1]["content"]
        return json.dumps({"insights": [{"text": "Helping with their game makes me glad.",
                                         "from": [numbered(listing, "fixing their game")]},
                                        "A plain one, from nothing in particular."],
                           "dream": {"text": "A river made of rain.",
                                     "from": [numbered(listing, "walk to the river"), numbered(listing, "rained")]}})
    brain.provider.mind_replies["sleep"] = [answer]
    mind._consolidate()
    insights = {e["text"]: json.loads(e["origin_ids"]) for e in mind.memory.recent(5, kinds=("insight",))}
    assert insights["Helping with their game makes me glad."] == [fixed]  # what it comes from, not the whole night
    assert insights["A plain one, from nothing in particular."] == []
    dream = mind.memory.recent(1, kinds=("dream",))[0]
    assert dream["text"] == "A river made of rain." and sorted(json.loads(dream["origin_ids"])) == sorted([walk, rain])


def test_a_night_whose_answer_she_cannot_read_is_gone_over_again(brain, caplog):
    mind = brain.brain.mind
    now = time.time()
    mind.memory.add("exchange", "The user thanked me for fixing their game", 0.8, 0.7, 0.8, at=now - 300)
    with mind._lock:
        mind.self["slept"] = now - 3600
    brain.provider.mind_replies["sleep"] = ["I'd rather not write that down."]
    with caplog.at_level(logging.WARNING):
        mind._consolidate()
    assert mind.self["review"] and "narrative" not in mind.self["review"]["done"]
    assert mind.self["slept"] == now - 3600  # the night is not over: it is gone over again
    assert "made nothing of" in caplog.text
    brain.provider.mind_replies["sleep"] = [json.dumps({"insights": ["Fixing things for them matters."],
                                                        "dream": "A wrench that sings."})]
    mind._consolidate()
    assert mind.self["review"] is None and mind.memory.recent(1, kinds=("dream",))[0]["text"] == "A wrench that sings."


def test_what_nags_her_and_what_she_put_off_come_with_what_came_of_them(brain):
    # the audit ("What recurred"): at 20:17 a thought of hers went back to whether a watcher was dead, a day after
    # the user had said to forget it; what she put off nagged her as if nothing had happened since
    mind = brain.brain.mind
    use(brain, Meaning())
    now = time.time()
    for index, text in enumerate(OTHER):
        mind.memory.add("exchange", text, 0.0, 0.3, 0.3, at=now - 5 * 86400 + index)
    hurt = mind.memory.add("exchange", "They said: your interpreter job notes are useless", -0.6, 0.6, 0.8,
                           at=now - 3 * 3600, sting=-0.5, app="cli", session="main", run_id=9001)
    mind.memory.add("exchange", "They said: sorry, the interpreter job notes were fine after all", 0.4, 0.4, 0.6,
                    at=now - 3600, app="cli", session="main")
    brain.brain.recall.sweep()
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Hm.", "want": "nothing"})] * 2
    mind._think("ruminate", next(e for e in mind.memory.recent(20) if e["id"] == hurt))
    assert "What came of it (an hour ago): They said: sorry, the interpreter job notes were fine" in asked(brain, "think")
    mind._think("resume", {"what": "redo the interpreter job notes", "app": "cli", "session": "main",
                           "at": now - 3 * 3600, "run": 9001})
    assert "What came of it (an hour ago): They said: sorry" in asked(brain, "think")


def test_a_moment_cited_as_a_whole_number_in_any_form_is_cited():
    from sentientmilk_framework.mind.life import _cited
    moments = [{"id": 7}, {"id": 9}]
    assert _cited([1, 2.0, "2", 3, "x", 0, -1], moments) == [7, 9] and _cited("1", moments) == []
