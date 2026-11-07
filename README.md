<p align="center"><img src="assets/logo.png" alt="SentientMilk" width="160"></p>

# SentientMilk

SentientMilk is one brain for all your apps. It runs as a local server; apps such as the
MilkChan desktop character, the `sentientmilk chat` CLI or a web chat connect to it. The
brain owns the provider and model, the agent loop, tools, memory, background tasks,
schedules and MCP servers. Apps add their own features on top: MilkChan adds a body
(expressions), screenshots and proactive messages.

SentientMilk is the authority: the provider, keys, personas, toolkits and memory are set
up in its own control panel, never inside an app. Without other settings it uses
`https://api.refuseless.com/v1` with `deepseek-v4.1-flash-fast`, so only an API key is
needed. The design, with its sources, is in [docs/architecture.md](docs/architecture.md).

The model can run shell commands and change files as the user who runs the brain, in the
folders an app allows. Only connect apps you trust.

## Run it

```bash
python -m pip install -e ".[dev]"     # ".[mcp]" adds MCP support without the test tools
sentientmilk                          # the control panel: set the API key under Provider
sentientmilk chat                     # a coding agent in the current folder
```

On Windows, `run.bat` does the same from this checkout (`run.bat` opens the panel,
`run.bat chat` chats); its first run creates `.venv` with Python 3.12. `build.bat` builds
`dist\windows\SentientMilk\` from `.venv` (or `SENTIENTMILK_PYTHON`); start it with
`SentientMilk.exe`, or with `SentientMilk.lnk` or `SentientMilk.cmd` (`SentientMilk.cmd chat`
chats) until the .exe is signed. Whichever you open last is how apps start the brain.
MilkChan's installer includes this folder and runs `SentientMilk setup`, which records the
installed brain without starting it.

The build is not a PyInstaller .exe, because Smart App Control blocks unsigned programs it
does not know, and a PyInstaller .exe is a new one on every build. The folder holds Python's
own runtime (signed by the Python Software Foundation), the package files pip installed
(the same bytes as in `.venv`, so Windows already knows them), the source, and
`SentientMilk.exe`: a small launcher (`scripts/host.cs`, compiled by the C# compiler
Windows has) that runs Python in its own process, so Windows shows SentientMilk's name and
version. It is the one new program, the one to sign. `scripts/bundle.py` makes the folder;
MilkChan's build uses it too. Source files git ignores (local settings, keys, databases)
stay out of the folder.

### The control panel

`sentientmilk` with no command opens a terminal control panel. It starts the brain when
none runs and shows it live:

- **Overview**: state, address, uptime, the provider, token use per app, tasks, schedules.
- **Provider**: service URL, model (with a model list from the service), keys (write-only),
  thinking, context window, images, streaming, request budget, shell.
- **Apps**: each connected app's persona, model, toolkits and conversations; its memory,
  where single entries can be forgotten.
- **Work**: tasks (cancel) and schedules (pause, delete). **Journal**: search and delete notes.
- **Tools**: toolkits on or off for every app, approval rules, MCP servers.
- **Plugins**: install (a folder or a git URL), turn on or off, settings (secrets
  write-only), remove.
- **Logs**: `brain.log` as it grows.

Keys: `1`-`8` tabs, `s` start, `x` stop, `r` refresh, `ctrl+s` save the open page, `q` quit.

The brain is a background service: it runs until it is stopped, never on its own, and
closing the panel leaves it running. While it runs, its milk carton sits in the Windows
notification area. A teal dot on the carton means it is working, and its tooltip names the
model. Double-click it (or **Open control panel**) to open the panel; **Stop the brain**
stops it. Without a notification area (no desktop, or `pystray` missing) it runs all the
same, and the panel's `x` stops it.

Opening SentientMilk (the panel or any command) records how to start it in `launch.json`.
Apps start the brain that way when none runs, each as its own process; a packaged app on
a computer where SentientMilk was never opened says so instead. One brain runs per home
folder. There is no autostart: after a reboot, a schedule that came due fires when the
brain next starts.

Other commands: `serve` (run in the foreground), `tasks [show|cancel ID]`,
`schedules [delete ID]`, `journal [QUERY] [--delete ID]`,
`mcp [add NAME (--url URL | -- COMMAND ...)|remove NAME]`,
`plugins [show NAME|install FOLDER_OR_GIT_URL|reload NAME|remove NAME|on NAME|off NAME|trust NAME|distrust NAME|set NAME KEY[=VALUE]...]`,
`stats`, `eval`.

The brain keeps its files in `~/.sentientmilk` (`--home` or `SENTIENTMILK_HOME` changes it):

- `config.json`: settings, including the API key; `mcp.json`: MCP servers; `plugins.json`:
  plugins turned off and their settings. All readable by the user only.
- `brain.sqlite3`: apps, sessions, the event log of every run, memory, journal, schedules.
- `server.json`: the running brain's address and token; `launch.json`: how apps start it;
  `brain.lock`, `brain.log`.
- `runs/<id>/`: long tool output and task progress files; `plugins/`: installed plugins;
  `toolkits/`: single-file toolkits of your own.

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
                     on_event=print)  # text.delta, tool.start/end, retry, compacting, cleared, ... as they happen
print(result["reply"], result["signals"], result["tools"])
for notification in client.events("jarvis"):  # reminders, finished tasks; blocks
    print(notification["type"], notification["data"])
```

