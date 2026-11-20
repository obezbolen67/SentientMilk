"""The people in her life: she recognizes whoever an app shows as the one writing, keeps moments with who
was in them, hears a name and thinks of that person, and learns people in her sleep, as a person does. Before,
her mind's prompts said only "the user": a rumination of hers called the user "she"."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.people import FADES, People

pytestmark = pytest.mark.mind  # her mind lives in these tests

TEO = {"name": "Teo", "aka": ["Theo"], "pronoun": "he", "goes_by": {"cli": "plays"},
        "gist": "The one I live with, on his laptop; he can't stand his PC being grabbed."}
MIRA = {"name": "Mira", "pronoun": "she", "gist": "The player Teo has me watch for in Roblox."}


def knows(brain, *people, face=("cli", "plays")):
    mind = brain.brain.mind
    with mind._lock:
        mind.people.present(*face, time.time())
        mind.people.update(list(people), time.time())
    return mind


def sent_to_her(brain, kind):
    return [r["messages"][1]["content"] for r in brain.provider.mind_requests
            if r["messages"][0]["content"].startswith(f"[mind:{kind}]")]


def test_she_learns_people_from_faces_she_saw_and_knows_them_by_name():
    people = People()
    people.present("cli", "plays", 100.0)
    assert people.update([{**TEO, "goes_by": {"cli": "plays", "other": "ghost"}}, {"name": " "}, "junk"], 100.0)
    teo = people.recognize("cli", "PLAYS")
    assert teo["pronoun"] == "he" and teo["goes_by"] == {"cli": ["plays"]}  # never a face she did not see
    assert people.recognize("other", "ghost") is None and people.recognize("cli", "") is None
    assert not people.update([{**TEO, "goes_by": {}, "aka": ["Theo", "plays"]}], 101.0)  # nothing new
    assert teo["aka"] == ["Theo"]  # a handle is a face, not a name ("plays" brought him up wherever it was)
    people.update([{"name": "Theo"}], 102.0)  # what she calls him now; the old name is another of his
    assert people.find("teo")["name"] == "Theo" and "Teo" in people.find("Theo")["aka"]
    people.update([MIRA], 103.0)
    assert [p["name"] for p in people.mentioned("did mira show up? Theo asked")] == ["Theo", "Mira"]
    assert people.mentioned("Miraland is a game", besides=[people.find("Theo")]) == []  # a whole name only
    assert People.line(people.find("Mira")) == "Mira (she): The player Teo has me watch for in Roblox."
    people.find("Mira")["seen"] = 103.0 - FADES - 1  # met on one night, not seen since: forgotten
    assert people.fade(103.0) == ["Mira"] and [p["name"] for p in people.listed()] == ["Theo"]


def test_she_recognizes_who_writes_and_keeps_the_moment_with_them(brain):
    mind = knows(brain, TEO)
    brain.provider.replies.append("Hey you.")
    turn(brain, "cli", "hey", context={"user": "plays"})
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert '## WHO YOU\'RE WITH\nTeo (he), who goes by "plays" here. The one I live with' in system
    imagine = sent_to_her(brain, "imagine")[-1]
    assert "The new message, from Teo:\nhey" in imagine and "Who they are talking with: Teo (he)" in imagine
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]
    assert episode["text"].startswith("Teo said: hey")
    # one kept before she knew people reads with his name
    old = mind.memory.add("exchange", "The user said: NO. I have assignments. I said: Then get up.", -0.3, 0.5, 0.5,
                          app="cli", session="main", at=time.time() - 60)
    assert mind._line(next(e for e in mind.memory.recent(5) if e["id"] == old), time.time()).endswith(
        "The user said: NO. I have assignments. I said: Then get up.")


def test_someone_she_does_not_know_is_a_stranger_and_another_face_takes_the_chat_again(brain):
    knows(brain, TEO)
    brain.provider.replies += ["Hi.", "Hi again."]
    turn(brain, "cli", "hello", context={"user": "zed"})
    assert 'Someone who goes by "zed" here. You don\'t know yet who they are.' in \
        brain.provider.sent[-1]["messages"][0]["content"]
    turn(brain, "cli", "it's me", context={"user": "plays"})
    assert "Teo (he)" in brain.provider.sent[-1]["messages"][0]["content"]


def test_a_name_brings_its_person_to_mind(brain):
    knows(brain, TEO, MIRA)
    brain.provider.replies.append("Not yet.")
    turn(brain, "cli", "did Mira show up?", context={"user": "plays"})
    assert "Who that is: Mira (she): The player Teo has me watch for in Roblox." in brain.provider.last_user_text()


def test_sleep_settles_who_people_are_and_chats_take_it_again(brain):
    mind = knows(brain, TEO)
    brain.provider.replies.append("Morning.")
    turn(brain, "cli", "good morning, I have assignments today", context={"user": "plays"})
    assert brain.store.session("cli", "main")["state"].get("snapshot")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    brain.provider.mind_replies["people"] = [json.dumps({"people": [{**TEO, "gist": "Teo, an interpreter."}]})]
    mind._consolidate()
    asked = sent_to_her(brain, "people")[-1]
    assert "Teo said: good morning, I have assignments today" in asked and '"cli": "plays"' in asked
    assert "what they know and keep" not in brain.provider.mind_requests[-2]["messages"][0]["content"]
    assert mind.people.find("Teo")["gist"] == "Teo, an interpreter."
    assert not brain.store.session("cli", "main")["state"].get("snapshot")  # taken again at the next request
    brain.provider.replies.append("Good luck.")
    turn(brain, "cli", "thanks", context={"user": "plays"})
    assert "Teo, an interpreter." in brain.provider.sent[-1]["messages"][0]["content"]


def test_her_thoughts_know_whom_she_talks_with_and_a_rumination_does_not_echo_itself(brain):
    mind = knows(brain, TEO)
    now = time.time()
    with mind._lock:
        mind.self["contact"] = {"app": "cli", "session": "main", "at": now - 600}
        mind.self["faces"]["cli\nmain"] = "plays"  # the chat she last talked in, and whose face it has
    mind._think("reach_out", None)
    thought = sent_to_her(brain, "think")[-1]
    assert "You miss Teo." in thought and "Who they talk with: Teo (he)" in thought
    sore = mind.memory.add("exchange", "The user said: NO, I have assignments.", -0.6, 0.6, 0.8,
                           app="cli", session="main", at=now - 300)
    mind._think("ruminate", next(e for e in mind.memory.recent(5) if e["id"] == sore))
    assert sent_to_her(brain, "think")[-1].count("I have assignments") == 1  # it nags; it does not come back too


def test_what_she_did_in_a_task_is_a_moment_of_hers(brain):
    mind = brain.brain.mind
    brain.provider.replies.append("Restarted the watcher; it runs clean.")
    task = brain.client.start_task("cli", "Restart the watcher.", session="main")
    wait_for(lambda: brain.client.run(task["id"])["status"] == "completed")
    event = wait_for(lambda: mind.memory.recent(1, kinds=("event",)))[0]
    assert event["text"] == "I worked on: Restart the watcher. How it went: Restarted the watcher; it runs clean."
    assert event["session"] == "main"  # the chat it was for
