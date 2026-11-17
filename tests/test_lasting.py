"""Her lasting memory kept one and true: a key names one memory, what she keeps that is like a new entry
comes back as she saves it, and as she sleeps she makes the same thing one and sets right what no longer
holds; nothing replaced or forgotten is lost."""

import json
import time
from types import SimpleNamespace

from sentientmilk_framework import lasting
from sentientmilk_framework.toolkits import memory as memory_kit


def save(brain, key, value, category):
    ctx = SimpleNamespace(brain=brain.brain, store=brain.store, app="milk", session="main", run={"kind": "turn"},
                          profile={})
    return memory_kit.memory_save.func(ctx, key, value, category)


def kept(brain):
    return {f"{e['category']}/{e['key']}": e["value"] for e in brain.store.memory_entries()}


def test_a_key_names_one_memory_and_what_is_like_it_comes_back_as_she_saves(brain):
    brain.store.remember("milk", "projects", "job", "He interprets for TP, 36 zl an hour.")
    result = save(brain, "job", "He interprets EN-RU for TP Polska; 36 zl an hour, 46 at night.", "user")
    assert kept(brain) == {"user/job": "He interprets EN-RU for TP Polska; 36 zl an hour, 46 at night."}
    assert "It replaces projects/job" in result
    assert brain.store.revisions()[0]["value"] == "He interprets for TP, 36 zl an hour."  # nothing is lost
    brain.store.remember("milk", "projects", "roblox_watch", "My app that finds a player's server; re-reads servers.")
    result = save(brain, "roblox_watch_listing", "roblox_watch now reads the whole pool in one request.", "projects")
    assert "You already keep these, like it:\n- projects/roblox_watch: My app" in result  # to fold them now
    assert "make them one entry" in result
    assert "already keep" not in save(brain, "cat", "Their cat is called Miso.", "user")


def test_as_she_goes_over_it_the_same_thing_becomes_one_and_what_no_longer_holds_goes(brain):
    brain.store.remember("milk", "projects", "roblox_watch", "My app; re-reads each server every 20 s.")
    brain.store.remember("milk", "projects", "roblox_watch_listing", "It reads the whole pool in one request now.")
    brain.store.remember("milk", "projects", "actions_button", "He plans an actions button. Not built yet.")
    brain.store.remember("milk", "user", "name", "Ilia.")
    brain.provider.tidy_answer = json.dumps({"changes": [
        {"keep": "projects/roblox_watch", "value": "My app that finds a player's server; it reads the whole pool "
         "in one request.", "from": ["projects/roblox_watch", "projects/roblox_watch_listing"], "why": "one app"},
        {"forget": "projects/actions_button", "why": "built since"},
        {"forget": "user/nobody", "why": "not kept"},  # names nothing she keeps: left out
        {"keep": "user/name", "value": "", "why": "empty"}]})  # nothing to keep: left out
    done = lasting.tidy(brain.brain, 0.0)
    assert kept(brain) == {"projects/roblox_watch": "My app that finds a player's server; it reads the whole pool in "
                                                    "one request.", "user/name": "Ilia."}
    assert done[0] == "kept projects/roblox_watch, folding in 1 (one app)" and len(done) == 2
    whys = {(r["key"], r["why"]) for r in brain.store.revisions()}
    assert ("roblox_watch_listing", "folded into projects/roblox_watch: one app") in whys
    assert ("actions_button", "forgotten as she went over her memory: built since") in whys
    asked = brain.provider.tidy_requests[0]["messages"][1]["content"]
    assert "Your lasting memory:\n" in asked and "Go over all of it." in asked and "Who you are:" in asked


def test_an_exact_detail_left_out_is_shown_to_her_once_and_what_she_answers_then_is_kept(brain):
    path = "C:\\Users\\me\\watch"
    brain.store.remember("milk", "projects", "watch", f"My app, in {path}, port 8791.")
    brain.store.remember("milk", "projects", "watch_target", "It looks for uid 4212265664 now.")
    fold = {"keep": "projects/watch", "from": ["projects/watch_target"], "why": "one app"}
    brain.provider.tidy_answer = [
        json.dumps({"changes": [{**fold, "value": "My app, port 8791; it looks for uid 4212265664."}]}),
        json.dumps({"changes": [{**fold, "value": f"My app in {path}, port 8791; looks for uid 4212265664."}]})]
    lasting.tidy(brain.brain, 0.0)
    again = brain.provider.tidy_requests[1]["messages"]
    assert again[-1]["content"].startswith("These exact details were in what you wrote over and are not in the new "
                                           f"entry:\n- projects/watch: {path}\n")
    assert kept(brain) == {"projects/watch": f"My app in {path}, port 8791; looks for uid 4212265664."}
    brain.store.remember("milk", "projects", "watch", f"My app; agents spawn in {path}\\runs.py:158-175.")
    brain.provider.tidy_answer = json.dumps({"changes": [{"keep": "projects/watch", "why": "line numbers",
                                                          "value": f"My app; agents spawn in {path}\\runs.py."}]})
    asked = len(brain.provider.tidy_requests)
    lasting.tidy(brain.brain, 0.0)
    assert len(brain.provider.tidy_requests) == asked + 1  # line numbers go out of date by themselves: not asked again


def test_she_goes_over_what_changed_as_she_sleeps_and_remembers_doing_it(brain):
    brain.client.update_config(mind=True)
    mind = brain.brain.mind
    brain.store.remember("milk", "user", "job", "He interprets.")
    mind.self["tidied"] = time.time() + 1  # gone over before; then something changed
    time.sleep(1.1)
    brain.store.remember("milk", "projects", "job_hours", "He works 160 h a month.")
    brain.provider.tidy_answer = json.dumps({"changes": [{"keep": "user/job", "value": "He interprets, 160 h a month.",
                                                          "from": ["projects/job_hours"], "why": "his job"}]})
    mind.memory.add("exchange", "The user said: I work 160 h now.", 0.2, 0.3, 0.4)
    brain.provider.mind_replies["sleep"] = ['{"insights": [], "dream": ""}']
    mind._consolidate()
    asked = brain.provider.tidy_requests[-1]["messages"][1]["content"]
    assert "Go over all of it, first what changed since you last did: projects/job_hours." in asked
    assert "- user/job (" in asked  # all of it: what goes out of date does so untouched
    assert kept(brain) == {"user/job": "He interprets, 160 h a month."}
    event = mind.memory.recent(1, kinds=("event",))[0]
    assert event["text"].startswith("I went over what I keep and set it right: kept user/job")
    assert mind.self["tidied"] > time.time() - 60


def test_once_after_her_past_she_goes_over_all_she_keeps(brain):
    brain.client.update_config(mind=True)
    mind = brain.brain.mind
    brain.store.remember("milk", "user", "name", "Ilia.")
    mind.self.pop("tidied", None)
    mind.self["past"] = {"done": [], "notes": [], "complete": True}
    brain.brain.journal._catch_up()
    assert "Go over all of it." in brain.provider.tidy_requests[-1]["messages"][1]["content"]
    asked = len(brain.provider.tidy_requests)
    brain.brain.journal._catch_up()  # once
    assert len(brain.provider.tidy_requests) == asked


def test_one_subject_in_other_words_comes_back_as_she_saves_it(brain):
    from conftest import Meaning, use
    use(brain, Meaning())
    brain.store.remember("milk", "user", "occupation", "Translates English and Russian for a living.")
    brain.brain.recall.sweep()
    result = save(brain, "job", "Works as an interpreter.", "user")  # no word in common
    assert "You already keep these, like it:\n- user/occupation: Translates" in result