- An **app** declares who the brain is there: name, environment, persona, signals,
  toolkits, permission rules and allowed folders (`roots`), and with `callbacks: true` that
  it starts a turn when a job or agent of a turn ends: its turns then wait at most 10 s for
  them and are told to end instead (MilkChan does). A **session** is one
  conversation in an app. Memory belongs to the app; the **journal** holds short, dated
  notes about sessions across all apps, oldest deleted first when it is full.
- The persona is who the model is in that app, not a role it plays: the prompt opens with it
  under **WHO YOU ARE**, says a description written as "she" or by name means "you", and asks
  for thinking in the first person, as that self. Nothing else in the prompt calls the model an
  AI, an assistant or "the brain"; compaction summaries speak to it as "you".
- A turn's input is a list of items: `text`, `image` (a data URL) and `event`
  (`{"type": "event", "name": "idle", "text": "..."}`). With `reply="optional"` the
  brain may stay silent (`result["silent"]`). `context` adds a line such as the user's
  name; the time is always added.
- With **signals** declared, replies start with one JSON line (`{"mood": "calm"}`) that the
  brain checks and strips; grouped options read `group/option`. A wrong signal is dropped
  and the model is told on its next turn.
- **Approvals**: tools whose policy is `ask` emit `approval.requested`. `on_approval`
  answers `allow`, `always` (saved as a rule) or `deny`; without it they are denied.
  Rules are `tool` or `tool(pattern)` lists under `deny`, `ask` and `allow`. A background
  task that waits sends `task.input_required`; `GET /runs/{id}` lists what it waits for
  (`waiting`), and `client.answer` answers it.
