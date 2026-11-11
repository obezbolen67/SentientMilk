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
- **Apps**: each connected app's persona, model, toolkits and conversations.
- **Work**: tasks (cancel) and schedules (pause, delete). **Memory**: what the brain remembers for
  every app (with the app that saved each entry), where single entries can be forgotten, and the
  journal, to search and delete notes.
- **Tools**: toolkits on or off for every app, approval rules, MCP servers.
- **Plugins**: install (a folder or a git URL), turn on or off, settings (secrets
  write-only), remove.
- **Skills**: every skill, who starts it, what is wrong with a broken one; open its folder,
  remove it.
- **Logs**: `brain.log` as it grows.

Keys: `1`-`9` tabs, `s` start, `x` stop, `r` refresh, `ctrl+s` save the open page, `q` quit.

The brain is a background service: it runs until it is stopped, never on its own, and
closing the panel leaves it running. While it runs, its milk carton sits in the Windows
notification area. A teal dot on the carton means it is working, and its tooltip names the
model. Double-click it (or **Open control panel**) to open the panel; **Stop the brain**
stops it. Without a notification area (no desktop, or `pystray` missing) it runs all the
same, and the panel's `x` stops it.

Opening SentientMilk (the panel or any command) records how to start it in `launch.json`.
Apps start the brain that way when none runs, each as its own process; a packaged app on
a computer where SentientMilk was never opened says so instead. One brain runs per home
folder. On Windows, **Start with Windows** on the panel's Overview starts the brain in the
background when you sign in, with only its tray icon: an entry in Windows' Startup apps
(the current user's Run key; Task Manager can turn it off too, and the switch shows that).
It runs `SentientMilkw.exe ... start`, the same program built with no console, which starts
the brain the recorded way and exits. Without it, a schedule that came due fires when the
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
    toolkits=["web", "schedule", "tasks"],  # every app has memory
    rules={"allow": ["schedule_create"]})
result = client.turn("jarvis", "main", "Lights off, please.", context={"user": "Tony"},
                     on_event=print)  # text.delta, tool.start/end, retry, compacting, cleared, ... as they happen
print(result["reply"], result["signals"], result["tools"])
for notification in client.events("jarvis"):  # finished tasks and jobs, due schedules; blocks
    print(notification["type"], notification["data"])
