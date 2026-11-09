"""Recover original records without relying on the compacted model context."""

import json

import pytest
from conftest import turn

from sentientmilk_framework.testing import tool_call
from sentientmilk_framework.toolkits import ToolContext, ToolError, ToolResult, files
from sentientmilk_framework.toolkits import history as kit


@pytest.fixture
def own_history(brain):
    run = brain.store.add_run("milk", "main", "turn", {}, status="working")
    return ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("milk", "main"))


def test_history_reads_original_tool_result_after_compaction_and_clearing(brain, own_history):
    run = own_history.run["id"]
    original = "original constraint and result: " + "detail " * 600 + "final evidence"
    saved = brain.store.add_event("milk", "main", run, "tool", {
        "call_id": "old-call", "name": "shell_run", "arguments": {"command": "inspect"},
        "content": original, "status": "error"})
    brain.store.add_event("milk", "main", run, "clearing", {"ids": [saved["id"]], "after": 100})
    brain.store.add_event("milk", "main", run, "compaction", {"upto": saved["id"], "summary": "Brief."})

    recovered = kit.history_read.func(own_history, event=saved["id"])
    assert original in recovered
    assert '"status": "error"' in recovered and '"command": "inspect"' in recovered
    assert brain.store.event(saved["id"])["content"] == original


def test_history_pages_raw_useful_events_with_stable_ids(brain, own_history):
    saved = [brain.store.add_event("milk", "main", None, "input", {
        "content": f"constraint {number}", "display": f"constraint {number}"}) for number in range(42)]
    brain.store.add_event("milk", "main", None, "end", {"reply": "duplicate end reply"})
    brain.store.add_event("milk", "main", None, "tool_start", {"call_id": "pending", "name": "shell_run"})
    first = kit.history_read.func(own_history)
    second = kit.history_read.func(own_history, offset=40)

    assert f'"id": {saved[0]["id"]},' in first and '"content": "constraint 39"' in first
    assert '"content": "constraint 40"' not in first
    assert "history_read(offset=40)" in first and "history_read(event=" in first
    assert f'"id": {saved[40]["id"]},' in second and '"content": "constraint 41"' in second
    assert '"content": "constraint 0"' not in second
    assert "duplicate end reply" not in first + second and "tool_start" not in first + second
    assert "past" in kit.history_read.func(own_history, offset=999)


def test_history_recovers_constraints_tool_calls_and_notes_without_hidden_reasoning(brain, own_history):
    brain.store.add_event("milk", "main", None, "input", {"content": "Never overwrite the original file."})
    message = tool_call("shell_run", {"command": "inspect --readonly"}, "inspect", "I will inspect it.")
    message.update(reasoning_content="hidden-thought", reasoning="hidden-thought",
                   reasoning_details=[{"text": "hidden-thought"}])
    assistant = brain.store.add_event("milk", "main", None, "assistant", {"message": message, "usage": {}})
    brain.store.add_event("milk", "main", None, "note", {"text": "Task returned the original evidence."})

    page = kit.history_read.func(own_history)
    recovered = json.loads(kit.history_read.func(own_history, event=assistant["id"]))
    assert "Never overwrite the original file." in page
    assert "Task returned the original evidence." in page
    assert "I will inspect it." in page and "inspect --readonly" in page and '"id": "inspect"' in page
    assert "hidden-thought" not in page and "reasoning_content" not in recovered["message"]
    assert "No history" in kit.history_search.func(own_history, "hidden-thought")
    assert brain.store.event(assistant["id"])["message"]["reasoning_content"] == "hidden-thought"


@pytest.mark.parametrize("app,session", [("cli", "main"), ("milk", "other"), ("milk", "agent-other")])
def test_history_event_ids_cannot_cross_app_or_session_boundaries(brain, own_history, app, session):
    foreign = brain.store.add_event(app, session, None, "input", {"content": "private foreign history"})
    for offset in (0, 12_000):
        with pytest.raises(ToolError, match="in this session"):
            kit.history_read.func(own_history, event=foreign["id"], offset=offset)


def test_history_search_is_scoped_case_insensitive_and_pageable(brain, own_history):
    saved = [brain.store.add_event("milk", "main", None, "input", {
        "content": "before " * 80 + f"Oat Milk constraint {number}" + " after" * 80}) for number in range(41)]
    for app, session in (("cli", "main"), ("milk", "other"), ("milk", "agent-other")):
        brain.store.add_event(app, session, None, "input", {"content": "Oat Milk private foreign history"})

    first = kit.history_search.func(own_history, "oAT mILK")
    second = kit.history_search.func(own_history, "oat milk", offset=40)
    assert f'Event {saved[0]["id"]} ' in first and "Oat Milk constraint 0" in first
    assert "Oat Milk constraint 40" not in first and "offset=40" in first
    assert f'Event {saved[40]["id"]} ' in second and "Oat Milk constraint 40" in second
    assert "private foreign history" not in first + second
    assert "history_read(event=" in first and len(first) < 12_000
    assert "No history" in kit.history_search.func(own_history, "absent constraint")
    assert "past" in kit.history_search.func(own_history, "oat milk", offset=999)
    with pytest.raises(ToolError, match="words"):
        kit.history_search.func(own_history, " ")


