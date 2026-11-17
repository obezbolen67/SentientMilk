"""Her memory is one: her mind's own and her long-term memory (0.30: the journal, the facts she kept and her
going over them are gone); what an older mind kept is set right once."""

import json
import time

import pytest

from sentientmilk_framework.mind import life
from sentientmilk_framework.mind.life import LOGIC

pytestmark = pytest.mark.mind


def test_her_wandering_and_her_sleep_go_without_the_facts_kept_before(brain):
    mind = brain.brain.mind
    brain.store.remember("milk", "projects", "roblox_watch", "My app that finds which server a player is in.")
    brain.provider.mind_replies["think"] = ['{"thought": "I wonder if the watcher found her.", "want": "nothing"}']
    mind._think("wonder", None)
    think = next(r for r in reversed(brain.provider.mind_requests) if r["messages"][0]["content"].startswith("[mind:think]"))
    assert "Something they know" not in think["messages"][1]["content"] and "roblox" not in think["messages"][1]["content"]
    mind.memory.add("exchange", "The user thanked me for the watcher", 0.6, 0.5, 0.6)
    brain.provider.mind_replies["sleep"] = [json.dumps({"insights": [], "dream": ""})]
    mind._consolidate()
    sleep = next(r for r in reversed(brain.provider.mind_requests) if r["messages"][0]["content"].startswith("[mind:sleep]"))
    assert "lasting memory" not in sleep["messages"][1]["content"] and "The user thanked me" in sleep["messages"][1]["content"]


def test_what_a_mind_before_030_kept_of_the_journal_and_her_tidying_goes(brain):
    mind = brain.brain.mind
    mind.self.update(past={"done": [], "notes": [], "complete": True}, tidied=1.0, story="I am Milk.")
    mind.save()
    again = life.Mind(brain.brain)
    assert not {"past", "tidied", "story"} & set(again.self)
    again.memory.close()


def test_what_an_older_mind_kept_is_set_right_once(brain):
    mind = brain.brain.mind
    now = time.time()
    stale = {"act": "talk", "what": "keep it light, joke about the dead watcher", "said": "Hii", "at": now - 60,
             "features": ["act:talk", "intent:chat", "tag:hello"], "chance": 0.8}
    hello = {"act": "do", "what": "say hi", "said": "hey", "at": now - 50,
             "features": ["act:do", "intent:chat", "act:do|intent:chat", "act:do|tag:hello", "act:do|when:night"]}
    asked = {"act": "do", "what": "tidy", "said": "tidy my notes", "at": now - 40, "gated": True,
             "features": ["act:do", "intent:request", "act:do|when:night"]}
    for decision in (stale, hello, asked):
        brain.store.add_run("milk", "main", "turn", {"input": None, "mind": decision})
    first = mind.memory.add("exchange", "The user said: Hii I talked it over (keep it light, joke about the dead "
                            "watcher). I said: Hii. The watcher is dead.", 0.1, 0.3, 0.2, app="milk", session="main",
                            at=now - 59)
    later = mind.memory.add("exchange", "The user said: how are you?. I said: Fine..", 0.1, 0.3, 0.2, app="milk",
                            session="main", at=now - 30)
    mind.values.weights.update({"act:do|intent:chat": 0.2, "act:do|tag:hello": 0.3, "act:do|when:night": 0.1})
    mind.self["concerns"] = [{"what": "say hi", "app": "milk", "session": "main", "at": now - 50}]
    mind.self.pop("logic", None)
    mind._bring_up_to_date()
    episode = next(e for e in mind.memory.recent(10) if e["id"] == first)
    assert episode["text"] == "The user said: Hii. I said: Hii. The watcher is dead."
    assert next(e for e in mind.memory.recent(10) if e["id"] == later)["text"] == "The user said: how are you? I said: Fine."
    assert set(mind.values.weights) >= {"act:do|when:night"}  # what a request taught too stays
    assert not {"act:do|intent:chat", "act:do|tag:hello"} & set(mind.values.weights)
    assert mind.self["concerns"] == [] and mind.self["logic"] == LOGIC
    mind.values.weights["act:do|tag:hello"] = 0.3
    mind._bring_up_to_date()  # once
    assert mind.values.weights["act:do|tag:hello"] == 0.3
