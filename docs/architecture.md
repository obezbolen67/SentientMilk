# SentientMilk v2: architecture

Current scheduling (0.7.0, 2026-11-11): one kind of schedule, once or repeating, each run a normal turn
in the schedule's own conversation ([scheduling](scheduling.md), section 9.6). Reminders are schedules.

Current memory (0.8.1, 2026-11-11): memory is shared by every app and always whole in context; each
session has its own session memory besides (section 10).

Status: built (version 0.4.0, 2026-11-06). Written 2026-11-05 as the design; section 17 lists
where the build differs from it and what the evals measured.

SentientMilk is one shared brain for several apps: MilkChan (a desktop character), a CLI chat
and a web chat. Apps add features (sprites, voice, proactive messages); the brain provides
thinking, tools, memory and the ability to work on its own for a long time. This document
designs the brain's agent runtime so the model inside works with its environment, its
context and MCP servers the way Claude Code does, and can run long, background and
scheduled tasks.

Honest limit: a harness cannot make a model smarter than it is. It can remove the causes of
failure that are not the model's fault: missing context, bloated context, bad tools, lost
progress. Every Anthropic number below was measured on Claude models. On
`deepseek-v4.1-flash-fast` we measure with our own evals (section 12) before we trust a rule.

## 1. Decisions at a glance

1. **One loop, one log.** Every piece of work (a chat turn, a background task, an agent)
   is a *run* of the same agent loop. Each step is written to an append-only event log in
   SQLite before the next step starts. A crash loses at most the step in flight.
2. **Writes stay in one place.** Agents read by default and return a short report. An agent
   that may change things is started on purpose, for its own part of the job, and each change
   it makes is approved like the main run's. Writers that share files are not coordinated.
3. **Tools built as an agent interface.** Few tools, clearly named, with token-efficient
   results, actionable errors and hard output caps. Big output goes to a file and the model
   gets the path. Edits are validated and rolled back when they break syntax.
4. **The past is rewritten only at compaction.** Requests are append-only between
   compactions, so the provider's prefix cache keeps hitting. Context shrinks in this order:
   output caps, then tool-result clearing, then compaction, then (for long tasks) a reset
   with a progress file.
5. **MCP servers are toolkits.** The brain is an MCP host. Each server is enabled, disabled
   and permissioned exactly like a built-in toolkit.
6. **Tasks, jobs and schedules are brain building blocks.** The brain runs background
   tasks, keeps shell jobs, and fires schedules. It never talks to the user on its own. It
   emits events, and each app decides what to do with them. Proactive messages stay
   MilkChan's feature.
7. **Memory is shared and always in context** (since 0.8; it was per app). Each session also has its
   own session memory, and the brain keeps a *journal*: short, timestamped notes about what happened
   in sessions across all apps (section 10).
8. **Evals from day one.** A small set of realistic tasks runs before and after every
   change to prompts, tools or context rules.

## 2. What the research says, and what we do with it

| Finding | Source | What SentientMilk does |
|---|---|---|
| Context is an "attention budget". Aim for "the smallest possible set of high-signal tokens". Recall degrades as context grows. | Anthropic, context engineering | Output caps, clearing, compaction (section 7), agents (section 5.5), tools loaded on demand (section 7.4). |
| Load data *just in time* through tools; keep only paths, queries and links up front. Claude Code loads its memory file up front and finds the rest with glob and grep. | Anthropic, context engineering | Search and read tools; no vector database. Memory, the session's memory and the journal are the only things loaded up front. |
| Tool-result clearing is the lightest compaction. After compaction, Claude Code keeps the summary plus the five most recently read files. | Anthropic, context engineering | Clear old tool results first. Re-read up to 5 recent files after compaction. |
| KV-cache hit rate is "the single most important metric". About 100 input tokens per output token. Cached input is 10x cheaper on Claude. Keep the prefix stable, append only, and serialize deterministically. | Manus | Request layout of section 7.1. Cache hits are logged on every call. |
| Don't add or remove tools in the middle of a task. | Manus | The tool list sent is fixed per profile; tools to load come into the conversation instead (section 7.4). |
| Compression must be *restorable*: drop a page's text but keep its URL. | Manus | Cleared results say how to get them back. Big outputs are saved to files. |
| Rewriting a todo list keeps the plan in recent attention ("recitation"). A typical task is about 50 tool calls. | Manus | `todo_write` tool. The full list is echoed back in its result. |
| Leave failed actions and errors in context; they stop the model repeating them. | Manus | Errors stay in the log and in context until compaction. |
| Share full traces. "Actions carry implicit decisions". Parallel subagents make conflicting choices. Claude Code's subagents only investigate. In 2026: "writes stay single-threaded", read-only helpers and clean-context reviewers work. | Cognition | Agents read by default; a writing agent gets its own part (section 5.5). |
| Subagents explore with tens of thousands of tokens and return "1,000-2,000 tokens". Multi-agent research beat single-agent by 90.2%, at about 15x the tokens. Each subagent needs "an objective, an output format, guidance on the tools and sources to use, and clear task boundaries". | Anthropic, context engineering and multi-agent research | Agent reports are capped at about 2,000 tokens (the whole one goes to a file). `agent_start` asks for exactly that brief. |
| Spawn returns an id at once; a wait collects results like a mailbox; persistent agents take follow-up messages; "smaller models ... forget to call kill_agent". | Schmid, subagent patterns 2026 | `agent_start`, `agents_wait`, `agent_message`, `agent_stop`, and a mailbox table for what agents send; an idle agent is deleted after a day. |
| Long work spans many context windows. An initializer sets up the work; each later session does one item, commits, and updates a progress file. A fresh context rebuilds state from the progress file, the feature list and `git log`. JSON feature lists get corrupted less often than markdown. | Anthropic, harnesses for long-running agents | Task workspace with `progress.md`, `plan.json` and git (section 9.4). |
| Self-evaluation is generous. A separate, skeptical evaluator is "a strong lever". Some models get "context anxiety" and wrap up early; resets helped Sonnet 4.5, compaction was enough for Opus 4.5. | Anthropic, harness design for long-running apps | Optional verifier subagent. Per-task choice of `compact` or `reset`, decided by evals. |
| The loop is "gather context, take action, verify work, repeat". Linting is a good verifier; LLM-as-judge is "generally not a very robust method". | Claude Agent SDK post | Rules in the system prompt. Verification through tests and checks, not judgment. |
| Consolidate tools around workflows. Use namespaced names. Return names, not UUIDs. Offer concise and detailed output. Truncate with a hint. Write errors that show a correct call. Claude Code caps a tool response at 25,000 tokens. | Anthropic, writing tools for agents | Tool rules of section 6.1. |
| A linter that blocks bad edits was the most valuable part of the agent-computer interface. Showing 100 lines worked better than 30 lines or the whole file. Paging search results one at a time did worse than no search (12.0% vs 15.7%). | SWE-agent | Edit validation with rollback. Read in windows. Search returns a compact list of all matches. |
| The agent is a stateless step function over an append-only event log. The default condenser keeps the first events and summarizes the rest, for "up to 2x" lower cost. | OpenHands SDK | Section 5. Compaction is stored as its own event; the raw log stays. |
| Persist at every step. Assume at-least-once: anything after the last record may run again. Pause by persisting and returning, not by blocking a thread. Record model and config in the run's input. | LangGraph, Temporal | Section 5.3. Approvals pause the run and free the thread. |
| MCP 2026-07-28 has a stateless core (no `initialize`, no sessions), `server/discover`, MRTR for elicitation, and deprecated sampling and roots. Tasks are an extension: `working`, `input_required`, `completed`, `failed`, `cancelled`. | MCP blog, Tasks overview | MCP host of section 8. Our run states use the same names. |
| Python SDK `mcp` 2.3.0 (2026-10-02) is async only. It falls back to `initialize` for older servers and handles MRTR itself. It does *not* implement the Tasks extension yet. | MCP Python SDK docs, PyPI | A dedicated MCP thread with an event loop. A long MCP call goes on as a job (section 8.3). |
| Claude Code defers MCP tool definitions: only names cost context until a tool is used. Big MCP output is saved to a file. Picking tools gets worse past 30-50; keep the 3-5 most used loaded and search for the rest (Opus 4: 49% to 74%). | Claude Code docs; Anthropic, advanced tool use | Only core tools are sent; the others are listed and loaded on demand (section 7.4). |
| Claude Code's scheduled tasks fire only between turns, with no catch-up. Recurring ones expire after 7 days. Its cloud routines run with the laptop off. | Claude Code docs | Durable schedules in the brain, with one catch-up run on start (section 9.6). |
| DeepSeek caches prefixes automatically. Usage reports `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`. On flash, a hit costs $0.003 to $0.006 per million tokens and a miss $0.15 to $0.3. With tools, `reasoning_content` "must be fully passed back" or the API returns 400. Context is 1M tokens. | DeepSeek API docs | Assistant messages are stored whole, reasoning included. Context window is configured per model. |

## 3. Concepts

Kept from the agreed v2 design:

- **Brain**: one process per home folder (`~/.sentientmilk`).
- **App**: a profile with persona, models, enabled toolkits, permissions and signals.
- **Session**: one conversation of an app. An app can have many.
- **Input items**: `text`, `image` and `event`. A turn can say `reply: optional`.
- **Signals**: structured values next to the reply, such as MilkChan's expression. They use
  the measured header format: one JSON line, then free text.
- **Toolkit**: a named group of tools. A tool reaches the model only if the brain, the app
  and the session all allow it.
- **Action**: a tool the app itself runs, such as MilkChan's own abilities.

New in this document:

