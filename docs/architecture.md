# SentientMilk v2: architecture

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
7. **Memory is per app.** Above it, the brain keeps a *journal*: short, timestamped notes
   about sessions across all apps. When the journal is full, the oldest notes are deleted.
8. **Evals from day one.** A small set of realistic tasks runs before and after every
   change to prompts, tools or context rules.

## 2. What the research says, and what we do with it

| Finding | Source | What SentientMilk does |
|---|---|---|
| Context is an "attention budget". Aim for "the smallest possible set of high-signal tokens". Recall degrades as context grows. | Anthropic, context engineering | Output caps, clearing, compaction (section 7), agents (section 5.5), tools loaded on demand (section 7.4). |
| Load data *just in time* through tools; keep only paths, queries and links up front. Claude Code loads its memory file up front and finds the rest with glob and grep. | Anthropic, context engineering | Search and read tools; no vector database. App memory and journal are the only things loaded up front. |
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
| Python SDK `mcp` 2.3.0 (2026-10-02) is async only. It falls back to `initialize` for older servers and handles MRTR itself. It does *not* implement the Tasks extension yet. | MCP Python SDK docs, PyPI | A dedicated MCP thread with an event loop. Long MCP calls run as background tasks. |
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
| `memory` | app, category, key, value, updated. Today's table plus an `app` column. |
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
        check budgets (steps, tokens, wall time, cost)   -> end(failed, "budget")
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

Each run has budgets: max steps (default 200 for tasks, 40 for turns; an app may give a turn
up to 200 with `max_steps`, as MilkChan does when it can use the computer), max wall time, and
max tokens or cost. Hitting one ends the run as `failed` with type `budget`. Its progress
is saved, so a new task can continue it. Today's `max_tool_rounds` becomes the step budget.

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
    progress note and last 15 steps.
  - `agent_stop(agent)` stops an agent and deletes it, with its session.
- **The agent's own tools**: `ask_lead(question)` waits for the lead's message (at most 30
  minutes, then it goes on by its best judgment and says what it assumed). `task_progress`
  notes also reach the lead as updates.
- **App actions**: an agent's action reaches the app as `agent.input_required`, with the
  action in the run's `waiting` list. The app runs it and answers as for a live turn. An app
  that declares actions must answer its agents' requests too, or they wait.
- **Limits**:
  - At most 5 working at once per lead session.
  - Names are unique among open agents.
  - The step budget is 200, as a task's.
  - An agent idle for 24 h is deleted the next time the lead starts one, or when the brain
    starts. Forgetting one costs nothing.
- **Mail**: what agents send the lead goes through one table, `agent_mail`. Each piece is
  claimed in one transaction, so it reaches the lead's session exactly once.

  | kind | posted when | delivered |
  |---|---|---|
  | `report` | an agent run ends (done, failed, or stopped by a cascade) | `agents_wait`; a note before the lead's next model call; or, when no run of the lead session goes on, a note plus `agent.finished` (not for a stop) |
  | `question` | `ask_lead` | the same, but the notification is `agent.asked` |
  | `update` | `task_progress` | `agents_wait` or the lead's next model call. Never wakes the lead; only the latest per agent waits, and a report replaces it |

  A report over 8,000 characters is cut, and the whole one is saved to
  `runs/<id>/report.md`.
- **Lifecycle**:
  - Apps hear `agent.updated` (`agent`, `name`, `status`, `run`) when an agent starts, asks,
    ends or is stopped. Statuses are working, asking, waiting (for the user), done, failed
    and stopped.
  - A stop from the user reaches the agents a run started (through `parent`). Such an agent
    stays; its report says it was stopped.
  - A turn given up because the user moved on does not stop its agents.
  - After a restart, working agents resume like tasks.
  - Deleting a chat deletes its idle agents at once. Working ones stop and delete their own
    session when their run ends. `agent_stop` works the same way.
  - A reminder an agent sets belongs to the lead's session, which outlives the agent.
- **The reviewer** of section 9.4 is the one helper its parent waits for (`Runs.subagent`, kind
  `subagent`), with a skeptical prompt. Like Claude Code's subagents it has its task's tools, folders and
  permissions: a call that needs approval is asked through the app (`task.input_required` with its
  `run`), so an app in bypass mode allows it and otherwise the user decides.

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
- **Work started since**: runs of the chat's agents started since, of tasks fired by reminders set
  since, and what those started, are cancelled quietly (no report, no note, no notification), as are
  jobs started since. Agents started since are deleted, reminders set since removed. The todo list goes
  back to the last one written before the message; files read since count as unread.
