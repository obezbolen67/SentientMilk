"""@ mentions: the cards the brain builds for a session, agent, plugin or file, the matches an app's picker
shows, and mention items in a turn."""

import time

import pytest
from conftest import turn
from test_plugins import make_plugin

from sentientmilk_framework import BrainError, mentions


def chat(brain, session, title, *exchanges, app="cli"):
    brain.client.update_session(app, session, title=title)
    for said, reply in exchanges:
        brain.provider.replies.append(reply)
        turn(brain, app, said, session=session)


def agent(brain, number, name, task, status="completed", report="", parent="main", app="cli"):
    session = f"agent-{number}"
    brain.store.update_session(app, session, "settings", lambda s: {**s, "agent": {
        "name": name, "task": task, "parent": parent, "created": time.time()}})
    run = brain.store.add_run(app, session, "agent", {}, status=status)
    if report:
        brain.store.update_run(run, result={"reply": report})
    return session


def test_a_session_card_brings_its_title_summary_and_last_turns(brain):
    chat(brain, "chat-1", "Groceries", ("plan the week's shopping", "Sure, what do you need?"),
         ("no dairy please", "Noted."), ("add oat milk", "Added. Anything else?"))
    card = mentions.card(brain.brain, "cli", "main", "session", "chat-1")
    assert card.startswith('[Mentioned session "Groceries" (chat-1) · 3 turns · last active ')
    assert "Summary: none yet; it began with: plan the week's shopping" in card
    lines = card.splitlines()
    assert lines[-4:] == ["  user: no dairy please", "  you: Noted.", "  user: add oat milk",
                          "  you: Added. Anything else?"]
    assert "sessions_read" not in card  # the CLI has no sessions toolkit to read more with

    brain.store.add_note("cli", "chat-1", "You planned the week's shopping; the user wants no dairy.", 24_000)
    assert "Summary: You planned the week's shopping; the user wants no dairy." in \
        mentions.card(brain.brain, "cli", "main", "session", "chat-1")
    time.sleep(0.01)
    brain.store.add_event("cli", "chat-1", None, "compaction", {"summary": "A newer summary.", "upto": 0})
    assert "Summary: A newer summary." in mentions.card(brain.brain, "cli", "main", "session", "Groceries")

    brain.client.declare_app("talk", name="Talk", toolkits=["sessions"])
    chat(brain, "chat-2", "Plans", ("hi", "Hello."), app="talk")
    assert 'If this is not enough: sessions_read(session="chat-2", part="turns")' in mentions.card(brain.brain, "talk", "main", "session", "chat-2")
    with pytest.raises(ValueError, match="No session chat-9 here"):
        mentions.card(brain.brain, "cli", "main", "session", "chat-9")


def test_agent_plugin_and_file_cards(brain, tmp_path):
    agent(brain, 4, "grocery-prices", "Find oat milk prices.", report="Oat milk is 2.10 at the corner shop.")
    card = mentions.card(brain.brain, "cli", "main", "agent", "grocery-prices")
    assert card.startswith('[Mentioned agent "grocery-prices" (#4) · done')
    assert "Task: Find oat milk prices." in card and "Report: Oat milk is 2.10" in card
    with pytest.raises(ValueError, match="no agent"):
        mentions.card(brain.brain, "cli", "chat-1", "agent", "grocery-prices")  # another chat's agent

    assert mentions.card(brain.brain, "cli", "main", "plugin", "github").startswith(
        '[Mentioned plugin "github" · on · trusted · 16 tools]')
    brain.client.update_plugin("github", enabled=False)
    assert "· off ·" in mentions.card(brain.brain, "cli", "main", "plugin", "github").splitlines()[0]
    make_plugin(tmp_path / "notes")
    brain.brain.install_plugin(str(tmp_path / "notes"), trusted=False)
    assert "untrusted" in mentions.card(brain.brain, "cli", "main", "plugin", "notes").splitlines()[0]

    text = brain.work / "groceries.txt"
    text.write_text("\n".join(f"item {n}" for n in range(1, 61)), encoding="utf-8")
    card = mentions.card(brain.brain, "cli", "main", "file", str(text))
    assert card.startswith(f"[Mentioned file {text} · ") and "item 40" in card and "item 41" not in card
    (brain.work / "photo.png").write_bytes(b"\x89PNG\0\0\0" * 100)
    assert "binary" in mentions.card(brain.brain, "cli", "main", "file", str(brain.work / "photo.png"))
    folder = mentions.card(brain.brain, "cli", "main", "file", str(brain.work))
    assert folder.startswith(f"[Mentioned folder {brain.work} · 2 entries]") and "groceries.txt" in folder
    with pytest.raises(ValueError, match="SentientMilk's own folder"):
        mentions.card(brain.brain, "cli", "main", "file", str(brain.home / "config.json"))
    with pytest.raises(ValueError, match="no file or folder"):
        mentions.card(brain.brain, "cli", "main", "file", str(brain.work / "nothing.txt"))


