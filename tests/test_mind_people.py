"""The people in her life (0.31): she recognizes whoever an app shows as the one writing, keeps moments with who
was in them, hears a name and thinks of that person, and learns people in her sleep, as a person does. Before,
her mind's prompts said only "the user": a rumination of hers called the user "she"."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.people import FADES, People

pytestmark = pytest.mark.mind  # her mind lives in these tests

ILIA = {"name": "Ilia", "aka": ["Illia"], "pronoun": "he", "goes_by": {"cli": "plays"},
        "gist": "The one I live with, on his laptop; he can't stand his PC being grabbed."}
VANNY = {"name": "Vanny", "pronoun": "she", "gist": "The player Ilia has me watch for in Roblox."}


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
    assert people.update([{**ILIA, "goes_by": {"cli": "plays", "other": "ghost"}}, {"name": " "}, "junk"], 100.0)
    ilia = people.recognize("cli", "PLAYS")
    assert ilia["pronoun"] == "he" and ilia["goes_by"] == {"cli": ["plays"]}  # never a face she did not see
    assert people.recognize("other", "ghost") is None and people.recognize("cli", "") is None
    assert not people.update([{**ILIA, "goes_by": {}, "aka": ["Illia", "plays"]}], 101.0)  # nothing new
    assert ilia["aka"] == ["Illia"]  # a handle is a face, not a name ("plays" brought him up wherever it was)
    people.update([{"name": "Illia"}], 102.0)  # what she calls him now; the old name is another of his
    assert people.find("ilia")["name"] == "Illia" and "Ilia" in people.find("Illia")["aka"]
    people.update([VANNY], 103.0)
    assert [p["name"] for p in people.mentioned("did vanny show up? Illia asked")] == ["Illia", "Vanny"]
    assert people.mentioned("Vannyland is a game", besides=[people.find("Illia")]) == []  # a whole name only
    assert People.line(people.find("Vanny")) == "Vanny (she): The player Ilia has me watch for in Roblox."
    people.find("Vanny")["seen"] = 103.0 - FADES - 1  # met on one night, not seen since: forgotten
    assert people.fade(103.0) == ["Vanny"] and [p["name"] for p in people.listed()] == ["Illia"]


def test_she_recognizes_who_writes_and_keeps_the_moment_with_them(brain):
    mind = knows(brain, ILIA)
    brain.provider.replies.append("Hey you.")
    turn(brain, "cli", "hey", context={"user": "plays"})
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert '## WHO YOU\'RE WITH\nIlia (he), who goes by "plays" here. The one I live with' in system
    imagine = sent_to_her(brain, "imagine")[-1]
    assert "The new message, from Ilia:\nhey" in imagine and "Who they are talking with: Ilia (he)" in imagine
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]
    assert episode["text"].startswith("Ilia said: hey")
    # one kept before she knew people reads with his name
    old = mind.memory.add("exchange", "The user said: NO. I have assignments. I said: Then get up.", -0.3, 0.5, 0.5,
                          app="cli", session="main", at=time.time() - 60)
    assert mind._line(next(e for e in mind.memory.recent(5) if e["id"] == old), time.time()).endswith(
        "The user said: NO. I have assignments. I said: Then get up.")


def test_someone_she_does_not_know_is_a_stranger_and_another_face_takes_the_chat_again(brain):
    knows(brain, ILIA)
    brain.provider.replies += ["Hi.", "Hi again."]
    turn(brain, "cli", "hello", context={"user": "zed"})
    assert 'Someone who goes by "zed" here. You don\'t know yet who they are.' in \
        brain.provider.sent[-1]["messages"][0]["content"]
    turn(brain, "cli", "it's me", context={"user": "plays"})
    assert "Ilia (he)" in brain.provider.sent[-1]["messages"][0]["content"]


def test_a_name_brings_its_person_to_mind(brain):
    knows(brain, ILIA, VANNY)
    brain.provider.replies.append("Not yet.")
    turn(brain, "cli", "did Vanny show up?", context={"user": "plays"})
    assert "Who that is: Vanny (she): The player Ilia has me watch for in Roblox." in brain.provider.last_user_text()


def test_sleep_settles_who_people_are_and_chats_take_it_again(brain):
    mind = knows(brain, ILIA)
    brain.provider.replies.append("Morning.")
    turn(brain, "cli", "good morning, I have assignments today", context={"user": "plays"})
    assert brain.store.session("cli", "main")["state"].get("snapshot")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    brain.provider.mind_replies["people"] = [json.dumps({"people": [{**ILIA, "gist": "Ilia, an interpreter."}]})]
    mind._consolidate()
    asked = sent_to_her(brain, "people")[-1]
    assert "Ilia said: good morning, I have assignments today" in asked and '"cli": "plays"' in asked
    assert "what they know and keep" not in brain.provider.mind_requests[-2]["messages"][0]["content"]
    assert mind.people.find("Ilia")["gist"] == "Ilia, an interpreter."
    assert not brain.store.session("cli", "main")["state"].get("snapshot")  # taken again at the next request
    brain.provider.replies.append("Good luck.")
    turn(brain, "cli", "thanks", context={"user": "plays"})
    assert "Ilia, an interpreter." in brain.provider.sent[-1]["messages"][0]["content"]


def test_she_meets_the_people_of_her_past_once(brain):
    mind = brain.brain.mind
    brain.provider.replies.append("Hi.")
    turn(brain, "cli", "hi", context={"user": "plays"})  # a face from before she knew people
    brain.store.remember("cli", "user", "name", 'His name is Ilia (the app shows him as "plays").')
    mind.people = People()
    brain.provider.mind_replies["people"] = [json.dumps({"people": [ILIA]})]
    mind._meet_past()
    asked = sent_to_her(brain, "people")[-1]
    assert 'name: His name is Ilia (the app shows him as "plays").' in asked
    assert mind.people.met_past and mind.people.recognize("cli", "plays")["name"] == "Ilia"


def test_her_thoughts_know_whom_she_talks_with_and_a_rumination_does_not_echo_itself(brain):
    mind = knows(brain, ILIA)
    now = time.time()
    with mind._lock:
        mind.self["contact"] = {"app": "cli", "session": "main", "at": now - 600}
        mind.self["faces"]["cli\nmain"] = "plays"  # the chat she last talked in, and whose face it has
    mind._think("reach_out", None)
    thought = sent_to_her(brain, "think")[-1]
    assert "You miss Ilia." in thought and "Who they talk with: Ilia (he)" in thought
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
