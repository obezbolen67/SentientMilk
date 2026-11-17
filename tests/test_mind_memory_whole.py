"""Her memory is one: her journal notes are her own and events of her life, she goes over the past her mind
never saw, what she knows comes up as her mind wanders and in sleep, a search reaches her own memories, and
what an older mind kept is set right."""

import json
import sqlite3
import time
from types import SimpleNamespace

from conftest import turn, wait_for

from sentientmilk_framework import journal
from sentientmilk_framework.mind.life import LOGIC
from sentientmilk_framework.toolkits import journal as journal_kit


def mind_on(brain):
    brain.client.update_config(mind=True)
    return brain.brain.mind


def test_her_journal_note_is_her_own_and_an_event_of_her_life(brain):
    mind = mind_on(brain)
    brain.store.remember("milk", "user", "name", "Their name is Ilia.")
    brain.provider.replies += ['{"expression": "arms_down/smile"}\nHi, Ilia!']
    turn(brain, "milk", "I adopted a cat named Miso.")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    brain.provider.journal_note = "Ilia told me he adopted a cat, Miso. I was glad for him."
    brain.brain.journal.write("milk", "main")
    system = brain.provider.journal_requests[0]["messages"][0]["content"]
    assert system.startswith(journal.PROMPT) and "first person" in system
    assert "Who you are:" in system and "Their name is Ilia." in system  # she writes it, knowing who he is
    event = mind.memory.recent(1, kinds=("event",))[0]
    exchange = mind.memory.recent(1, kinds=("exchange",))[0]
    assert event["text"] == brain.store.notes()[0]["note"] == "Ilia told me he adopted a cat, Miso. I was glad for him."
    assert event["valence"] == exchange["valence"] and event["salience"] >= 0.35  # its feeling; the gist is kept


def test_once_she_goes_over_the_past_her_mind_never_saw(brain):
    for session in ("chat-a", "chat-b"):
        brain.provider.replies += ['{"expression": "arms_down/smile"}\nSure.']
        turn(brain, "milk", f"tell me about {session}", session=session)
    brain.store.add_note("milk", "chat-a", "You talked about chat-a.")  # the old journal, about "you"
    with sqlite3.connect(brain.store.path) as db:  # an hour ago: quiet since
        db.execute("UPDATE events SET at = at - 3600")
    mind = mind_on(brain)
    brain.provider.journal_note = "I told them about it."
    mind.self.pop("past", None)  # the test brain started with her mind on, and nothing to go over then
    brain.brain.journal.catch_up()
    events = mind.memory.recent(10, kinds=("event",))
    assert sorted(e["session"] for e in events) == ["chat-a", "chat-b"] and all(e["valence"] == 0.0 for e in events)
    notes = brain.store.notes()
    assert [n["note"] for n in notes] == ["I told them about it."] * 2  # the journal in her own words
    assert all(n["at"] < time.time() - 3000 for n in notes)  # when it happened
    assert brain.store.find_session("milk", "chat-a")["state"]["journaled_upto"] > 0
    asked = len(brain.provider.journal_requests)
    brain.brain.journal.catch_up()  # once
    brain.brain.journal._check_quiet()
    time.sleep(0.3)
    assert len(brain.provider.journal_requests) == asked and mind.self["past"]["complete"]


def test_what_she_knows_comes_to_mind_as_she_wanders_and_in_her_sleep(brain):
    mind = mind_on(brain)
    brain.store.remember("milk", "projects", "roblox_watch", "My app that finds which server a player is in.")
    brain.provider.mind_replies["think"] = ['{"thought": "I wonder if the watcher found her.", "want": "nothing"}']
    mind._think("wonder", None)
    think = next(r for r in reversed(brain.provider.mind_requests) if r["messages"][0]["content"].startswith("[mind:think]"))
    assert "Something they know comes to mind: roblox watch: My app that finds" in think["messages"][1]["content"]
    mind.memory.add("exchange", "The user thanked me for the watcher", 0.6, 0.5, 0.6)
    brain.provider.mind_replies["sleep"] = [json.dumps({"insights": [], "dream": "", "story": "You build things."})]
    mind._consolidate()
    sleep = next(r for r in reversed(brain.provider.mind_requests) if r["messages"][0]["content"].startswith("[mind:sleep]"))
    assert "What they know and keep (their lasting memory):" in sleep["messages"][1]["content"]
    assert "roblox_watch: My app" in sleep["messages"][1]["content"]


def test_a_search_of_her_journal_reaches_her_own_memories_of_any_time(brain):
    mind = mind_on(brain)
    mind.memory.add("event", "I patched the cheat menus of MDRG with Ilia.", 0.3, 0.3, 0.4, at=time.time() - 30 * 86400)
    brain.store.remember("milk", "user", "email", "His mail is a@b.c. It is full, so mine goes out from elsewhere.")
    assert mind._something_known() == "email: His mail is a@b.c."  # what she knows comes to mind as its gist
    found = mind.look_back("MDRG cheat")
    assert len(found) == 1 and "30 days ago" in found[0] and "patched the cheat menus" in found[0]
    assert mind.look_back("") == [] and mind.look_back("tomatoes") == []
    ctx = SimpleNamespace(brain=brain.brain, store=brain.store)
    result = journal_kit.journal_search.func(ctx, "MDRG")  # the journal keeps 20 notes; her memory, her life
    assert "What comes back to you:" in result and "patched the cheat menus" in result


def test_what_an_older_mind_kept_is_set_right_once(brain):
    mind = mind_on(brain)
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
    assert mind.look_back("joke dead watcher light") == [] or "keep it light" not in mind.look_back("watcher")[0]
    assert set(mind.values.weights) >= {"act:do|when:night"}  # what a request taught too stays
    assert not {"act:do|intent:chat", "act:do|tag:hello"} & set(mind.values.weights)
    assert mind.self["concerns"] == [] and mind.self["logic"] == LOGIC
    mind.values.weights["act:do|tag:hello"] = 0.3
    mind._bring_up_to_date()  # once
    assert mind.values.weights["act:do|tag:hello"] == 0.3
