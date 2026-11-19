"""Her body's record: every push, kept after it has faded from her, and her levels at each message, thought and
sleep. For audits and for replaying her days through a changed model: she is never shown it. A body that dropped a
push once its effect had faded left nothing to tell what had moved her (the audit of 2026-11-18, finding 11)."""

import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.body import START

pytestmark = pytest.mark.mind  # her mind lives in these tests


def test_every_push_is_kept_after_it_has_faded_from_her_and_goes_with_its_chat(brain):
    mind = brain.brain.mind
    with mind._lock, mind._pushing_for("cli\nmain"):
        mind.body.apply({"cortisol": 0.3}, 'The user said "you are useless"')
    with mind._lock:
        mind.body.apply({"novelty": 0.2}, "her mind wandered")
        mind.body.at += 30 * 86400  # long gone from her
        mind.body.apply({"endorphin": 0.01}, "a later push")
    assert not any(why.startswith("The user said") for _, why, _ in mind.body.pushed)
    record = mind.memory.body_record()
    kept = next(p for p in record["pushes"] if p["why"] == 'The user said "you are useless"')
    assert kept["moved"]["cortisol"] > 0 and kept["chat"] == "cli\nmain"
    assert next(p for p in record["pushes"] if p["why"] == "her mind wandered")["chat"] is None
    mind.forget("cli", "main")  # a deleted chat's words go from the record too; what was of no chat stays
    whys = [p["why"] for p in mind.memory.body_record()["pushes"]]
    assert 'The user said "you are useless"' not in whys and "her mind wandered" in whys


def test_her_levels_are_kept_at_each_message_thought_and_sleep(brain):
    mind = brain.brain.mind
    brain.provider.replies += ["Hi."]
    result = turn(brain, "cli", "Hello there")
    wait_for(lambda: mind.memory.recorded(result["run"]))  # her turn is kept just after it ends
    mind._think("wonder", None)
    now = time.time()
    with mind._lock:  # a night with the brain off: she slept and woke by her body's own rules
        mind.body.peak = (mind.body.hour(now - 5 * 3600) - 12) % 24
        mind.body.at, mind.body.asleep = now - 11 * 3600, False
        mind.body.levels["adenosine"] = 0.62
        mind._live_until(now)
    moments = [(row["moment"], row["chat"]) for row in mind.memory.body_record()["levels"]]
    assert ("message", "cli\nmain") in moments and ("turn ended", "cli\nmain") in moments
    assert ("thought", None) in moments and ("fell asleep", None) in moments and ("woke", None) in moments
    assert all(set(START) <= set(row["levels"]) for row in mind.memory.body_record()["levels"])
