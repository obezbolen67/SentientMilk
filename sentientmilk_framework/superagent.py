"""Super agents: agents that Claude does, through the user's own Claude Code, for code and hard thinking.

An agent started with ``super_agent`` (agents.py) is an ordinary agent to everyone else: a session of its own,
runs of kind ``agent``, its report in the lead's mailbox, messages, stopping, approvals. Only its engine differs:
instead of the brain's loop and model, each run is one Claude Code process in headless mode (``claude -p``,
stream-json both ways, claudecode.py) on the super model, at the thinking effort set in the panel
(``super_model``, ``super_effort``: the nearest one the model takes). Its models and their names are Claude
Code's. Claude works in the app's folders with Claude Code's own tools. Restricted mode keeps the user's own
Claude Code settings, hooks, plugins and MCP servers out, confines its file tools to those folders and refuses
bypassing permissions.

Claude Code signs in as it does for the user (their Claude account, or their key): nothing is taken out of it,
and its use counts against their Claude plan. What it does is written into the agent's session as it happens
(its words, tool calls and results), so apps show it like any agent's steps. What Claude Code would ask the user
(changing files, commands it does not judge read-only) comes to the host over stdio and is decided like any
agent's call: the brain's rules first (``shell_run``, ``files_write``, ``files_edit`` and ``web_fetch`` rules hold
for Claude's Bash, Write, Edit and WebFetch too, as do rules naming Claude's tools), then the app asks the user
(or allows it, in its bypass). A message to a working super agent is the next user message of the same process;
a message to one that finished resumes its Claude Code session in a new run (one Claude Code deleted starts anew
with the agent's task and last report). The run itself (its input, messages, approvals, its end) goes as any
run's (Runs); only the work is Claude Code's. See docs/architecture.md, 5.6.
"""

import json
import logging
import os
import queue
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from . import permissions
from .claudecode import Process, failure, prompt_file
from .exceptions import BrainError

logger = logging.getLogger(__name__)

# Restricted mode leaves out the tools that run code unless named; these are named, the rest of Claude Code's
# (scheduling, messaging, design sync...) are not a super agent's.
TOOLS = "Bash,PowerShell,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task"
# Claude Code's tools as the brain's rules name them: (rule name, the argument rules match, Claude's argument)
RULE_NAMES = {"Bash": ("shell_run", "command", "command"), "PowerShell": ("shell_run", "command", "command"),
              "Write": ("files_write", "path", "file_path"), "Edit": ("files_edit", "path", "file_path"),
              "NotebookEdit": ("files_edit", "path", "notebook_path"), "WebFetch": ("web_fetch", "url", "url")}
PROMPT = """## YOU ARE A SUPER AGENT
You work for {name}, who talks with the user in their app (the lead). It gave you one part of a job, the
task in the first message, because it needs code or deeper thinking. Nobody watches you live; the user
approves your changes when you are asked.
- Stay within the task: change only what it covers.
- Find out what you can by yourself. If a decision is not yours, take the safest choice and say what you
  assumed.
- The user's computer is {name}'s: never look at the screen or use the mouse and keyboard (no screenshots,
  no input scripts). When a part needs that, say in your report what {name} should do there. Your MCP
  tools (mcp__...) are {name}'s connected apps and yours to use, their own captures and input included:
  they work inside that app, not on the user's screen.
- Verify what you did (run it, test it) before you report.
- End with a compact report for the lead, findings first: what you did, the exact paths, names and results,
  what you verified and what you did not. Put long output in files and name them."""
RESTARTED = "[The brain restarted while you worked: continue the task where you were.]"
LOST = ("[The Claude Code session you worked in is gone (Claude Code deletes old ones), so you start without "
        "what you did and read before. Look again at what you need.]")


