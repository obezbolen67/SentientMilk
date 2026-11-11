import json
import time
from datetime import datetime

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import context, scheduler
from sentientmilk_framework.toolkits import schedule as schedule_kit
from sentientmilk_framework.testing import tool_call


def test_a_task_works_in_its_own_session_and_reports_back(brain):
    brain.provider.replies += ["1, 2, 3. Done.", "The task says: 1, 2, 3."]
    events = brain.client.events("cli")
    brain.client.start_task("cli", "Count to three.", session="main")
    task = wait_for(lambda: next((r for r in brain.store.runs(kind="task") if r["status"] == "completed"), None))
    assert "task_progress" in [t["function"]["name"] for t in brain.provider.sent[0]["tools"]]
    assert task["session"] == f"task-{task['id']}" and task["result"]["reply"] == "1, 2, 3. Done."
    seen = []
    for notification in events:
        seen.append(notification["type"])
        if notification["type"] == "task.completed":
            assert notification["data"]["reply"] == "1, 2, 3. Done."
            break
    assert seen[0] == "task.updated"
    turn(brain, "cli", "how did it go?")
    # The note joins whichever request comes next: the turn's own last step if the task was quick.
    seen_by_model = json.dumps(brain.provider.sent[-1]["messages"])
    assert "Background task" in seen_by_model and "1, 2, 3. Done." in seen_by_model


def test_a_reviewer_sends_unfinished_work_back(brain):
    def reply(payload):
        system = payload["messages"][0]["content"]
        if "## REVIEWER" in system:
            return "PASS: it is there." if reviewed else "FAIL: the file is missing."
        return "Wrote it." if not reviewed else "Fixed it now."

    reviewed = False

    def flip(payload):
        nonlocal reviewed
        answer = reply(payload)
        if answer.startswith("FAIL"):
            reviewed = True
        return answer

    brain.provider.replies += [flip] * 6
    task = brain.client.start_task("cli", "Write a file.", session="main", verify=True)
    done = wait_for(lambda: brain.store.run(task["id"])["status"] == "completed" and brain.store.run(task["id"]))
    assert done["result"]["reply"] == "Fixed it now."
    notes = brain.store.events("cli", task["session"], types=("note",))
    assert "did not pass" in notes[0]["text"] and "the file is missing" in notes[0]["text"]


def reviewer_waits(brain):
    return wait_for(lambda: next((r for r in brain.store.runs(kind="subagent") if r["status"] == "input_required"),
                                 None))


def test_a_reviewer_gets_the_tools_of_its_task(brain):
    brain.provider.replies += ["Wrote it.", "PASS: fine."]
    task = brain.client.start_task("cli", "Write a.txt.", session="main", verify=True)
    wait_for(lambda: brain.store.run(task["id"])["status"] == "completed")
    reviewer = brain.store.runs(kind="subagent")[0]
    profile = brain.brain.profile(reviewer["app"], reviewer["session"], reviewer["options"]["profile"])
    names = set(brain.brain.toolset(profile, "subagent").by_name)
    assert {"files_read", "files_write", "files_edit", "shell_run", "memory_save", "todo_write"} <= names


def test_a_reviewer_asks_for_approval_like_its_task(brain):
    brain.provider.replies += ["Wrote it.", tool_call("shell_run", {"command": "echo checked"}, "v1"), "PASS: checked."]
    task = brain.client.start_task("cli", "Write a.txt.", session="main", verify=True)
    reviewer = reviewer_waits(brain)
    asked = wait_for(lambda: [n["data"] for n in brain.store.notifications("cli", 0)
                              if n["type"] == "task.input_required"])
    assert asked == [{"task": task["id"], "run": reviewer["id"], "session": reviewer["session"], "name": "reviewer"}]
    [request] = brain.brain.runs.waiting(reviewer["id"])
    brain.client.answer(reviewer["id"], call_id=request["call_id"], decision="allow")
    done = wait_for(lambda: brain.store.run(task["id"])["status"] == "completed" and brain.store.run(task["id"]))
    assert done["result"]["reply"] == "Wrote it."
    ran = next(e for e in brain.store.run_events(reviewer["id"]) if e["type"] == "tool")
    assert ran["status"] == "ok" and "checked" in ran["content"]


