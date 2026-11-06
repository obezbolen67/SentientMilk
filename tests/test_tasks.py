import json
import time
from datetime import datetime

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import context, scheduler
from sentientmilk_framework.journal import CAPACITY
from sentientmilk_framework.testing import tool_call


def test_a_task_works_in_its_own_session_and_reports_back(brain):
    def reply(payload):  # the task and the rest of the turn race for the next reply
        return "1, 2, 3. Done." if "## BACKGROUND TASK" in payload["messages"][0]["content"] else "Started it for you."

    brain.provider.replies += [tool_call("task_start", {"goal": "Count to three."}, "t1"),
                               reply, reply, "The task says: 1, 2, 3."]
    events = brain.client.events("cli")
    assert turn(brain, "cli", "count to three in the background")["reply"] == "Started it for you."
    task = wait_for(lambda: next((r for r in brain.store.runs(kind="task") if r["status"] == "completed"), None))
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


@pytest.mark.parametrize("when, kind", [("every 30m", "every"), ("2099-01-01T09:00", "at"), ("0 9 * * 1-5", "cron")])
def test_when_is_read_as_a_time_an_interval_or_cron(when, kind):
    assert scheduler.parse_when(when, time.time())[0] == kind


@pytest.mark.parametrize("bad", ["every 10s", "2000-01-01T09:00", "61 * * * *", "tomorrow-ish"])
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


def test_wake_schedules_tell_the_app_and_missed_ones_fire_once(brain):
    schedule = brain.client.create_schedule("milk", "every 1m", "stretch")
    brain.store.update_schedule(schedule["id"], next_at=time.time() - 1)
    brain.brain.scheduler._wake.set()
    fired = wait_for(lambda: [n for n in brain.store.notifications("milk") if n["type"] == "schedule.fired"])
    assert fired[0]["data"]["text"] == "stretch" and not fired[0]["data"]["late"]
    brain.brain.scheduler.stop()
    brain.store.update_schedule(schedule["id"], next_at=time.time() - 3600)
    brain.brain.scheduler.start()
    late = [n for n in brain.store.notifications("milk") if n["type"] == "schedule.fired"][-1]
    assert late["data"]["late"] and brain.store.schedule(schedule["id"])["next_at"] > time.time()


def test_creating_a_schedule_from_chat_needs_approval(brain):
    brain.provider.replies += [tool_call("schedule_create", {"when": "every 2h", "text": "drink water"}, "s1"), "Set."]
    asked = []
    brain.client.turn("cli", "main", "remind me to drink water", on_approval=lambda e: asked.append(e) or "allow")
    assert asked[0]["name"] == "schedule_create"
    assert brain.client.schedules("cli")[0]["payload"] == {"mode": "wake", "text": "drink water"}


def test_task_schedules_start_background_tasks(brain):
    brain.provider.replies.append("Summary written.")
    schedule = brain.client.create_schedule("cli", "every 1d", "Summarize the news.", mode="task")
    brain.brain.scheduler._fire(brain.store.schedule(schedule["id"]))
    task = wait_for(lambda: next((r for r in brain.store.runs(kind="task") if r["status"] == "completed"), None))
    assert task["options"]["goal"] == "Summarize the news."


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
    for index in range(CAPACITY // 300 + 5):
        brain.store.add_note("cli", "main", f"{index:04d} " + "z" * 295, CAPACITY)
    notes = brain.store.notes()
    assert sum(len(n["note"]) for n in notes) <= CAPACITY and notes[-1]["note"] != "Talked with the user."


def test_an_app_can_keep_its_sessions_out_of_the_journal(brain):
    brain.client.update_app("milk", journal={"write": False})
    brain.provider.replies.append('{"expression": "arms_down/smile"}\nHi!')
    turn(brain, "milk", "secret stuff")
    brain.brain.journal.write("milk", "main")
    assert brain.store.notes() == [] and brain.provider.journal_requests == []
