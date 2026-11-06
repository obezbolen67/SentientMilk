# SentientMilk

SentientMilk is one brain for all your apps. It runs as a local server; apps such as the
MilkChan desktop character, the `sentientmilk chat` CLI or a web chat connect to it. The
brain owns the provider and model, the agent loop, tools, memory, background tasks,
schedules and MCP servers. Apps add their own features on top: MilkChan adds a body
(expressions), screenshots and proactive messages.

Without other settings it uses `https://api.refuseless.com/v1` with
`deepseek-v4.1-flash-fast`, so only an API key is needed. The design, with its sources,
is in [docs/architecture.md](docs/architecture.md).

The model can run shell commands and change files as the user who runs the brain, in the
folders an app allows. Only connect apps you trust.

## Run it

```bash
python -m pip install -e ".[dev]"     # ".[mcp]" adds MCP support without the test tools
sentientmilk config api_key=sk-...    # sentientmilk config shows the settings
sentientmilk chat                     # a coding agent in the current folder
```

Any app (and every CLI command) starts the brain when none is running, as its own
process. One brain runs per home folder; it exits on its own after `idle_exit_minutes`
(30) with no app connected, no work or jobs and no enabled schedules. There is no
autostart: after a reboot, a schedule that came due fires when an app next starts the brain.

Other commands: `serve` (run in the foreground), `tasks [show|cancel ID]`,
`schedules [delete ID]`, `journal [QUERY] [--delete ID]`,
`mcp [add NAME (--url URL | -- COMMAND ...)|remove NAME]`, `stats`, `eval`.

The brain keeps its files in `~/.sentientmilk` (`--home` or `SENTIENTMILK_HOME` changes it):

- `config.json`: settings, including the API key; `mcp.json`: MCP servers. Both readable by the user only.
- `brain.sqlite3`: apps, sessions, the event log of every run, memory, journal, schedules.
- `server.json`: the running brain's address and token; `brain.lock`, `brain.log`.
- `runs/<id>/`: long tool output and task progress files; `toolkits/`: your own toolkits.

## Use it from an app

```python
from sentientmilk_framework import connect

client = connect()  # the running brain, started when none runs
client.declare_app("jarvis",
    name="Jarvis",
    environment="You run the user's smart home. Replies are spoken aloud.",
    persona="You are Jarvis, dry and precise.",  # the default; the user may change it
    signals={"mood": {"options": ["calm", "pleased", "concerned"]}},  # optional
    toolkits=["memory", "web", "schedule", "tasks"],
    rules={"allow": ["schedule_create"]})
result = client.turn("jarvis", "main", "Lights off, please.", context={"user": "Tony"},
                     on_event=print)            # text.delta, tool.start, tool.end, ... as they happen
print(result["reply"], result["signals"], result["tools"])
for notification in client.events("jarvis"):  # reminders, finished tasks; blocks
    print(notification["type"], notification["data"])
```

- An **app** declares who the brain is there: name, environment, persona, signals,
  toolkits, permission rules and allowed folders (`roots`). A **session** is one
  conversation in an app. Memory belongs to the app; the **journal** holds short, dated
  notes about sessions across all apps, oldest deleted first when it is full.
- A turn's input is a list of items: `text`, `image` (a data URL) and `event`
  (`{"type": "event", "name": "idle", "text": "..."}`). With `reply="optional"` the
  brain may stay silent (`result["silent"]`). `context` adds a line such as the user's
  name; the time is always added.
- With **signals** declared, replies start with one JSON line (`{"mood": "calm"}`) that the
  brain checks and strips; grouped options read `group/option`. A wrong signal is dropped
  and the model is told on its next turn.
- **Approvals**: tools whose policy is `ask` emit `approval.requested`. `on_approval`
  answers `allow`, `always` (saved as a rule) or `deny`; without it they are denied.
  Rules are `tool` or `tool(pattern)` lists under `deny`, `ask` and `allow`.