@pytest.mark.parametrize("kind", ["input", "attachment"])
def test_reading_one_image_event_restores_its_images_without_base64_in_text(brain, own_history, kind):
    image = "data:image/png;base64," + "A" * 10_000
    saved = brain.store.add_event("milk", "main", None, kind, {"content": [
        {"type": "text", "text": "Original screenshot constraint."},
        {"type": "image_url", "image_url": {"url": image}}]})

    page = kit.history_read.func(own_history)
    recovered = kit.history_read.func(own_history, event=saved["id"])
    assert isinstance(recovered, ToolResult) and recovered.images == [image]
    assert "Original screenshot constraint." in recovered.text
    assert image not in page + recovered.text and "A" * 1_000 not in page + recovered.text
    assert brain.store.event(saved["id"])["content"][1]["image_url"]["url"] == image


def test_oversized_recovery_pages_text_and_omits_inline_base64(brain, own_history):
    image = "data:image/png;base64," + "B" * 10_000
    saved = brain.store.add_event("milk", "main", None, "tool", {
        "call_id": "big", "name": "render", "arguments": {}, "status": "ok",
        "content": "evidence " * 5_000 + image + " final-marker"})
    pages = [kit.history_read.func(own_history, event=saved["id"], offset=offset)
             for offset in (0, 12_000, 24_000, 36_000)]
    assert all(len(page) < 13_000 for page in pages)
    assert f'history_read(event={saved["id"]}, offset=12000)' in pages[0]
    assert "final-marker" not in pages[0] and "final-marker" in pages[-1]
    assert "[base64 data omitted]" in pages[-1] and "B" * 1_000 not in "".join(pages)
    assert not list(own_history.run_dir().glob("history-*.txt"))
    assert "past" in kit.history_read.func(own_history, event=saved["id"], offset=99_999)


def test_no_files_profile_recovers_hidden_middle_through_history_tools_alone(brain, own_history):
    saved = brain.store.add_event("milk", "main", None, "tool", {
        "call_id": "old", "name": "inspect", "arguments": {}, "status": "ok",
        "content": "prefix " * 3_200 + "middle-only-evidence" + " suffix" * 3_200})
    available = brain.brain.toolset(own_history.profile, "turn").by_name
    assert "history_read" in available and "files_read" not in available
    brain.store.update_run(own_history.run["id"], status="completed")
    brain.provider.replies += [tool_call("history_read", {"event": saved["id"]}, "first"),
                               tool_call("history_read", {"event": saved["id"], "offset": 12_000}, "middle"),
                               "Recovered the evidence."]

    result = turn(brain, "milk", "Recover the original evidence without rerunning inspect.")
    recovered = [event for event in brain.store.run_events(result["run"])
                 if event["type"] == "tool" and event["name"] == "history_read"]
    assert "middle-only-evidence" not in recovered[0]["content"]
    assert "middle-only-evidence" in recovered[1]["content"]
    assert all(event["status"] == "ok" for event in recovered)


def test_later_image_text_pages_do_not_reattach_the_images(brain, own_history):
    image = "data:image/png;base64," + "A" * 10_000
    saved = brain.store.add_event("milk", "main", None, "attachment", {"content": [
        {"type": "text", "text": "screenshot context " * 1_000},
        {"type": "image_url", "image_url": {"url": image}}]})

    first = kit.history_read.func(own_history, event=saved["id"])
    second = kit.history_read.func(own_history, event=saved["id"], offset=12_000)
    assert isinstance(first, ToolResult) and first.images == [image]
    assert isinstance(second, str) and "[base64 data omitted]" in second


def test_listing_large_private_requests_creates_no_copy_another_app_can_read(brain, own_history):
    private = "Private current request: " + "confidential details " * 3_000 + "private-final-marker"
    saved = brain.store.add_event("milk", "main", None, "input", {"content": private, "display": private})
    assert "files_read" not in brain.brain.toolset(own_history.profile, "turn").by_name
    listed = kit.history_read.func(own_history)
    foreign_run = brain.store.add_run("cli", "main", "turn", {})
    foreign = ToolContext(brain.brain, brain.store.run(foreign_run), brain.brain.profile("cli", "main"))

    with pytest.raises(ToolError, match="does not exist"):
        files.files_read.func(foreign, str(own_history.run_dir() / "history-1.txt"))
    assert len(listed) < 1_000 and "Private current request:" in listed
    assert f'Event {saved["id"]} ' in listed and "history_read(event=ID)" in listed
    assert "private-final-marker" not in listed
    assert not list(own_history.run_dir().glob("history*.txt"))
    assert brain.store.event(saved["id"])["content"] == private


def test_search_pagination_keeps_large_queries_out_of_saved_output(brain, own_history):
    query = "private-query-" * 3_000
    for _ in range(41):
        brain.store.add_event("milk", "main", None, "input", {"content": query})

    found = kit.history_search.func(own_history, query)
    assert not list(own_history.run_dir().glob("history*.txt"))
    assert len(found) < 12_000 and "offset=40" in found


def test_history_tools_are_core_readonly_and_accept_no_other_session():
    assert kit.TOOLKIT.part is True
    for item in kit.TOOLKIT.tools:
        assert item.core and item.readonly and item.policy == "auto"
        assert not {"app", "session", "agent"} & item.parameters["properties"].keys()
