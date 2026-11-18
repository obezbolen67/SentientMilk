"""What her tools did in a turn is hers, and she knows it (0.43; the audit of 2026-11-18, findings 2, 10 and 13).

Run 565: the user called a timing idea for their practice app sensible and went on talking about it; her mind
read the turn as talk, and she started a helper on the project. Nothing updated that reading: the turn taught
her nothing about acting, her memory of it said nothing had been done, and two turns later she told the user
"nothing was started". Runs 675 (a search of the whole home folder) and 680 (24 browser calls) were "talk" too.
"""

import json
import threading

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.testing import tool_call

pytestmark = pytest.mark.mind  # her mind lives in these tests

BANTER = '[0.6, 0.5, 0.2, "chat", "banter", "amused", ["talk", "laugh along", 0.1, 0.9, 1]]'
AGENT = "## YOU ARE AN AGENT"


def calls(*items) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        for name, arguments, call_id in items]}


def test_her_first_action_that_changes_something_makes_a_talk_her_choice_to_act(brain):
    mind = brain.brain.mind
    notes, clock = brain.work / "notes.txt", brain.work / "clock.py"
    notes.write_text("the response clock idea", encoding="utf-8")
    brain.provider.mind_replies["imagine"] = [BANTER]
    brain.provider.replies += [tool_call("files_read", {"path": str(notes)}),  # a look changes nothing
                               tool_call("files_write", {"path": str(clock), "content": "tick"}), "Building it."]
    result = turn(brain, "cli", "that timing idea is sensible", on_approval=lambda _: "allow")
    decision = brain.store.run(result["run"])["options"]["mind"]
    # the first call that changes something is her choosing to act, before its result is known
    assert decision["act"] == "do" and decision["gated"] and str(clock) in decision["what"]
    assert decision["acted"]["from"] == "talk" and decision["acted"]["tool"] == "files_write"
    assert decision["check"]["tool"] == "files_write" and decision["check"]["target"]["path"] == str(clock)
    assert "act:do" in decision["features"] and not any(f.startswith("act:talk") for f in decision["features"])
    outcome = wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))
    assert outcome["did"] == "do" and outcome["resolved_by"] is not None  # its own result settled the forecast
    assert mind.values.uses.get("act:do") and "act:talk" not in mind.values.uses  # what she learns from
    text = wait_for(lambda: mind.memory.of_run(result["run"]))["text"]
    assert "It began as talk, until I chose to act: " in text
    assert f"looked at files_read {notes}" in text and f"changed files_write {clock}" in text
    # what follows is hers to learn from like any choice: the user never said go
    uses = mind.values.uses["act:do"]
    brain.provider.mind_replies["imagine"] = [json.dumps([
        0.0, -0.3, -0.2, "annoyed", "chat", "complaint", "", ["talk", "own it", 0.1, 0.9, 1],
        {"run": result["run"], "quote": "I never said go", "dimension": "free", "verdict": "negative"}])]
    brain.provider.replies += ["You're right, I jumped."]
    turn(brain, "cli", "I never said go")
    assert "Prior turn %d to this speaker: do" % result["run"] in brain.provider.mind_requests[-1]["messages"][1]["content"] \
        or any("Prior turn %d to this speaker: do" % result["run"] in r["messages"][1]["content"]
               for r in brain.provider.mind_requests)
    wait_for(lambda: mind.values.uses.get("act:do", 0) > uses)


def test_a_look_alone_leaves_a_talk_a_talk_and_is_remembered_as_looked_at(brain):
    mind = brain.brain.mind
    notes = brain.work / "notes.txt"
    notes.write_text("the response clock idea", encoding="utf-8")
    brain.provider.mind_replies["imagine"] = [BANTER]
    brain.provider.replies += [tool_call("files_read", {"path": str(notes)}), "Read it."]
    result = turn(brain, "cli", "what did I write about the clock?")
    decision = brain.store.run(result["run"])["options"]["mind"]
    assert decision["act"] == "talk" and "acted" not in decision
    text = wait_for(lambda: mind.memory.of_run(result["run"]))["text"]
    assert f"looked at files_read {notes}" in text and "changed" not in text and "chose to act" not in text


def test_what_she_started_is_kept_as_started_and_told_as_still_going(brain):
    mind = brain.brain.mind
    release = threading.Event()

    def route(payload):
        if AGENT in payload["messages"][0]["content"]:
            release.wait(10)
            return "The clock is in."
        if not any(m["role"] == "tool" for m in payload["messages"]):
            return calls(("agent_start", {"name": "vera-clock", "task": "Add the response clock."}, "s1"))
        return "It's running in the background."
    brain.provider.mind_replies["imagine"] = [BANTER]
    brain.provider.replies += [route] * 3
    try:
        result = turn(brain, "cli", "that timing idea is sensible")
        assert brain.store.run(result["run"])["options"]["mind"]["acted"]["tool"] == "agent_start"
        text = wait_for(lambda: mind.memory.of_run(result["run"]))["text"]
        assert "started helper vera-clock (still going)" in text
        assert "changed agent_start" not in text  # a call that started something is told as what it started
        brain.provider.mind_replies["imagine"] = [BANTER]
        brain.provider.replies += ["Yes, it's on it."]
        turn(brain, "cli", "is anything running?")
        note = brain.provider.last_user_text().split("[Inside you:")[1]
        assert "Still going: " in note and "helper vera-clock" in note.split("Still going: ")[1]
    finally:
        release.set()
    wait_for(lambda: [r for r in brain.store.runs(kind="agent") if r["status"] == "completed"])


def test_what_her_tools_did_names_the_folder_it_was_in(brain):
    # the audit (finding 12): her memory of a task said "I traced it to server/asr.py"; two projects of the user's
    # have such a file, and later she could not tell which one, and searched the whole home folder
    mind = brain.brain.mind
    project = brain.work / "speech"
    (project / "server").mkdir(parents=True)
    (project / "server" / "asr.py").write_text("model = None\n", encoding="utf-8")
    brain.provider.replies += [tool_call("shell_run", {"command": "git status", "cwd": str(project)}),
                               tool_call("files_read", {"path": "speech/server/asr.py"}), "It has no VAD."]
    result = turn(brain, "cli", "what does the transcription server do?", on_approval=lambda _: "allow")
    text = wait_for(lambda: mind.memory.of_run(result["run"]))["text"]
    assert f"files_read {brain.work / 'speech' / 'server' / 'asr.py'}" in text
    assert f"shell_run git status (in {project})" in text
