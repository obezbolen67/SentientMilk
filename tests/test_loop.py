import base64
import io
import json
import threading
import time

import pytest
from conftest import turn, wait_for
from PIL import Image

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
    asked = []

    def wave(event):
        asked.append(event["name"])
        return f"waved {event['arguments']['times']}x"

    assert brain.client.turn("bot", "main", "wave!", on_action=wave)["reply"] == "I waved."
    assert asked == ["wave"] and tool_results(brain.provider.sent[1])["w1"] == "waved 2x"
    assert brain.provider.sent[0]["tools"][0]["function"]["name"] == "wave"


def test_an_action_can_answer_with_a_picture_the_model_then_sees(brain):
    brain.client.declare_app("eye", name="Eye", toolkits=["tasks"], actions=[
        {"name": "screenshot", "description": "See the screen.", "readonly": True}])
    picture = Image.effect_noise((1600, 900), 60).convert("RGB")
    output = io.BytesIO()
    picture.save(output, "PNG")
    shot = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    brain.provider.replies += [tool_call("screenshot", {}, "s1"), "I see noise.",
                               tool_call("screenshot", {}, "s2"), "I could not look."]

    assert brain.client.turn("eye", "main", "what's on my screen?",
                             on_action=lambda event: ("The screen now.", [shot]))["reply"] == "I see noise."
    first, second = brain.provider.sent[0], brain.provider.sent[1]
    assert not any(b.get("type") == "image_url" for m in first["messages"] if isinstance(m["content"], list)
                   for b in m["content"])  # nothing is sent before the model asks
    assert tool_results(second)["s1"] == "The screen now."
    after = second["messages"][-1]
    assert after["role"] == "user" and after["content"][1]["type"] == "image_url"
    sent = after["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(sent.split(",", 1)[1]))) as seen:
        assert max(seen.size) <= 768  # stored small, like the images of a turn's input

    def broken(event):
        raise RuntimeError("the screen is locked")

    assert brain.client.turn("eye", "main", "and now?", on_action=broken)["reply"] == "I could not look."
    assert "the screen is locked" in tool_results(brain.provider.sent[3])["s2"]
    task = brain.client.start_task("eye", "summarize nothing", session="main")
    brain.provider.replies.append("done")
    wait_for(lambda: brain.client.run(task["id"])["status"] == "completed")
    assert "screenshot" not in [t["function"]["name"] for t in brain.provider.sent[-1].get("tools", [])]


def test_an_answer_that_comes_while_other_tools_still_run_is_kept(brain, monkeypatch):
    """The app answers an action at once; the brain is still running a slow tool of the same step."""
    from sentientmilk_framework.toolkits import memory as memory_kit

    real = memory_kit.memory_list.func

    def slow(ctx, category=""):
        time.sleep(1)
        return real(ctx, category)

    monkeypatch.setattr(memory_kit.memory_list, "func", slow)
    brain.client.declare_app("eye", name="Eye", toolkits=["memory"], actions=[
        {"name": "screenshot", "description": "See the screen.", "readonly": True}])
    brain.provider.replies += [tool_calls(("memory_list", {}), ("screenshot", {})), "Seen and listed."]
    assert brain.client.turn("eye", "main", "look", on_action=lambda event: "a chart")["reply"] == "Seen and listed."
    results = tool_results(brain.provider.sent[1])
    assert results["call_1_screenshot"] == "a chart" and "memory_list" not in results["call_1_screenshot"]


def test_an_action_that_asks_waits_for_the_users_approval_first(brain):
    brain.client.declare_app("hands", name="Hands", toolkits=[], actions=[
        {"name": "press", "description": "Press a button.", "policy": "ask",
         "parameters": {"type": "object", "properties": {"button": {"type": "string"}}}}])
    pressed, asked = [], []

    def approve(decision):
        def answer(event):
            asked.append(event["name"])
            return decision
        return answer

    brain.provider.replies += [tool_call("press", {"button": "a"}, "p1"), "Not allowed.",
                               tool_call("press", {"button": "b"}, "p2"), "Pressed b.",
                               tool_call("press", {"button": "c"}, "p3"), "Pressed c."]
    run = lambda text, decision: brain.client.turn(  # noqa: E731
        "hands", "main", text, on_approval=approve(decision), on_action=lambda e: pressed.append(e["arguments"]))
    assert run("press a", "deny")["reply"] == "Not allowed."
    assert pressed == [] and "did not allow" in tool_results(brain.provider.sent[1])["p1"]
    assert run("press b", "always")["reply"] == "Pressed b." and pressed == [{"button": "b"}]
    assert run("press c", "deny")["reply"] == "Pressed c."  # "always" saved a rule: not asked again
    assert asked == ["press", "press"] and pressed[-1] == {"button": "c"}
    with pytest.raises(BrainError):
        brain.client.declare_app("bad", name="Bad", actions=[{"name": "x", "policy": "sometimes"}])


def test_a_stop_while_the_model_writes_ends_the_turn_where_it_is(brain):
    started = threading.Event()
    run = {}

    def writing(_payload):
        started.wait(5)
        brain.client.cancel(run["id"])  # the user presses Stop as the reply starts coming
        return "A long story that is never told to its end."

    brain.provider.replies.append(writing)
    run["id"], _listener = brain.brain.runs.start_turn("cli", "main", [{"type": "text", "text": "a story"}], {})
    started.set()
    wait_for(lambda: brain.store.run(run["id"])["status"] in loop_module.TERMINAL)
    assert brain.store.run(run["id"])["status"] == "cancelled"
    assert not any(e["type"] == "assistant" for e in brain.store.run_events(run["id"]))  # nothing half-said is kept


def test_a_stop_while_an_approval_waits_ends_the_turn_quietly(brain):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo x"}, "s1"), "ran it"]

    def stop_then_deny(event):  # the app denies what was asked once the user stopped: the run has ended by then
        brain.client.cancel(event["run"])
        wait_for(lambda: brain.store.run(event["run"])["status"] == "cancelled")
        return "deny"

    result = turn(brain, "cli", "run echo", on_approval=stop_then_deny)
    assert result["status"] == "cancelled" and result["reply"] == ""


def test_a_stop_as_the_turn_is_about_to_wait_for_approval_still_ends_it(brain, monkeypatch):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo x"}, "s1"), "ran it"]
    real = loop_module.Loop._run_tools

    def stop_first(self, run, *args):  # Stop lands while the run still works, just before it waits
        brain.brain.runs.cancel(run["id"])
        return real(self, run, *args)

    monkeypatch.setattr(loop_module.Loop, "_run_tools", stop_first)

    def deny_once_stopped(event):
        wait_for(lambda: brain.store.run(event["run"])["status"] == "cancelled", timeout=5)
        return "deny"

    assert turn(brain, "cli", "run echo", on_approval=deny_once_stopped)["status"] == "cancelled"


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
    streamed = turn(brain, "cli", "read them all")["events"]
    clearings = brain.store.events("cli", "main", types=("clearing",))
    assert 1 <= len(clearings) <= 4  # in batches, not at every step
    told = [e for e in streamed if e["type"] == "cleared"]  # apps can show it (MilkChan draws it)
    assert len(told) == len(clearings) and told[0]["results"] == len(clearings[0]["ids"])
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
    result = turn(brain, "cli", "read every file")
    assert result["reply"] == "all read"
    kinds = [e["type"] for e in result["events"]]
    assert "compacting" in kinds and kinds.index("compacting") < kinds.index("compacted")  # apps see it start
    assert "compaction" in [e["type"] for e in brain.store.events("cli", "main")]
    summary_request = next(p for p in brain.provider.sent if p["messages"][0]["content"] == context.COMPACT_PROMPT)
    transcript = summary_request["messages"][1]["content"]
    assert "read every file" in transcript and "\nYOU:" in transcript and "ASSISTANT" not in transcript
    assert "AI assistant" not in context.COMPACT_PROMPT  # the summary speaks to her, not about "the assistant"
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

    # An app gives a long turn more steps (computer use); the server takes no more than a task's.
    brain.provider.replies.clear()
    brain.provider.replies += [tool_call("files_find", {"pattern": f"*{i}"}, f"y{i}") for i in range(4)] + ["done"]
    assert brain.client.turn("cli", "main", "five steps", max_steps=5)["reply"] == "done"
    for wrong in (10_000, "9"):
        with pytest.raises(BrainError) as caught:
            brain.client.turn("cli", "main", "too many", max_steps=wrong)
        assert caught.value.type == "bad_request"


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


def test_reasoning_is_passed_back_with_tool_loops_and_not_into_the_next_turn(brain):
    message = tool_call("files_find", {"pattern": "*"}, "f1")
    message["reasoning_content"] = "I should look around first."
    brain.provider.replies += [message, "nothing here", "hello"]
    turn(brain, "cli", "look")
    assistant = next(m for m in brain.provider.sent[1]["messages"] if m["role"] == "assistant")
    assert assistant["reasoning_content"] == "I should look around first."
    turn(brain, "cli", "hi")
    earlier = [m for m in brain.provider.sent[-1]["messages"] if m["role"] == "assistant"]
    assert earlier and not any(m.get("reasoning_content") for m in earlier)


def test_reasoning_stays_through_steering_in_its_run():
    """A steering message joins the running turn: its tool loop still needs its reasoning."""
    def said(run, text):
        return {"id": 0, "run": run, "type": "assistant", "message": {"content": text, "reasoning_content": "why " + text}}
    events = [{"id": 1, "run": 1, "type": "input", "content": "first"}, said(1, "a"),
              {"id": 2, "run": 2, "type": "input", "content": "second"}, said(2, "b"),
              {"id": 3, "run": 2, "type": "input", "content": "steer"}, said(2, "c")]
    sent = [m for m in context.project(events, None) if m["role"] == "assistant"]
    assert [m.get("reasoning_content") for m in sent] == [None, "why b", "why c"]


def test_usage_and_cache_hits_are_counted(brain):
    brain.provider.replies += ["one"]
    turn(brain, "cli", "hi")
    stats = brain.client.stats()["apps"]["cli"]
    assert stats["prompt_tokens"] == 100 and stats["cached_tokens"] == 60 and stats["cache_hit_rate"] == 0.6
    assert json.loads(json.dumps(stats))