class SuperAgents:
    def __init__(self, brain):
        self.brain = brain
        self.claude = brain.claude
        self._live: dict = {}  # run id -> SuperRun while its process works

    # ============== Whether there is one ==============

    def ready(self) -> bool:
        """A super model is set and Claude Code is there (whether it can work now, problem() says)."""
        return bool(self.brain.config.values()["super_model"] and self.claude.argv())

    def why_not(self) -> str:
        if not self.brain.config.values()["super_model"]:
            return "There is no super model: the user turned super agents off in SentientMilk (Provider)."
        problem = self.claude.problem()
        return f"{problem.message}, so there are no super agents now. {problem.details or ''}".strip() if problem else ""

    def label(self) -> str:
        return self.claude.label(self.brain.config.values()["super_model"])

    def status(self) -> dict:
        """For the panel and apps: the model, its name in Claude Code and the effort it starts with."""
        values = self.brain.config.values()
        model = values["super_model"]
        return {"model": model, "label": self.label() if model else "", "effort": values["super_effort"],
                "starts_with": self.claude.effort(model, values["super_effort"]) if model else None,
                "ready": self.ready()}

    # ============== Running ==============

    def execute(self, run: dict, profile: dict, emit) -> None:
        """One run of a super agent, to its end (Loop.execute hands it over)."""
        work = SuperRun(self, run, profile, emit)
        self._live[run["id"]] = work
        try:
            work.execute()
        finally:
            self._live.pop(run["id"], None)

    def close(self) -> None:
        """The brain stops: no Claude Code goes on working behind it (a restart resumes their sessions)."""
        for work in list(self._live.values()):
            work.kill()


def _text(content) -> str:
    """A tool result's content as text: a string, or blocks."""
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return "" if content is None else str(content)


