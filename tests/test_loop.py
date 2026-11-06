import json

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import BrainError, context
from sentientmilk_framework import loop as loop_module
from sentientmilk_framework.loop import INTERRUPTED_CALL
from sentientmilk_framework.testing import tool_call, tool_calls
from sentientmilk_framework.toolkits import Tool, Toolkit


def tool_results(payload):
    return {m["tool_call_id"]: m["content"] for m in payload["messages"] if m["role"] == "tool"}


def test_tools_run_and_their_results_reach_the_model(brain):
    (brain.work / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    brain.provider.replies += [tool_call("files_read", {"path": "notes.txt"}, "c1"), "It says alpha and beta."]
    result = turn(brain, "cli", "what is in notes.txt?")
    assert result["reply"] == "It says alpha and beta."
    assert [t["status"] for t in result["tools"]] == ["completed"]
    assert "     1\talpha" in tool_results(brain.provider.sent[1])["c1"]
    assert [e["type"] for e in result["events"] if e["type"].startswith("tool")] == ["tool.start", "tool.end"]


def test_read_only_calls_in_one_message_all_run(brain):
    for name in "abc":
        (brain.work / f"{name}.txt").write_text(name * 3, encoding="utf-8")
    brain.provider.replies += [tool_calls(*[("files_read", {"path": f"{n}.txt"}) for n in "abc"]), "read all three"]
    turn(brain, "cli", "read them")
    results = tool_results(brain.provider.sent[1])
    assert sorted(results) == ["call_0_files_read", "call_1_files_read", "call_2_files_read"]
    assert all("aaa" in v or "bbb" in v or "ccc" in v for v in results.values())


def test_risky_tools_wait_for_approval_and_a_denial_reaches_the_model(brain):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo hi"}, "s1"), "ok, I will not"]
    asked = []
    result = brain.client.turn("cli", "main", "say hi in the shell",
                               on_approval=lambda event: asked.append(event) or ("deny", "not now"))
    assert asked[0]["name"] == "shell_run" and result["reply"] == "ok, I will not"
    assert "did not allow" in tool_results(brain.provider.sent[1])["s1"] and "not now" in tool_results(
        brain.provider.sent[1])["s1"]


def test_allow_always_saves_a_rule_for_the_app(brain):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo one"}, "s1"), "done",
                               tool_call("shell_run", {"command": "echo one"}, "s2"), "done again"]
    brain.client.turn("cli", "main", "go", on_approval=lambda event: "always")
    assert brain.client.app("cli")["settings"]["rules"]["allow"] == ["shell_run(echo one)"]
    asked = []
    brain.client.turn("cli", "main", "again", on_approval=lambda event: asked.append(event) or "deny")
    assert asked == [] and "one" in tool_results(brain.provider.sent[3])["s2"]


def test_app_actions_run_in_the_app(brain):
    brain.client.declare_app("bot", name="Bot", toolkits=[], actions=[
        {"name": "wave", "description": "Wave at the user.", "parameters": {
            "type": "object", "properties": {"times": {"type": "integer"}}}}])
    brain.provider.replies += [tool_call("wave", {"times": 2}, "w1"), "I waved."]

    def on_event(event):
        if event["type"] == "action.requested":
            brain.client.answer(event["run"], call_id=event["call_id"], result=f"waved {event['arguments']['times']}x")

    assert brain.client.turn("bot", "main", "wave!", on_event=on_event)["reply"] == "I waved."
    assert tool_results(brain.provider.sent[1])["w1"] == "waved 2x"
    assert brain.provider.sent[0]["tools"][0]["function"]["name"] == "wave"


def test_a_new_turn_gives_up_a_turn_still_waiting_for_approval(brain):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo x"}, "s1"), "moving on"]
    run_id, listener = brain.brain.runs.start_turn("cli", "main", [{"type": "text", "text": "do it"}], {})
    wait_for(lambda: brain.store.run(run_id)["status"] == "input_required")
    assert turn(brain, "cli", "never mind")["reply"] == "moving on"
    assert brain.store.run(run_id)["status"] == "cancelled"
    messages = brain.provider.sent[1]["messages"]
    assert any(m["role"] == "tool" and m["tool_call_id"] == "s1" for m in messages)  # history stays valid


