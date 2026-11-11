"""Memory (lasting, shared by every app, always whole in context) and session memory (one session's)."""

import json
import sqlite3

import pytest
from conftest import turn

from sentientmilk_framework import context
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import memory as memory_kit
from sentientmilk_framework.store import Store
from sentientmilk_framework.testing import tool_call


def system(brain, index=-1):
    return brain.provider.sent[index]["messages"][0]["content"]


def test_every_app_sees_all_memory_whole_without_asking_for_it(brain):
    brain.client.declare_app("bare", name="Bare", environment="No toolkits.", toolkits=[])
    for n in range(40):  # far past the old 8,000 characters, after which only the categories went in
        brain.store.remember("milk", "projects", f"project_{n}", f"Project {n} is about " + "x" * 300)
    brain.store.remember("bare", "user", "name", "Tester")
    brain.provider.replies += ["Hi."]
    turn(brain, "bare", "hello")
    shown = system(brain)
    assert "## YOUR MEMORY" in shown and "- name: Tester" in shown and "- name: Tester [" not in shown
    assert all(f"- project_{n}: Project {n} is about" in shown for n in range(40))
    assert "- project_0: Project 0 is about " + "x" * 300 + " [milk]" in shown  # saved by another app
    toolset = brain.brain.toolset(brain.brain.profile("bare", "main"), "turn")
    assert set(toolset.by_name) >= {"memory_save", "memory_forget"}  # every app has its tools
    assert not {"memory_list", "memory_get", "session_memory_save"} & set(toolset.by_name)  # it is all in context


def test_a_fact_one_app_saves_another_app_knows(brain):
    brain.provider.replies += [tool_call("memory_save", {"category": "user", "key": "job", "value": "a nurse"}),
                               "Noted."]
    turn(brain, "milk", "I work as a nurse")
    assert brain.client.memory() == {"user": {"job": "a nurse"}}
    assert brain.client.memory_entries()[0]["app"] == "milk"
    brain.provider.replies += ["Hello."]
    turn(brain, "cli", "hi")
    assert "- job: a nurse [milk]" in system(brain)


def test_session_memory_stays_in_its_session_through_compaction(brain):
    save = {"key": "reply_language", "value": "English only in this chat.", "scope": "session"}
    brain.provider.replies += [tool_call("memory_save", save), "Sure."]
    result = turn(brain, "cli", "answer in English here")
    ended = [e for e in result["events"] if e["type"] == "tool.end"]
    assert ended[0]["result"] == "Remembered for this session: reply_language: English only in this chat."
    assert brain.client.session("cli", "main")["session_memory"] == {"reply_language": "English only in this chat."}
    assert brain.client.session("cli", "other")["session_memory"] == {}
    brain.provider.replies += ["Earlier work.", "Still English."]
    brain.client.compact_session("cli", "main")
    turn(brain, "cli", "and now?")
    assert "## THIS SESSION'S MEMORY" in system(brain) and "- reply_language: English only in this chat." in system(brain)
    brain.provider.replies += ["Other chat."]
    turn(brain, "cli", "hi", session="other")
    assert "reply_language" not in system(brain)


def test_agents_and_tasks_follow_the_chat_memory_but_do_not_change_it(brain):
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"no_push": "Never push."}})
    profile = brain.brain.profile("cli", "agent-1", {"from_session": "main"})
    taken = context.snapshot(brain.store, profile)
    assert taken["session_memory"].startswith("The memory of the session you work for")
    assert "- no_push: Never push." in taken["session_memory"]
    run = brain.store.run(brain.store.add_run("cli", "agent-1", "agent", {}, status="working"))
    ctx = ToolContext(brain.brain, run, profile, "call-1")
    with pytest.raises(ToolError, match="Only the session's own turns"):
        memory_kit.memory_save.func(ctx, "no_push", "Push away.", scope="session")
    assert memory_kit.memory_save.func(ctx, "job", "a nurse", "user") == "Remembered user/job for every app and chat."


def test_a_return_puts_the_chat_memory_back_as_it_was(brain):
    brain.provider.replies += [tool_call("memory_save", {"key": "server", "value": "staging", "scope": "session"}), "Ok."]
    turn(brain, "cli", "use staging")
    brain.provider.replies += [tool_call("memory_save", {"key": "server", "value": "production", "scope": "session"}, "c2"),
                               tool_call("memory_save", {"key": "no_push", "value": "Never push.", "scope": "session"}, "c3"),
                               tool_call("memory_forget", {"key": "server", "scope": "session"}, "c4"), "Done."]
    turn(brain, "cli", "switch to production, never push, then drop the server")
    assert brain.client.session("cli", "main")["session_memory"] == {"no_push": "Never push."}
    target = [e for e in brain.client.history("cli", "main") if e["role"] == "user"][1]
    preview = brain.client.rewind_preview("cli", "main", target["id"])
    assert preview["session_memory"] is True and preview["kept"] == []  # this chat's memory goes back
    brain.client.rewind("cli", "main", target["id"])
    assert brain.client.session("cli", "main")["session_memory"] == {"server": "staging"}
    brain.provider.replies += ["Back."]
    turn(brain, "cli", "where were we?")
    assert "- server: staging" in system(brain) and "no_push" not in system(brain)


