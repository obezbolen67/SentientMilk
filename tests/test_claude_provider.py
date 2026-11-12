"""She thinks with Claude through the user's Claude Code (claude_provider.py), here the stand-in (fake_claude.py)
through the real loop: her tools through the host's MCP server, approvals, warm conversations, going on after a
restart, a record when nothing goes on, one-off helper calls, and Claude Code's own words for what went wrong."""

import json
from types import SimpleNamespace

import pytest
from conftest import claude_log, claude_starts, turn, wait_for

from sentientmilk_framework import BrainError
from sentientmilk_framework.claude_provider import RECORD, key, record
from sentientmilk_framework.transport import OMITTED_IMAGE


@pytest.fixture
def claude(brain, tmp_path):
    brain.client.update_config(provider="claude_code")
    brain.brain.claude.info()
    log = lambda: claude_log(tmp_path)  # noqa: E731
    return SimpleNamespace(
        log=log, said=lambda: [e["said"] for e in log() if "said" in e],
        starts=lambda: [s for s in claude_starts(tmp_path) if s["provider"]],
        once=lambda: [s for s in claude_starts(tmp_path) if "--no-session-persistence" in s["args"]])


def text(content) -> str:
    return content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content)


def test_she_thinks_with_claude_code_and_only_with_what_sentientmilk_gives_it(brain, claude):
    events = []
    result = brain.client.turn("cli", "main", "hello there", on_event=events.append)
    assert result["reply"] == "echo: hello there"
    assert "".join(e["text"] for e in events if e["type"] == "text.delta") == "echo: hello there"  # streamed
    usage = brain.store.run(result["run"])["usage"]
    assert (usage["prompt_tokens"], usage["cached_tokens"], usage["completion_tokens"]) == (103, 90, 7)
    [started] = claude.starts()
    args = started["args"]
    for flag in ("--safe-mode", "--restricted", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in args  # none of the user's CLAUDE.md, settings, plugins or MCP servers
    assert args[args.index("--tools") + 1] == "" and args[args.index("--model") + 1] == "default"
    assert args[args.index("--effort") + 1] == "medium"
    assert "In this app you are called CLI" in started["system"]  # her own prompt, from a file
    tools = next(e["tools"] for e in claude.log() if "tools" in e)
    assert "files_read" in tools and "shell_run" in tools and "tools_search" not in tools  # all of hers, none deferred


def test_her_tools_run_in_the_brain_and_their_results_go_back_to_the_same_claude_code(brain, claude):
    (brain.work / "a.txt").write_text("apple pie", encoding="utf-8")
    result = turn(brain, "cli", 'CALL files_read {"path": "a.txt"}')
    assert "apple pie" in result["reply"] and result["reply"].startswith("result: ")
    tools = [e for e in brain.store.run_events(result["run"]) if e["type"] == "tool"]
    assert [(t["name"], t["status"]) for t in tools] == [("files_read", "ok")]  # named as hers, not mcp__milk__
    assert len(claude.starts()) == 1  # the result went to the Claude Code that called it


def test_the_next_turn_goes_on_in_the_warm_claude_code(brain, claude):
    turn(brain, "cli", "first")
    second = turn(brain, "cli", "second")
    assert second["reply"] == "echo: second" and len(claude.starts()) == 1
    assert "second" in text(claude.said()[-1]) and RECORD not in text(claude.said()[-1])  # only what is new


def test_an_approval_holds_her_call_while_claude_code_waits_and_what_came_meanwhile_reaches_it(brain, claude):
    def approve(event):
        brain.brain.note("cli", "main", "The user also said: keep it short.")  # comes while the call waits
        return "allow"

    result = brain.client.turn("cli", "main", 'CALL files_write {"path": "b.txt", "content": "made"}',
                               on_approval=approve)
    assert (brain.work / "b.txt").read_text(encoding="utf-8") == "made"
    assert "then: [Note: The user also said: keep it short.]" in result["reply"]  # after the result, as the user's
    assert len(claude.starts()) == 1


def test_after_a_restart_her_conversation_goes_on_in_claude_codes_session(brain, claude):
    turn(brain, "cli", "remember the plum")
    claude_code = brain.brain.claude
    claude_code.close()  # the brain stops: its Claude Code ends, where the turn ended is kept on disk
    assert not list(claude_code.folder.glob("*.md"))  # and its prompt file is gone with it (live, one was left)
    claude_code.conversations = None  # as a new brain would start
    result = turn(brain, "cli", "what did I say?")
    assert result["reply"] == "resumed echo: what did I say?"
    first, then = claude.starts()
    assert "--resume" not in first["args"]
    assert then["args"][then["args"].index("--resume") + 1].startswith("claude-session-")
    assert RECORD not in text(claude.said()[-1])


def test_a_conversation_that_cannot_go_on_starts_from_a_record_of_it(brain, claude):
    """Thought with an API service until now (or cleared, compacted, returned to before): a new session."""
    brain.client.update_config(provider="api")
    brain.provider.replies += ["Hi from the API."]
    turn(brain, "cli", "hello api")
    brain.client.update_config(provider="claude_code")
    result = turn(brain, "cli", "and now?")
    first = text(claude.said()[0])
    assert first.startswith(RECORD) and "hello api" in first and "<you>\nHi from the API.\n</you>" in first
    assert result["reply"] == "echo: and now?"  # the new message after the record


def test_her_helpers_are_one_off_calls_on_the_helper_model(brain, claude):
    turn(brain, "cli", "name this chat")
    once = wait_for(claude.once)
    args = once[0]["args"]
    assert args[args.index("--model") + 1] == "haiku" and "--effort" not in args  # Haiku 9 takes no effort
    assert "--mcp-config" not in args
    wait_for(lambda: brain.store.session("cli", "main")["settings"].get("title"))


def test_an_apps_own_model_is_an_api_services_so_claude_code_thinks_with_its_own(brain, claude):
    brain.client.update_app("cli", model="deepseek-v9")
    turn(brain, "cli", "hi")
    args = claude.starts()[0]["args"]
    assert args[args.index("--model") + 1] == "default"


def test_claude_codes_words_for_what_went_wrong(brain, claude, monkeypatch):
    with pytest.raises(BrainError) as caught:
        turn(brain, "cli", "LIMIT please")
    assert caught.value.type == "plan_limit" and "resets at" in caught.value.details

    monkeypatch.setenv("FAKE_SIGNED_OUT", "1")
    assert brain.client.claude_code(refresh=True)["signed_in"] is False
    started = len(claude.starts())
    with pytest.raises(BrainError) as caught:
        turn(brain, "cli", "hello")
    assert caught.value.type == "claude_code" and caught.value.message == "Claude Code is not signed in"
    assert "/login" in caught.value.details and len(claude.starts()) == started  # nothing started to fail

    monkeypatch.setattr(brain.brain.claude, "argv", lambda: [])
    with pytest.raises(BrainError, match="not installed"):
        turn(brain, "cli", "hello")


def test_stopping_her_turn_ends_its_claude_code(brain, claude):
    result = {}

    def go():
        try:
            result["done"] = turn(brain, "cli", "be slow")
        except BrainError as exc:
            result["error"] = exc

    import threading
    worker = threading.Thread(target=go)
    worker.start()
    run = wait_for(lambda: brain.store.runs(kind="turn", statuses=("working",)))[0]
    pool = wait_for(lambda: brain.brain.claude.conversations)
    wait_for(lambda: pool.live and pool.live[0].alive())
    brain.client.cancel(run["id"])
    worker.join(15)
    wait_for(lambda: not pool.live)  # dropped and ended: nothing goes on with it


def test_what_claude_code_says_about_itself(brain, claude):
    status = brain.client.claude_code()
    assert status["version"] == "9.9.9" and status["signed_in"] and status["account"]["plan"] == "Claude Max"
    models = {m["value"]: m for m in status["models"]}
    assert models["default"]["label"] == "Default (Opus 9)" and models["haiku"]["efforts"] == []
    assert models["sonnet"]["efforts"] == ["low", "medium", "high"]
    assert brain.brain.claude.effort("sonnet", "max") == "high"


def test_a_message_is_known_by_what_it_says_not_by_how_its_pictures_were_sent():
    picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    smaller = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BB"}}
    sent = {"role": "user", "content": [{"type": "text", "text": "look"}, picture]}
    assert key(sent) == key({"role": "user", "content": [{"type": "text", "text": "look"}, smaller]})
    assert key(sent) == key({"role": "user", "content": "look\n" + OMITTED_IMAGE})  # dropped later
    assert key(sent) != key({"role": "user", "content": "look again"})
    call = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "t1", "type": "function", "function": {"name": "a", "arguments": json.dumps({"x": 1})}}]}
    assert key(call) != key({**call, "tool_calls": [{**call["tool_calls"][0], "id": "t2"}]})


def test_a_record_shows_what_came_before_and_sends_whats_new_as_it_is():
    picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    blocks = record([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "files_read", "arguments": '{"path": "a"}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "A"},
        {"role": "user", "content": [{"type": "text", "text": "this"}, picture]}])
    assert blocks[0]["text"].startswith(RECORD)
    assert '<call tool="files_read" id="t1">{"path": "a"}</call>' in blocks[0]["text"]
    assert '<result id="t1">\nA\n</result>' in blocks[0]["text"]
    assert blocks[1:] == [{"type": "text", "text": "this"},
                          {"type": "image", "source": {"type": "base64", "data": "AAAA", "media_type": "image/png"}}]