def test_after_a_crash_side_effects_are_not_repeated_blindly(brain):
    store = brain.store
    run = store.add_run("cli", "task-x", "task", {"goal": "g", "profile": {"from_session": "main"}}, status="working")
    store.add_event("cli", "task-x", run, "input", {"content": "do the thing", "display": "do the thing"})
    store.add_event("cli", "task-x", run, "assistant", {"message": tool_calls(
        ("shell_run", {"command": "rm -rf build"}), ("files_find", {"pattern": "*"})), "usage": {}})
    store.add_event("cli", "task-x", run, "tool_start", {"call_id": "call_0_shell_run", "name": "shell_run"})
    store.add_event("cli", "task-x", run, "tool_start", {"call_id": "call_1_files_find", "name": "files_find"})
    brain.provider.replies.append("checked and finished")
    brain.brain.runs.recover()
    wait_for(lambda: store.run(run)["status"] == "completed")
    results = tool_results(brain.provider.sent[0])
    assert results["call_0_shell_run"] == INTERRUPTED_CALL  # not run again
    assert "No files match" in results["call_1_files_find"] or "\n" in results["call_1_files_find"]


def test_an_interrupted_turn_ends_failed_and_history_stays_valid(brain):
    store = brain.store
    run = store.add_run("cli", "main", "turn", {}, status="working")
    store.add_event("cli", "main", run, "input", {"content": "hi", "display": "hi"})
    store.add_event("cli", "main", run, "assistant", {"message": tool_call("files_find", {"pattern": "*"}, "f1"),
                                                      "usage": {}})
    brain.brain.runs.recover()
    assert store.run(run)["status"] == "failed" and store.run(run)["error"]["type"] == "interrupted"
    brain.provider.replies.append("hello again")
    turn(brain, "cli", "hello?")
    assert tool_results(brain.provider.sent[0])["f1"] == context.INTERRUPTED


def test_old_tool_results_are_cleared_in_batches_with_a_way_back(brain):
    brain.client.update_config(context_window=8000)
    for index in range(14):
        (brain.work / f"f{index}.txt").write_text("\n".join([f"file {index}"] + ["y" * 99] * 18), encoding="utf-8")
    brain.provider.replies += [tool_call("files_read", {"path": f"f{i}.txt"}, f"r{i}") for i in range(14)] + ["ok"]
    turn(brain, "cli", "read them all")
    clearings = brain.store.events("cli", "main", types=("clearing",))
    assert 1 <= len(clearings) <= 4  # in batches, not at every step
    results = tool_results(brain.provider.sent[-1])
    assert results["r0"] == context.CLEARED.format(name="files_read")
    assert "file 13" in results["r13"]


def test_a_long_session_is_compacted_into_a_summary(brain):
    brain.client.update_config(context_window=8000)
    line = "x" * 99
    for index in range(10):
        (brain.work / f"f{index}.txt").write_text("\n".join([f"file {index}"] + [line] * 40), encoding="utf-8")
    planned = iter([tool_call("files_read", {"path": f"f{i}.txt"}, f"r{i}") for i in range(10)] + ["all read"])

    def reply(payload):
        if payload["messages"][0]["content"] == context.COMPACT_PROMPT:
            return "SUMMARY: reading the files one by one"
        return next(planned)

    brain.provider.replies += [reply] * 20
    assert turn(brain, "cli", "read every file")["reply"] == "all read"
    assert "compaction" in [e["type"] for e in brain.store.events("cli", "main")]
    summary_request = next(p for p in brain.provider.sent if p["messages"][0]["content"] == context.COMPACT_PROMPT)
    assert "read every file" in summary_request["messages"][1]["content"]
    after = next(p for p in brain.provider.sent[brain.provider.sent.index(summary_request) + 1:])
    assert after["messages"][1]["content"].startswith(context.SUMMARY_PREFIX + "SUMMARY: reading the files")
    assert "## Files you read recently" in after["messages"][1]["content"]
    assert len(brain.store.events("cli", "main", types=("tool",))) == 10  # the raw log keeps everything