- **Run**: one execution of the agent loop. Its kind is `turn` (an app is waiting), `task`
  (background, started by an app or a schedule), `agent` (a run of an agent), `subagent` (a
  task's reviewer, which the task waits for) or `compact`.
- **Agent**: a copy of the model with a fresh context that does one part of a job in the
  background, in a session of its own (`agent-<id>`). Its runs report to the session that
  started it.
- **Event**: one immutable record in the log, such as an input, a model reply, a tool call,
  a tool result, an approval or a compaction.
- **Job**: a background shell command with a log file.
- **Schedule**: a stored rule that fires at a time (`at`), on a cron expression, or every N
  minutes.
- **Notification**: something the brain tells apps, such as a task finishing or a schedule
  firing. Apps read notifications from a stream with a cursor.
- **Memory**: facts one app keeps. Each app has its own.
- **Journal**: short, timestamped notes about sessions across all apps.

## 4. Process and storage

```
            apps: MilkChan, CLI chat, web backend
                  | HTTP + SSE on 127.0.0.1, bearer token
+-----------------v-------------------------------------------+
| brain process (one per home; brain.lock)                    |
|                                                             |
|  HTTP threads -- start runs, stream their events            |
|  run executor (worker threads) -- turns, tasks, agents      |
|  scheduler thread -- fires schedules                        |
|  MCP thread -- one event loop, one task per MCP server      |
|  summarizer queue -- compaction, journal notes              |
|                                                             |
|  brain.sqlite3 (WAL)          files under home              |
+-------------------------------------------------------------+
```

- An HTTP request never runs the loop itself. It starts a run and streams that run's
  events. So a turn survives the app going away, and an app can *detach* a long turn
  into a background task, like Ctrl+B in Claude Code.
- `brain.lock` guarantees one brain per home. Any run still marked `working` at startup was
  therefore interrupted, so no lease logic is needed.
- The brain stays alive while it has enabled schedules, working runs or jobs. Otherwise it
  exits after 30 idle minutes, and the next app restarts it. For schedules to fire with no
  app open, `sentientmilk autostart on` registers it at login (a Windows startup entry, a
  systemd user unit on Linux).

Tables in `brain.sqlite3`:

| Table | Holds |
|---|---|
| `apps` | the profile of each app |
| `sessions` | app, id, body, persona override, settings |
| `runs` | id, app, session, kind, parent run, status, goal, options (model, budgets, toolkits), result, usage, timestamps |
| `events` | id, run, session, seq, time, type, data (JSON). The single source of truth; it replaces today's `messages` and `transcript` tables. |
| `jobs` | id, run, command, pid, status, exit code, log path |
| `schedules` | id, app, session, kind, spec, payload, next fire time, last fire time, catch-up, created by, enabled |
| `notifications` | id, time, app, session, type, data |
| `memory` | category, key, value, app (the one that saved it), updated. Shared by every app since 0.8. |
| `journal` | id, time, app, session, note |

Files under home:

```
~/.sentientmilk/
  server.json   url, token, pid (mode 0600)
  config.json   providers, defaults, policies (secrets only as *_set flags over the API)
  mcp.json      MCP servers
  toolkits/     plugin toolkits (*.py)
  runs/<id>/    big tool outputs, job logs, task workspace notes
```

Run states use the MCP Tasks names plus `queued`: `queued`, `working`, `input_required`,
`completed`, `failed`, `cancelled`.

## 5. The agent loop

### 5.1 Events

| Type | Data |
|---|---|
| `input` | the typed items as sent, *including* the dynamic tail (section 7.1) |
| `assistant` | the provider message as returned: content, `reasoning_content`, tool calls; plus usage and cache hits |
| `tool_start` / `tool_end` | call id, tool, arguments / result as the model saw it, status, path of the full output if capped |
| `approval` | requested call and the answer: allow once, allow always, or deny with a reason |
| `action` | an app action requested, and its result |
| `note` | system notes: a task finished, the brain restarted, an expression was rejected |
| `compaction` | the summary and the range of events it replaces; the raw events stay |
| `clearing` | the tool results that were cleared |
| `end` | status, reply, signals, total usage |
| `rewound` | the user went back to before event `to` (section 5.6); it takes the id of the last event that went |

Model messages and the app transcript are both *projections* of the log. The projection is
deterministic, so the same log always gives the same request bytes.

### 5.2 One step

```
run(r):
    while True:
        check the caller's budget (max_steps), if any   -> end(failed, "budget")
        request = build_context(r)                       # section 7
        if request is too big: compact(r); continue
        message = provider.call(request, stream=r.streams)   # text.delta events
        log(assistant, message)
        if no tool calls:
            signals = parse_signals(message)   # header format; a bad value adds a note
            log(end, completed); return
        for each call (read-only calls in parallel, others in order):
            policy = permissions(call)
            off  -> log(tool_end, error "this tool is disabled here")
            ask  -> log(approval requested); r.status = input_required; return
            action -> log(action requested); r.status = input_required; return
            auto -> log(tool_start); result = run tool with timeout; log(tool_end)
```

- Pausing returns from the loop and frees the thread. An answer (approval or action
  result) is logged and the run is queued again. The loop then picks up the pending call.
- The tool list is computed once per run and never changes inside it.

### 5.3 Crash recovery

At startup the brain finds runs marked `working`:

- A `tool_start` without a `tool_end`, on a tool marked read-only: run it again.
- The same on any other tool: log a `tool_end` that says "The brain stopped while this
  ran. It may or may not have finished. Check before repeating it." Side effects are never
  repeated blindly.
- Tasks then continue. Turns end as `failed` with type `interrupted`, because no app is
  waiting for them. The app can read what happened from the history.
- Each run stores its model, its budgets and its toolkits in `runs.options`. A resumed run
  uses those, not whatever the config says now.

### 5.4 Limits

A run has no step limit: a turn, a task or an agent works until its job is done or the user
stops it. A turn that ended at 40 steps left the user's job half done (the user, 2026-11-09).
A caller that wants a limit sets `max_steps` (the evals do); hitting it ends the run as
`failed` with type `budget`, and its progress is saved, so a new task can continue it.

### 5.5 Agents

An agent is a copy of the model with a fresh context. It does one part of a job in the
background, in its own session `agent-<id>` (the id of its first run), while the run that
started it (the lead: a turn or a task) goes on. `agents.py` keeps them; `toolkits/agents.py`
holds the tools.

- **What an agent has**: the lead's whole profile. That is every toolkit, MCP server and app
  action, `tools_search` and `tools_load`, the lead's rules (its changes ask the user, naming
  the agent) and the lead's model. What differs is the context: it knows only the task the
  lead wrote. The first version gave agents an access level and a toolkit list. In use, the
  model left `web` out for an agent that had to look up a price, and the agent spent three
  minutes finding out it had no internet.
- **The lead's tools** (turns and tasks only, so agents never start agents: one orchestrator):
  - `agent_start(name, task)` starts one and returns at once.
  - `agent_message(agent, message)`: a working agent reads it at its next step, and it
    answers a question the agent asked. An idle agent takes it as a new run in its session,
    so it keeps its whole history.
  - `agents_wait(agents, timeout)` waits for the named agents, or every working one. It
    returns when they finish, one asks something, the timeout runs out, or the user writes.
    It hands over all the mail that came.
  - `agents_status(agent)` shows what each agent does now. Naming one shows its todo list,
    progress note and its steps.
  - `agent_stop(agent)` stops an agent and deletes it, with its session.
- **The agent's own tools**: `ask_lead(question)` waits for the lead's message, however long
  that takes (a stop ends it). `task_progress` notes also reach the lead as updates.
- **App actions**: an agent's action reaches the app as `agent.input_required`, with the
  action in the run's `waiting` list. The app runs it and answers as for a live turn. An app
  that declares actions must answer its agents' requests too, or they wait.
- **No caps** (the user, 2026-11-09): any number work at once, with no step limit, as a
  turn's. Names are unique among open agents. An agent stays until it is stopped; only
  stopped ones and ones that never ran are swept.
- **Mail**: what agents send the lead goes through one table, `agent_mail`. Each piece is
  claimed in one transaction, so it reaches the lead's session exactly once.

  | kind | posted when | delivered |
  |---|---|---|
  | `report` | an agent run ends (done, failed, or interrupted) | `agents_wait`; a note before the lead's next model call; or, when no run of the lead session goes on, a note plus `agent.finished` (not for an interruption) |
  | `question` | `ask_lead` | the same, but the notification is `agent.asked` |
  | `update` | `task_progress` | `agents_wait` or the lead's next model call. Never wakes the lead; only the latest per agent waits, and a report replaces it |

  A report over 8,000 characters is cut, and the whole one is saved to
  `runs/<id>/report.md`.
- **Lifecycle**:
  - Apps hear `agent.updated` (`agent`, `name`, `status`, `run`) when an agent starts, asks,
    ends or is stopped. Statuses are working, asking, waiting (for the user), done, failed,
    interrupted (its run was cut short; it stays, and a message goes on with it) and stopped
    (deleted as soon as its run ends).
  - Agents are work of their own: stopping the lead's turn, or a turn given up because the
    user moved on, does not stop them (2026-11-12: a Stop reached only the agents the stopped
    turn had started or messaged, and left them listed as stopped with their names taken).
    The user stops an agent in the app (`POST /v1/agents/<id>/stop`), or the lead does
    (`agent_stop`). A return to an earlier message stops what it undoes (section 5.7), which
    leaves an older agent it messaged since interrupted.
  - A message that comes as an agent writes its report is read before the run ends: a run
    seals itself just before it ends (`Runs.seal`) unless a message waits, and a message to a
    sealed run starts the agent's next run. A failed run's report names the messages it did
    not read.
  - After a restart, working agents resume like tasks.
  - Deleting a chat deletes its idle agents at once. Working ones stop and delete their own
    session when their run ends. `agent_stop` works the same way.
  - A schedule an agent makes belongs to the lead's session, which outlives the agent.
- **The reviewer** of section 9.4 is the one helper its parent waits for (`Runs.subagent`, kind
  `subagent`), with a skeptical prompt. Like Claude Code's subagents it has its task's tools, folders and
  permissions: a call that needs approval is asked through the app (`task.input_required` with its
  `run`), so an app in bypass mode allows it and otherwise the user decides.
