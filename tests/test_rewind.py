"""Returning to a message: the chat goes back to just before it, with the files, the todo list and the work
she started since; what cannot be undone is named."""

import json
import time
from pathlib import Path

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import BrainError
from sentientmilk_framework.toolkits import ToolContext, ToolError, files, shell

WAIT = "Start-Sleep -Seconds 60" if shell.shell_name("") == "powershell" else "sleep 60"


def calls(*items) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        for name, arguments, call_id in items]}


def allow(event):
    return "allow"


def said(brain, session="main"):
    return [entry for entry in brain.client.history("cli", session) if entry["role"] == "user"]


def test_a_return_takes_back_the_chat_her_files_and_her_todo_list(brain):
    notes = brain.work / "notes.txt"
    notes.write_text("first\n", encoding="utf-8")
    brain.provider.replies += [calls(("files_read", {"path": "notes.txt"}, "r1"),
                                     ("todo_write", {"items": [{"text": "plan", "status": "pending"}]}, "t1")),
                               "Read it."]
    turn(brain, "cli", "read my notes", on_approval=allow)
    brain.provider.replies += [calls(("files_edit", {"path": "notes.txt", "old": "first", "new": "changed"}, "e1"),
                                     ("files_write", {"path": "sub/new.txt", "content": "made"}, "w1"),
                                     ("todo_write", {"items": [{"text": "plan", "status": "done"}]}, "t2"),
                                     ("memory_save", {"category": "user", "key": "k", "value": "v"}, "m1")),
                               "Changed it."]
    changed = turn(brain, "cli", "change them", on_approval=allow)
    brain.provider.replies += [calls(("files_edit", {"path": "notes.txt", "old": "changed", "new": "again"}, "e2")),
                               "Again."]
    turn(brain, "cli", "and again", on_approval=allow)
    before = brain.client.history("cli", "main", tools=True)
    target = said(brain)[1]
    assert [(e["id"], e["text"]) for e in changed["events"] if e["type"] == "input"] == [(target["id"], "change them")]

    preview = brain.client.rewind_preview("cli", "main", target["id"])
    assert (preview["text"], preview["messages"], preview["todo"]) == ("change them", 2, True)
    assert sorted((Path(f["path"]).name, f["change"]) for f in preview["files"]) == [
        ("new.txt", "delete"), ("notes.txt", "restore")]
    assert preview["kept"] == [{"name": "memory_save", "count": 1}]  # memories are the app's
    assert notes.read_text(encoding="utf-8") == "again\n"  # a dry run changes nothing

    done = brain.client.rewind("cli", "main", target["id"])
    assert done["problems"] == [] and done["text"] == "change them"
    assert notes.read_text(encoding="utf-8") == "first\n"  # as before its first change since
    assert not (brain.work / "sub" / "new.txt").exists()
    assert [e["text"] for e in brain.client.history("cli", "main")] == ["read my notes", "Read it."]
    assert brain.client.session("cli", "main")["todo"] == [{"text": "plan", "status": "pending"}]
    assert brain.store.memories("cli")["user"]["k"] == "v"
    assert not brain.store.versions("cli", "main")  # put back: nothing left to restore

    brain.provider.replies += ["Fresh."]
    turn(brain, "cli", "change them differently")
    sent = json.dumps(brain.provider.sent[-1]["messages"])
    assert "Read it." in sent and "Changed it." not in sent and "Again." not in sent
    after = brain.client.history("cli", "main")
    assert min(e["id"] for e in after[2:]) > max(e["id"] for e in before)  # an id never means two messages


def test_a_return_to_a_message_read_mid_turn_keeps_what_came_before_it(brain):
    run = brain.store.add_run("cli", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("cli", "main"), "c1")
    first = brain.store.add_event("cli", "main", run, "input", {"content": "a", "display": "write it"})
    files.files_write.func(ctx, "f.txt", "one")
    second = brain.store.add_event("cli", "main", run, "input", {"content": "b", "display": "no, two"})  # steered
    files.files_write.func(ctx, "f.txt", "two")
    files.files_write.func(ctx, "f.txt", "three")  # one version per message: before its first change
    with pytest.raises(BrainError) as busy:
        brain.client.rewind("cli", "main", second["id"])
    assert busy.value.type == "busy"
    brain.store.update_run(run, status="completed")

    brain.client.rewind("cli", "main", second["id"])
    assert (brain.work / "f.txt").read_text(encoding="utf-8") == "one"
    assert [e["text"] for e in said(brain)] == ["write it"]
    assert brain.client.rewind("cli", "main", first["id"])["files"][0]["change"] == "delete"
    assert not (brain.work / "f.txt").exists()


def test_only_a_message_the_user_sent_is_a_place_to_return_to(brain):
    brain.provider.replies += ["Hi."]
    turn(brain, "cli", "hello")
    reply = [e for e in brain.client.history("cli", "main") if e["role"] == "assistant"][0]
    for wrong in (reply["id"], 99999):
        with pytest.raises(BrainError) as caught:
            brain.client.rewind_preview("cli", "main", wrong)
        assert caught.value.type == "bad_request"
    with pytest.raises(BrainError):
        brain.client.rewind("milk", "main", said(brain)[0]["id"])  # another chat's message