def test_a_reviewer_runs_what_the_rules_allow_without_asking(brain):
    brain.client.update_app("cli", rules={"allow": ["shell_run"]})
    brain.provider.replies += ["Wrote it.", tool_call("shell_run", {"command": "echo checked"}, "v1"), "PASS: checked."]
    task = brain.client.start_task("cli", "Write a.txt.", session="main", verify=True)
    wait_for(lambda: brain.store.run(task["id"])["status"] == "completed")
    reviewer = brain.store.runs(kind="subagent")[0]
    assert next(e for e in brain.store.run_events(reviewer["id"]) if e["type"] == "tool")["status"] == "ok"
    assert not [n for n in brain.store.notifications("cli", 0) if n["type"] == "task.input_required"]


def test_stopping_a_task_stops_its_waiting_reviewer(brain):
    brain.provider.replies += ["Wrote it.", tool_call("shell_run", {"command": "echo checked"}, "v1")]
    task = brain.client.start_task("cli", "Write a.txt.", session="main", verify=True)
    reviewer = reviewer_waits(brain)
    brain.client.cancel(task["id"])
    assert wait_for(lambda: brain.store.run(task["id"])["status"] == "cancelled")
    assert brain.store.run(reviewer["id"])["status"] == "cancelled"


def test_a_reviewer_waiting_at_a_restart_ends(brain):
    run = brain.store.add_run("cli", "agent-9", "subagent", {"input": []}, status="input_required")
    brain.brain.runs.recover()
    assert brain.store.run(run)["status"] == "failed"


def test_a_reviewer_sees_the_folders_of_the_chat_the_task_came_from(brain):
    (brain.work / "a.txt").write_text("the work", encoding="utf-8")
    brain.provider.replies += ["Wrote a.txt.", tool_call("files_read", {"path": "a.txt"}, "v1"), "PASS: a.txt is there."]
    task = brain.client.start_task("cli", "Write a.txt.", session="main", verify=True)
    wait_for(lambda: brain.store.run(task["id"])["status"] == "completed")
    reviewer = brain.store.runs(kind="subagent")[0]
    read = next(e for e in brain.store.run_events(reviewer["id"]) if e["type"] == "tool")
    assert read["status"] == "ok" and "the work" in read["content"]


def test_tasks_resume_after_a_restart(brain):
    task = brain.store.add_run("cli", "task-77", "task", {"goal": "g", "input": [{"type": "text", "text": "g"}],
                                                          "profile": {"from_session": "main"}}, status="working")
    brain.provider.replies.append("finished after the restart")
    brain.brain.runs.recover()
    assert wait_for(lambda: brain.store.run(task)["status"] == "completed")
    assert "The brain restarted" in brain.provider.last_user_text()


def test_a_reset_starts_fresh_from_the_progress_notes(brain, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "progress.md").write_text("## 10:00\nBuilt the parser.", encoding="utf-8")
    text = context.handoff(run_dir, [{"text": "parser", "status": "done"}, {"text": "cli", "status": "pending"}], None)
    assert "Built the parser." in text and "2. [ ] cli" in text


@pytest.mark.parametrize("when, kind", [("every 30m", "every"), ("2099-01-01T09:00", "at"), ("0 9 * * 1-5", "cron"),
                                        ("in 20m", "at"), ("in 2 hours", "at")])
def test_when_is_read_as_once_or_repeating(when, kind):
    assert scheduler.parse_when(when, time.time())[0] == kind


def test_in_is_once_that_long_from_now_in_the_zone():
    now = datetime(2026, 11, 9, 23, 50).timestamp()
    kind, spec = scheduler.parse_when("in 20m", now, "Europe/Warsaw")
    assert kind == "at" and datetime.fromisoformat(spec).timestamp() == now + 1200


@pytest.mark.parametrize("bad", ["every 10s", "2000-01-01T09:00", "61 * * * *", "tomorrow-ish", "in 0m"])
def test_bad_times_are_explained(bad):
    with pytest.raises(ValueError):
        scheduler.parse_when(bad, time.time())


def test_cron_finds_the_next_matching_minute():
    friday = datetime(2026, 11, 6, 10, 30).timestamp()  # a Friday
    assert datetime.fromtimestamp(scheduler.cron_next("0 9 * * 1-5", friday)) == datetime(2026, 11, 9, 9, 0)
    assert datetime.fromtimestamp(scheduler.cron_next("*/15 * * * *", friday)) == datetime(2026, 11, 6, 10, 45)
    assert datetime.fromtimestamp(scheduler.cron_next("0 12 * * 7", friday)) == datetime(2026, 11, 8, 12, 0)
    # day of month OR weekday when both are given, as cron does
    assert datetime.fromtimestamp(scheduler.cron_next("0 0 13 * 5", friday)) == datetime(2026, 11, 13, 0, 0)
    created = friday - 100
    assert scheduler.next_fire("every", "3600", friday, created) == created + 3600  # no drift