def test_what_the_user_forgets_leaves_every_system_block_at_once(brain):
    brain.store.remember("milk", "user", "pet", "a cat named Biscuit")
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"tone": "Be brief."}})
    brain.provider.replies += ["Hi.", "Hi again."]
    turn(brain, "cli", "hi")
    assert "Biscuit" in system(brain) and "Be brief." in system(brain)
    brain.client.forget("user", "pet")
    brain.client.forget_session_memory("cli", "main", "tone")
    turn(brain, "cli", "hi")
    assert "Biscuit" not in system(brain) and "Be brief." not in system(brain)
    assert brain.client.memory() == {} and brain.client.session("cli", "main")["session_memory"] == {}


def test_memory_kept_per_app_before_becomes_shared_once(tmp_path):
    path = tmp_path / "brain.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE memory (app TEXT NOT NULL, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                             updated REAL NOT NULL, PRIMARY KEY (app, category, key));
        CREATE TABLE sessions (app TEXT NOT NULL, id TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}',
                               state TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, PRIMARY KEY (app, id));
    """)
    db.executemany("INSERT INTO memory VALUES (?, ?, ?, ?, ?)", [
        ("milkchan", "user", "name", json.dumps("Illia"), 1.0), ("cli", "user", "name", json.dumps("Illia S"), 2.0),
        ("milkchan", "projects", "bot", json.dumps("A trading bot."), 1.5)])
    db.execute("INSERT INTO sessions(app, id, state, created) VALUES ('milkchan', 'main', ?, 0)",
               (json.dumps({"snapshot": {"memory": "Categories: user (1 items)"}, "todo": []}),))
    db.commit()
    db.close()
    store = Store(path)
    assert store.memories() == {"projects": {"bot": "A trading bot."}, "user": {"name": "Illia S"}}  # newest wins
    assert [e["app"] for e in store.memory_entries()] == ["milkchan", "cli"]
    assert store.session("milkchan", "main")["state"] == {"todo": []}  # its old snapshot is taken again
    Store(path)  # once: a second start changes nothing
    assert len(store.memory_entries()) == 2


def flat(payload) -> str:
    """Everything a request said after the system block, as text."""
    return json.dumps(payload["messages"][1:], ensure_ascii=False)


def test_a_chat_left_open_hears_what_another_chat_saved_since(brain):
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello", session="old")  # open since yesterday: its snapshot is taken
    before = system(brain)
    brain.provider.replies += [tool_call("memory_save", {"category": "user", "key": "cat", "value": "Biscuit"}),
                               "Noted."]
    turn(brain, "milk", "my cat is Biscuit")
    brain.provider.replies += ["Biscuit, yes."]
    turn(brain, "milk", "what is my cat called?", session="old")
    assert system(brain) == before  # the cached prefix holds
    assert "Your memory changed" in flat(brain.provider.sent[-1]) and "- user/cat: Biscuit" in flat(brain.provider.sent[-1])
    brain.provider.replies += ["Still Biscuit."]
    turn(brain, "milk", "and again?", session="old")
    assert flat(brain.provider.sent[-1]).count("Your memory changed") == 1  # once, then it is known
    brain.provider.replies += [tool_call("memory_forget", {"category": "user", "key": "cat"}, "f"), "Forgot."]
    turn(brain, "milk", "forget my cat")
    assert "Your memory changed" not in flat(brain.provider.sent[-1])  # her own changes are no news to her
    brain.provider.replies += ["Ok."]
    turn(brain, "cli", "hi")  # another app, newer: Biscuit is gone from its system block already
    assert "Biscuit" not in system(brain)
    brain.provider.replies += ["Gone."]
    turn(brain, "milk", "my cat?", session="old")
    assert "- forgotten: user/cat" in flat(brain.provider.sent[-1])


def agent_for(brain, chat="main", name="helper"):
    """An agent session working for ``chat``, as Agents.start makes one."""
    session = f"agent-{name}"
    brain.store.update_session("cli", session, "settings",
                               lambda s: {**s, "agent": {"name": name, "parent": chat, "base": chat}})
    return session


def test_what_works_for_a_chat_hears_its_memory_change(brain):
    helper = agent_for(brain)
    brain.provider.replies += ["Working."]
    turn(brain, "cli", "start", session=helper)  # its snapshot: no chat memory yet
    brain.provider.replies += [tool_call("memory_save", {"key": "no_push", "value": "Never push.", "scope": "session"}),
                               "Ok."]
    turn(brain, "cli", "never push in this chat")
    notes = [e["text"] for e in brain.store.events("cli", helper) if e["type"] == "note"]
    assert notes == ["The memory of the session you work for changed. Now:\n- no_push: Never push."]
    super_run = brain.store.add_run("cli", "agent-coder", "agent", {"super": True}, status="working")
    agent_for(brain, name="coder")
    brain.client.forget_session_memory("cli", "main", "no_push")  # the user's change
    steered = brain.store.run(super_run)["options"]["steer"]
    assert steered == [{"type": "text", "text": "[The memory of the session you work for changed (the user changed it);"
                                                 " it is empty now.]"}]
    assert "snapshot" not in brain.store.session("cli", helper)["state"]  # taken again: what went leaves it
    assert len([e for e in brain.store.events("cli", helper) if e["type"] == "note"]) == 1


def test_an_agent_between_runs_hears_what_memory_changed(brain):
    helper = agent_for(brain)
    profile = brain.brain.profile("cli", helper, {"from_session": "main"})
    brain.brain.session_snapshot(profile)
    brain.store.remember("milk", "user", "job", "a nurse")
    assert "- user/job: a nurse [milk]" in brain.brain.memory_news(profile)
    assert brain.brain.memory_news(profile) == ""  # told once
