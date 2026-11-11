"""Memory (lasting, shared by every app, always whole in context) and session memory (one session's)."""

import json
import sqlite3

from conftest import turn
from sentientmilk_framework import context
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
    assert {"memory_save", "session_memory_save"} <= set(toolset.by_name)  # every app has its tools


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
    save = {"key": "reply_language", "value": "English only in this chat."}
    brain.provider.replies += [tool_call("session_memory_save", save), "Sure."]
    result = turn(brain, "cli", "answer in English here")
    ended = [e for e in result["events"] if e["type"] == "tool.end"]
    assert ended[0]["result"] == "Remembered for this session: reply_language: English only in this chat."
    assert brain.client.session("cli", "main")["memory"] == {"reply_language": "English only in this chat."}
    assert brain.client.session("cli", "other")["memory"] == {}
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
    for kind in ("agent", "task"):
        tools = brain.brain.toolset(profile, kind).by_name
        assert "session_memory_save" not in tools and "memory_save" in tools


def test_a_return_puts_the_chat_memory_back_as_it_was(brain):
    brain.provider.replies += [tool_call("session_memory_save", {"key": "server", "value": "staging"}), "Ok."]
    turn(brain, "cli", "use staging")
    brain.provider.replies += [tool_call("session_memory_save", {"key": "server", "value": "production"}, "c2"),
                               tool_call("session_memory_save", {"key": "no_push", "value": "Never push."}, "c3"),
                               tool_call("session_memory_forget", {"key": "server"}, "c4"), "Done."]
    turn(brain, "cli", "switch to production, never push, then drop the server")
    assert brain.client.session("cli", "main")["memory"] == {"no_push": "Never push."}
    target = [e for e in brain.client.history("cli", "main") if e["role"] == "user"][1]
    preview = brain.client.rewind_preview("cli", "main", target["id"])
    assert preview["memory"] is True and {"name": "session_memory_save", "count": 2} not in preview["kept"]
    brain.client.rewind("cli", "main", target["id"])
    assert brain.client.session("cli", "main")["memory"] == {"server": "staging"}
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
    assert brain.client.memory() == {} and brain.client.session("cli", "main")["memory"] == {}


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