def test_a_one_off_runs_once_and_then_reads_as_done(brain):
    schedule = brain.client.create_schedule("cli", "in 1m", "Tell the user to stretch.")
    assert schedule["kind"] == "at" and schedule["enabled"]
    brain.provider.replies.append("Time to stretch!")
    due = time.time() - 1  # its time came
    brain.store.update_schedule(schedule["id"], next_at=due, spec=datetime.fromtimestamp(due).astimezone().isoformat())
    brain.brain.scheduler.wake()
    run = wait_for(lambda: next((r for r in brain.store.runs(app="cli") if r["session"] == schedule["execution_session"]
                                 and r["status"] == "completed"), None))
    assert run["result"]["reply"] == "Time to stretch!"
    done = brain.store.schedule(schedule["id"])
    assert not done["enabled"] and done["next_at"] is None
    assert "done, it ran at" in schedule_kit.describe(done)


def test_creating_a_schedule_from_chat_needs_approval(brain):
    brain.provider.replies += [tool_call("schedule_create", {"when": "every 2h", "text": "drink water"}, "s1"), "Set."]
    asked = []
    brain.client.turn("cli", "main", "remind me to drink water", on_approval=lambda e: asked.append(e) or "allow")
    assert asked[0]["name"] == "schedule_create"
    schedule = brain.client.schedules('cli')[0]
    assert schedule['payload']['text'] == 'drink water' and schedule['execution_session'].startswith('schedule-')
    assert "every 2h, next" in schedule_kit.describe(schedule)


def test_the_brain_runs_the_schedules_of_an_app_that_does_not_call_back(brain):
    """The CLI never claims its due work; MilkChan (callbacks) does, so the brain leaves its work to it."""
    cli = brain.client.create_schedule("cli", "every 1d", "Summarize the news.")
    milk = brain.client.create_schedule("milk", "every 1d", "Summarize the news.")
    brain.provider.replies.append("Summary written.")
    for schedule in (cli, milk):
        brain.store.update_schedule(schedule["id"], next_at=time.time() - 1)
    brain.brain.scheduler.wake()
    run = wait_for(lambda: next((r for r in brain.store.runs(app="cli") if r["session"] == cli["execution_session"]
                                 and r["status"] == "completed"), None))
    assert run["result"]["reply"] == "Summary written."
    assert [o["status"] for o in brain.client.scheduled_occurrences("milk")] == ["pending"]  # MilkChan's to run


def test_the_journal_keeps_short_notes_from_every_app_and_drops_the_oldest(brain):
    brain.provider.replies += ['{"expression": "arms_down/smile"}\nHi!', "Done."]
    turn(brain, "milk", "I adopted a cat named Miso.")
    brain.brain.journal.write("milk", "main")
    assert brain.store.notes()[0]["note"] == "Talked with the user."
    assert "Miso" in brain.provider.journal_requests[0]["messages"][1]["content"]
    brain.store.update_session("cli", "main", "state", lambda state: {})
    turn(brain, "cli", "hello")
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert "RECENT NOTES FROM YOUR OTHER SESSIONS" in system and "milk] Talked with the user." in system
    for index in range(100):  # no caps: every note stays, the oldest too
        brain.store.add_note("cli", "main", f"{index:04d} " + "z" * 295)
    notes = brain.store.notes()
    assert len(notes) == 101 and notes[-1]["note"] == "Talked with the user."


def test_an_app_can_keep_its_sessions_out_of_the_journal(brain):
    brain.client.update_app("milk", journal={"write": False})
    brain.provider.replies.append('{"expression": "arms_down/smile"}\nHi!')
    turn(brain, "milk", "secret stuff")
    brain.brain.journal.write("milk", "main")
    assert brain.store.notes() == [] and brain.provider.journal_requests == []


def test_a_task_waiting_for_approval_says_what_it_waits_for(brain):
    brain.provider.replies += [tool_call("shell_run", {"command": "echo hi"}, "t1"), "Said hi."]
    task = brain.client.start_task("cli", "say hi in the shell", session="main")
    wait_for(lambda: brain.client.run(task["id"])["status"] == "input_required")
    waiting = brain.client.run(task["id"])["waiting"]
    assert [(w["kind"], w["name"], w["arguments"]["command"]) for w in waiting] == [("approval", "shell_run", "echo hi")]
    brain.client.answer(task["id"], call_id="t1", decision="allow")
    wait_for(lambda: brain.client.run(task["id"])["status"] == "completed")
    assert brain.client.run(task["id"])["waiting"] == []