class SuperRun:
    """One run of a super agent. It keeps the run protocol as the loop does (Runs: input, messages, approvals,
    the end); only the work is Claude Code's."""

    def __init__(self, owner: SuperAgents, run: dict, profile: dict, emit):
        self.owner, self.brain, self.store = owner, owner.brain, owner.brain.store
        self.run, self.profile, self.emit = run, profile, emit
        self.calls: dict = {}  # tool use id -> (name, input)
        self.process: Optional[Process] = None
        self.reply = ""
        self.resumed = False  # it went on with a Claude Code session of an earlier run
        self.error: Optional[str] = None  # what Claude Code said went wrong (not signed in, a plan limit...)
        self.limit: Optional[dict] = None  # the plan's last rate limit news
        # messages sent to the process, and those it took in (it says so: --replay-user-messages). One sent as
        # it works joins the turn after its next tool result, or, as it writes, is a turn of its own after it
        self.said = self.taken = 0

    # ============== The process ==============

    def start(self, prompt: str) -> None:
        values, profile, claude = self.brain.config.values(), self.profile, self.owner.claude
        roots = profile["roots"]
        folder = profile.get("cwd") or (roots[0] if roots else str(Path.home()))
        # in a file, not on the command line: memory is long, and Windows ends a command line at 32k characters
        appended = prompt_file(claude.folder, PROMPT.format(name=profile["name"]) + self._memory(), "super-")
        files = [appended]
        args = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--replay-user-messages", "--restricted", "--tools", TOOLS, "--strict-mcp-config",
                "--permission-mode", "manual", "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
                "--model", values["super_model"], "--append-system-prompt-file", appended]
        effort = claude.effort(values["super_model"], values["super_effort"])
        if effort:
            args += ["--effort", effort]
        for root in roots:
            if root != folder:
                args += ["--add-dir", root]
        # the lead's MCP servers too: code that lives in an app the user connected (a game editor) is Claude's
        # as well, and Claude can check it there (2026-11-09: it had none, so the lead wrote it by trial and error)
        servers = self.brain.mcp.for_claude(profile.get("toolkits") or [])
        if servers:
            fd, mcp_file = tempfile.mkstemp(prefix="super-mcp-", suffix=".json", dir=self.brain.home)
            with os.fdopen(fd, "w", encoding="utf-8") as config:  # a file, not argv: env and headers may hold keys
                json.dump({"mcpServers": servers}, config)
            args += ["--mcp-config", mcp_file]
            files.append(mcp_file)
        resumed = self._state().get("claude_session")  # Claude Code finds it from any folder
        if resumed:
            args += ["--resume", resumed]
        self.resumed = bool(resumed)
        self.said = self.taken = 0
        self.process = Process(claude, args, folder, files)
        self.process.initialize()
        self.say(prompt)

    def send(self, message: dict) -> None:
        self.process.send(message)

    def say(self, text: str) -> None:
        self.said += 1
        self.process.say(text)

    def close(self) -> None:
        """Its work is done: it ends on its own (it saves its session), and all it wrote is read."""
        self.process.close()

    def kill(self) -> None:
        if self.process is not None:
            self.process.kill()

    # ============== One run ==============

    def _memory(self) -> str:
        """The user's memory (who they are, how they want things done) and the memory of the chat it works for
        ("don't push until I say"), as the lead has them: they hold for the work too."""
        from .context import render_memory
        from .toolkits.memory import session_memory

        profile, store = self.profile, self.brain.store
        parts, entries = [], store.memory_entries()
        if entries:
            parts.append("## THE USER'S MEMORY\nWhat the lead remembers about the user, in every app; [app] marks "
                         "the app that saved one.\n" + render_memory(entries, profile["app"]))
        chat = profile.get("base_session") or profile["session"]
        kept = session_memory((store.find_session(profile["app"], chat) or {}).get("state") or {})
        if kept:
            parts.append("## THE CHAT'S MEMORY\nWhat the chat you work for keeps to: follow it in your work too.\n"
                         + "\n".join(f"- {key}: {value}" for key, value in kept.items()))
        return "".join("\n\n" + part for part in parts)

    def execute(self) -> None:
        run, runs = self.run, self.brain.runs
        reason = self.owner.why_not()
        if reason:
            raise BrainError("super_unavailable", reason)
        if self.store.run(run["id"])["options"].get("cancel"):  # stopped before it started (or before a restart)
            return runs.end(self.store.run(run["id"]), "cancelled", self.emit)
        runs.log_input(run, self.profile, self.emit)
        inputs = [e for e in self.store.run_events(run["id"]) if e["type"] == "input"]
        message = _text(inputs[0]["content"]) if inputs else ""
        # the brain restarted during this run, after Claude Code took it: its session goes on
        restarted = self._state().get("claude_run") == run["id"]
        try:
            if self._converse(RESTARTED if restarted or not message else message):
                return
            # the session it would go on with is gone (Claude Code deletes old ones): it starts anew
            self.store.update_session(run["app"], run["session"], "state", lambda state: {
                key: value for key, value in state.items() if key not in ("claude_session", "claude_run")})
            self._converse(self._anew(message))
        finally:
            self.kill()

    def _converse(self, prompt: str) -> bool:
        """One Claude Code process, to the run's end (True), or False when the session it resumed is gone."""
        runs = self.brain.runs
        attention = runs.attention(self.run["id"])
        self.start(prompt)
        while True:
            if attention.stopped.is_set():
                self.kill()
                runs.end(self.store.run(self.run["id"]), "cancelled", self.emit)
                return True
            if attention.woken.is_set():
                self._take_messages()
            try:
                event = self.process.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                self.close()
                if self._gone():
                    return False
                raise BrainError("super_failed", "Claude Code stopped before it finished",
                                 "\n".join(self.process.errors) or None)
            ended = self._handle(event)
            if ended is not None:
                return ended

    def _gone(self) -> bool:
        return self.resumed and any("No conversation found" in line for line in self.process.errors)

    def _anew(self, message: str) -> str:
        """What a super agent whose Claude Code session is gone starts with: its task, its last report and
        what this run is for."""
        app, session = self.run["app"], self.run["session"]
        task = self.brain.agents.record(app, session).get("task", "")
        last = self.store.runs(app=app, session=session, statuses=("completed",), limit=1)
        report = ((last[0]["result"] or {}).get("reply") or "").strip() if last else ""
        parts = [LOST, f"Your task:\n{task}"]
        if report:
            parts.append(f"Your last report:\n{report}")
        if message and message != task:
            parts.append(f"Now:\n{message}")
        return "\n\n".join(parts)

    def _handle(self, event: dict) -> Optional[bool]:
        """One message from Claude Code: None while the run goes on, then what _converse returns."""
        kind, run = event.get("type"), self.run
        if kind == "system" and event.get("subtype") == "init" and event.get("session_id"):
            self.store.update_session(run["app"], run["session"], "state",
                                      lambda state: {**state, "claude_session": event["session_id"],
                                                     "claude_run": run["id"]})
        elif kind == "assistant" and event.get("error"):  # Claude Code's words for it, not Claude's
            self.error = event["error"]
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                self._said(block)
        elif kind == "rate_limit_event":
            self.limit = event.get("rate_limit_info") or self.limit
        elif kind == "user" and event.get("isReplay"):
            self.taken += 1
        elif kind == "user":
            content = (event.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    self._done(block)
        elif kind == "control_request":
            request = event.get("request") or {}
            if request.get("subtype") == "can_use_tool":
                answer = self._permit(request)
            else:
                answer = None
            response = ({"subtype": "success", "request_id": event.get("request_id"), "response": answer}
                        if answer is not None else
                        {"subtype": "error", "request_id": event.get("request_id"),
                         "error": f"SentientMilk does not answer {request.get('subtype')}"})
            self.send({"type": "control_response", "response": response})
        elif kind == "result":
            return self._result(event)
        return None

    def _said(self, block: dict) -> None:
        run, store = self.run, self.store
        if block.get("type") == "text" and block.get("text", "").strip():
            self.reply = block["text"]
            store.add_event(run["app"], run["session"], run["id"], "assistant",
                            {"message": {"role": "assistant", "content": block["text"]}, "usage": {}})
            self.emit({"type": "text.delta", "text": block["text"]})
        elif block.get("type") == "tool_use":
            call_id, name, arguments = block.get("id", ""), block.get("name", ""), block.get("input") or {}
            self.calls[call_id] = (name, arguments)
            call = {"id": call_id, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
            store.add_event(run["app"], run["session"], run["id"], "assistant",
                            {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "usage": {}})
            store.add_event(run["app"], run["session"], run["id"], "tool_start", {"call_id": call_id, "name": name})
            self.emit({"type": "tool.start", "call_id": call_id, "name": name, "arguments": arguments})

    def _done(self, block: dict) -> None:
        call_id = block.get("tool_use_id", "")
        name, arguments = self.calls.pop(call_id, ("?", {}))
        status, text = ("error" if block.get("is_error") else "ok"), _text(block.get("content"))
        self.store.add_event(self.run["app"], self.run["session"], self.run["id"], "tool",
                             {"call_id": call_id, "name": name, "arguments": arguments, "content": text,
                              "status": status})
        self.emit({"type": "tool.end", "call_id": call_id, "name": name, "arguments": arguments, "status": status,
                   "result": text[:2000]})

    def _take_messages(self) -> None:
        """Messages from the lead, sent while it works: logged as any run's, then the next user messages of the
        same process."""
        for logged in self.brain.runs.take_messages(self.store.run(self.run["id"]), self.emit):
            self.say(_text(logged["content"]))

    def _result(self, event: dict) -> Optional[bool]:
        run, store, runs = self.run, self.store, self.brain.runs
        usage = event.get("usage") or {}
        cached = usage.get("cache_read_input_tokens") or 0
        prompt = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0) + cached
        total = store.run(run["id"])["usage"] or {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                                  "cached_tokens": 0}
        total = {**total, "calls": total["calls"] + (event.get("num_turns") or 1),
                 "prompt_tokens": total["prompt_tokens"] + prompt, "cached_tokens": total["cached_tokens"] + cached,
                 "completion_tokens": total["completion_tokens"] + (usage.get("output_tokens") or 0),
                 "cost_usd": round(total.get("cost_usd", 0) + (event.get("total_cost_usd") or 0), 4)}
        store.update_run(run["id"], usage=total)
        failed = bool(event.get("is_error")) or event.get("subtype") != "success"
        if not failed and self.taken < self.said:
            return None  # a message it was sent as it wrote is its next turn
        if not failed and not runs.seal(store.run(run["id"])):
            self._take_messages()  # the lead wrote as it finished: it reads that and goes on
            return None
        self.close()
        reply = str(event.get("result") or self.reply or "").strip()
        if failed:
            if self._gone():
                return False
            error = failure(self.error, reply, self.limit) if self.error else BrainError(
                "super_failed", f"Claude Code could not finish: {reply or event.get('subtype')}",
                "\n".join(self.process.errors) or None)
            runs.end(store.run(run["id"]), "failed", self.emit, error=error)
            return True
        runs.end(store.run(run["id"]), "completed", self.emit, reply=reply,
                 extra={"model": self.brain.config.values()["super_model"]})
        return True

    # ============== Asking before changes ==============

    def _rules(self, name: str, arguments: dict) -> str:
        """off, ask or auto, by the brain's rules: under the brain's own tool name and under Claude's."""
        rules, cwd = self.profile["rules"], self.profile.get("cwd")
        found = []
        own = RULE_NAMES.get(name)
        if own:
            tool = SimpleNamespace(name=own[0], policy=None, rule_arg=own[1])
            found.append(permissions.decide(tool, {own[1]: arguments.get(own[2], "")}, rules, cwd))
        found.append(permissions.decide(SimpleNamespace(name=name, policy=None, rule_arg=None), arguments, rules, cwd))
        for decision in ("off", "ask", "auto"):
            if decision in found:
                return decision
        return "ask"

    def _always_rule(self, name: str, arguments: dict) -> str:
        """The rule an "always allow" saves: the brain's, for Claude's tools it has a name for (this command,
        this file), else the whole tool under Claude's name (an MCP server's tool, Task...)."""
        own = RULE_NAMES.get(name)
        if own:
            tool, arguments = SimpleNamespace(name=own[0], rule_arg=own[1]), {own[1]: arguments.get(own[2], "")}
        else:
            tool = SimpleNamespace(name=name, rule_arg=None)
        return permissions.always_rule(tool, arguments, self.profile.get("cwd"))

    def _permit(self, request: dict) -> dict:
        """What Claude Code asks: decided by the rules, or asked like any agent's call (the app asks the user,
        or allows it in its bypass); this waits for the answer, as its Claude Code does."""
        run, runs = self.run, self.brain.runs
        name, arguments = request.get("tool_name", ""), request.get("input") or {}
        allow = {"behavior": "allow", "updatedInput": arguments}
        decision = self._rules(name, arguments)
        if decision == "off":
            return {"behavior": "deny", "message": f"Refused: {name} is not allowed here."}
        if decision == "auto":
            return allow
        call_id = request.get("tool_use_id") or f"super-{time.time_ns()}"
        runs.ask(run, "approval", call_id, name, arguments, self.emit)
        answer = runs.await_answer(run, call_id, self.emit)
        if answer is None:
            return {"behavior": "deny", "message": "The agent was stopped.", "interrupt": True}
        if answer["decision"] == "deny":
            reason = f" Their reason: {answer['reason']}" if answer.get("reason") else ""
            return {"behavior": "deny", "message": f"The user did not allow this call.{reason}"}
        if answer["decision"] == "always":
            self.brain.allow_always(run["app"], self._always_rule(name, arguments))
        return allow

    def _state(self) -> dict:
        return (self.store.find_session(self.run["app"], self.run["session"]) or {}).get("state") or {}