- **Tasks** (`client.start_task`, or the model's `task_start`) run in the background in
  their own session, keep a progress file, can be checked by a reviewer (`verify=True`)
  and report back as a note in the parent session plus a `task.completed` notification.
- **Schedules** (`at 2026-11-06T09:00`, `every 30m`, or 5-field cron) either wake the app
  (a `schedule.fired` notification) or start a task.
- Failures raise `BrainError` with `type` (`config_missing`, `rate_limit`,
  `auth_error`, `timeout`, `network`, `payload_too_large`, `brain_unreachable`, ...),
  `message` and `details`. A client from `connect()` starts the brain again when it vanished.

## Toolkits

| Toolkit | Tools |
| --- | --- |
| `files` | `files_read`, `files_search`, `files_find`, `files_edit`, `files_write` (a change that breaks Python, JSON or TOML syntax is refused) |
| `shell` | `shell_run` (PowerShell on Windows; `shell` setting), `shell_output`, `shell_stop` for background jobs |
| `web` | `web_search` (Brave, needs `web_search_key`), `web_fetch` |
| `todo` | `todo_write` |
| `memory` | `memory_save`, `memory_get`, `memory_list`, `memory_forget` |
| `journal` | `journal_search` |
| `agents` | `agent_run`: a read-only helper that returns a report |
| `tasks` | `task_start`, `task_status`, `task_cancel` |
| `schedule` | `schedule_create`, `schedule_list`, `schedule_delete` |
| `mcp:<server>` | the server's tools, as `mcp__<server>__<tool>` |

An app enables the toolkits it lists; the user can disable any of them for the whole
brain (`disabled_toolkits`), an app or a session. A toolkit of your own is a Python file in
`~/.sentientmilk/toolkits/`:

```python
from sentientmilk_framework.toolkits import Toolkit, tool

@tool(readonly=True, args={"city": "City name."})
def weather_now(ctx, city: str):
    """The current weather in a city."""
    return f"Sunny in {city}."

TOOLKIT = Toolkit("weather", "Current weather.", [weather_now])
```

## How it works

Every turn, task and helper is a **run** of one agent loop. Each step is written to an
append-only event log before the next one starts, so a crashed or restarted brain picks
runs up where they stopped; a tool call that may have run is reported to the model as
interrupted instead of being run twice. Requests stay append-only, so the provider's
prefix cache keeps hitting (61-90% measured). When the context fills up, old tool results
are cleared at 50% of `context_window` and older turns are summarized at 75%, keeping the
todo list and re-reading recent files. Long output goes to `runs/<id>/` and the model gets
the path.

## HTTP API

The server listens on 127.0.0.1 only. Every request needs `Authorization: Bearer <token>`
with the token from `server.json`. Paths start with `/v1`; streams are server-sent events.

| Request | Does |
| --- | --- |
| `GET /health`, `GET`/`PATCH /config`, `POST /models`, `GET /stats` | brain status, settings (secrets only as `*_set`), models, token use |
| `PUT`/`GET /apps/{app}`, `PATCH /apps/{app}/settings` | declare an app; the user's persona, model, toolkits, rules, roots |
| `GET /apps/{app}/sessions`, `GET /apps/{app}/memory` | sessions and memory of an app |
| `GET`/`PATCH /apps/{app}/sessions/{id}` | a session and its settings |
| `GET`/`DELETE /apps/{app}/sessions/{id}/history`, `POST .../import` | the shown history; history an app kept before |
| `POST /apps/{app}/sessions/{id}/turns` | `input`, `context`, `reply`: a stream ending in `done` or `error` |
| `GET /events?app=&after=` | notifications from a cursor (`-1`: from now), then live |
| `POST`/`GET /tasks`, `GET /tasks/{id}` | start and list tasks |
| `GET /runs/{id}`, `GET /runs/{id}/events` | a run; its log, then live |
| `POST /runs/{id}/answer`, `/cancel`, `/detach` | answer an approval, question or action; cancel; let a turn go on in the background |
| `GET`/`POST /schedules`, `PATCH`/`DELETE /schedules/{id}` | schedules |
| `GET /toolkits`, `GET`/`PUT /mcp`, `POST /mcp/{name}/reconnect` | toolkits and MCP servers |
| `GET /journal?q=`, `DELETE /journal/{id}`, `GET /jobs/{id}` | the journal; background shell jobs |

Errors answer `{"error": {"type", "message", "details", "http_status"}}`. The stored API
key is only ever sent to the stored `base_url`.

## Settings

`api_key`, `base_url`, `model`, `light_model` (summaries, journal notes, helpers; empty:
the same as `model`), `context_window` (128000), `thinking_mode` (`default`, `none`,
`minimal`, `low`, `medium`, `high`, `xhigh` or `tokens`), `thinking_tokens`, `vision`,
`request_budget` (bytes per request, 800 KiB), `stream`, `web_search_key`, `shell`,
`task_workers` (2), `idle_exit_minutes` (30; 0 never), `rules`, `disabled_toolkits`.

## Development

Use Python 3.12:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
sentientmilk eval                  # 8 real tasks against the configured model
```

`sentientmilk_framework.testing.FakeProvider` stands in for the provider in tests, for
this repository and for apps.

## Repository layout

```text
sentientmilk_framework/
  server.py      HTTP server, the brain lock, idle exit
  client.py      BrainClient and connect() for apps
  brain.py       apps, sessions, profiles, validation of what apps send
  runs.py        turns, tasks, helpers, answers, crash recovery
  loop.py        the agent loop: tools, approvals, budgets, retries, compaction
  context.py     system prompt, projection of the log into messages, clearing, summaries
  signals.py     the signals line of replies
  permissions.py rules and policies
  provider.py    the OpenAI-compatible provider, streaming and usage
  store.py       SQLite: the event log and everything else
  journal.py     notes about sessions across apps
  scheduler.py   at, every and cron schedules
  mcp_host.py    MCP servers as toolkits
  toolkits/      built-in toolkits
  transport.py   images sized to the request budget
  config.py, thinking.py, exceptions.py
  evals.py, eval_tasks/, testing.py, cli.py
tests/
docs/architecture.md
```
