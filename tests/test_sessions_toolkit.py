"""The sessions toolkit: she lists, reads, searches, renames and (asking every time) deletes her other chats."""

import pytest
from conftest import turn

from sentientmilk_framework.testing import tool_call
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import sessions as kit


@pytest.fixture
def talk(brain):
    brain.client.declare_app("talk", name="Talk", toolkits=["sessions"])

    def chat(session, title, *exchanges):
        brain.client.update_session("talk", session, title=title)
        for said, reply in exchanges:
            brain.provider.replies.append(reply)
            turn(brain, "talk", said, session=session)
    chat("chat-1", "Groceries", ("plan the week's shopping", "Sure."), ("add oat milk", "Added oat milk."))
    chat("chat-2", "Holidays", ("where should we go", "Lisbon, for the light."))
    chat("main", "Today", ("hello", "Hi!"))
    run = brain.store.add_run("talk", "main", "turn", {}, status="working")
    return ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("talk", "main"), "call-1")


def test_she_lists_her_chats_newest_first(brain, talk):
    listed = kit.sessions_list.func(talk).splitlines()
    assert listed[0].startswith('main "Today" (this one) · 1 turn')
    assert listed[1].startswith('chat-2 "Holidays" · 1 turn') and listed[2].startswith('chat-1 "Groceries" · 2 turns')
    assert 'chat-1 "Groceries"' in kit.sessions_list.func(talk, "groc") and "Holidays" not in kit.sessions_list.func(
        talk, "groc")
    brain.store.add_note("talk", "chat-1", "You planned the shopping.", 24_000)
    assert "You planned the shopping." in kit.sessions_list.func(talk, "groc")


def test_she_reads_a_summary_or_the_plain_turns_page_by_page(brain, talk, monkeypatch):
    brain.store.add_note("talk", "chat-1", "You planned the shopping.", 24_000)
    summary = kit.sessions_read.func(talk, "Groceries")
    assert summary.startswith('[Mentioned session "Groceries" (chat-1)') and "Journal notes:" in summary
    turns = kit.sessions_read.func(talk, "chat-1", part="turns")
    assert turns.splitlines()[:4] == ["1. user: plan the week's shopping", "   you: Sure.", "2. user: add oat milk",
                                      "   you: Added oat milk."]
    monkeypatch.setattr(kit, "PAGE", 1)
    first, second = kit.sessions_read.func(talk, "chat-1", part="turns"), kit.sessions_read.func(
        talk, "chat-1", part="turns", offset=1)
    assert "add oat milk" not in first and "offset=1" in first and second.startswith("2. user: add oat milk")
    assert "conversation you are in" in kit.sessions_read.func(talk, "main")
    with pytest.raises(ToolError, match="No session chat-9"):
        kit.sessions_read.func(talk, "chat-9")
    with pytest.raises(ToolError, match="part"):
        kit.sessions_read.func(talk, "chat-1", part="everything")


def test_she_searches_the_plain_turns_of_her_other_chats(brain, talk):
    found = kit.sessions_search.func(talk, "OAT milk")
    assert found.splitlines() == ['chat-1 "Groceries" #2 user: add oat milk', 'chat-1 "Groceries" #2 you: Added oat milk.']
    assert "No turn" in kit.sessions_search.func(talk, "hello")  # only in this chat, which she has
    with pytest.raises(ToolError):
        kit.sessions_search.func(talk, " ")


def test_she_renames_and_deletes_asking_first(brain, talk):
    assert kit.session_rename.func(talk, "chat-2", "Lisbon trip") == 'Renamed chat-2 to "Lisbon trip".'
    assert brain.store.notifications("talk")[-1]["type"] == "session.titled"
    assert kit.session_delete.policy == "always" and kit.session_delete.rule_arg == "session"
    with pytest.raises(ToolError, match="the one you are in"):
        kit.session_delete.func(talk, "main")
    busy = brain.store.add_run("talk", "chat-2", "turn", {}, status="working")
    with pytest.raises(ToolError, match="working in it"):
        kit.session_delete.func(talk, "chat-2")
    brain.store.update_run(busy, status="completed")
    assert kit.session_delete.func(talk, "Lisbon trip") == 'Deleted chat-2 "Lisbon trip" and its history.'
    assert "chat-2" not in [s["id"] for s in brain.client.sessions("talk")]
    assert brain.store.notifications("talk")[-1]["type"] == "session.deleted"


def test_deleting_a_chat_asks_even_when_a_rule_allows_it(brain, talk):
    brain.client.update_app("talk", rules={"allow": ["session_delete"]})
    brain.store.update_run(talk.run["id"], status="completed")
    asked = []
    brain.provider.replies += [tool_call("session_delete", {"session": "chat-1"}, "d1"), "Kept it."]
    turn(brain, "talk", "delete the groceries chat", on_approval=lambda request: asked.append(request) or "deny")
    assert asked and asked[0]["always_ask"] is True
    assert "chat-1" in [s["id"] for s in brain.client.sessions("talk")]
