"""Stop ends a turn at once, whatever runs: a tool that ignores it, a wait inside a tool, a command, the model,
a helper. A message the user sends while she works (steering) reaches her at her next step; one that comes
as she finishes is handed back as unread, for the app to send as the next turn."""

import json
import os
import re
import threading
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import BrainError
from sentientmilk_framework.testing import tool_call
from sentientmilk_framework.toolkits import Tool, Toolkit
from sentientmilk_framework.toolkits.shell import kill_tree

SECONDS = {"type": "object", "properties": {"seconds": {"type": "number"}}}
SLEEP = "Start-Sleep -Seconds 20" if os.name == "nt" else "sleep 20"


@pytest.fixture
def slow(brain):
    def nap(ctx, seconds: float = 30):  # deaf to the stop
        time.sleep(seconds)
        return "slept"

    def doze(ctx, seconds: float = 30):
        return f"woke: {ctx.interruption()}" if ctx.pause(seconds) else "slept"

    brain.brain.plugins["slow"] = Toolkit("slow", "Slow tools.", [
        Tool("nap", "Sleep.", SECONDS, nap, readonly=True, policy="auto"),
        Tool("doze", "Sleep until woken.", SECONDS, doze, readonly=True, policy="auto")])
    brain.client.declare_app("slow", name="Slow", environment="Tests.", toolkits=["slow", "shell"],
                             rules={"allow": ["shell_run"]})
    return brain


def start(brain, text, app="slow"):
    """A turn on its own thread, as an app runs it: its events, its result, the thread."""
    events, result = [], {}

    def run():
        try:
            result["value"] = brain.client.turn(app, "main", text, on_event=events.append)
        except BrainError as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    run_id = wait_for(lambda: next((e["run"] for e in events if e.get("run") is not None), None))
    return events, result, thread, run_id


def stopped_in_time(brain, events, thread, run_id, limit=2.0):
    wait_for(lambda: any(e["type"] == "tool.start" for e in events) or None)
    began = time.monotonic()
    brain.client.cancel(run_id)
    thread.join(10)
    return not thread.is_alive() and time.monotonic() - began < limit


def test_stop_ends_the_turn_at_once_even_while_a_tool_ignores_it(slow):
    slow.provider.replies = [tool_call("nap", {"seconds": 30})]
    events, result, thread, run_id = start(slow, "Take a nap")
    assert stopped_in_time(slow, events, thread, run_id)
    assert result["value"]["status"] == "cancelled"
    tool = [e for e in slow.store.events("slow", "main") if e["type"] == "tool"][-1]
    assert "stopped" in tool["content"].lower()
    slow.provider.replies = ["Awake."]
    assert turn(slow, "slow", "Hi")["reply"] == "Awake."  # the session is free again at once


def test_stop_ends_the_turn_while_the_model_has_not_written_a_word(slow):
    slow.provider.replies = [lambda payload: time.sleep(10) or "Too late."]
    events, result, thread, run_id = start(slow, "Think hard")
    wait_for(lambda: slow.provider.sent or None)
    began = time.monotonic()
    slow.client.cancel(run_id)
    thread.join(10)
    assert time.monotonic() - began < 2 and result["value"]["status"] == "cancelled"


def test_stop_wakes_a_job_wait_and_ends_a_command_in_the_foreground(slow):
    def wait_for_job(payload):
        job = int(re.search(r"Started job (\d+)", json.dumps(payload["messages"])).group(1))
        return tool_call("shell_output", {"job": job, "wait": 120})
    slow.provider.replies = [tool_call("shell_run", {"command": SLEEP, "background": True}), wait_for_job]
    events, result, thread, run_id = start(slow, "Wait for the job")
    wait_for(lambda: any(e["type"] == "tool.start" and e["name"] == "shell_output" for e in events) or None)
    assert stopped_in_time(slow, events, thread, run_id)
    job = max(slow.brain.jobs)
    assert slow.store.job(job)["status"] == "running"  # background work goes on; only the wait ended
    kill_tree(slow.brain.jobs[job])

    slow.provider.replies = [tool_call("shell_run", {"command": SLEEP, "timeout": 25})]
    events, result, thread, run_id = start(slow, "Sleep in the foreground")
    assert stopped_in_time(slow, events, thread, run_id, limit=3.0)
    tool = [e for e in slow.store.events("slow", "main") if e["type"] == "tool"][-1]
    assert "stopped" in tool["content"].lower() and not slow.brain.jobs.get(job + 1)


def test_stop_reaches_the_helpers_of_a_turn(brain):
    store, runs = brain.store, brain.brain.runs
    parent = store.add_run("milk", "main", "turn", {}, status="working")
    child = store.add_run("milk", "agent-x", "subagent", {}, parent=parent, status="working")
    runs.cancel(parent)
    assert store.run(child)["options"].get("cancel") and runs.attention(child).stopped.is_set()


def test_a_message_sent_while_she_works_reaches_her_at_her_next_step(slow):
    slow.provider.replies = [tool_call("doze", {"seconds": 30}), "Blue it is."]
    events, result, thread, run_id = start(slow, "Paint the fence")
    wait_for(lambda: any(e["type"] == "tool.start" for e in events) or None)
    began = time.monotonic()
    slow.client.steer(run_id, "Use the blue paint")
    thread.join(10)
    assert time.monotonic() - began < 2 and result["value"]["reply"] == "Blue it is."
    messages = slow.provider.sent[-1]["messages"]
    assert messages[-2]["role"] == "tool" and "woke: The user sent you a message" in messages[-2]["content"]
    assert messages[-1]["role"] == "user" and "Use the blue paint" in json.dumps(messages[-1]["content"])
    assert {"type": "steered", "text": "Use the blue paint"}.items() <= next(
        e for e in events if e["type"] == "steered").items()
    assert [h["text"] for h in slow.client.history("slow", "main") if h["role"] == "user"] == \
        ["Paint the fence", "Use the blue paint"]


def test_a_message_that_comes_as_she_finishes_is_handed_back_unread(slow):
    holder = {}

    def final(payload):
        slow.client.steer(wait_for(lambda: holder.get("run")), "One more thing")
        return "Done."
    slow.provider.replies = [final]
    events, result, thread, holder["run"] = start(slow, "Hello")
    thread.join(10)
    assert result["value"]["reply"] == "Done."
    assert result["value"]["unread"] == [{"type": "text", "text": "One more thing"}]

    with pytest.raises(BrainError) as ended:
        slow.client.steer(holder["run"], "Too late")
    assert ended.value.type == "ended"
