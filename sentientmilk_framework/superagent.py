"""Super agents: agents that Claude does, through the user's own Claude Code, for code and hard thinking.

An agent started with ``super_agent`` (agents.py) is an ordinary agent to everyone else: a session of its own,
runs of kind ``agent``, its report in the lead's mailbox, messages, stopping, approvals. Only its engine differs:
instead of the brain's loop and model, each run is one Claude Code process in headless mode (``claude -p``,
stream-json both ways) on the super model, at the thinking effort set in the panel (``super_model``,
``super_effort``). Claude works in the app's folders with Claude Code's own tools. Restricted mode keeps the
user's own Claude Code settings, hooks, plugins and MCP servers out, confines its file tools to those folders and
refuses bypassing permissions.

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
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

from . import permissions
from .config import EFFORTS
from .exceptions import BrainError
from .toolkits.shell import kill_tree

logger = logging.getLogger(__name__)

MODELS = (("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5"),
          ("claude-fable-5-2", "Fable 5.2"))
EFFORT_NAMES = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra high", "max": "Max"}
assert set(EFFORT_NAMES) == set(EFFORTS)
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
VERSION_AGE = 600  # seconds a ``claude --version`` answer is kept
LOOK_AGE = 60  # seconds where claude is stays known
STDERR_LINES = 30
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def label(model: str) -> str:
    return dict(MODELS).get(model, model)


class SuperAgents:
    def __init__(self, brain):
        self.brain = brain
        self._found = (0.0, None)  # (when, path) of the claude command
        self._versions: dict = {}  # path -> (when, version)
        self._live: dict = {}  # run id -> SuperRun while its process works

    # ============== Whether there is one ==============

    def command(self) -> Optional[str]:
        """Claude Code's command: the one set in the panel, or claude where it is found."""
        configured = self.brain.config.values()["super_command"]
        if configured:
            return configured if Path(configured).is_file() else shutil.which(configured)
        when, found = self._found
        if time.time() - when > LOOK_AGE:
            local = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
            found = shutil.which("claude") or (str(local) if local.is_file() else None)
            self._found = (time.time(), found)
        return found

    def argv(self) -> List[str]:
        """What starts Claude Code, before its arguments (tests start a stand-in)."""
        command = self.command()
        return [command] if command else []

    def version(self) -> str:
        argv = self.argv()
        if not argv:
            return ""
        when, version = self._versions.get(argv[0], (0.0, ""))
        if time.time() - when > VERSION_AGE:
            try:
                version = subprocess.run(argv + ["--version"], capture_output=True, text=True, timeout=20,
                                         creationflags=_NO_WINDOW, env=_env()).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                version = ""
            self._versions[argv[0]] = (time.time(), version)
        return version

    def ready(self) -> bool:
        return bool(self.brain.config.values()["super_model"] and self.argv())

    def why_not(self) -> str:
        if not self.brain.config.values()["super_model"]:
            return "There is no super model: the user turned super agents off in SentientMilk (Provider)."
        return ("Claude Code is not installed on this computer, so there are no super agents: the user installs it "
                "and signs in to it, or sets where it is in SentientMilk (Provider).")

    def label(self) -> str:
        return label(self.brain.config.values()["super_model"])

    def status(self) -> dict:
        """For the panel and apps: the model and effort, and the Claude Code that runs them."""
        values = self.brain.config.values()
        return {"model": values["super_model"], "label": label(values["super_model"]),
                "effort": values["super_effort"], "command": self.command() or "", "version": self.version(),
                "ready": self.ready(), "models": [list(m) for m in MODELS], "efforts": list(EFFORTS)}

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