- **Actions** are tools the app runs itself, offered in turns only (the app is there to
  run them). The model calls one, the turn emits `action.requested`, and `on_action(event)`
  returns the result, or `(text, [image data URLs])`: the images reach the model right
  after the result, stored small like input images. MilkChan's `screenshot` is one: the
  model looks at the screen only when a message needs it. An action declared with
  `"policy": "ask"` passes the same rules and approvals as a tool before the app runs it
  (MilkChan's `computer_act`).
- **Tasks** (`client.start_task`) run in the background in their own session, keep a
  progress file, can be checked by a reviewer (`verify=True`) and report back as a note in
  the parent session plus a `task.completed` notification.
- **Agents** are the model's own background work: copies of it with a fresh context that
  each do one part of a job, in sessions of their own. They have all of its tools, rules and
  app actions (their approvals and actions reach the app as `agent.input_required`); what they
  know is the task it writes. They can ask it questions (`ask_lead`) and send progress notes.
  Each report, question and update reaches the chat once: through `agents_wait`, as a note,
  or with `agent.finished` / `agent.asked` when nobody was there to take it. Apps hear
  `agent.updated` as agents start and end; `client.agents(app, session)`, `client.agent(id)`
  and `client.stop_agent(id)` (which deletes it) let them show and stop agents.
- **Tools on demand**: requests carry only the core tools plus `tools_search` and
  `tools_load`; the rest are listed by name and loaded into the conversation when needed, so
  the tool list (and the prompt cache) stays the same. An action declared with
  `"core": true` is always sent.
- **Schedules** (`at 2026-11-06T09:00`, `every 30m`, or 5-field cron) either wake the app
  (a `schedule.fired` notification) or start a task.
- Failures raise `BrainError` with `type` (`config_missing`, `rate_limit`,
  `auth_error`, `timeout`, `network`, `payload_too_large`, `brain_unreachable`, ...),
  `message` and `details`. A client from `connect()` starts the brain again when it vanished.

## Toolkits

| Toolkit | Tools |
| --- | --- |
| `files` | `files_read`, `files_search`, `files_find`, `files_edit`, `files_write` (a change that breaks Python, JSON or TOML syntax is refused) |
| `shell` | `shell_run` (PowerShell on Windows; `shell` setting), `shell_output`, `shell_stop` for background jobs; a command still running after 30 s goes on as one |
| `web` | `web_search` (Brave, needs `web_search_key`), `web_fetch` |
| `todo` | `todo_write` |
| `memory` | `memory_save`, `memory_get`, `memory_list`, `memory_forget` |
| `journal` | `journal_search` |
| `agents` | `agent_start`, `agent_message`, `agents_wait`, `agents_status`, `agent_stop` |
| `schedule` | `schedule_create`, `schedule_list`, `schedule_delete` |
| `mcp:<server>` | the server's tools, as `mcp__<server>__<tool>` |
| `plugins` | `plugin_list`, `plugin_install`, `plugin_reload`: the model writes its own plugins (installing always asks) |
| `github` (plugin) | search, repositories and files, issues and pull requests (diffs, reviews, checks), Actions runs with the log of what failed, any REST read; opening, commenting, reviewing, merging and any other REST call ask first |

An app enables the toolkits it lists, and every app gets the toolkits of enabled plugins;
the user can disable any of them for the whole brain (`disabled_toolkits`), an app or a
session.

## Plugins

Plugins extend the brain for every app. A plugin is a folder with a `plugin.json` that
brings toolkits, MCP servers and settings (`docs/architecture.md`, section 6.5):

```json
{"name": "weather", "version": "1.0.0", "description": "Current weather.",
 "toolkits": ["tools.py"],
 "settings": {"key": {"label": "API key", "secret": true, "env": ["WEATHER_KEY"]}}}
```

```python
# tools.py
from sentientmilk_framework.toolkits import Toolkit, tool

@tool(readonly=True, args={"city": "City name."})
def weather_now(ctx, city: str):
    """The current weather in a city."""
    key = ctx.brain.plugins.settings("weather")["key"]
    return f"Sunny in {city}."

TOOLKIT = Toolkit("weather", "Current weather.", [weather_now])
```

Install it with `sentientmilk plugins install C:/plugins/weather` (or a git URL), or from
the panel. A single file with `TOOLKIT` in `~/.sentientmilk/toolkits/` loads as a plugin
too. A plugin runs as you, inside the brain: install only plugins you trust.

A model can write its own plugins with the `plugins` toolkit: it writes the files, then
`plugin_install` asks you every time, whatever your rules or an app's bypass say, because
installing runs the plugin's code. Trust follows a plugin's exact files: what you install
yourself is trusted, but a plugin a model installed, or one changed since you trusted it,
is not. Each tool of an untrusted plugin asks you every time it runs, and its MCP servers
don't start, until you trust it in the panel (Plugins: Trust) or with
`sentientmilk plugins trust NAME`.

**GitHub** comes built in. It uses the token set in its settings, else `GITHUB_TOKEN` or
`GH_TOKEN`, else the login of the `gh` CLI; without any, it reads public data only.
Reading asks nothing; every change asks first.

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
| `GET /apps/{app}/sessions`, `GET /apps/{app}/memory` | sessions (each with `title`, `preview`: the start of its first message, `last_active`) and memory of an app |
| `GET`/`PATCH`/`DELETE /apps/{app}/sessions/{id}` | a session and its settings (`title` among them); `context`: how full it is (`used` tokens at the last step, the `window`, and the `clear_at`/`compact_at` fractions); deleting it and its history, refused (409 `busy`) while a turn of it goes on |
| `POST /apps/{app}/sessions/{id}/compact` | sum up the whole session now (a model call): `compacted`, and the context in tokens `before` and `after` |
| `GET`/`DELETE /apps/{app}/sessions/{id}/history`, `POST .../import` | the shown history (`?tools=1` adds each tool call: name, arguments, status, output, seconds); history an app kept before |
| `POST /apps/{app}/sessions/{id}/turns` | `input`, `context`, `reply`: a stream ending in `done` or `error` |
| `GET /events?app=&after=` | notifications from a cursor (`-1`: from now), then live |
| `POST`/`GET /tasks`, `GET /tasks/{id}` | start and list tasks |
| `GET /runs/{id}`, `GET /runs/{id}/events` | a run and what it waits for (`waiting`); its log, then live |
| `POST /runs/{id}/answer`, `/cancel`, `/steer`, `/detach` | answer an approval, question or action (`result`, `images`); cancel at once (waits inside tools end, calls still running are left behind with a stopped result, a command in the foreground is ended, helpers stop too); steer: `input` for a turn that works, which reaches the model at its next step (waits end early, approvals it waits for are refused; 409 `ended` once the turn is over, and one that comes as it finishes is returned in `done` as `unread`); let a turn go on in the background |
| `GET`/`POST /schedules`, `PATCH`/`DELETE /schedules/{id}` | schedules |
| `GET /toolkits`, `GET`/`PUT /mcp`, `POST /mcp/{name}/reconnect` | toolkits and MCP servers |
| `GET`/`POST /plugins`, `PATCH`/`DELETE /plugins/{name}`, `POST /plugins/{name}/reload` | plugins: list (secrets only as `set`), install (`source`: a folder or git URL), `enabled`, `settings` and `trusted`, reload from its source, remove |
| `GET /apps`, `DELETE /apps/{app}/memory/{category}/{key}`, `POST /shutdown` | apps, forgetting a memory, stopping the brain |
| `GET /journal?q=`, `DELETE /journal/{id}`, `GET /jobs/{id}` | the journal; background shell jobs |

Errors answer `{"error": {"type", "message", "details", "http_status"}}`. The stored API
key is only ever sent to the stored `base_url`.

## Settings

`api_key`, `base_url`, `model`, `light_model` (summaries, journal notes, helpers; empty:
the same as `model`), `context_window` (128000), `thinking_mode` (`default`, `none`,
`minimal`, `low`, `medium`, `high`, `xhigh` or `tokens`), `thinking_tokens`, `vision`,
`request_budget` (bytes per request, 800 KiB), `stream`, `web_search_key`, `shell`,
`task_workers` (2), `rules`, `disabled_toolkits`.

## Development

Use Python 3.12:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
sentientmilk eval                  # 10 real tasks against the configured model
```

`sentientmilk_framework.testing.FakeProvider` stands in for the provider in tests, for
this repository and for apps. `tests/test_panel.py` drives the panel headless.

## Repository layout

```text
sentientmilk_framework/
  server.py      HTTP server, the brain lock
  tray.py        the brain's milk carton in the notification area
  client.py      BrainClient and connect() for apps; launch.json
  panel.py       the terminal control panel (Textual)
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
  plugins/       plugin loading, settings and install; github/: the GitHub plugin
  toolkits/      built-in toolkits
  transport.py   images sized to the request budget
  config.py, thinking.py, exceptions.py
  evals.py, eval_tasks/, testing.py, cli.py
tests/
docs/architecture.md
run.bat                                                     Windows: run from this checkout
build.bat, scripts/bundle.py, scripts/host.cs              the Windows build (a folder on signed Python)
```