- **Super agents** (`superagent.py`): `agent_start(..., super_agent=true)` starts an agent that
  Claude does through the user's own Claude Code, for code and for problems that need deep
  thinking. To the lead and to apps it is an agent like any other: its session, steps, mail,
  approvals, messages and stopping all work the same, and its summary carries `super` (the
  model's name). Only the engine differs:
  - Each run is one Claude Code process in headless mode (`claude -p`, stream-json both
    ways), on the panel's **super model** (`super_model`, default `claude-opus-5-5`; empty:
    no super agents) at its **thinking effort** (`super_effort`: low, medium, high, xhigh or
    max; default high). `super_command` says where `claude` is when it is not found on
    `PATH` or in `~/.local/bin`.
  - It runs in `--restricted` mode: the user's own Claude Code settings, hooks, plugins and
    MCP servers stay out, file tools stay in the app's folders (the session's `cwd`, the
    other roots as `--add-dir`), and bypassing permissions is refused. Its tools are named:
    Bash, PowerShell, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, NotebookEdit, Task.
  - What Claude Code would ask the user comes to the host over stdio
    (`--permission-prompt-tool stdio`). The brain's rules decide first, under the brain's
    names (`shell_run(command)` for Bash and PowerShell, `files_write(path)`,
    `files_edit(path)`, `web_fetch(url)`) and under Claude's own; the rest is an
    `approval_request` like any agent's call (`agent.input_required`, the run's `waiting`
    list). "Always" saves the brain-named rule, or, for a tool the brain has no name for (an
    MCP server's, Task), a rule for the whole tool under Claude's name.
  - Its words, tool calls and results are written into the session as they happen, so apps
    show its steps. Usage counts input, cache writes and cache reads as prompt tokens, plus
    `cost_usd` as Claude Code reports it.
  - A message to a working super agent is the next user message of the same process. Claude
    Code takes it in after its next tool result, or, while it writes, as a turn of its own
    after the one it is in; it says when it took each one (`--replay-user-messages`), and the
    run ends only at a result once it took them all. One to a finished agent resumes its
    Claude Code session (`--resume`, kept in the session state; Claude Code finds it from any
    folder) in a new run. Claude Code deletes old sessions (30 days by default): one it no
    longer has starts anew, told its task, its last report and the message. A stop kills the
    process tree. After a brain restart the run resumes its session with a note to go on; an
    approval it waited for is closed (its process is gone) and Claude Code asks again.
  - The run itself is kept as any run's, through `Runs`: its input, messages, approvals, the
    seal and the end are the loop's code, so the two engines cannot drift apart. One
    difference: Claude Code lives on while it waits for an approval, so the run waits in its
    own thread (`Runs.await_answer`), and the answer wakes it there instead of starting the run
    again. Nothing is read from the store while it waits: stops, messages and answers come as
    in-memory signals (`Attention`).
  - The lead hears it has super agents (a line of `agent_start`'s guide in YOUR TOOLS, 7.3,
    with the model's name) only while one can start: a super model is set and Claude Code is
    found. Otherwise `super_agent=true` is refused with why, and the lead starts an ordinary
    agent. The guide gives them all code, even a small script, and deep thinking. The first
    wording ("what you would struggle with") left a small script with the lead in a live test
    (2026-11-09): next to "do small things yourself", a model judges code it can write as
    small.
  - It signs in as Claude Code does for the user and counts against their Claude plan; the
    brain takes nothing out of it. `GET /config` carries `super`: the model, effort, the
    command and its version, and whether it is ready (the panel's Provider page shows it).

### 5.6 Going back to a message

Like Claude Code's rewind, an app can take a chat back to just before a message the user sent
(`rewind.py`; `GET` previews, `POST` does it; refused with 409 while a run of the chat goes on).

- **The log**: every event of the session from that message on is deleted, compactions and clearings
  made since included. A `rewound` event takes the id of the last one deleted, because SQLite gives a
  deleted top id out again and ids are kept elsewhere (file versions, apps' history entries): an id
  never names two messages. The input event's id is what apps name; a run tells it as it logs the
  message (`input`, and `steered` for a message read mid-turn).
- **Files**: `files_write` and `files_edit` keep the file as it was before its first change since the
  session's latest message (`file_versions`: content, or none for a new file). A return puts each file
  back to its first version since that message, or deletes it. An agent's or a task's versions belong to
  the chat they work for and outlive the agent's session, so a stopped agent's changes still go back.
  A file that cannot be written keeps its versions for a later return; the answer names it.
- **Work started since**: runs of the chat's agents started since, of schedules made since, and what
  those started, are cancelled quietly (no report, no note, no notification), as are jobs started
  since. Agents started since are deleted, schedules made since removed. The todo list goes
  back to the last one written before the message; files read since count as unread.
- **Kept**: calls that change something and are not undone are named (`kept`): commands, app actions
  (the screen), the web and other services, lasting memory (every app's) and the journal. Session
  memory goes back to how it was (section 10.2).
- Agents and tasks that started before the message go on, and their changes stay.

## 6. Environment interface: toolkits

### 6.1 Rules for every tool

- **Names**: `<toolkit>_<verb>`, such as `files_read` and `shell_run`. MCP tools are
  `mcp__<server>__<tool>`. OpenAI-style APIs only accept `[A-Za-z0-9_-]` in names, so no
  dots.
- **Descriptions are prompts.** Write them as for a new colleague: what the tool is for,
  when *not* to use it, the input format, and an example.
- **Results are short and human.** Names and paths, not internal ids. Where it helps, a
  `detail: "concise" | "full"` argument.
- **Hard caps.** About 30,000 characters per result (Claude Code's shell cap). Above it,
  the full output is saved to `runs/<id>/out-<n>.txt`. The model gets the head, the tail
  and the path, plus a hint ("search the file, or read it with offset").
- **Errors teach.** Say what was wrong and show a correct call. No raw tracebacks.
- **Read-only flag.** Each tool declares `readonly`. It decides parallel execution, crash
  re-runs and the default policy.
- **Plugins** (section 6.5) use the same contract. The schema comes from type hints and
  the docstring, as `ai.py` already does.

### 6.2 Built-in toolkits

| Toolkit | Tools | Notes |
|---|---|---|
| `files` | `files_read(path, offset, limit)`, `files_search(pattern, path, glob)`, `files_find(glob)`, `files_edit(path, old, new, all)`, `files_write(path, content)` | Read gives numbered lines in windows: 500 lines by default, whole lines, with a footer "lines 1-500 of 1,834". Images come back as images. Search uses ripgrep if it is installed, otherwise Python, and returns `path:line: text` for every match; only the user's stop ends a search. A result over 30,000 characters goes to a file with both ends shown. Edit is an exact, unique string replace. It fails if the file was not read in this session or changed on disk since. Paths are confined to the app's roots; what the user attached in the session (`mentions.attachment`) can be read wherever it is. |
| `shell` | `shell_run(command, cwd, timeout, background)`, `shell_output(job, since, wait)`, `shell_stop(job)` | One shell per OS, named in the description: PowerShell on Windows, bash elsewhere. Every session has a working folder; there is no hidden shell state. `background=true` returns a job id at once. A command still running after 30 s (`timeout` can only shorten that) is not stopped: it goes on as a job and the model gets control back, because it cannot know a download is slow and, offered longer waits, always took them (measured 2026-11-06: `timeout: 120` on every download). `shell_output(wait=...)` waits as long as asked for a job to end when the model needs the result, and says when a job has written nothing for 10 s or more, so the model can tell a slow job from a stuck one. MCP calls go the same way (section 8.3). |
| `web` | `web_search(query, count)`, `web_fetch(url, offset)` | Search is today's Brave tool. Fetch turns HTML into text with the standard library, pages long text with `offset`, and saves the full text to a file. |
| `browser` | `browser_open(url, new_tab, headless)`, `browser_view(tab, find, part, picture)`, `browser_act(steps, tab)`, `browser_read(tab, offset)`, `browser_script(code, tab)`, `browser_log(kind, tab, find)` | Her own Chrome, out of sight or on the user's screen: section 6.7. |
| `todo` | `todo_write(items)` | The whole list each time, with each item `pending`, `doing` or `done`. The result repeats it. |
| `memory` | `memory_save(key, value, category, scope)`, `memory_forget(key, category, scope)`; scope `everywhere` or, in turns, `session` | Every app has it (section 10). |
| `journal` | `journal_search(query)` | Read only. The brain writes notes itself. |
| `agents` | `agent_start(name, task)`, `agent_message(agent, message)`, `agents_wait(agents, timeout)`, `agents_status(agent)`, `agent_stop(agent)`; for agents, `ask_lead(question)` | Section 5.5. |
| (workers) | `task_progress(note)` | Every task and agent has it, whatever its toolkits: notes that outlive its context and show how far it got. |
| `schedule` | `schedule_create(when, text, timezone, title)`, `schedule_list()`, `schedule_update(id, ...)`, `schedule_delete(id)` | Section 9.6. |
| `mcp:<server>` | the server's tools | Section 8. |
| `plugins` | `plugin_list`, `plugin_install(folder)`, `plugin_reload(name)` | Section 6.5: a model makes its own tools; installing always asks. |
| `skills` | `skill_use(name, arguments)`, `skill_list()`, `skill_delete(name)` | Section 6.6. `skill_use` is a core tool. |
| `sessions` | `sessions_list(query)`, `sessions_read(session, part, offset)`, `sessions_search(query)`, `session_rename(session, title)`, `session_delete(session)` | The app's other conversations (not agents' or tasks'), named by id or exact title. `part="summary"` gives the session's mention card (`mentions.py`: newest journal note or compaction summary, last turns) and its journal notes; `part="turns"` its plain turns, 40 a page. Deleting always asks and refuses the current or a busy session. |
| `github` (plugin) | `github_search`, `github_repo`, `github_files`, `github_issues`, `github_issue`, `github_diff`, `github_runs`, `github_run`, `github_get`; asking first: `github_issue_create`, `github_comment`, `github_issue_update`, `github_pr_create`, `github_pr_review`, `github_pr_merge`, `github_api` | Section 6.5. |
| app actions | declared by the app | Run in the app; the brain waits for the result. |

Every app has `memory`. MilkChan enables `web`, `browser`, `todo`, `journal`, `schedule`, `files`,
`shell`, `agents`, `plugins`, `sessions` and `skills`. The CLI chat enables most of them plus MCP,
rooted in the folder it was started in.

### 6.3 Permissions

- Each tool has a policy: `auto`, `ask` or `off`. It can be set by the brain default, the
  app and the session; the strictest one wins.
- Defaults: read-only tools are `auto`. Writes, shell and `schedule_create` are `ask`.
- **Rules** narrow `ask` into `auto` for safe cases, in Claude Code's order: deny, then
  ask, then allow, first match wins. For example `shell_run(git status*)`,
  `files_edit(<root>/**)`. As Claude Code's docs say, command-prefix rules "are not a
  security boundary". The real boundary is path confinement, plus the brain running as the
  user and only on 127.0.0.1.
- **Approval** pauses the run (section 5.2). The app shows the request and answers with
  allow once, allow always (saved as a rule in the app profile), or deny with a reason. The
  reason goes to the model.
- Policy **`always`** asks every time: rules other than deny do not apply, the request
  carries `always_ask: true`, which an app must show the user even in a mode that allows
  everything, and "allow always" counts as once. Installing or reloading a plugin and the
  tools of untrusted plugins have it (section 6.5).
- A background task waiting for approval becomes `input_required` and raises a
  notification. Whoever starts a task can pre-approve tools for it.

### 6.4 Checks after edits

After `files_edit` or `files_write` the brain checks the file: `compile()` for `.py`,
`json.loads` for `.json`, `tomllib` for `.toml`. If the edit broke a file that parsed
before, the brain restores the old content. It returns the error with the lines around
it. This is SWE-agent's linter guardrail. Checks are per file type, so more types can be
added later.

### 6.5 Plugins

A plugin extends the brain for every app at once: it is installed in SentientMilk, not in
an app, so MilkChan, the CLI and any other app get its tools without knowing it exists.
It is a folder with a `plugin.json` (`sentientmilk_framework/plugins/__init__.py` has
the whole contract):

```json
{"name": "github", "version": "1.0.0", "description": "...",
 "toolkits": ["tools.py"],
 "mcp": {"servers": {"search": {"command": "search-server", "env": {"TOKEN": "${token}"}}}},
 "settings": {"token": {"label": "Token", "secret": true, "env": ["GITHUB_TOKEN"], "help": "..."}}}
```

- **Toolkits**: Python files of the folder, each defining `TOOLKIT` or `TOOLKITS` under
  the toolkit contract (6.1). The folder is imported as a package, so its files import
  each other (`from . import client`). A tool reads its settings with
  `ctx.brain.plugins.settings("<name>")`.
- **MCP servers**: as in `mcp.json` (section 8); `${key}` takes the plugin's setting, any
  other `${NAME}` the environment. A server named like the plugin is toolkit
  `mcp:<plugin>`, others `mcp:<plugin>-<server>`. The user's `mcp.json` wins a name both
  use. Changing a plugin with servers restarts the MCP host.
- **Settings**: what the user sets in the panel (Plugins) or with `sentientmilk plugins
  set`. A value comes from what the user set, else the first `env` variable that is set,
  else `default`. Secrets are only ever shown as set or not; `<set>` sent back keeps one.

Where they come from: built-in plugins ship in `sentientmilk_framework/plugins/<name>/`;
the user's live in `~/.sentientmilk/plugins/<name>/`, installed from a folder or a git URL
(cloned without its `.git`). Single-file toolkits in `~/.sentientmilk/toolkits/*.py` load
as plugins too. `~/.sentientmilk/plugins.json` (user-only, written atomically) keeps which
are off and their settings; an unreadable one is set aside as `plugins.json.invalid`, not
overwritten.

Every enabled plugin's toolkits are offered to every app on top of the toolkits the app
declares, and the usual three levels (brain, app, session) switch them off. They are not
core, so they cost one line of YOUR TOOLS (7.3) until the model loads them. A
plugin that fails to load (a bad manifest, an import error, a toolkit name already taken)
is listed with its error; the brain and every other plugin go on. A plugin runs as the
user, inside the brain, with the brain's rights: the panel says to install only plugins
one trusts.

**Trust** belongs to a plugin's exact files: `plugins.json` keeps a SHA-256 fingerprint of
them (Python's caches left out). Built-in plugins are trusted. A plugin the user installs
(panel, command line, API) is trusted as it is then. One a model installs, one that appears
on disk, and one whose files changed after it was trusted are not. An untrusted plugin's
tools all get policy `always` and lose `readonly` (so a crash never re-runs them), and its
MCP servers do not start. The user trusts it in the panel (Plugins: Trust) or with
`sentientmilk plugins trust NAME`.

**Plugins a model makes.** The `plugins` toolkit lets a model extend itself: it writes a
plugin with `files_write` in a folder open to it, then calls `plugin_install(folder)`.
`plugin_install`'s description is a complete guide to the format with an example, so no
other documentation is needed. `plugin_reload(name)` copies the plugin in again from where
it came from and imports it afresh, and `plugin_list` shows every plugin with its trust and
errors. Installing and reloading run the plugin's code inside the brain, so both have
policy `always`: the user is asked every time. No rule, "allow always" or app bypass skips
that (`permissions.decide` returns `always`, the request carries `always_ask`, an "always"
answer is taken as once and saves no rule); only a deny rule still refuses it. Such a
plugin starts untrusted, so each of its tools asks too, until the user trusts it. The
plugin manager's `version` grows at each load, and a run rebuilds its tools at the next
step when it changed: a model can install a plugin, try its tool, fix it and reload it in
one turn. A plugin installed by a model cannot take the name of a built-in one or of one
already installed.

**The GitHub plugin** is built in and on by default. It talks to the REST API with
`requests` (no new dependency). Its token is its setting, else `GITHUB_TOKEN` or
`GH_TOKEN`, else `gh auth token`; without one it reads public data only (60 requests an
hour). The token is only sent to the configured API host: a full URL to any other host is
refused, and `requests` drops it on the redirect of job logs to storage. Reading tools are
read-only and `auto`; changes are `ask`, with rules matching the repository
(`github_comment(me/*)`) or for `github_api` the path. Results are short lines a person
would read (`#12 [PR, draft] Title [labels] — @who · 3 comments`), files come in numbered
windows like `files_read`, a failed run shows its failed steps and the end of each failed
job's log, and long output goes to a file. Errors say what to do: set a token on 401, when
the rate limit resets on 403, that a private repository needs a token on 404, and
GitHub's own reasons on 422. `github_get` and `github_api` reach everything else the REST
API has (releases, branches, gists, workflow re-runs).

### 6.6 Skills

Copied from Claude's Agent Skills, which work well because they cost almost nothing until
used (progressive disclosure):

1. **Listed**: the system prompt has a SKILLS section with each skill's name and
   description (about 50-100 tokens each; past 8,000 characters only names). It says where
   the skills folder is.
2. **Loaded**: when a task matches, the model calls `skill_use(name, arguments)`. The result
   is `Base directory for this skill: <folder>` and the SKILL.md body with arguments filled
   in, and stays in the conversation like any tool result.
3. **Read as needed**: the skill's other files, through the file tools (the skills folder
   and the shipped skills are readable; the skills folder is writable).

`skills.py` reads `<home>/skills/<name>/SKILL.md` and the shipped `assets/skills`, again
whenever a SKILL.md changes (by mtime), so a skill the model writes counts from its next
step; a change costs one prompt-cache miss. Frontmatter is the subset skills use (plain
and quoted values, `|` and `>` blocks; other fields are kept and ignored), read without a
YAML dependency. Fields acted on: `name` (must equal the folder), `description` (at most
1,024 characters, no XML tags; without one, the body's first line), `argument-hint`,
`disable-model-invocation`, `user-invocable`. A skill that breaks a rule is listed by
`skill_list` and the panel with what is wrong, and not offered to the model.

The user starts a skill with a `skill` input item (`/name` in an app): at the start of the
turn, or when steered, it becomes `[The user started the skill /name with: ...]` and the
loaded skill, stored in the input event (`skills` names it, so a return puts `/name`
back). Arguments follow Claude Code: `$ARGUMENTS`, `$N` and `$ARGUMENTS[N]` (shell-like
words), `${SKILL_DIR}` (and `${CLAUDE_SKILL_DIR}`), a backslash before `$` for a dollar
sign; arguments no placeholder took are added as `ARGUMENTS: ...`.

The model writes skills with `files_write`/`files_edit`, guided by the shipped
`skill-creator` skill rather than prompt text; a write into the skills folder ends with
whether the skill now reads well. Writes ask as usual, keep versions (a return undoes
them), and `skill_delete` keeps a version of every file it deletes. Not copied:
`allowed-tools` (approval rules already do that), forked contexts, hooks, `paths`,
project-level skill folders, and `!command` expansion.

### 6.7 Her browser

`browser.py`, `browser_page.js`, `desktops.py`; the `browser` toolkit: `browser_open(url,
new_tab, headless)`, `browser_view(tab, find, part, picture)`, `browser_act(steps, tab)`,
`browser_read(tab, offset)`, `browser_script(code, tab)`, `browser_log(kind, tab, find)`.
It is for the web as a person uses
it: pages that need scripts, clicks, forms and accounts. `web_fetch` stays the quick way to
read a public page once; computer use stays for the user's own windows.

**Which Chrome.** Her own: the installed Chrome (else Edge, or `browser_command`) with a
profile in `<home>/browser/profile`, so what she signs in to stays, and nothing of the
user's own profile is touched (Chrome 136 and later refuse remote debugging of the default
profile anyway). Claude in Chrome drives the user's real Chrome through an extension and a
native messaging host; that needs an extension installed and trusted, and puts her in the
user's own sessions, which is not what a desktop character should have by default.

**Out of sight, or on the user's screen.** On Windows it starts (`CreateProcessW` with
`lpDesktop`) on the brain's hidden desktop, in a job that ends with the brain. Windows
there are real: pages lay out, paint and run their timers as on the screen, WebGL uses the
GPU and screenshots work, and nothing takes the user's focus. When the user wants to watch
her ("don't run it headless"), it runs on their desktop instead, driven the same way:
`browser_headless` (the panel's Out of sight) says where it opens, `browser_open
headless=false|true` (and the panel's Show and Hide) move it now. A Chrome process cannot
change desktops, so moving starts it again on the other one: the session cookies come along
(`Storage.getCookies`, and back with `Storage.setCookies`; they also wait in the profile
while it is closed, since for her it is still open), and the conversation's pages open
again at their addresses. On the user's screen nothing needs its focus: new windows open
behind what they use (`createTarget` with `background`), focus is emulated, covered windows
paint (`--disable-backgrounding-occluded-windows`). A minimized window still reads, clicks
and types (measured), but paints nothing, so a picture of it would wait forever: the window
comes back first. It never closes while idle there (they may be looking at it), and the
user closing her window is told to her as such. Chrome starts with `--no-startup-window`,
so no window is there but hers. Measured on Chrome 157 (2026-11-12) against a local page
that reports what it sees, each launch compared with the same Chrome started plainly:

| How it is driven | `navigator.webdriver` | What else gives it away |
|---|---|---|
| fixed `--remote-debugging-port` | false | nothing |
| port 0, or `--remote-debugging-pipe` | true | |
| with `--disable-blink-features=AutomationControlled` | false | a warning bar: 56 px less page |
| `Runtime.enable` (Puppeteer's way) | false | nothing seen on 157 (the stack-getter check no longer shows it); left off all the same |
| a minimized window | false | a 158 x 27 window at the screen's bottom edge, clicks at screen points outside it; timers once a second, no `requestAnimationFrame`, screenshots time out |
| typed with `Input.insertText` | false | `input` events with no key events |

So: a free port fixed per launch on 127.0.0.1 (found through `/json/version`), windows of
normal size, `Runtime` never enabled (pages are read in an isolated world,
`Page.createIsolatedWorld`), focus emulated for each tab, the pointer moved along a path
before every click, and text typed key by key. A page sees the user's Chrome on the user's
connection. Checks that the visitor is a human are the user's: she never tries to pass one,
and the step `show` hands the browser over.

**Tabs.** Each conversation (agents and tasks too, by session) has tabs `t1`, `t2`... in
windows of their own, so every page renders as the one in front. Links that open a tab or a
window open the conversation's next tab, which becomes current; a page that closes itself
(a sign-in window) stops being a tab. Tabs are kept in `browser/tabs.json` with their
addresses: the browser closes after 10 idle minutes and when the brain stops, a crash
closes it, and each tab opens again where it was when next used. Deleting a conversation or
an agent closes its tabs.

**Pages as text.** `browser_page.js` turns the page into indented lines: headings as `#`,
lists as `-`, groups (form, dialog, nav, table, …) as heads, and everything that can be
used as `role eN "name" [states] = "value"` (with a link's address, a select's options, a
file input's files). Things in a sentence stay in it in brackets; a row of fields gets a
line each. Ids hold while the element lives and never repeat in a tab, so an old id
misses instead of hitting something else. Lists and tables over 25 items show 20 and the
id that shows them all (`part`); `find` keeps the lines with some words and what they are
in. A view over 12,000 characters keeps its shape and everything that can be used, but each
run of prose shows its first two lines and how many more there are (and their links):
reading is `browser_read`'s, 20,000 characters at a time. A page of 1,000 paragraphs and a
3,000-row table came to 3 KB this way instead of 100 KB. Same-site frames and open shadow
roots are read in the page's world. A frame of another site (a payment form, an embedded
sign-in, a cookie banner) runs in a process of its own: auto-attach (`Target.setAutoAttach`,
iframes only, nested ones too) gives it a session, it is read in a world of the brain's own
like the page, and its iframe element in the parent's world is marked with its key
(`DOM.getFrameOwner`, `DOM.resolveNode`), so the parent's view says where the frame's view
goes. Every world gives out ids from the tab's latest (`__milk.sync`), so ids never repeat
across them and each id is acted on in its own world, at its place in the frame plus the
frame's place in the window. What has no id (a canvas, a map) is pointed at as "x,y" in the
tab's latest picture (`picture=true`), through frames of other sites too.

**Acting.** `browser_act` takes steps (click, fill, type, key, hover, scroll, drag,
upload, wait, open, back, forward, reload, dialog, save, close, show). A right click opens
the page's own menu only: Chrome's would stay open on the screen, out of her reach. `save`
keeps the page in the working folder as a PDF (a PDF tab's own document), a picture of all
of it, its HTML or a web archive, never over a file that is there. A target is brought into
view and hit-tested first: a covered one names what covers it, a disabled or hidden one
says so. After each step the brain waits for the page to settle: the load, pending
requests (documents, fetches, scripts; not streams), and 350 ms without DOM changes,
at most 10 s. The reply says how each step went, then what changed on the page (lines
gone and new), or the whole page when it is another page or most of it changed. Steps stop
at the first failure, at a dialog of the page (unless the next step answers it), and when
the tab goes to another site. Alerts are closed and told; confirm and prompt wait for the
step `dialog`. Downloads go to the conversation's working folder; uploads take files from
the folders open to her only.

**Approvals per site.** A tool's `seen(brain, run, arguments)` gives the arguments as the
rules and the user see them: the browser adds `site` (the tab's host, or the url's) and
what each step's target is (`about`). Its tools have `rule_arg="site"`: "allow always" on
an act saves `browser_act(github.com)`, a rule can deny `browser_*(*.bank.com)`. Opening,
viewing and reading run without asking; acting and scripts ask.

**Console and network.** `browser_log` reads a tab's console or its requests since the page
loaded. Requests come from the `Network` events the brain has on anyway (method, status or
error, type, address). The console needs `Runtime`, which stays off: it is enabled for the
moment of the call, when V8 tells every message it kept (logs, warnings, errors, uncaught
exceptions), objects are taken as JSON while they are still there, and it is disabled again.

**The user's screen.** The step `show` (the lead's only) moves her browser to the user's
screen if it is not there and brings the tab in front: they sign in, pass the check, or
pay, and she goes on there with what they did. The panel's Show on my screen does the same
from the user's side (with a window of their own when she has no page), Hide takes it back,
and Forget sign-ins deletes the profile.

## 7. Context management

### 7.1 Request layout

```
+ system ------------------------------------------+  stable for the session;
| who you are (persona), environment, rules,       |  rebuilt only at compaction
| app instructions                                 |  (the skills listing: when a
| memory, session memory and journal snapshot      |  skill changes)
| more tools, skills listing, signal format        |
+ tools -------------------------------------------+  fixed for a run
+ history -----------------------------------------+  append-only between
| [compaction summary]                             |  compactions
| input, assistant, tool, tool, assistant, ...     |
+ newest input ------------------------------------+
| items + tail: time, signal reminder, new notes   |  stored in the input event, so
+--------------------------------------------------+  later requests repeat it exactly
```

- Nothing that changes often goes in the system block: no clock, no live memory. The time
  goes in the tail.
- Today's `FORMAT_REMINDER` is added at send time and never stored. So the next request
  differs from the previous one at the previous user message, and the provider re-reads
  that whole turn, tool results included, without the cache. Storing the tail fixes that.
  The transcript still hides it.
- Images: only the newest few are sent, at least 3 and fewer than 7: the newest step's as the
  model sees them (`image_pixels`, 1.6 MP by default: 1600×1000 of a 2560×1600 screen; 768 px
  until 0.9, where the default model read none of a screen's small text, see transport.py), the
  others as 256×160 thumbnails, and older ones become the note "[Earlier screenshot omitted.]",
  four at a time. The provider reads every image of a request again, cached or not: on
  2026-11-07 MilkChan's RimWorld turn carried 42 thumbnails and each call took 47-83 s; the
  same request took 47 s to its first token with them, 14 s without them, while a tiny request
  answered in 2 s. A new image comes in a user message, and the provider re-reads from the
  previous user message anyway (see below), so turning the image before it into a thumbnail
  costs nothing; changing older ones does, which is why they go four at a time.
  Before that, every older image was kept as a thumbnail, because the cache cost of dropping
  them one by one was measured on 2026-11-06 (MilkChan's 49-step Gmail turn, 23 screenshots,
  two replays per rule):

  | rule | cache hit rate | uncached tokens |
  |---|---|---|
  | old: newest full, 3 thumbnails, the rest dropped | 87.8%, 85.8% | 98k, 114k |
  | up to 6 full, then the older ones dropped until 2 remain | 88.8%, 81.9% | 102k, 164k |
  | newest full, all older ones thumbnails (kept) | 93.9%, 93.9% | 58k, 58k |

  An image costs about 250 prompt tokens at any size (`estimate_tokens` counts 300). Only
  the byte budget, clearing and compaction change history.
- What the provider does that we cannot change (measured on refuseless,
  deepseek-v4.1-flash-fast, 2026-11-06):
  - Within a run, about 5-9% of the previous request misses at random: a call sometimes
    gets the cache of a request two or more steps back. A `prompt_cache_key` or `user`
    field does not change that, and waiting 6 s helps little.
  - A new user message (the next turn, or an image after tool results) makes the provider
    render the assistant messages since the previous user message another way, so the
    cache ends there. With or without reasoning sent back: the first call of a turn re-reads
    the whole previous turn once.
  - Requests with images report erratic prompt tokens (the same request: 19.5k tokens without
    its two images, 10.7k with them).
- Requests are serialized deterministically: key order stays fixed and the projection is
  stable.

### 7.2 The shrink ladder

Each step runs only when the previous one is not enough. Thresholds are fractions of the
model's context window, from `usage.prompt_tokens` of the last call (no tokenizer needed).
Today's byte budget (`request_budget`) stays as a second limit for proxies that cap body
size.

1. **Caps at the source** (section 6.1). These always apply.
2. **Tool-result clearing at 50%.** Tool results older than the last five are replaced by a
   restorable stub, such as `[cleared: files_read path=src/app.py; read it again if
   needed]`. The batch is logged as one `clearing` event, so it happens once, not on every
   request.
3. **Compaction at 75%.** The light model summarizes everything except the first input and
   the most recent events (about 10% of the window). It uses a fixed template:
   - the user's requests, quoted when short
   - the goal and the current state
   - decisions and why
   - files, URLs and ids touched
   - errors met and how they were fixed
   - open problems
   - next steps

   The new context is the rebuilt system block (fresh memory, session memory and journal), then
   the summary, then the recent events. The brain re-reads up to five recently read files
   and repeats the current todo list. The raw events stay in the log.
4. **Reset with handoff** (tasks only, when `context: reset`). The brain starts a fresh
   context from the task's goal, `progress.md`, `plan.json`, the todo list and
   `git log --oneline -20`. Evals decide whether DeepSeek needs this or compaction is
   enough.
5. **Subagents** keep exploration out of the main context (section 5.5).

### 7.3 Rules in the system prompt

Kept short, at the "right altitude", with a few examples instead of many rules. Add a rule
only when an eval shows the failure:

- Look before you act: search and read before editing.
- Verify after acting: run the test, read the output, check the file.
- For work with three or more steps, keep a todo list.
- Keep going until the goal is met or you are blocked. Ask only through approval or a
  question when you must.
- Report what you verified and what you did not.

**YOUR TOOLS** is the one place for what the model can do (`context.tools_section`, from
`Toolset.toolmap`): every toolkit of the run, in the profile's order, with its description,
the tools sent with each request by name and the others after "load:" with their parameters.
Under a toolkit come its tools' **guides** (`Tool.guide`): when and how to use the tool, as
the brain is now (a guide can be a function of the profile: `agent_start`'s adds super
agents while one can start). A rule about a tool comes only with the tool, in the run's
toolset: a read-only agent was once told to save memories with a tool it did not have.

- **Parts of the model** (`Toolkit.part`: memory, journal, schedule, todo, agents, sessions,
  skills, plugins) are marked "[part of you]", under one principle: they live in the brain,
  not on the computer; whatever words the user uses for one mean it; the model sees them
  only through their tools, never on the screen or in files; what those tools show is the
  whole truth (when they show nothing, there is nothing to find elsewhere, SentientMilk's own
  folder included); and when the user speaks of something they do not show, the model finds
  what they mean among its abilities, or asks.
- **Where things come from**: the section says the user sets the model up in SentientMilk's
  panel and the app's settings, so what they "made", "installed" or "set up" is in the map;
  a toolkit from a plugin the user installed or an MCP server they added says so
  (`Toolset.origins`), and a guide that follows a setting names it (super agents: Provider >
  Super model). Without that, told "I made a superagent for you", she reasoned it might be
  "a Claude Code subagent" in a config file, and went looking in the home folder.
- Why (2026-11-09): told "I made a superagent for you, can you talk to him?", MilkChan
  checked `agents_status` (empty), then took screenshots and read windows to find "him",
  twice, the second time after a rule and `agents_status` both said she makes them herself:
  the user's claim beat the tool. Her tools were split over three places (MORE TOOLS listed
  only the tools to load, rules sat in HOW YOU WORK, super agents had a rule of their own),
  and nothing said what lived in the brain; the one place described was YOUR COMPUTER.
- **What changed**: the first turn after an app's tool map changed (a plugin installed or
  removed, an MCP server connected or gone, a toolkit switched off, a guide changed with a
  setting such as the super model) gets a note before the user's message, listing new and
  gone tools and changed guide lines (`Loop._tool_news`; what the app's turns last saw is
  kept in `seen/<app>.json`, and an app's first turn says nothing). The user often says
  "I installed X for you" right after the change.
- Measured (2026-11-09, MilkChan on `deepseek-v4.1-flash-abliterated`, thinking high, her screen
  tools on a fake desktop, fresh chats): "I made a superagent for you, can you talk to him?"
  went from 0 of 3 clean (6 screenshots, windows and commands before making one) to 7 of 7
  (0); "I installed a new plugin for you, try it out" from 2 of 3 (10 file and shell calls)
  to 3 of 3, its tool called at once; "I set up a reminder for you earlier" (none) stopped
  searching SentientMilk's folder, and half the turns still search the home folder once for
  a note.

### 7.4 Many tools

Tool definitions come first in a request, so every tool costs context on every call, and
changing them misses the whole prompt cache. Picking the right tool also gets worse past
30-50 tools (Anthropic, tool search). So only **core** tools are sent; the rest are loaded
into the conversation when needed:

- Requests carry the core tools and, when there are others, `tools_search` and `tools_load`.
  This list is the same on every step of a profile.
  - Core tools are flagged by their toolkit (`Tool.core`): `memory_save`, `todo_write`,
    `files_read`, `files_search`, `shell_run`, `shell_output`, `web_search`, `web_fetch`, and
    `task_progress` for workers.
  - An app marks the actions it wants sent with `"core": true`.
- YOUR TOOLS (7.3) lists the others after "load:", by toolkit, with the toolkit's
  description and each tool's parameter names (`files_edit(path, old, new, all?)`). A toolkit
  with more than 20 tools to load is listed by count only. With only the names, the model
  often called a tool before loading it with arguments it guessed (`old_string`, in 2 of 4 eval
  runs); with the parameters listed, 0 of 3.
- `tools_load(names)` returns their descriptions and parameters. The model then calls them
  **by name**, like the others: the schemas sit in the conversation, which only grows at
  its end.
  - Measured on 2026-11-07 (Refuseless, `deepseek-v4.1-flash-fast`): a call to a tool not
    in `tools`, after its schema came in a tool result, was passed on in 5 of 5 tries with
    the right arguments.
- `tools_search(query)` ranks every tool of the run by the query's words: name first, then
  toolkit, then description and parameters. An empty query lists them all.
- The brain accepts a call to any tool of the run, loaded or not. When the arguments are
  wrong, the error shows the parameters. An unknown name gets the closest names and a
  pointer to `tools_search`. So a schema forgotten after compaction costs one failed call,
  and there is no "loaded" state to keep.
- MilkChan, 2026-11-07: 26 tools (16.9k characters, about 4.2k tokens) went with every
  request. Now 11 go (screenshot, the 8 core tools and the 2 meta-tools), and 19 more are
  listed. In 99 turns, 12 tools were ever called.

### 7.5 Measuring

Every `assistant` event stores prompt tokens, cached tokens (`prompt_cache_hit_tokens` on
DeepSeek, `prompt_tokens_details.cached_tokens` on OpenAI) and output tokens.
`sentientmilk stats` shows the cache hit rate per app and per task. **First open check:**
does the Refuseless proxy pass DeepSeek's cache through? If hits are always zero, cache
rules still help latency elsewhere but stop saving money here.

## 8. MCP

### 8.1 Configuration

`~/.sentientmilk/mcp.json`, editable through the API and `sentientmilk mcp add`:

```json
{"servers": {
  "github": {"url": "https://api.githubcopilot.com/mcp/",
             "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}},
  "notes":  {"command": "uv", "args": ["run", "notes-server"], "env": {"NOTES_DIR": "D:/notes"}}
}}
```

Secret values are only ever shown as set or not set, like other brain secrets.

### 8.2 Runtime

- The `mcp` package (2.x) is async only, and the brain is threaded. One MCP thread runs an
  `anyio` event loop.
- Each server lives in one long-running async task holding its `async with Client(...)`
  block. A Client cannot be reused once that block ends.
- Brain threads send calls through a queue and wait on a `concurrent.futures.Future`. A
  server takes one call at a time; calls waiting for a server that closes or cannot be
  reached fail with the reason rather than wait for ever.
- Version handling uses the SDK's default `auto` mode: a `server/discover` probe, falling
  back to `initialize` for older servers.
- Tool lists are cached and refreshed on the server's change notification, or on
  reconnect.
- Reconnect after failure uses up to five tries with backoff from 1 s, as Claude Code
  does. A failed server shows in `GET /v1/toolkits` with its error, and its tools go
  missing until it comes back.
- `mcp` pulls in starlette, uvicorn, pydantic, httpx2 and opentelemetry. So it is an
  optional extra, `pip install sentientmilk[mcp]`, and the brain works without it.

### 8.3 Behaviour

- **Naming and enablement**: `mcp__<server>__<tool>`. Each server is toolkit
  `mcp:<server>` with the same three-level enable and policy rules. MCP tools default to
  `ask`. A server marks a tool read-only through its `readOnlyHint` annotation; the brain
  takes that as a hint only and keeps the policy as the user set it.
- **Output**: text content goes to the model; `structuredContent` goes in as compact JSON.
  The 30,000-character cap and the save-to-file rule apply. Images come back as images.
- **No time limit**: a call still running after 30 s, or when the user sends a message, is
  not cut: it goes on as a job, like a command (section 7), listed with the app's jobs.
  Its result says so, and when the call never started, which call holds the server and
  for how long. Its end leaves a note with the result (pictures saved as files) and calls
  the app back. `shell_stop` or the app's stop cancels it and frees the server; the
  user's stop of the run cancels a call it still waits for. A server's question that
  nobody is left to answer (its run ended) is cancelled.
- **Elicitation** (MRTR): the SDK's `elicitation_callback` turns it into a question to
  the app: a turn pauses, a task becomes `input_required`. Sampling and roots are
  deprecated in the spec, so they are not offered.
- **Long calls**: the SDK does not implement the Tasks extension yet. A call that may take
  long runs inside a background task, with the SDK's `progress_callback` feeding progress
  events. Tasks support moves to the SDK once it ships there.
- **Remote auth**: v1 supports static headers with environment variables. OAuth
  (`OAuthClientProvider`, with the `iss` check the 2026 spec requires) comes when a
  server needs it.
- **Resources and prompts**: not in v1. Add `mcp_read(server, uri)` when a real server
  needs it.

## 9. Tasks: background, long-running, scheduled

### 9.1 Kinds of work

| Kind | Started by | Lives | Reports |
|---|---|---|---|
| turn | an app sending input | until it replies | its own SSE stream |
| task | an app (`POST /v1/tasks`), a schedule, or a detached turn | until done; survives restarts | notifications plus a note in the parent session |
| agent | the model (`agent_start`) | until stopped; its runs survive restarts | its mail, exactly once: `agents_wait`, a note, `agent.finished` or `agent.asked` (section 5.5) |
| job | `shell_run(background=true)`, or a command still running after 30 s | until the process exits; *not* across a brain restart (marked lost) | `shell_output`; a note and a `job.finished` notification when it ends (an app with `callbacks` starts a turn then, so its turns wait at most 10 s) |
| schedule | the model (with approval), an app, or the user | until deleted | creates tasks or wake notifications |

### 9.2 Background tasks

- A task runs in its own child session (`<session>/task-<id>`), so it never mixes with the
  chat. It starts with the goal and a short handoff from the parent: the last request plus
  relevant notes.
- Whoever starts the task sets its toolkits, budgets, pre-approved tools and context mode
  (`compact` or `reset`). The defaults come from the app.
- The executor runs N tasks at once (default 2) next to turns. A turn never waits for a
  task.
- When a task ends, the brain writes a `note` into the parent session ("Background task 12
  'update the README' completed: <summary>") and a notification for the app. The model
  sees the note on the next turn, like Claude Code's background-task notices.

### 9.3 Notifications

- `GET /v1/events?app=<app>&after=<cursor>` is a server-sent event stream. Apps that were
  closed catch up from their cursor; nothing is lost.
- Types: `task.updated`, `task.input_required`, `task.completed`, `task.failed`,
  `agent.updated` (an agent started, asked, ended or was stopped: `agent`, `name`, `status`,
  `run`), `agent.finished` (reports nobody collected, with `agents`: id, name, status),
  `agent.asked` (a question nobody collected: `agent`, `name`, `question`, `run`),
  `agent.input_required` (an agent waits for an approval or an app action: `agent`, `name`,
  `run`),
  `job.finished`, `schedule.fired`, `session.titled` (after a session's first reply the
  model names it in a few words, off the request path; a title the user gave stays).
- Notifications are kept 7 days, and at most 1,000 per app.
- The brain never starts a conversation itself. MilkChan, for example, can react to
  `task.completed` by sending a turn with an `event` input item and `reply: optional`. The
  brain then speaks if it has something worth saying. This is design rule 1: proactive
  behaviour is the app's feature.

### 9.4 Long-running task harness

For tasks that may take hours, following Anthropic's long-running harness:

1. **Initialize** (first step of the task): write `plan.json`, a list of items, each with
   `done: false` and an acceptance check. Write `progress.md` and, for code, make sure the
   workspace is a git repository.
2. **Work in increments**: one item at a time. After each: run its check, commit (code),
   flip `done`, append to `progress.md`. The prompt forbids editing or removing items
   instead of finishing them.
3. **Survive the context**: compaction or reset (section 7.2) always re-injects the plan,
   the progress and `git log`.
4. **Verify before done**: when every item is done, an optional verifier subagent runs the
   checks with a skeptical prompt. A failed check reopens its item. Anthropic found a
   separate skeptical evaluator far easier to tune than self-criticism.
5. **No step limit** (section 5.4): the user stops a task that runs away. The workspace keeps
   everything, so the task can be resumed.

Small tasks ("look this up and tell me") skip steps 1 and 4. The model decides by the
task's size, and the app can force either.

### 9.5 Background shell jobs

- Output streams to `runs/<id>/job-<n>.log`.
- `shell_output(job, since)` returns new lines, capped.
- When the job ends, the brain writes a note and a notification.
- A brain restart marks running jobs as `lost`, as Claude Code does on resume. A command
  that must survive a restart belongs in a task, not a job.

### 9.6 Scheduler

- **One kind** (0.7): a schedule is work for later, once or repeating. At its time she runs with
  its saved instructions, a normal turn in the schedule's own conversation (`schedule-<id>`).
  A reminder is a schedule whose instructions say what to tell the user. The `wake` (notify
  the app) and `task` (background task) modes of 0.6 are gone; their schedules are adopted on
  start, with their rules (`Store._adopt_old_schedules`).
- **When**: once, an ISO time or `in 20m` / `in 2h` / `in 1d`; repeating, `every N` (minutes,
  hours, days: fixed durations) or 5-field cron for clock times. Named zones (`zoneinfo`)
  follow daylight saving. A one-off that ran is done (no next time); a new time runs again.
- **Who runs it**: an app that calls back (MilkChan) runs its due work through its own turn
  workflow, so its persona, actions and approvals apply; for any other app (the CLI) the
  brain starts the turn itself (`Scheduler._run_unattended`). A busy conversation keeps its
  work until it is free.
- **Firing**: one thread sleeps until the earliest fire time, or until a schedule changes.
  It queues the occurrence, then computes the next time from the stored rule, not from the
  last fire time, so a schedule never drifts.
- **Missed fires** while the brain was down: `catch_up: "once"` (default) fires once on
  start, marked late. `"skip"` jumps to the next time.
- **Review**: schedules the model creates need approval (an app may allow them), and they
  show in `schedule_list` and the API so the user can review and delete them. They don't
  expire, unlike Claude Code's session cron, because this brain is the user's own
  long-lived service.

## 10. Memory, session memory and the journal

Rework of 0.8.0 (2026-11-11). Before it, memory was per app and went into the system block only for an
app that enabled the `memory` toolkit, and only while it fit 8,000 characters: past that, the model saw
the category names and had to call `memory_list`, which it rarely did. The user's memory had grown to 35
entries (about 13,000 characters), so in practice the model saw almost none of it, and a "for this chat"
instruction had nowhere to go but lasting memory (where it leaked into every chat) or the conversation
(where compaction may blur it).

Now there are three kinds, by how long they last and where they hold:

| | Memory | Session memory | Journal |
|---|---|---|---|
| What | lasting facts: who the user is, the people and pets in their life, what they like and how they want things done, what they work on | this session's instructions and what its work must keep in mind ("answer in English here", "don't push until I say", the staging server's address, a decision) | what happened in each session, 1 to 3 sentences a note |
| Who writes | the model (`memory_save`, unasked, as soon as it learns a fact); the user forgets entries | the model, in the session's turns (`memory_save` with `scope: session`); the user takes entries out | the brain's summarizer, off the request path |
| Where it holds | every app, every session (one user, one brain); each entry names the app that saved it | its session; the agents and tasks working for it follow it read-only | read by every app, searchable (`journal_search`) |
| In context | always, whole, in every system block: no app asks for it, no size cut | always, whole, in its session's system block, after memory (where they differ, it wins there) | the newest notes of other sessions, about 1,500 tokens; the rest by search |
| Ends | when forgotten | with the session; a return to a message (5.6) puts it back as it was then | when 20 newer notes are written |

### 10.1 Memory

- `memory(app, category, key, value, updated)`, keyed by category and key: one fact per name for every
  app, and `app` is the one that saved it. The system block lists it by category, `- key: value`, with
  `[app]` after an entry another app saved, so the CLI knows a fact came from MilkChan.
- 0.8.0 merged the per-app tables once at start (`store._share_memory`): where two apps had the same
  category and key, the newest stayed; every session's snapshot is taken again.
- Every app has the `memory` toolkit, listed or not (`Brain.profile`); a user who switches its tools off
  still has memory in context. Two tools for both scopes: `memory_save` (core) and `memory_forget`. There
  is no tool to read memory: it is all in context, and what changes later comes as a note (10.3). (0.8.0
  had five tools; `memory_list` and the separate session tools went the same day, one core tool fewer.)
- Memory holds lasting facts only. As measured on 2026-11-07, the old wording ("about the user, their
  preferences, plans or events") saved a setting changed once, "not a bug, don't fix it", in 3 of 3 runs,
  and passed the two `memory-what-lasts` tasks 1 time in 6; `memory_save`'s description and its guide
  took them to 9 of 9. Its description now also sends what holds only in a session to session memory:
  the `session-memory` eval (a chat-only rule and a rule for everywhere in one message) passed 5 of 5
  with the two tools of 0.8.1, and the three memory evals above still pass (2026-11-11).
- No cap: memory is whole however long it grows. Its cost is tokens in the system block, cached with the
  prefix; the light model's compaction does not touch it.

### 10.2 Session memory

- Kept in the session's state, `session_memory: {key: value}`, beside the todo list; `GET
  /v1/apps/<app>/sessions/<id>` returns it as `session_memory`. `scope: session` works only in turns: an
  agent or task has the session memory of the chat it works for (`profile.base_session`) in its system
  block, under "The memory of the session you work for", and cannot change it. A super agent (Claude
  Code) gets it, and the user's memory, in its appended prompt.
- What works for the chat hears a change at once (`Brain.chat_memory_changed`): its agents, its tasks
  and their agents get a note at their next step when the model changes it; when the user does, their
  snapshots and the chat's are taken again, so what was taken out leaves every system block. A super
  agent at work, whose prompt is fixed, is steered with the memory as it is now. Clearing a
  conversation clears its memory with its state.
- It is what Claude Code lacks: there a rule said only in the conversation can be lost at compaction,
  which re-injects CLAUDE.md from disk but nothing scoped to the session. Here a session's own rules
  come back whole after every compaction, without making them every chat's.
- Rewind (5.6) rebuilds it from the session's `memory_save` and `memory_forget` calls with `scope:
  session` before the message, so those calls are undone, not kept.

### 10.3 Snapshots

Memory, session memory and the journal are a snapshot in the session's state, put in the system block:
taken at the session's first request, again at compaction, and dropped (taken again at the next request)
after the user forgets a memory or a session memory entry (`Store.drop_snapshots`) or returns to a
message. A save of the model's own changes nothing there until then, so the cached prefix holds; the
model sees what it saved in the call's result, which is short and so is never cleared (7.2). What
another chat or app saved or forgot since a session's snapshot reaches its next turn as a note before
the input (`Brain.memory_news`, like the tool changes of 7.3; an agent's next run too, since its
session lives on between runs), so a chat left open yesterday knows
today's facts without its system block changing; the snapshot's `seen` list is what the session
already knows, its own saves included.

### 10.4 The journal

The brain's record of what happened, so the CLI brain knows what MilkChan's brain talked about this
morning.

- **Writing**: the summarizer queue (light model, off the request path) writes a note:
  - when a session has been quiet for 20 minutes and has new events since its last note;
  - at compaction;
  - when a task ends.

  Each note is 1 to 3 sentences, at most 400 characters, with time, app and session.
- **Kept**: the 20 newest notes (`store.JOURNAL_NOTES`, the user 2026-11-11); writing the 21st deletes
  the oldest. The timestamp decides the order.
- **Reading**: the newest notes from *other* sessions, up to about 1,500 tokens, go in the
  system block as `[2026-11-05 09:12, milkchan] ...`. They are snapshotted like memory.
  `journal_search(query)` searches the kept notes.
- **Per-app switches**: `journal: {read: true, write: true}` in the app profile. A private
  app can turn writing off.
- **User control**: `GET /v1/journal` and `DELETE /v1/journal/<id>`. The CLI gets
  `sentientmilk journal`. The panel's Memory tab shows memory (with the app that saved each entry, to
  forget) and the journal (to search and delete).

### 10.5 How other harnesses do it

| | Claude Code | Codex | SentientMilk |
|---|---|---|---|
| Lasting instructions the user writes | CLAUDE.md: managed, user (`~/.claude/CLAUDE.md`, every project), project and local files, loaded at start and re-read after compaction | AGENTS.md: global (`~/.codex/AGENTS.md`), repository and folder files, merged, the closer one winning | the app's persona and environment, the user's rules and session instructions (settings) |
| What the model learns and keeps | auto memory: `MEMORY.md`, an index whose first 200 lines (or 25 KB) load at session start, with topic files read on demand | memories (opt-in): past sessions summarized in the background into `~/.codex/memories`, read by the next session; the docs say rules that must always apply belong in AGENTS.md | memory, whole in every system block, shared by every app |
| What happened before | the transcript of earlier sessions (resume) | the memories above | the journal, written by the brain, read by every app |
| One session's own rules | only the conversation and its compaction summary | only the conversation | session memory, whole after every compaction |

Sources: [Claude Code memory](https://code.claude.com/docs/en/memory),
[Codex memories](https://developers.openai.com/codex/memories), and the AGENTS.md guide of the Codex docs.

## 11. Models and providers

- Named providers (from the agreed design). Each app picks a **main** model and a **light**
  model. The light one does compaction, journal notes and, by default, read-only agents. Both
  can be the same.
- Each model entry has a `context_window` setting. Thresholds in section 7.2 use it. The
  Refuseless model name is not in DeepSeek's docs, so we set it by hand and verify it with
  a long-context eval.
- Assistant messages are stored whole, including `reasoning_content`. DeepSeek rejects a
  tool loop with a 400 if it is missing. `ai.py` already keeps the whole message. Requests
  carry it only for the current turn's replies (from the first message of the run the newest
  message belongs to, so steering keeps it): on 2026-11-07 the provider began counting the
  older reasoning too, 24k of a 63k-token request.
- `ai.py` shrinks to `provider.py`: one call in, one message out, with streaming and usage.
  The loop moves to `loop.py`, where the event log lives.
- Strict tool schemas (DeepSeek beta) only if evals show bad tool arguments.

## 12. Evaluation

`sentientmilk eval [--model ...] [tasks...]` runs tasks from `evals/*.json`. Each one gets
a temporary home and a temporary workspace. It runs through the real HTTP API as a
background task, then checks a verifiable outcome: a command exits 0, a file holds text, or
the reply contains an answer. No LLM judge.

For each task it records: pass or fail, steps, tool calls, tool errors, prompt tokens,
cache hit rate, wall time and cost.

The first set has about 15 tasks, with three kept back to catch overfitting:

- Fix a failing test in a small repository.
- Answer a question that needs a search across a codebase.
- Refactor across three files without breaking the tests.
- Find a fact with web search and fetch.
- A long task: build a small CLI with tests, using several compactions.
- Recover after the brain is killed in the middle of a task.
- Create, list and delete a schedule.
- Use a local test MCP server, including an elicitation.
- Ten MilkChan chat turns with screenshots: the signal format holds (today's scratchpad
  measurement, made permanent).

Rules, tool descriptions and thresholds change only when an eval shows a gain, and the
change is kept only if the held-back tasks don't get worse.

## 13. HTTP API additions

These come on top of the agreed sessions and turns API. Every route uses the existing
bearer token.

| Method and path | Does |
|---|---|
| `GET /v1/events?app=&after=` | notification stream (SSE) with a cursor |
| `POST /v1/tasks` | start a task: session, goal, toolkits, budgets, pre-approved tools, context mode |
| `GET /v1/tasks?app=&status=&kind=`, `GET /v1/tasks/<id>` | list tasks (or with `kind=agent` agents' runs), or show one |
| `GET /v1/agents?app=&session=&all=` | the agents a session started (open ones; `all=1` adds closed ones) |
| `GET /v1/agents/<id>`, `POST /v1/agents/<id>/stop` | one agent with its steps, todo and progress; stop and delete it (the session hears that the user did) |
| `GET /v1/tasks/<id>/events` | replay, then follow live (SSE) |
| `POST /v1/tasks/<id>/cancel` | cancel cooperatively: a tool call that runs finishes first; text the model is writing stops within 0.3 s and is dropped; a run about to wait for answers ends instead |
| `POST /v1/runs/<id>/answer` | answer an approval, question or action |
| `POST /v1/runs/<id>/detach` | turn a running turn into a background task |
| `GET/POST /v1/schedules`, `PATCH/DELETE /v1/schedules/<id>` | manage schedules |
| `GET /v1/toolkits` | toolkits, MCP servers included, with status and errors |
| `GET/PUT /v1/mcp`, `POST /v1/mcp/<name>/reconnect` | MCP configuration |
| `GET/POST /v1/plugins`, `PATCH/DELETE /v1/plugins/<name>` | plugins (section 6.5): list, install (`source`), turn on or off, set and trust (`enabled`, `settings`, `trusted`), remove |
| `POST /v1/plugins/<name>/reload` | copy a plugin in again from its source and import it |
| `GET /v1/memory`, `DELETE /v1/memory/<category>/<key>` | memory, shared by every app: `entries`, each with the app that saved it |
| `DELETE /v1/apps/<app>/sessions/<id>/memory/<key>` | take one thing out of a session's memory |
| `GET /v1/journal`, `DELETE /v1/journal/<id>` | view and prune the journal |
| `GET /v1/jobs/<id>` | job status and the tail of its log |
| `GET/POST /v1/apps/<app>/sessions/<id>/rewind` | preview or go back to before a user message (section 5.6) |
| `GET /v1/skills`, `DELETE /v1/skills/<name>` | skills (section 6.6), removing one of the user's |

## 14. Build plan

Each phase ships on its own, keeps both test suites green, and leaves MilkChan working.

| # | Phase | Main changes | Done when |
|---|---|---|---|
| 1 | Contract (the agreed step 1) | apps and sessions, typed inputs, header signals with `text.delta` streaming; MilkChan and the CLI move to it | MilkChan runs live; the signal eval passes |
| 2 | Loop and log | `loop.py`, `provider.py`, `events` table (migrating `messages` and `transcript`), runs and executor, crash recovery, stored tail, usage and cache metrics; eval runner with 5 tasks | the kill-and-resume test passes; the Refuseless cache check is answered |
| 3 | Toolkits and permissions | `toolkits/` (files, shell, web with fetch, todo, memory), policies, rules, approvals, output caps, edit checks, plugin loading; old `tools/*.py` and `conversation.py` go | the edit, search and test-fixing evals pass |
| 4 | Context management | clearing, compaction with the light model, re-reading files, thresholds per model | the long-task eval passes and stays within its budget |
| 5 | Tasks | tasks, child sessions, harness (plan, progress, verifier), subagents, jobs, notifications; MilkChan subscribes and shows task results | a task survives a brain restart; MilkChan reacts to `task.completed` |
| 6 | Scheduler | schedules, cron parser, catch-up, tools, autostart | schedules fire across a restart; DST tests pass |
| 7 | MCP | `mcp_host.py`, `mcp.json`, deferred tools, elicitation as questions | the MCP eval passes against a local test server |
| 8 | Memory and journal | per-app memory, journal writer, snapshots, API and CLI | notes appear across apps; eviction keeps the newest |

Kept from today's code: `transport.py` (images, byte budget), `exceptions.py`,
`config.py` (grows providers and policies), `thinking.py`, `store.py` (grows tables),
`server.py` and `client.py` (grow routes), and Brave search inside the new `web` toolkit.

## 15. Not doing, and why

- **Coordinated parallel writers** (locks, merges, agent teams that message each other):
  conflicting decisions (Cognition). Agents read by default; a writing agent is given its
  own part.
- **Vector database or RAG**: just-in-time search is what Claude Code does, and it keeps
  results fresh.
- **LangGraph or Temporal as dependencies**: too heavy for one user on one machine. We take
  their rules (persist every step, at-least-once, pause by returning) and keep SQLite.
- **Hooks**: plugin toolkits, edit checks and app actions cover the known needs. Add
  pre- and post-tool hooks only when one is missing.
- **A sandbox**: for now, path confinement plus approvals. An OS sandbox for `shell` is a
  later phase if the brain gets riskier jobs.
- **SentientMilk as an MCP server**: apps use its HTTP API; nothing needs this yet.

## 16. Decisions on the open questions

1. **Shell on Windows**: PowerShell 5.1 by default, since every Windows has it. The `shell`
   setting picks another one (`pwsh`, `cmd`, `bash`).
2. **Autostart**: off unless switched on (2026-11-08, the user asked for it). The panel's
   **Start with Windows** writes the current user's Run key (`autostart.py`, which MilkChan
   uses for its own switch too); Task Manager's off (StartupApproved) reads as off. Windows
   runs `SentientMilkw.exe` (a no-console build of the same host) with `start`, which starts
   the brain as apps do and exits, so the brain keeps a hidden console for what it runs.
   Without it, a schedule that came due after a reboot fires when the brain next starts
   (`catch_up`).
3. **Light model**: the same `deepseek-v4.1-flash-fast` (`light_model` empty means the main
   model).

## 17. As built

- Apps start the brain as its own process (`connect()`); `brain.lock` lets one process win.
  It is a background service: it runs until it is stopped (its tray icon, the panel, or
  `POST /v1/shutdown`), never on its own. Apps start it the way SentientMilk recorded in `launch.json` when it
  was last opened (on Windows, `dist\windows\SentientMilk\runtime\python.exe -m
  sentientmilk_framework --home <home> serve --log`); a packaged app (PyInstaller's, or a
  folder from `scripts/bundle.py`, whose runtime holds `bundle.json`) never runs a brain of
  its own. The spawn drops PyInstaller's `_PYI_*` variables, so a packaged brain unpacks
  into its own temporary folder instead of locking its parent's.
- SentientMilk is the authority: the provider, keys, personas, toolkits, rules and memory are
  managed in its terminal control panel (`sentientmilk`, `panel.py`, Textual). Apps declare
  defaults and keep only settings about themselves (MilkChan: look, screenshots, proactive
  messages). The panel stops the brain through `POST /shutdown`.
- App actions may declare `policy: "ask"`; they then pass rules and approvals before the
  app is asked to run them, and "always" saves a rule as for tools. Approval and action
  requests share a call id, so answers are matched to requests by kind.
- MilkChan's computer use is two actions: `computer_view` (UI Automation controls as
  text lines with ids that stay the same while the window stays open) and `computer_act`
  (asks). Text is the main view because it is cheaper and exact. Apps that draw their own
  UI (games, the Roblox app) are seen through their pixels: OCR text with ids, and a
  picture with the ids marked, which the model reads; it clicks by id because its own
  points land 7 to 80 picture pixels off. Points in a close-up cover icons.
- Without ripgrep, `files_search` walks in Python and stops after 30 s, saying how far
  it got: with MilkChan's home folder as root, an unbounded walk once held a turn for
  over ten minutes.
- App actions can answer with images, shown to the model after the result. MilkChan's
  screenshot is such an action instead of an image on every message. Measured on
  `deepseek-v4.1-flash-fast`, 2026-11-06: no look in 6 of 6 small-talk and plain questions;
  a look in 9 of 9 "what's on my screen", "this error" and "what I'm working on" messages
  without an earlier look; idle turns looked 3 of 3; signals valid 18 of 18, including
  every turn after a look, so the format reminder needs no copy on the image message.
- Apps answer approvals: MilkChan asks in a desktop dialog, or in its terminal chat for
  turns typed there; a waiting background task is answered through `waiting`.
- Eval tasks live in `sentientmilk_framework/eval_tasks/*.json`: 10 tasks, 3 held back.
  Kill-and-resume and the MCP elicitation are covered by the test suite instead, with a
  stand-in provider and a local test MCP server.
- Measured on `deepseek-v4.1-flash-fast` through Refuseless, 2026-11-06: 8 of 8 pass;
  prompt cache hits 61-90% on multi-step tasks (Refuseless passes DeepSeek's prefix cache
  through); signals were valid in 6 of 6 screenshot turns.
- Option updates of a run are one transaction (`Store.update_run_options`): the loop, steering,
  stops and agents change them from different threads. Writing back a copy read earlier lost
  a message steered while a turn started. Readers that come after a run (titles, the
  journal, `Brain.profile`) use `Store.find_session`, which never creates a session; they
  brought back chats the user had just deleted.
- Calls run in the order the model wrote them; reads next to each other run together. A
  call that waits for the user holds back the calls after it: a read after a write that
  waited for approval used to run first.
- A command the same as one still running as a job, in the same folder, is not started again: the answer
  points to that job (the model started one download twice in a row). A job log a leftover process still
  holds stays in the run's folder instead of failing the command (WinError 32).
- A signals line after other text (junk the model wrote first) is still found, as a line holding only an
  object of the app's signals, and taken out of the reply.
- MilkChan's proactive messages stay in MilkChan: an idle turn sends an `idle` event with
  `reply: optional`, and the brain may answer `[silent]`. Finished tasks and jobs reach MilkChan as
  notifications; it turns each into a turn so the character says it. A due schedule reaches it as
  `schedule.ready`, and MilkChan runs it as a turn in the schedule's own conversation (9.6).

## Sources

- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic: Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Claude: Building agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
- [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Cognition: Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) and [Multi-agents: what's actually working](https://cognition.com/blog/multi-agents-working)
- [Anthropic: Introducing advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use) and the [tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Philipp Schmid: How agents manage other agents, four subagent patterns](https://www.philschmid.de/subagent-patterns-2026)
- [MCP blog: the 2026-07-28 specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP: Tasks extension overview](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP Python SDK docs](https://py.sdk.modelcontextprotocol.io/) and [mcp on PyPI](https://pypi.org/project/mcp/)
- [Claude Code: how it works](https://code.claude.com/docs/en/how-claude-code-works), [subagents](https://code.claude.com/docs/en/sub-agents), [hooks](https://code.claude.com/docs/en/hooks), [permissions](https://code.claude.com/docs/en/permissions), [MCP](https://code.claude.com/docs/en/mcp), [memory](https://code.claude.com/docs/en/memory), [scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks)
- [OpenHands SDK: agent architecture](https://docs.openhands.dev/sdk/arch/agent) and [context condenser](https://docs.openhands.dev/sdk/guides/context-condenser)
- [LangGraph: human-in-the-loop](https://docs.langchain.com/oss/python/langgraph/human-in-the-loop) and [persistence](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Temporal: durable execution means deciding what survives failure](https://temporal.io/blog/durable-execution-means-deciding-what-survives-failure) and [AI framework integrations](https://temporal.io/blog/ai-framework-integrations)
- [SWE-agent: the agent-computer interface](https://princeton-nlp.github.io/SWE-agent/background/aci) and [paper](https://arxiv.org/abs/2405.15793)
- [DeepSeek API: context caching](https://api-docs.deepseek.com/guides/kv_cache), [tool calls](https://api-docs.deepseek.com/guides/tool_calls), [thinking mode](https://api-docs.deepseek.com/guides/thinking_mode)