```

- An **app** declares who the brain is there: name, environment, persona, signals,
  toolkits, permission rules and allowed folders (`roots`), and with `callbacks: true` that
  it starts a turn when a job or agent of a turn ends: its turns then wait at most 10 s for
  them and are told to end instead (MilkChan does). A **session** is one
  conversation in an app. **Memory** (lasting facts about the user and their world) is shared by
  every app and always whole in context, no app has to ask for it; each session also has its own
  **session memory** (instructions and facts for that conversation only, kept through compaction),
  and the **journal** holds short, dated notes about what happened in sessions across all apps.
- The persona is who the model is in that app, not a role it plays: the prompt opens with it
  under **WHO YOU ARE**, says a description written as "she" or by name means "you", and asks
  for thinking in the first person, as that self. Nothing else in the prompt calls the model an
  AI, an assistant or "the brain"; compaction summaries speak to it as "you".
- A turn's input is a list of items: `text`, `image` (a data URL), `event`
  (`{"type": "event", "name": "idle", "text": "..."}`) and up to 8 `mention`s
  (`{"type": "mention", "kind": "session", "ref": "chat-1", "label": "Groceries"}`; kinds:
  `session`, `agent`, `plugin`, `file`). The brain turns each mention into a short card
  after the user's text and keeps it with the message; history entries list them as
  `mentions`, and `GET /apps/{app}/mentions` offers what an `@` picker shows. A file the user
  **attached** is a file mention with `"attached": true` (up to 20 a message, not counted as
  mentions; a message may be attachments alone): the model gets its path (with the start of a
  text file), a picture inline as well when images are on and it reads as one (up to 20 MB;
  otherwise its path and why), and the file tools may read it from then on in that session,
  wherever it is. With `reply="optional"` the
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
- **Super agents** are agents Claude does, through the user's own Claude Code, for code and
  deep thinking: `agent_start(..., super_agent=true)`. The model and its thinking effort (low
  to max) are set under Provider > Super model in the control panel (default: Opus 5.5, high).
  They work like any agent, asking before changes; they need Claude Code installed and signed
  in, and use the user's Claude plan.
- **Tools on demand**: requests carry only the core tools plus `tools_search` and
  `tools_load`; the rest are listed with their parameters and loaded into the conversation when needed, so
  the tool list (and the prompt cache) stays the same. An action declared with
  `"core": true` is always sent.
- **Schedules** are work for later, once (ISO time, `in 20m`) or repeating (`every 30m`, 5-field cron);
  reminders are schedules too. Each belongs to an app and runs as a normal turn in its own persistent
  conversation: an app that calls back runs it through its own workflow, otherwise the brain does.
  Named timezones follow daylight saving; offline deliveries wait and coalesce. The model clarifies
  missing clock times and can update, pause or delete schedules. See [the scheduling
  contract](docs/scheduling.md) for the app adapter and recovery protocol.
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
| `memory` (every app) | `memory_save`, `memory_forget`, each with `scope` everywhere (lasting) or session (this session only) |
| `journal` | `journal_search` |
| `agents` | `agent_start`, `agent_message`, `agents_wait`, `agents_status`, `agent_stop` |
| `schedule` | `schedule_create`, `schedule_list`, `schedule_update`, `schedule_delete` |
| `mcp:<server>` | the server's tools, as `mcp__<server>__<tool>` |
| `plugins` | `plugin_list`, `plugin_install`, `plugin_reload`: the model writes its own plugins (installing always asks) |
| `skills` | `skill_use` (sent with every request, like Claude's Skill tool), `skill_list`, `skill_delete`: her skills (see Skills) |
| `sessions` | `sessions_list`, `sessions_read` (a summary, or the plain turns without tool calls), `sessions_search`, `session_rename`, `session_delete` (always asks): the app's other conversations |
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

## Skills

Skills work as they do in Claude: instructions for a kind of task that load only when a
task needs them. A skill is a folder in `~/.sentientmilk/skills/` with a `SKILL.md`:

```markdown
---
name: filing-receipts
description: Files receipt photos into the expenses sheet. Use when the user sends a receipt.
argument-hint: "[month]"
---