def _env() -> dict:
    """The brain's environment, without what ties a process to a Claude Code session it may run inside."""
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("CLAUDECODE", "CLAUDE_CODE_")) and key not in ("CLAUDE_PID", "CLAUDE_EFFORT")}


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
        self.process: Optional[subprocess.Popen] = None
        self.events: queue.Queue = queue.Queue()
        self.errors: deque = deque(maxlen=STDERR_LINES)
        self.readers: List[threading.Thread] = []
        self.write_lock = threading.Lock()
        self.reply = ""
        self.resumed = False  # it went on with a Claude Code session of an earlier run
        # messages sent to the process, and those it took in (it says so: --replay-user-messages). One sent as
        # it works joins the turn after its next tool result, or, as it writes, is a turn of its own after it
        self.said = self.taken = 0

    # ============== The process ==============

    def start(self, prompt: str) -> None:
        values, profile = self.brain.config.values(), self.profile
        roots = profile["roots"]
        folder = profile.get("cwd") or (roots[0] if roots else str(Path.home()))
        args = self.owner.argv() + [
            "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--replay-user-messages", "--restricted", "--tools", TOOLS, "--strict-mcp-config",
            "--permission-mode", "manual", "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
            "--model", values["super_model"], "--effort", values["super_effort"],
            "--append-system-prompt", PROMPT.format(name=profile["name"]) + self._memory()]
        for root in roots:
            if root != folder:
                args += ["--add-dir", root]
        # the lead's MCP servers too: code that lives in an app the user connected (a game editor) is Claude's
        # as well, and Claude can check it there (2026-11-09: it had none, so the lead wrote it by trial and error)
        servers, mcp_file = self.brain.mcp.for_claude(profile.get("toolkits") or []), None
        if servers:
            fd, mcp_file = tempfile.mkstemp(prefix="super-mcp-", suffix=".json", dir=self.brain.home)
            with os.fdopen(fd, "w", encoding="utf-8") as config:  # a file, not argv: env and headers may hold keys
                json.dump({"mcpServers": servers}, config)
            args += ["--mcp-config", mcp_file]
        resumed = self._state().get("claude_session")  # Claude Code finds it from any folder
        if resumed:
            args += ["--resume", resumed]
        self.resumed = bool(resumed)
        self.events, self.errors = queue.Queue(), deque(maxlen=STDERR_LINES)
        self.said = self.taken = 0
        self.process = subprocess.Popen(
            args, cwd=folder, env=_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=_NO_WINDOW,
            start_new_session=os.name != "nt")
        process, events, errors = self.process, self.events, self.errors  # this process's: a next one has its own
        self.readers = [
            threading.Thread(target=self._read, args=(process, events, errors, mcp_file), daemon=True,
                             name=f"super-{self.run['id']}"),
            threading.Thread(target=lambda: errors.extend(line.rstrip() for line in process.stderr), daemon=True)]
        for reader in self.readers:
            reader.start()
        self.send({"type": "control_request", "request_id": "init", "request": {"subtype": "initialize",
                                                                                "hooks": None}})
        self.say(prompt)

    @staticmethod
    def _read(process: subprocess.Popen, events: queue.Queue, errors: deque, mcp_file: Optional[str]) -> None:
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except ValueError:
                errors.append(line.rstrip())
        if mcp_file:  # it read the file when it started
            try:
                os.remove(mcp_file)
            except OSError:
                pass
        events.put(None)  # the end of its output

    def send(self, message: dict) -> None:
        with self.write_lock:
            try:
                self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass  # it ended: its end shows in its output

    def say(self, text: str) -> None:
        self.said += 1
        self.send({"type": "user", "session_id": "", "parent_tool_use_id": None,
                   "message": {"role": "user", "content": text}})

    def close(self) -> None:
        """Its work is done: it ends on its own (it saves its session), and all it wrote is read."""
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.kill()
        for reader in self.readers:
            reader.join(timeout=5)

    def kill(self) -> None:
        if self.process is not None:
            kill_tree(self.process)

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
        if not self.owner.argv():
            raise BrainError("super_unavailable", self.owner.why_not())
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
                event = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                self.close()
                if self._gone():
                    return False
                raise BrainError("super_failed", "Claude Code stopped before it finished",
                                 "\n".join(self.errors) or None)
            ended = self._handle(event)
            if ended is not None:
                return ended

    def _gone(self) -> bool:
        return self.resumed and any("No conversation found" in line for line in self.errors)

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
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                self._said(block)
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
            error = BrainError("super_failed", f"Claude Code could not finish: {reply or event.get('subtype')}",
                               "\n".join(self.errors) or None)
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