def test_projection_never_puts_notes_between_a_call_and_its_result():
    events = [
        {"id": 1, "type": "input", "content": "go"},
        {"id": 2, "type": "assistant", "message": tool_call("files_find", {"pattern": "*"}, "a")},
        {"id": 3, "type": "note", "text": "job finished"},
        {"id": 4, "type": "tool", "call_id": "a", "name": "files_find", "content": "x"},
        {"id": 5, "type": "input", "content": "next"},
    ]
    roles = [m["role"] for m in context.project(events, None)]
    assert roles == ["user", "assistant", "tool", "user"]
    assert context.project(events, None)[-1]["content"] == "[Note: job finished]\n\nnext"


def test_many_mcp_tools_are_listed_and_called_through_tools_call(brain, monkeypatch):
    calls = []
    many = [Tool(name=f"mcp__big__t{i}", description=f"Tool number {i}.", toolkit="mcp:big",
                 parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
                 func=lambda ctx, x=0, i=i: calls.append((i, x)) or f"t{i} got {x}", policy="auto")
            for i in range(50)]
    monkeypatch.setattr(brain.brain.mcp, "toolkits", lambda: {"mcp:big": Toolkit("mcp:big", "big", many)})
    monkeypatch.setattr(brain.brain.mcp, "servers", lambda: ["big"])
    brain.client.declare_app("big", toolkits=["memory", "mcp:*"])
    brain.provider.replies += [tool_call("tools_describe", {"names": ["mcp__big__t7"]}, "d"),
                               tool_call("tools_call", {"name": "mcp__big__t7", "arguments": {"x": 3}}, "c"), "done"]
    turn(brain, "big", "use t7")
    names = [t["function"]["name"] for t in brain.provider.sent[0]["tools"]]
    assert "tools_call" in names and "mcp__big__t7" not in names
    assert "mcp__big__t7: Tool number 7." in brain.provider.sent[0]["messages"][0]["content"]
    assert '"x"' in tool_results(brain.provider.sent[1])["d"]
    assert calls == [(7, 3)] and tool_results(brain.provider.sent[2])["c"] == "t7 got 3"


def test_the_step_budget_stops_runaway_loops(brain, monkeypatch):
    monkeypatch.setitem(loop_module.STEP_BUDGET, "turn", 3)
    brain.provider.replies += [tool_call("files_find", {"pattern": f"*{i}"}, f"x{i}") for i in range(5)]
    with pytest.raises(BrainError) as caught:
        brain.client.turn("cli", "main", "loop forever")
    assert caught.value.type == "budget"


def test_helpers_investigate_with_read_only_tools_and_report(brain):
    (brain.work / "a.py").write_text("def answer():\n    return 42\n", encoding="utf-8")

    def helper_or_main(payload):
        names = [t["function"]["name"] for t in payload.get("tools") or []]
        if "HELPER" in payload["messages"][0]["content"]:
            assert "files_edit" not in names and "shell_run" not in names and "agent_run" not in names
            if not any(m["role"] == "tool" for m in payload["messages"]):
                return tool_call("files_search", {"pattern": "return"}, "h1")
            return "answer() in a.py returns 42 (line 2)."
        return tool_call("agent_run", {"goal": "Find what answer() returns."}, "a1")

    brain.provider.replies += [helper_or_main, helper_or_main, helper_or_main, "It returns 42."]
    assert turn(brain, "cli", "what does answer() return?")["reply"] == "It returns 42."
    assert tool_results(brain.provider.sent[-1])["a1"] == "answer() in a.py returns 42 (line 2)."
    assert any(r["kind"] == "subagent" and r["status"] == "completed" for r in brain.store.runs())


def test_reasoning_is_passed_back_with_tool_loops(brain):
    message = tool_call("files_find", {"pattern": "*"}, "f1")
    message["reasoning_content"] = "I should look around first."
    brain.provider.replies += [message, "nothing here"]
    turn(brain, "cli", "look")
    assistant = next(m for m in brain.provider.sent[1]["messages"] if m["role"] == "assistant")
    assert assistant["reasoning_content"] == "I should look around first."


def test_usage_and_cache_hits_are_counted(brain):
    brain.provider.replies += ["one"]
    turn(brain, "cli", "hi")
    stats = brain.client.stats()["apps"]["cli"]
    assert stats["prompt_tokens"] == 100 and stats["cached_tokens"] == 60 and stats["cache_hit_rate"] == 0.6
    assert json.loads(json.dumps(stats))