1. Read the receipt ...
```

Every app with the `skills` toolkit lists each skill's name and description in the
model's prompt. When a task matches one, it loads the instructions with `skill_use`, and
reads the skill's other files (references, scripts, templates) only when they say to.
The user starts one directly with `/name` and arguments (a `skill` input item; the
MilkChan chat and `sentientmilk chat` offer it). `$ARGUMENTS`, `$0`, `$1` and
`${SKILL_DIR}` in the instructions take what was passed and the skill's folder.
`disable-model-invocation: true` makes a skill the user's only; `user-invocable: false`
keeps it out of the `/` list. The folder's name is the skill's name (lowercase letters,
numbers and hyphens); the description says what it does and when to use it.

The model writes and edits skills with its file tools (the skills folder is open to them;
the rest of `~/.sentientmilk` stays closed), after loading the built-in `skill-creator`.
A file write asks you as usual, a change counts from its next step, and returning to an
earlier message takes it back. Skills written for Claude work as they are: copy a skill's
folder in. A skill of yours replaces a built-in one of the same name.

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
| `GET /apps/{app}/sessions`, `GET /memory` | sessions (each with `title`, `preview`: the start of its first message, `last_active`); memory, shared by every app: `entries`, each with the app that saved it |
| `GET`/`PATCH`/`DELETE /apps/{app}/sessions/{id}` | a session and its settings (`title` among them); `context`: how full it is (`used` tokens at the last step, the `window`, and the `clear_at`/`compact_at` fractions); deleting it and its history, refused (409 `busy`) while a turn of it goes on |
| `POST /apps/{app}/sessions/{id}/compact` | sum up the whole session now (a model call): `compacted`, and the context in tokens `before` and `after` |
| `GET`/`DELETE /apps/{app}/sessions/{id}/history`, `POST .../import` | the shown history (`?tools=1` adds each tool call: name, arguments, status, output, seconds); each entry's `id` is its event's; history an app kept before |
| `GET`/`POST /apps/{app}/sessions/{id}/rewind` (`?to=` / `{"to"}`: a user message's `id`) | go back to just before that message (GET: what it would do). Undone: what came after it, files changed since with `files_write`/`files_edit` (also by agents started since), the todo list and the session's own memory, work started since (jobs, agents' runs, runs of new schedules: stopped quietly), new agents and schedules (deleted). Answers `text` and `mentions` (the message), `messages`, `files` ({path, change}), `todo` and `session_memory` (whether each goes back), `agents`, `stopped`, `schedules`, `kept` (calls whose effects stay: {name, count}) and, after a POST, `problems`; refused (409 `busy`) while a run of the session goes on |
| `POST /apps/{app}/sessions/{id}/turns` | `input` (text, image, event, mention and skill items: `{"type": "skill", "name", "arguments"}` starts a skill as the user's `/name` does), `context`, `reply`: a stream ending in `done` or `error` |
| `GET /apps/{app}/mentions?q=&kind=&session=`, `GET /apps/{app}/mentions/{kind}?ref=&session=` | what an `@` picker offers (`kind`, `ref`, `label`, `note`, `time`; a path lists that folder), and the card the brain reads for one |
| `GET /events?app=&after=` | notifications from a cursor (`-1`: from now), then live |
| `POST`/`GET /tasks`, `GET /tasks/{id}` | start and list tasks |
| `GET /runs/{id}`, `GET /runs/{id}/events` | a run and what it waits for (`waiting`); its log, then live |
| `POST /runs/{id}/answer`, `/cancel`, `/steer`, `/detach` | answer an approval, question or action (`result`, `images`); cancel at once (waits inside tools end, calls still running are left behind with a stopped result, a command in the foreground is ended, helpers stop too); steer: `input` for a turn that works, which reaches the model at its next step (waits end early, approvals it waits for are refused; 409 `ended` once the turn is over, and one that comes as it finishes is returned in `done` as `unread`); let a turn go on in the background |
| `GET`/`POST /schedules`, `PATCH`/`DELETE /schedules/{id}` | schedules |
| `GET /apps/{app}/scheduled?pending=1` | durable scheduled deliveries for the app |
| `GET /toolkits`, `GET`/`PUT /mcp`, `POST /mcp/{name}/reconnect` | toolkits and MCP servers |
| `GET`/`POST /plugins`, `PATCH`/`DELETE /plugins/{name}`, `POST /plugins/{name}/reload` | plugins: list (secrets only as `set`), install (`source`: a folder or git URL), `enabled`, `settings` and `trusted`, reload from its source, remove |
| `GET /skills`, `DELETE /skills/{name}` | skills (`name`, `description`, `argument_hint`, `model_invocable`, `user_invocable`, `builtin`, `path`, `error`); removing one of the user's |
| `GET /apps`, `DELETE /memory/{category}/{key}`, `DELETE /apps/{app}/sessions/{id}/memory/{key}`, `POST /shutdown` | apps, forgetting a memory or one thing of a session's memory, stopping the brain |
| `GET /journal?q=`, `DELETE /journal/{id}`, `GET /jobs/{id}` | the journal; background shell jobs |
| `GET /apps/{app}/jobs?since=`, `POST /jobs/{id}/stop` | an app's running jobs and those that ended after `since`, each with its newest output line (`last`); stopping one and everything it started |

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
  scheduler.py   schedules, once or repeating (at, in, every, cron)
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