def test_work_she_started_since_stops_quietly_and_her_new_agents_and_reminders_go(brain):
    brain.client.update_app("cli", rules={"allow": ["files_write", "shell_run", "schedule_create"]})
    (brain.work / "keep.txt").write_text("mine", encoding="utf-8")

    def route(payload):
        system = payload["messages"][0]["content"]
        has_results = any(m["role"] == "tool" for m in payload["messages"])
        if "## YOU ARE AN AGENT" in system:
            return "Report." if has_results else calls(("files_write", {"path": "agent.txt", "content": "x"}, "a1"))
        if has_results:
            return "Started."
        return calls(("agent_start", {"name": "helper", "task": "write agent.txt"}, "s1"),
                     ("schedule_create", {"when": "every 1d", "text": "check the notes"}, "s2"),
                     ("shell_run", {"command": WAIT, "background": True}, "s3"))

    brain.provider.replies += [route] * 4
    turn(brain, "cli", "set it all up")
    wait_for(lambda: (brain.work / "agent.txt").exists())
    wait_for(lambda: all(r["status"] == "completed" for r in brain.store.runs(kind="agent")))
    [job] = [j for j in brain.store.jobs("cli", 0) if j["status"] == "running"]
    target = said(brain)[0]

    preview = brain.client.rewind_preview("cli", "main", target["id"])
    assert [a["name"] for a in preview["agents"]] == ["helper"]
    assert [r["text"] for r in preview["reminders"]] == ["check the notes"]
    assert [(s["kind"], s["id"]) for s in preview["stopped"]] == [("job", job["id"])]
    assert [(Path(f["path"]).name, f["change"]) for f in preview["files"]] == [("agent.txt", "delete")]

    brain.client.rewind("cli", "main", target["id"])
    assert not (brain.work / "agent.txt").exists() and (brain.work / "keep.txt").exists()
    assert wait_for(lambda: brain.store.job(job["id"])["status"] == "stopped", 30)
    assert brain.store.schedules("cli") == []
    assert wait_for(lambda: brain.client.agents("cli", "main") == [])
    time.sleep(1)  # the job's watcher has ended by now: it said nothing
    assert brain.store.events("cli", "main", types=("note",)) == []
    assert not [n for n in brain.store.notifications("cli") if n["type"] == "job.finished"]
    assert brain.client.history("cli", "main") == []


def test_the_same_command_is_not_started_again_while_it_runs(brain):
    run = brain.store.add_run("cli", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("cli", "main"), "c1")
    started = shell.shell_run.func(ctx, WAIT, background=True)
    job = int(started.split()[2].rstrip("."))
    with pytest.raises(ToolError) as again:
        shell.shell_run.func(ctx, f"  {WAIT} ", background=True)
    assert f"job {job} runs this same command" in str(again.value) and f"shell_output(job={job})" in str(again.value)
    other = brain.work / "other"
    other.mkdir()
    second = int(shell.shell_run.func(ctx, WAIT, cwd="other", background=True).split()[2].rstrip("."))  # elsewhere: fine
    for each in (job, second):
        shell.stop(brain.brain, brain.store.job(each))
    wait_for(lambda: brain.store.job(job)["status"] == "stopped", 30)
    assert "Started job" in shell.shell_run.func(ctx, "echo done", background=True)


def test_a_log_held_by_a_leftover_process_does_not_break_the_command(brain, monkeypatch):
    run = brain.store.add_run("cli", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("cli", "main"), "c1")
    real = Path.unlink

    def held(path, missing_ok=False):
        if path.name.startswith("job-"):
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    assert shell.shell_run.func(ctx, "echo hi").startswith("[exit code 0]\nhi")


def test_a_file_that_cannot_be_put_back_is_named_and_keeps_its_version(brain, monkeypatch):
    run = brain.store.add_run("cli", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("cli", "main"), "c1")
    first = brain.store.add_event("cli", "main", run, "input", {"content": "a", "display": "first"})
    (brain.work / "f.txt").write_text("old", encoding="utf-8")
    files.files_read.func(ctx, "f.txt")
    second = brain.store.add_event("cli", "main", run, "input", {"content": "b", "display": "second"})
    files.files_write.func(ctx, "f.txt", "new")
    brain.store.update_run(run, status="completed")
    real = Path.write_bytes

    def locked(path, data):
        if path.name == "f.txt":
            raise PermissionError(13, "Access is denied")
        return real(path, data)

    monkeypatch.setattr(Path, "write_bytes", locked)
    done = brain.client.rewind("cli", "main", second["id"])
    assert len(done["problems"]) == 1 and "f.txt: Access is denied" in done["problems"][0]
    assert [e["text"] for e in said(brain)] == ["first"]  # the chat went back all the same
    monkeypatch.setattr(Path, "write_bytes", real)
    brain.client.rewind("cli", "main", first["id"])  # a later return further back still has it
    assert (brain.work / "f.txt").read_text(encoding="utf-8") == "old"
