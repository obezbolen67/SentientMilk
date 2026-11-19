"""Session memory: one chat's own, always whole in its context; what lasts beyond a chat is her long-term memory's
(test_recall.py)."""


from conftest import turn

from sentientmilk_framework import context
from sentientmilk_framework.testing import tool_call


def system(brain, index=-1):
    return brain.provider.sent[index]["messages"][0]["content"]


def test_every_app_has_the_chats_memory_in_its_turns(brain):
    brain.client.declare_app("bare", name="Bare", environment="No toolkits.", toolkits=[])
    profile = brain.brain.profile("bare", "main")
    assert set(brain.brain.toolset(profile, "turn").by_name) >= {"memory_save", "memory_forget"}
    assert not {"memory_save", "memory_forget"} & set(brain.brain.toolset(profile, "agent").by_name)


def test_session_memory_stays_in_its_session_through_compaction(brain):
    save = {"key": "reply_language", "value": "English only in this chat."}
    brain.provider.replies += [tool_call("memory_save", save), "Sure."]
    result = turn(brain, "cli", "answer in English here")
    ended = [e for e in result["events"] if e["type"] == "tool.end"]
    assert ended[0]["result"] == "Remembered for this chat: reply_language: English only in this chat."
    assert brain.client.session("cli", "main")["session_memory"] == {"reply_language": "English only in this chat."}
    assert brain.client.session("cli", "other")["session_memory"] == {}
    brain.provider.replies += ["Earlier work.", "Still English."]
    brain.client.compact_session("cli", "main")
    turn(brain, "cli", "and now?")
    assert "## THIS SESSION'S MEMORY" in system(brain) and "- reply_language: English only in this chat." in system(brain)
    brain.provider.replies += ["Other chat."]
    turn(brain, "cli", "hi", session="other")
    assert "reply_language" not in system(brain)


def test_agents_and_tasks_follow_the_chat_memory(brain):
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"no_push": "Never push."}})
    profile = brain.brain.profile("cli", "agent-1", {"from_session": "main"})
    taken = context.snapshot(brain.store, profile)
    assert taken["session_memory"].startswith("The memory of the session you work for")
    assert "- no_push: Never push." in taken["session_memory"]


def test_a_return_puts_the_chat_memory_back_as_it_was(brain):
    brain.provider.replies += [tool_call("memory_save", {"key": "server", "value": "staging"}), "Ok."]
    turn(brain, "cli", "use staging")
    brain.provider.replies += [tool_call("memory_save", {"key": "server", "value": "production"}, "c2"),
                               tool_call("memory_save", {"key": "no_push", "value": "Never push."}, "c3"),
                               tool_call("memory_forget", {"key": "server"}, "c4"), "Done."]
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


def test_what_the_user_forgets_leaves_the_system_block_at_once(brain):
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"tone": "Be brief."}})
    brain.provider.replies += ["Hi.", "Hi again."]
    turn(brain, "cli", "hi")
    assert "Be brief." in system(brain)
    brain.client.forget_session_memory("cli", "main", "tone")
    turn(brain, "cli", "hi")
    assert "Be brief." not in system(brain)
    assert brain.client.session("cli", "main")["session_memory"] == {}


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
    brain.provider.replies += [tool_call("memory_save", {"key": "no_push", "value": "Never push."}), "Ok."]
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
