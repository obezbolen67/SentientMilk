"""Sessions as apps manage them: titles (named by the model after the first reply, renamed by the user),
previews, deleting a session, compacting one now, and opening the control panel."""

import json
import subprocess
import sys
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import BrainError, context, titles
from sentientmilk_framework import client as client_module


def listed(brain, app, session):
    return next((entry for entry in brain.client.sessions(app) if entry["id"] == session), None)


def test_a_session_is_named_after_its_first_reply_once_and_announced(brain):
    brain.provider.title = "Roblox server hunt"
    brain.provider.replies = ["Sure, which game?"]
    turn(brain, "milk", "Can you help me find a Roblox server?", session="chat-1")
    assert wait_for(lambda: (listed(brain, "milk", "chat-1") or {}).get("title")) == "Roblox server hunt"
    entry = listed(brain, "milk", "chat-1")
    assert entry["preview"].startswith("Can you help me find") and entry["last_active"]
    asked = brain.provider.title_requests[0]["messages"][-1]["content"]
    assert "Can you help me find a Roblox server?" in asked and "Sure, which game?" in asked
    # the title is stored, then announced: a busy machine reads between the two
    titled = wait_for(lambda: [n for n in brain.store.notifications("milk", 0) if n["type"] == "session.titled"])
    assert [n["data"] for n in titled] == [{"session": "chat-1", "title": "Roblox server hunt"}]

    turn(brain, "milk", "Item Asylum", session="chat-1")
    turn(brain, "milk", "Hello", session="chat-2")
    wait_for(lambda: (listed(brain, "milk", "chat-2") or {}).get("title"))
    assert len(brain.provider.title_requests) == 2  # one per session, never again


def test_a_title_is_cleaned_and_the_users_own_title_stays(brain):
    brain.provider.title = '"Groceries for Sunday."\nSecond line'
    turn(brain, "milk", "What should I buy?", session="chat-1")
    assert wait_for(lambda: (listed(brain, "milk", "chat-1") or {}).get("title")) == "Groceries for Sunday"

    brain.client.update_session("milk", "chat-2", title="Mine")
    turn(brain, "milk", "Hi", session="chat-2")
    brain.client.update_session("milk", "chat-1", title="Shopping")  # a rename
    assert listed(brain, "milk", "chat-1")["title"] == "Shopping"
    assert listed(brain, "milk", "chat-2")["title"] == "Mine" and len(brain.provider.title_requests) == 1
    with pytest.raises(BrainError):
        brain.client.update_session("milk", "chat-1", title="x" * 81)


def test_a_title_that_comes_after_the_session_was_deleted_does_not_bring_it_back(brain, monkeypatch):
    """The model names a session off the request path, and the user may delete it meanwhile: writing the
    title created the session again, empty but titled, so a deleted chat came back to the list."""
    respond = brain.provider.respond

    def deleted_while_named(payload):
        if payload["messages"][0].get("content") == titles.PROMPT:
            brain.store.delete_session("milk", "chat-1")
        return respond(payload)
    monkeypatch.setattr(brain.provider, "respond", deleted_while_named)
    turn(brain, "milk", "Remember the milk", session="chat-1")
    wait_for(lambda: brain.provider.title_requests)
    time.sleep(0.5)  # the title is written right after its reply
    assert listed(brain, "milk", "chat-1") is None


def test_a_session_is_deleted_with_its_history_but_not_while_she_works_in_it(brain):
    turn(brain, "milk", "Remember the milk", session="chat-1")
    brain.client.delete_session("milk", "chat-1")
    assert listed(brain, "milk", "chat-1") is None
    assert brain.client.history("milk", "chat-1") == []

    run = brain.store.add_run("milk", "chat-2", "turn", {})
    brain.store.update_run(run, status="working")
    with pytest.raises(BrainError) as refused:
        brain.client.delete_session("milk", "chat-2")
    assert refused.value.type == "busy"


def test_compact_sums_up_the_whole_session_now_and_reports_its_context(brain):
    brain.provider.usage = {**brain.provider.usage, "prompt_tokens": 5000}
    turn(brain, "milk", "My cat is called Biscuit", session="chat-1")
    turn(brain, "milk", "She likes tuna", session="chat-1")
    brain.provider.replies = ["The user has a cat, Biscuit, who likes tuna."]
    result = brain.client.compact_session("milk", "chat-1")
    assert result["compacted"] and result["before"] == 5000 and 0 < result["after"] < 5000
    assert brain.client.session("milk", "chat-1")["context"]["used"] == result["after"]
    compaction = [e for e in brain.store.events("milk", "chat-1") if e["type"] == "compaction"]
    assert compaction[-1]["summary"].startswith("The user has a cat, Biscuit")

    brain.provider.usage = {**brain.provider.usage, "prompt_tokens": 900}
    turn(brain, "milk", "What does she like?", session="chat-1")
    sent = json.dumps(brain.provider.sent[-1]["messages"])
    assert context.SUMMARY_PREFIX.strip()[:20] in sent and "My cat is called Biscuit" not in sent
    assert brain.client.history("milk", "chat-1")[0]["text"] == "My cat is called Biscuit"  # the user still sees it

    assert not brain.client.compact_session("milk", "chat-empty")["compacted"]


def test_open_panel_runs_the_recorded_command_in_its_own_window(tmp_path, monkeypatch):
    program = tmp_path / "SentientMilk.exe"
    program.write_bytes(b"")
    (tmp_path / "launch.json").write_text(json.dumps(
        {"command": [str(program), "-m", "sentientmilk_framework", "--home", str(tmp_path), "serve", "--log"]}))
    started = []
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda command, **options: started.append((command, options)))
    client_module.open_panel(tmp_path)
    command, options = started[0]
    assert command == [str(program), "-m", "sentientmilk_framework", "--home", str(tmp_path)]
    if sys.platform == "win32":
        assert options["creationflags"] & subprocess.CREATE_NEW_CONSOLE


def test_naming_or_noting_a_session_deleted_just_before_does_not_bring_it_back(brain):
    """The title and journal jobs start right after a turn; the user may delete the chat before they read it."""
    turn(brain, "milk", "Remember the milk", session="chat-1")
    wait_for(lambda: brain.provider.title_requests)
    time.sleep(0.3)  # the turn's own title job is done
    brain.store.delete_session("milk", "chat-1")
    titles._name(brain.brain, "milk", "chat-1")
    brain.brain.journal.write("milk", "chat-1")
    brain.brain.journal._check_quiet()
    assert listed(brain, "milk", "chat-1") is None
