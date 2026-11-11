# Scheduling (0.7.0)

There is one kind of schedule: work for later, once or repeating. A reminder is a schedule whose
instructions say what to tell the user. SentientMilk owns time and durable delivery. An app that calls
back (`callbacks: true`, as MilkChan) executes the instructions through its normal turn workflow,
including its persona, tools, permissions, approvals, files and streaming UI; for an app that does not
(the CLI), the brain starts the same turn itself. The `wake` and `task` modes of 0.6 are gone: their
schedules are adopted on start with their rules, and `POST /v1/schedules` refuses another `mode`.

When: once, an ISO time (`2026-11-06T17:00`) or `in 20m` / `in 2h` / `in 1d`; repeating, `every 30m`
/ `every 2h` or a 5-field cron expression for clock times. A one-off that ran is done; giving it a new
time with PATCH `when` runs it again.

## Creating and managing a schedule

The model's schedule guide asks for one-off versus recurring, days, an exact time, timezone and complete
instructions. "Every morning" establishes daily recurrence but still needs a clock time. A clock time
alone does not imply daily recurrence. Tool context supplies the owning app; the model cannot choose
another app. The current local IANA timezone is included in the model's input context.

```python
schedule = client.create_schedule("milkchan", "0 9 * * 1-5",
    "Find current news and write a concise report with source links.",
    session="main", timezone="Europe/Warsaw", title="Morning news")
client.update_schedule(schedule["id"], enabled=False)  # pause future and pending work
client.update_schedule(schedule["id"], when="0 10 * * 1-5", enabled=True)
```

PATCH accepts `when`, `text`, `title`, `timezone`, `enabled`
and `catch_up` (`once` or `skip`). Delete preserves reports. Updating timing or instructions invalidates
obsolete pending work; a started occurrence may finish. Deleting its dedicated session disables the
recurrence, while deleting the source chat leaves it intact.

One `schedule-<id>` conversation is created with each app schedule and reused for every occurrence.
Its starting settings copy the source session's workspace, instructions and permission settings; later
app configuration still applies normally. Reports and failures are stored here, rather than in the
source chat. Schedule IDs never recycle, even after deletion.

Cron uses five fields (minute, hour, day of month, month, day of week, Sunday=0/7). Day of month and
day of week use normal cron OR semantics when both are restricted. Daily/weekday calendar rules follow
the saved named zone across daylight saving. Nonexistent times are skipped, repeated times run once
at their first occurrence, and nonexistent explicit one-off wall times are rejected. Intervals are fixed
durations: `every 1d` is 24 hours. ISO timestamps with offsets name an absolute instant.

## App adapter and recovery

Listen for `schedule.ready`, and query `client.scheduled_occurrences(app)` on startup, reconnect and
periodically. Notifications are wakeups; the durable occurrence ledger is authoritative regardless of
notification cursor. For each returned item dispatch the app's usual turn workflow to `item["session"]`,
passing `occurrence=item["id"]` to `client.turn`. No synthetic user text is needed: the server supplies
the saved instructions and due-time metadata. Do not use an idle workflow that can suppress replies.

```python
for item in client.scheduled_occurrences(app):
    client.turn(app, item["session"], None, occurrence=item["id"],
                on_event=normal_event_handler)
```

Use local in-flight deduplication and skip locally busy target sessions; retry on a later wakeup. The
backend also checks app/session ownership, allows one live stream consumer (409 `busy` otherwise),
and atomically creates one normal run per occurrence. Busy conversations defer pending work. A
repeated claim reuses that run and replays completed tool records, pending requests, or its final result.
Keep the app's normal action/approval handlers attached. A disconnected mutating action without a
recorded result is reported as uncertain; the model must inspect its effect before repeating it.
Read-only actions can replay. Backend crash recovery uses the existing tool interruption safeguards.

The due occurrence, recurrence advancement and durable notification commit together. An unavailable
app waits; a pending occurrence coalesces to the latest due slot. A started occurrence prevents overlap
and records later slots as skipped. Startup catches up once, or skips when requested, rather than
replaying every missed slot. The scheduler never starts arbitrary app executables. Keep SentientMilk
running for prompt timing, and keep the owning app open for execution; otherwise work waits until
they reconnect. Calendar scheduling is not a hard real-time execution guarantee.

`scheduled_occurrences(app, pending=False)` returns the latest 100 audit records, including completed,
failed, cancelled and skipped work, linked to their run and session. Failed turns also leave a readable
failure in session history. Restarting the brain resumes interrupted scheduled runs. Normal session
rewind includes work performed by schedules created after the selected source message.
