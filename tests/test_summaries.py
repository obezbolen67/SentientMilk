"""She goes over a conversation as it ends and keeps what matters with memory_save (summaries.py): as herself,
out of the conversation's sight, never twice over the same part, and not over a short chat."""

import json

from conftest import MILK, turn, wait_for

from sentientmilk_framework import mentions, summaries
from sentientmilk_framework.testing import tool_call

SMILE = '{"expression": "arms_down/smile"}\n'
HOME = {"key": "home_city", "value": "Illia lives in Kraków.", "category": "user"}
TONE = {"key": "tone", "value": "I settled on short answers in this chat.", "scope": "session"}


def chat(brain, session, messages=summaries.MESSAGES):
    for index in range(messages):
        brain.provider.replies.append(SMILE + f"Reply {index}.")
        turn(brain, "milk", f"message {index}", session=session)


def keeps(brain, *saves):
    """What she answers going over a conversation: these memory_save calls, then a line."""
    brain.provider.replies += [tool_call("memory_save", save, f"m{index}") for index, save in enumerate(saves)]
    brain.provider.replies.append("Kept where Illia lives and how I answer here.")


def mark(brain, session):
    return brain.store.find_session("milk", session)["state"].get("summarized")


def test_she_goes_over_a_conversation_as_herself_and_keeps_what_matters(brain):
    brain.client.declare_app("milk", **{**MILK, "toolkits": MILK["toolkits"] + ["files", "shell"]})
    brain.store.remember("milk", "user", "name", "Illia")
    chat(brain, "chat-1")
    shown, sent = brain.client.history("milk", "chat-1", tools=True), len(brain.provider.sent)
    keeps(brain, HOME, TONE)
    (run,) = brain.brain.summaries.go_over("milk", "chat-1")
    assert run["status"] == "completed" and run["kind"] == "summary" and run["session"] == f"summary-{run['id']}"

    asked = brain.provider.sent[sent]
    assert asked["model"] == brain.provider.sent[0]["model"]  # the conversation's own model
    system = asked["messages"][0]["content"]
    assert "You are Milk." in system and "name: Illia" in system  # her persona, and what she knows already
    assert [tool["function"]["name"] for tool in asked["tools"]] == ["memory_save"]  # no files, no shell
    said = json.dumps(asked["messages"][-1], ensure_ascii=False)
    assert "USER: message 0" in said and "YOU: Reply 3." in said

    assert brain.client.memory()["user"] == {"name": "Illia", "home_city": "Illia lives in Kraków."}
    assert brain.client.session("milk", "chat-1")["session_memory"] == {"tone": TONE["value"]}  # the chat's own
    newest = brain.store.events("milk", "chat-1")[-1]
    assert mark(brain, "chat-1") == {"event": newest["id"], "at": newest["at"]}
    assert brain.client.history("milk", "chat-1", tools=True) == shown  # nothing shows in the conversation
    assert [found["id"] for found in mentions.chats(brain.brain, "milk")] == ["chat-1"]  # hers are no chat

    brain.provider.replies.append(SMILE + "Hi again.")
    turn(brain, "milk", "back again", session="chat-1")
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert HOME["value"] in system and TONE["value"] in system  # its next turn knows what she kept
    assert not [e for e in brain.store.events("milk", "chat-1", after=newest["id"]) if e["type"] == "note"]


def test_nothing_new_or_a_short_chat_is_not_gone_over_again(brain):
    chat(brain, "chat-1")
    keeps(brain, HOME)
    assert len(brain.brain.summaries.go_over("milk", "chat-1")) == 1
    sent = len(brain.provider.sent)
    assert brain.brain.summaries.go_over("milk", "chat-1") == []  # nothing new
    assert brain.client.summarize_session("milk", "chat-1") == {"queued": False, "messages": 0}
    chat(brain, "chat-1", messages=summaries.MESSAGES - 1)  # a little more: not yet
    assert brain.client.summarize_session("milk", "chat-1") == {"queued": False, "messages": summaries.MESSAGES - 1}
    assert brain.brain.summaries.go_over("milk", "chat-1") == []
    assert len(brain.provider.sent) == sent + summaries.MESSAGES - 1  # only the chat's own turns asked the model
    assert brain.client.memory()["user"] == {"home_city": HOME["value"]}  # kept once
    chat(brain, "chat-short", messages=2)
    assert brain.client.summarize_session("milk", "chat-short")["queued"] is False
    assert brain.client.summarize_session("milk", "never-used") == {"queued": False, "messages": 0}


def test_at_an_apps_start_she_goes_over_conversations_that_ended_unasked(brain):
    chat(brain, "chat-done")
    keeps(brain)
    brain.brain.summaries.go_over("milk", "chat-done")
    chat(brain, "chat-crashed")  # the app was killed before it said the conversation ended
    chat(brain, "chat-short", messages=1)
    keeps(brain, HOME)
    assert brain.client.summarize_sessions("milk") == {"queued": ["chat-crashed"]}
    assert wait_for(lambda: mark(brain, "chat-crashed"))  # in the background
    assert brain.client.memory()["user"] == {"home_city": HOME["value"]}
    assert brain.client.summarize_sessions("milk") == {"queued": []}  # summary sessions are not conversations


def test_a_summary_never_waits_for_an_answer_and_can_be_switched_off(brain):
    brain.client.update_app("milk", rules={"ask": ["memory_save"]})
    chat(brain, "chat-1")
    keeps(brain, HOME)
    (run,) = brain.brain.summaries.go_over("milk", "chat-1")
    assert run["status"] == "completed" and "user" not in brain.client.memory()  # refused, not waiting
    chat(brain, "chat-2")
    brain.client.update_config(session_summaries=False)
    assert brain.client.summarize_session("milk", "chat-2") == {"queued": False, "messages": 0}


def test_events_after_the_mark_are_found_even_with_an_id_given_out_again(brain):
    chat(brain, "chat-1", messages=1)
    last = brain.store.events("milk", "chat-1")[-1]
    with brain.store._db() as db:  # a return to an earlier message deleted the newest events
        db.execute("DELETE FROM events WHERE id = ?", (last["id"],))
    again = brain.store.add_event("milk", "chat-1", None, "note", {"text": "later"})
    assert again["id"] == last["id"]  # SQLite gave the id out again
    assert [e["id"] for e in brain.store.events_since("milk", "chat-1", last["id"], last["at"])] == [again["id"]]


def test_a_return_keeps_what_she_kept_before_it_and_undoes_what_she_kept_after(brain):
    chat(brain, "chat-1")
    keeps(brain, TONE)
    brain.brain.summaries.go_over("milk", "chat-1")
    chat(brain, "chat-1", messages=1)
    users = [entry["id"] for entry in brain.client.history("milk", "chat-1") if entry["role"] == "user"]
    brain.client.rewind("milk", "chat-1", users[-1])  # after what she went over: what she kept stays
    assert brain.client.session("milk", "chat-1")["session_memory"] == {"tone": TONE["value"]}
    brain.client.rewind("milk", "chat-1", users[1])  # into it: gone with the part she kept it from
    assert brain.client.session("milk", "chat-1")["session_memory"] == {}
