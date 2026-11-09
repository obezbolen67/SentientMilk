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
a message to one that finished resumes its Claude Code session in a new run. See docs/architecture.md, 5.6.
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
          ("claude-fable-5-1", "Fable 5.1"))
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
    def __init__(self, owner: SuperAgents, run: dict, profile: dict, emit):
        self.owner, self.brain, self.store = owner, owner.brain, owner.brain.store
        self.run, self.profile, self.emit = run, profile, emit
        self.events: queue.Queue = queue.Queue()
        self.errors: deque = deque(maxlen=STDERR_LINES)
        self.calls: dict = {}  # tool use id -> (name, input)
        self.process: Optional[subprocess.Popen] = None
        self.write_lock = threading.Lock()
        self.reply = ""
        self.mcp_file: Optional[str] = None  # the lead's MCP servers for --mcp-config; removed when it ends

    # ============== The process ==============

    def start(self, prompt: str) -> None:
        values, profile = self.brain.config.values(), self.profile
        roots = profile["roots"]
        folder = profile.get("cwd") or (roots[0] if roots else str(Path.home()))
        args = self.owner.argv() + [
            "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--restricted", "--tools", TOOLS, "--strict-mcp-config",
            "--permission-mode", "manual", "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
            "--model", values["super_model"], "--effort", values["super_effort"],
            "--append-system-prompt", PROMPT.format(name=profile["name"])]
        for root in roots:
            if root != folder:
                args += ["--add-dir", root]
        # the lead's MCP servers too: code that lives in an app the user connected (a game editor) is Claude's
        # as well, and Claude can check it there (2026-11-09: it had none, so the lead wrote it by trial and error)
        servers = self.brain.mcp.for_claude(profile.get("toolkits") or [])
        if servers:
            fd, self.mcp_file = tempfile.mkstemp(prefix="super-mcp-", suffix=".json", dir=self.brain.home)
            with os.fdopen(fd, "w", encoding="utf-8") as config:  # a file, not argv: env and headers may hold keys
                json.dump({"mcpServers": servers}, config)
            args += ["--mcp-config", self.mcp_file]
        resumed = self._state().get("claude_session")
        if resumed:
            args += ["--resume", resumed]
        self.process = subprocess.Popen(
            args, cwd=folder, env=_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=_NO_WINDOW,
            start_new_session=os.name != "nt")
        threading.Thread(target=self._read, daemon=True, name=f"super-{self.run['id']}").start()
        threading.Thread(target=lambda: self.errors.extend(line.rstrip() for line in self.process.stderr),
                         daemon=True).start()
        self.send({"type": "control_request", "request_id": "init", "request": {"subtype": "initialize",
                                                                                "hooks": None}})
        self.say(prompt)

    def _read(self) -> None:
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                self.errors.append(line.rstrip())
        if self.mcp_file:  # it read the file when it started
            try:
                os.remove(self.mcp_file)
            except OSError:
                pass
        self.events.put(None)  # the end of its output

    def send(self, message: dict) -> None:
        with self.write_lock:
            try:
                self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass  # it ended: its end shows in its output

    def say(self, text: str) -> None:
        self.send({"type": "user", "session_id": "", "parent_tool_use_id": None,
                   "message": {"role": "user", "content": text}})

    def kill(self) -> None:
        if self.process is not None:
            kill_tree(self.process)

    # ============== One run ==============

    def execute(self) -> None:
        run, store, runs = self.run, self.store, self.brain.runs
        if not self.owner.argv():
            raise BrainError("super_unavailable", self.owner.why_not())
        runs.loop._log_input(run, self.profile, self.emit)
        logged = self._inputs()
        # the brain restarted during this run, after Claude Code took it: its session goes on
        restarted = self._state().get("claude_run") == run["id"]
        prompt = RESTARTED if restarted or not logged else _text(logged[0]["content"])
        attention = runs.attention(run["id"])
        self.start(prompt)
        try:
            while True:
                if attention.stopped.is_set() or store.run(run["id"])["options"].get("cancel"):
                    self.kill()
                    return runs.loop._end(store.run(run["id"]), "cancelled", self.emit)
                self._steer()
                try:
                    event = self.events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if event is None:
                    raise BrainError("super_failed", "Claude Code stopped before it finished",
                                     "\n".join(self.errors) or None)
                if self._handle(event):
                    return
        finally:
            self.kill()

    def _handle(self, event: dict) -> bool:
        """One message from Claude Code; True once the run ended."""
        kind, run = event.get("type"), self.run
        if kind == "system" and event.get("subtype") == "init" and event.get("session_id"):
            self.store.update_session(run["app"], run["session"], "state",
                                      lambda state: {**state, "claude_session": event["session_id"],
                                                     "claude_run": run["id"]})
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                self._said(block)
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
        return False

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

    def _steer(self) -> None:
        """Messages from the lead, sent while it works: logged as the loop logs them, then the next user
        messages of the same process."""
        if not self.store.run(self.run["id"])["options"].get("steer"):
            return
        seen = {e["id"] for e in self._inputs()}
        self.brain.runs.loop._take_messages(self.store.run(self.run["id"]), self.emit)
        for event in self._inputs():
            if event["id"] not in seen:
                self.say(_text(event["content"]))

    def _inputs(self) -> list:
        return [e for e in self.store.run_events(self.run["id"]) if e["type"] == "input"]

    def _result(self, event: dict) -> bool:
        run, store = self.run, self.store
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
        if store.run(run["id"])["options"].get("steer"):
            return False  # the lead wrote meanwhile: it goes on with that (sent at the next round)
        self.process.stdin.close()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.kill()
        reply = str(event.get("result") or self.reply or "").strip()
        if event.get("is_error") or event.get("subtype") != "success":
            error = BrainError("super_failed", f"Claude Code could not finish: {reply or event.get('subtype')}",
                               "\n".join(self.errors) or None)
            self.brain.runs.loop._end(store.run(run["id"]), "failed", self.emit, error=error)
            return True
        self.brain.runs.loop._end(store.run(run["id"]), "completed", self.emit, reply=reply,
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

    def _permit(self, request: dict) -> dict:
        """What Claude Code asks: decided by the rules, or asked like any agent's call (the app asks the user,
        or allows it in its bypass); this waits for the answer."""
        run, store, runs = self.run, self.store, self.brain.runs
        name, arguments = request.get("tool_name", ""), request.get("input") or {}
        allow = {"behavior": "allow", "updatedInput": arguments}
        decision = self._rules(name, arguments)
        if decision == "off":
            return {"behavior": "deny", "message": f"Refused: {name} is not allowed here."}
        if decision == "auto":
            return allow
        call_id = request.get("tool_use_id") or f"super-{time.time_ns()}"
        asked = {"call_id": call_id, "name": name, "arguments": arguments}
        store.add_event(run["app"], run["session"], run["id"], "approval_request", asked)
        self.emit({"type": "approval.requested", **asked})
        attention = runs.attention(run["id"])
        paused = False
        while True:
            with runs.pause_lock:  # an answer and the pause never cross (as in Loop._settle)
                answer = next((e for e in store.run_events(run["id"]) if e["type"] == "approval"
                               and e["call_id"] == call_id), None)
                if answer is None and not paused:
                    store.update_run(run["id"], status="input_required")
            if answer is not None:
                break
            if attention.stopped.is_set():
                return {"behavior": "deny", "message": "The agent was stopped.", "interrupt": True}
            if not paused:
                self.emit({"type": "paused", "status": "input_required"})
                runs.paused(store.run(run["id"]))
                paused = True
            time.sleep(0.2)
        # the answer spawned the run again (Runs._answer): that waits for the session and finds it ended
        store.update_run(run["id"], status="working")
        if answer["decision"] == "deny":
            reason = f" Their reason: {answer['reason']}" if answer.get("reason") else ""
            return {"behavior": "deny", "message": f"The user did not allow this call.{reason}"}
        own = RULE_NAMES.get(name)
        if answer["decision"] == "always" and own:
            tool = SimpleNamespace(name=own[0], policy="ask", rule_arg=own[1])
            self.brain.allow_always(run["app"], permissions.always_rule(tool, {own[1]: arguments.get(own[2], "")},
                                                                        self.profile.get("cwd")))
        return allow

    def _state(self) -> dict:
        return (self.store.find_session(self.run["app"], self.run["session"]) or {}).get("state") or {}