def test_matches_for_the_picker(brain):
    chat(brain, "chat-1", "Groceries", ("add oat milk", "Added."))
    chat(brain, "chat-2", "Grocery budget", ("how much", "About 40."))
    chat(brain, "chat-3", "Holidays", ("where to", "Lisbon."))
    agent(brain, 7, "grocery-prices", "Find prices.", status="working")
    found = mentions.candidates(brain.brain, "cli", "chat-3", "groc")
    assert [(m["kind"], m["ref"]) for m in found] == [
        ("session", "chat-2"), ("session", "chat-1")]  # newest first; the agent belongs to main
    assert found[0]["label"] == "Grocery budget" and found[0]["time"] > 0
    in_main = mentions.candidates(brain.brain, "cli", "main", "groc")
    assert ("agent", "grocery-prices") in [(m["kind"], m["ref"]) for m in in_main]
    assert "chat-3" not in [m["ref"] for m in mentions.candidates(brain.brain, "cli", "chat-3", "")]  # the open one
    assert "agent-7" not in [m["ref"] for m in mentions.candidates(brain.brain, "cli", "main", "")]
    plugins = mentions.candidates(brain.brain, "cli", "main", "git", kind="plugin")
    assert plugins[0]["ref"] == "github" and plugins[0]["note"] == "16 tools"
    assert not [m for m in mentions.candidates(brain.brain, "cli", "main", "groc") if m["kind"] == "file"]

    (brain.work / "notes").mkdir()
    (brain.work / "notes.txt").write_text("x", encoding="utf-8")
    (brain.work / "other.txt").write_text("y", encoding="utf-8")
    files = mentions.candidates(brain.brain, "cli", "main", str(brain.work) + "/no")
    assert [(m["label"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1], m["note"]) for m in files] == [
        ("notes", "folder"), ("notes.txt", "1 B")]
    for number in range(8):
        chat(brain, f"chat-1{number}", f"Note {number}", ("x", "y"))
    assert len([m for m in mentions.candidates(brain.brain, "cli", "main", "note") if m["kind"] == "session"]) == 5
    assert len(mentions.candidates(brain.brain, "cli", "main", "note", kind="session")) == 8


def test_a_mention_in_a_message_brings_its_card_and_shows_as_a_chip(brain):
    chat(brain, "chat-1", "Groceries", ("add oat milk", "Added."))
    brain.provider.replies += ["You decided on oat milk.", "It is gone."]
    asked = turn(brain, "cli", "what did we decide in @Groceries?", items=[
        {"type": "mention", "kind": "session", "ref": "chat-1", "label": "Groceries"}])
    assert asked["reply"] == "You decided on oat milk."
    sent = brain.provider.sent[-1]["messages"][-1]["content"]
    assert sent.index("what did we decide in @Groceries?") < sent.index('[Mentioned session "Groceries"')
    entry = brain.client.history("cli", "main")[-2]
    assert entry["text"] == "what did we decide in @Groceries?"
    assert entry["mentions"] == [{"kind": "session", "ref": "chat-1", "label": "Groceries"}]

    turn(brain, "cli", "and @Old?", items=[{"type": "mention", "kind": "session", "ref": "chat-9", "label": "Old"}])
    assert "[Mentioned session chat-9: it no longer exists]" in brain.provider.sent[-1]["messages"][-1]["content"]
    with pytest.raises(BrainError, match="at most 8 mentions"):
        turn(brain, "cli", "many", items=[{"type": "mention", "kind": "session", "ref": "chat-1"}] * 9)
    with pytest.raises(BrainError, match="kind"):
        turn(brain, "cli", "odd", items=[{"type": "mention", "kind": "memory", "ref": "x"}])


def test_the_picker_endpoints(brain):
    chat(brain, "chat-1", "Groceries", ("add oat milk", "Added."))
    found = brain.client.mentions("cli", "groc", session="main")
    assert found[0]["ref"] == "chat-1" and found[0]["kind"] == "session"
    assert brain.client.mentions("cli", "groc", kind="plugin", session="main") == []
    card = brain.client.mention_card("cli", "session", "chat-1", session="main")
    assert card.startswith('[Mentioned session "Groceries"')
    with pytest.raises(BrainError, match="No session chat-9"):
        brain.client.mention_card("cli", "session", "chat-9", session="main")