- **Kept**: calls that change something and are not undone are named (`kept`): commands, app actions
  (the screen), the web and other services, memories (the app's) and the journal.
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
| `files` | `files_read(path, offset, limit)`, `files_search(pattern, path, glob)`, `files_find(glob)`, `files_edit(path, old, new, all)`, `files_write(path, content)` | Read gives numbered lines in windows: 500 lines by default, long lines cut, with a footer "lines 1-500 of 1,834". Images come back as images. Search uses ripgrep if it is installed, otherwise Python, and returns `path:line: text` for all matches up to a cap. Edit is an exact, unique string replace. It fails if the file was not read in this session or changed on disk since. Paths are confined to the app's roots. |
| `shell` | `shell_run(command, cwd, timeout, background)`, `shell_output(job, since, wait)`, `shell_stop(job)` | One shell per OS, named in the description: PowerShell on Windows, bash elsewhere. Every session has a working folder; there is no hidden shell state. `background=true` returns a job id at once. A command still running after 30 s (`timeout` can only shorten that) is not stopped: it goes on as a job and the model gets control back, because it cannot know a download is slow and, offered longer waits, always took them (measured 2026-11-06: `timeout: 120` on every download). `shell_output(wait=...)` waits up to 600 s for a job to end when the model needs the result. |
| `web` | `web_search(query, count)`, `web_fetch(url, offset)` | Search is today's Brave tool. Fetch turns HTML into text with the standard library, pages long text with `offset`, and saves the full text to a file. |
| `todo` | `todo_write(items)` | The whole list each time, with each item `pending`, `doing` or `done`. The result repeats it. |
| `memory` | `memory_save`, `memory_get`, `memory_list`, `memory_forget` | Scoped to the session's app (section 10). |
| `journal` | `journal_search(query)` | Read only. The brain writes notes itself. |
| `agents` | `agent_start(name, task)`, `agent_message(agent, message)`, `agents_wait(agents, timeout)`, `agents_status(agent)`, `agent_stop(agent)`; for agents, `ask_lead(question)` | Section 5.5. |
| (workers) | `task_progress(note)` | Every task and agent has it, whatever its toolkits: notes that outlive its context and show how far it got. |
| `schedule` | `schedule_create(when, what)`, `schedule_list()`, `schedule_delete(id)` | Section 9.6. |
| `mcp:<server>` | the server's tools | Section 8. |
| `plugins` | `plugin_list`, `plugin_install(folder)`, `plugin_reload(name)` | Section 6.5: a model makes its own tools; installing always asks. |
| `sessions` | `sessions_list(query)`, `sessions_read(session, part, offset)`, `sessions_search(query)`, `session_rename(session, title)`, `session_delete(session)` | The app's other conversations (not agents' or tasks'), named by id or exact title. `part="summary"` gives the session's mention card (`mentions.py`: newest journal note or compaction summary, last turns) and its journal notes; `part="turns"` its plain turns, 40 a page. Deleting always asks and refuses the current or a busy session. |
| `github` (plugin) | `github_search`, `github_repo`, `github_files`, `github_issues`, `github_issue`, `github_diff`, `github_runs`, `github_run`, `github_get`; asking first: `github_issue_create`, `github_comment`, `github_issue_update`, `github_pr_create`, `github_pr_review`, `github_pr_merge`, `github_api` | Section 6.5. |
| app actions | declared by the app | Run in the app; the brain waits for the result. |

MilkChan enables `memory`, `web`, `todo`, `journal`, `schedule`, `files`, `shell` and
`agents`. The CLI chat enables the same plus MCP, rooted in the folder it was started in.

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
core, so they cost one line of the MORE TOOLS listing (7.4) until the model loads them. A
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

## 7. Context management

### 7.1 Request layout

```
+ system ------------------------------------------+  stable for the session;
| who you are (persona), environment, rules,       |  rebuilt only at compaction
| app instructions                                 |
| app memory snapshot, journal snapshot            |
| signal format                                    |
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
- Images: only the newest few are sent, at least 3 and fewer than 7: the newest at 768 px, the
  others as 256 px thumbnails, and older ones become the note "[Earlier screenshot omitted.]",
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

   The new context is the rebuilt system block (fresh memory and journal snapshots), then
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

A rule about a tool comes only with the tool: the todo, memory and agents rules check the
run's toolset, not the app's toolkits. A read-only agent was told to save memories with a
tool it did not have.

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
- The system block lists the others under MORE TOOLS, by toolkit, with the toolkit's
  description. A toolkit with more than 20 tools to load is listed by count only.
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
- Brain threads send calls through a queue and wait on a `concurrent.futures.Future`.
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
| agent | the model (`agent_start`) | until stopped or idle for a day; its runs survive restarts | its mail, exactly once: `agents_wait`, a note, `agent.finished` or `agent.asked` (section 5.5) |
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
5. **Budgets** stop runaway tasks (section 5.4). The workspace keeps everything, so the
   task can be resumed.

Small tasks ("look this up and tell me") skip steps 1 and 4. The model decides by the
task's size, and the app can force either.

### 9.5 Background shell jobs

- Output streams to `runs/<id>/job-<n>.log`.
- `shell_output(job, since)` returns new lines, capped.
- When the job ends, the brain writes a note and a notification.
- A brain restart marks running jobs as `lost`, as Claude Code does on resume. A command
  that must survive a restart belongs in a task, not a job.

### 9.6 Scheduler

- **Kinds**: `at` (an ISO time), `cron` (5 fields: lists, ranges, steps), `every`
  (minutes). Times are in the machine's local zone (`zoneinfo`). The cron parser is about
  50 lines plus tests, so no new dependency is needed.
- **Payloads**:
  - `wake`: write a note into the session and raise `schedule.fired` with the text ("remind
    me at 17:00 to stretch"). No model call; the app decides what to show.
  - `task`: start a background task with a stored goal ("every morning, summarize my
    unread GitHub notifications").
- **Firing**: one thread sleeps until the earliest fire time, or until a schedule changes.
  It fires, then computes the next time from the stored rule, not from the last fire time,
  so a schedule never drifts.
- **Missed fires** while the brain was down: `catch_up: "once"` (default) fires once on
  start, marked late. `"skip"` jumps to the next time.
- **Limits**: 50 schedules per app. Schedules the model creates need approval, and they
  show in `schedule_list` and the API so the user can review and delete them. They don't
  expire, unlike Claude Code's session cron, because this brain is the user's own
  long-lived service.

## 10. Memory and journal

### 10.1 Per-app memory

- Today's `memory` table gains an `app` column. The memory tools only see the session's
  app. Existing rows move to app `milkchan`, the only app so far.
- If an app's memory is small (under about 2,000 tokens), a snapshot goes in the system
  block. Otherwise only its categories go there, and the tools fetch the rest. The
  snapshot is refreshed at session start and at compaction (section 7.1). A new fact is
  still visible at once, because the tool result that saved it sits in context.
- Memory holds lasting facts only: who the user is, what they like, what they work on. The
  model saves them unasked, as soon as it learns them. One-time events and changes stay
  out, because the journal (10.2) records what happened. As measured on 2026-11-07, the
  old wording ("about the user, their preferences, plans or events") saved a setting
  changed once, "not a bug, don't fix it", in 3 of 3 runs, and passed the two
  `memory-what-lasts` tasks 1 time in 6. `memory_save`'s description and a working rule
  took them to 9 of 9; `memory-across-sessions` passed 3 of 3 and the other 7 tasks 7 of 7.

### 10.2 The journal

The brain's only shared memory: condensed notes about what happened in each session, so
the CLI brain knows what MilkChan's brain talked about this morning.

- **Writing**: the summarizer queue (light model, off the request path) writes a note:
  - when a session has been quiet for 20 minutes and has new events since its last note;
  - at compaction;
  - when a task ends.

  Each note is 1 to 3 sentences, at most 400 characters, with time, app and session.
- **Capacity**: at most 24,000 characters in total (about 6,000 tokens). Adding a note
  deletes the oldest notes until it fits. The timestamp decides the order.
- **Reading**: the newest notes from *other* sessions, up to about 1,500 tokens, go in the
  system block as `[2026-11-05 09:12, milkchan] ...`. They are snapshotted like memory.
  `journal_search(query)` searches every note still kept.
- **Per-app switches**: `journal: {read: true, write: true}` in the app profile. A private
  app can turn writing off.
- **User control**: `GET /v1/journal` and `DELETE /v1/journal/<id>`. The CLI gets
  `sentientmilk journal`.

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
| `GET /v1/journal`, `DELETE /v1/journal/<id>` | view and prune the journal |
| `GET /v1/jobs/<id>` | job status and the tail of its log |
| `GET/POST /v1/apps/<app>/sessions/<id>/rewind` | preview or go back to before a user message (section 5.6) |

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
- **Skills** (instruction packs loaded on demand): useful later for the CLI. They fit the
  deferred-tools pattern of section 7.4.
- **A sandbox**: for now, path confinement plus approvals. An OS sandbox for `shell` is a
  later phase if the brain gets riskier jobs.
- **SentientMilk as an MCP server**: apps use its HTTP API; nothing needs this yet.

## 16. Decisions on the open questions

1. **Shell on Windows**: PowerShell 5.1 by default, since every Windows has it. The `shell`
   setting picks another one (`pwsh`, `cmd`, `bash`).
2. **Autostart**: none. The brain keeps running while an app is open, work is pending or a
   schedule is enabled. After a reboot, a schedule that came due fires when the next app
   starts the brain (`catch_up`).
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
  `reply: optional`, and the brain may answer `[silent]`. Reminders and finished tasks reach
  MilkChan as notifications; it turns each into a turn so the character says it.

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
