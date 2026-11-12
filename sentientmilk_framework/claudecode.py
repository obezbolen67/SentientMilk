"""The user's own Claude Code: where it is, what it says about itself, and talking with it headless.

Two parts of SentientMilk think with Claude through it, on the user's sign-in and plan: super agents
(superagent.py), and the brain itself when the user picks Claude Code as its provider (claude_provider.py). Both
start ``claude -p`` with stream-json both ways and speak its control protocol (initialize, permission questions,
MCP messages for tools the host serves). Prompts go in files, never on the command line (Windows ends a command
line at 32k characters, and a batch-file launcher would read its symbols).

What Claude Code offers comes from Claude Code: its ``initialize`` answer names its models (with the efforts each
takes), the account it is signed in to and its version. That answer is kept, taken again when Claude Code itself
changed (updated, moved), after ``INFO_AGE``, and whenever one of its processes starts anyway; the panel's Refresh
asks at once. Nothing of it is written into SentientMilk.
"""

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, List, Optional

from .config import EFFORTS
from .exceptions import BrainError
from .toolkits.shell import kill_tree

logger = logging.getLogger(__name__)

INFO_AGE = 600  # seconds what Claude Code said about itself is kept (sign-ins and plans change)
FAILED_AGE = 10  # seconds "not signed in" and the like are kept: the user may be fixing it right now
LOOK_AGE = 60  # seconds where claude is stays known
PROBE_TIMEOUT = 20.0
STDERR_LINES = 30
# Claude Code gives its efforts' names only: how the panel says them
EFFORT_NAMES = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra high", "max": "Max"}
assert set(EFFORT_NAMES) == set(EFFORTS)
# what an assistant message's ``error`` says went wrong -> (type, message, details); the loop retries
# server_error, and apps show a claude_code error's own words
ERRORS = {
    "authentication_failed": ("claude_code", "Claude Code is not signed in",
                              "Open a terminal, run claude and sign in with /login: SentientMilk uses Claude through "
                              "it, on your plan."),
    "billing_error": ("claude_code", "Claude Code's account cannot pay for this",
                      "Check your Claude plan or API credits in Claude Code (/status)."),
    "server_error": ("server_error", "Claude's service had a problem", "SentientMilk tries again in a moment."),
    "invalid_request": ("claude_code", "Claude refused the request", None),
    "unknown": ("claude_code", "Claude Code could not answer", None),
}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def child_env(extra: Optional[dict] = None) -> dict:
    """The brain's environment, without what ties a process to a Claude Code session it may run inside."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CLAUDECODE", "CLAUDE_CODE_")) and key not in ("CLAUDE_PID", "CLAUDE_EFFORT")}
    return {**env, **(extra or {})}


def _model(entry: dict) -> dict:
    return {"value": str(entry.get("value", "")), "model": str(entry.get("resolvedModel") or entry.get("value", "")),
            "label": str(entry.get("displayName") or entry.get("value", "")),
            "about": str(entry.get("description") or ""),
            "efforts": [e for e in entry.get("supportedEffortLevels") or [] if e in EFFORTS]
            if entry.get("supportsEffort") else []}


def failure(kind: str, text: str = "", limit: Optional[dict] = None) -> BrainError:
    """What a failed answer of Claude Code means, in the user's words."""
    if kind == "rate_limit":
        resets = (limit or {}).get("resetsAt")
        when = f"at {time.strftime('%H:%M on %a %d %b', time.localtime(resets))}" if resets else "later"
        return BrainError("plan_limit", "Your Claude plan's usage limit is reached",
                          f"It resets {when}. Until then, SentientMilk can think with an API service instead "
                          "(Provider in its panel).")
    if "prompt is too long" in text.lower():  # the loop compacts the conversation and tries again
        return BrainError("payload_too_large", "The conversation is too long for Claude", text)
    type_, message, details = ERRORS.get(kind, ERRORS["unknown"])
    return BrainError(type_, message, details or text or None)


def outdated(errors) -> bool:
    return any("unknown option" in line.lower() for line in errors)


class ClaudeCode:
    def __init__(self, brain):
        self.brain = brain
        self.folder = brain.home / "claude-code"  # where her own Claude Code sessions run: none of the user's
        for leftover in self.folder.glob("*.md"):  # prompts of processes that ended with an earlier brain
            try:
                leftover.unlink()
            except OSError:
                pass
        self._found = (0.0, None)  # (when, path) of the claude command
        self._info: Optional[dict] = None
        self._lock = threading.Lock()
        self._probing = threading.Lock()  # one question at a time; who comes meanwhile takes its answer
        self._asking = False
        self.conversations = None  # the provider's (claude_provider.Conversations), made when first used
        # each model's context window, as its replies say (its initialize answer does not): kept across restarts
        try:
            self.windows = json.loads((self.folder / "windows.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.windows = {}

    # ============== Where it is ==============

    def command(self) -> Optional[str]:
        """Claude Code's command: the one set in the panel, or claude where it is found."""
        configured = self.brain.config.values()["claude_command"]
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

    def _stamp(self) -> tuple:
        """Changes when Claude Code does: another one set or found, or the same one updated."""
        argv = self.argv()
        try:
            stat = Path(argv[-1]).stat() if argv else None
        except OSError:
            stat = None
        return tuple(argv), (stat.st_mtime, stat.st_size) if stat else None

    # ============== What it says about itself ==============

    def info(self, refresh: bool = False) -> dict:
        """``command``, ``version``, ``signed_in``, ``account`` (email, organization, plan, provider), ``models``
        (value, model, label, about, efforts), ``error`` and when it was ``checked``. Asked of Claude Code at
        once the first time, after it changed, after a failure (soon) or with ``refresh``; else kept, and asked
        again behind the caller's back once old."""
        wanted = time.time()
        with self._lock:
            known = self._info
            if not refresh and self._usable(known):
                self._old(known)
                return known
        return self._ask(wanted)

    def known(self) -> Optional[dict]:
        """What it said about itself as far as known now, never waiting for it (None before it first said):
        asked behind the caller's back when there is nothing yet or it is old."""
        with self._lock:
            known = self._info
            if not self._usable(known):
                self._behind()
            else:
                self._old(known)
            return known

    def _usable(self, known: Optional[dict]) -> bool:
        return known is not None and known["stamp"] == self._stamp() and (
            not known["error"] or time.time() - known["checked"] < FAILED_AGE)

    def _old(self, known: dict) -> None:
        if time.time() - known["checked"] > INFO_AGE:
            self._behind()

    def _behind(self) -> None:
        if not self._asking:
            self._asking = True
            threading.Thread(target=self._ask_behind, daemon=True, name="claude-code-info").start()

    def _ask_behind(self) -> None:
        try:
            self._ask(time.time())
        finally:
            self._asking = False

    def _ask(self, wanted: float) -> dict:
        with self._probing:
            known = self._info
            if known is not None and known["checked"] >= wanted:  # asked meanwhile, or a process told it
                return known
            return self._probe()

    def _probe(self) -> dict:
        stamp, argv = self._stamp(), self.argv()
        info = {"command": argv[-1] if argv else "", "version": "", "signed_in": False, "account": {},
                "models": [], "error": "", "checked": time.time(), "stamp": stamp}
        if not argv:
            info["error"] = "not installed"
            return self._keep(info)
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            process = Process(self, ["-p", "--input-format", "stream-json", "--output-format", "stream-json",
                                     "--verbose", "--tools", "", "--restricted", "--safe-mode", "--strict-mcp-config",
                                     "--disable-slash-commands", "--no-session-persistence"], self.folder)
        except OSError as exc:
            info["error"] = f"could not start: {exc}"
            return self._keep(info)
        try:
            process.initialize()
            deadline = time.monotonic() + PROBE_TIMEOUT
            while time.monotonic() < deadline:
                try:
                    event = process.events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if event is None:
                    break
                if event.get("type") == "control_response":
                    if self._info is not None and self._info["checked"] >= info["checked"]:
                        return self._info  # learn() read it
                    break
            info["error"] = ("too old for SentientMilk: run claude update" if outdated(process.errors) else
                             "did not answer" + (f": {process.errors[-1]}" if process.errors else ""))
            return self._keep(info)
        finally:
            process.close(wait=5)

    def learn(self, answer: dict) -> None:
        """Claude Code's ``initialize`` answer, from any of its processes."""
        account = answer.get("account") or {}  # signed out: {"tokenSource": "none", ...}
        signed_in = bool(account) and (account.get("tokenSource") != "none" or
                                       account.get("apiKeySource") not in (None, "", "none"))
        models = [_model(m) for m in answer.get("models") or [] if isinstance(m, dict)]
        for entry in models:  # "Default (recommended)" says less than the model it is
            real = next((m for m in models if m["model"] == entry["model"] and m["value"] != "default"), None)
            if entry["value"] == "default" and real:
                entry["label"] = f"Default ({real['label']})"
        self._keep({"command": (self.argv() or [""])[-1], "version": str(answer.get("claude_code_version") or ""),
                    "signed_in": signed_in,
                    "account": {"email": account.get("email", ""), "organization": account.get("organization", ""),
                                "plan": account.get("subscriptionType", ""), "provider": account.get("apiProvider", "")}
                    if signed_in else {},
                    "models": models, "error": "" if signed_in else "not signed in", "checked": time.time(), "stamp": self._stamp()})

    def _keep(self, info: dict) -> dict:
        with self._lock:
            self._info = info
        return info

    def status(self, refresh: bool = False) -> dict:
        """For the panel and apps (what it said about itself, without the bookkeeping)."""
        return {key: value for key, value in self.info(refresh).items() if key != "stamp"}

    # ============== Models ==============

    def models(self) -> List[dict]:
        """Claude Code's models as far as known now. Its first answer is waited for (the brain asks as it
        starts): a name that changed from "opus" to "Opus 5.5" a second later told her that her tools changed."""
        known = self.known()
        return (known if known is not None else self.info())["models"]

    def model(self, value: str) -> Optional[dict]:
        """Claude Code's entry for a model: by its value ("opus", "default"), else by the model it is."""
        models = self.models()
        return next((m for m in models if m["value"] == value), None) or \
            next((m for m in models if m["model"] == value and m["value"] != "default"), None)

    def learn_windows(self, usage: dict) -> None:
        """A result's ``modelUsage``: {"claude-sonnet-5-5": {"contextWindow": 1000000, ...}}."""
        windows = {name: entry["contextWindow"] for name, entry in usage.items()
                   if isinstance(entry, dict) and isinstance(entry.get("contextWindow"), int)}
        with self._lock:
            if windows.items() <= self.windows.items():
                return
            self.windows = {**self.windows, **windows}
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                (self.folder / "windows.json").write_text(json.dumps(self.windows), encoding="utf-8")
            except OSError:
                logger.warning("Could not keep Claude Code's context windows", exc_info=True)

    def window(self, value: str) -> Optional[int]:
        """A model's context window as Claude Code said it; None before one of its replies said it."""
        entry = self.model(value)
        return self.windows.get(entry["model"] if entry else value)

    def label(self, value: str) -> str:
        """How Claude Code names a model: "Opus 5.5", "Default (Opus 5.5)"; one it does not list, as given."""
        entry = self.model(value)
        return entry["label"] if entry else value

    def effort(self, value: str, wanted: str) -> Optional[str]:
        """The effort to start a model with: ``wanted`` where it takes it, else the nearest lower one it takes
        (Opus 4.6 has no xhigh); None for a model without efforts. A model it does not list gets ``wanted``."""
        entry = self.model(value)
        if entry is None:
            return wanted
        levels = entry["efforts"]
        if not levels:
            return None
        if wanted in levels:
            return wanted
        lower = [e for e in EFFORTS[:EFFORTS.index(wanted)] if e in levels]
        return lower[-1] if lower else levels[0]

    # ============== Running ==============

    def problem(self) -> Optional[BrainError]:
        """Why Claude Code cannot think now, in words for the user; None when it can."""
        info = self.info()
        if not info["command"]:
            return BrainError("claude_code", "Claude Code is not installed on this computer",
                              "Install it and sign in to it, or set where it is in the SentientMilk control panel "
                              "(Provider).")
        if info["error"] == "not signed in":
            return failure("authentication_failed")
        if info["error"]:
            return BrainError("claude_code", " ".join(f"Claude Code {info['version']} {info['error']}".split()))
        return None

    def pool(self):
        """The provider's warm conversations (claude_provider.Conversations)."""
        from .claude_provider import Conversations

        with self._lock:
            if self.conversations is None:
                self.conversations = Conversations(self)
            return self.conversations

    def close(self) -> None:
        """The brain stops: no Claude Code of the provider's goes on behind it."""
        if self.conversations is not None:
            self.conversations.close()


class Process:
    """One ``claude -p`` speaking stream-json: its output as events (None at its end) in ``events``, or to
    ``on_event(process, event)`` on its reader thread; its last stderr lines; the temporary files it was given
    (deleted once it ended)."""

    def __init__(self, claude: ClaudeCode, args: List[str], cwd, files: List[str] = (), env: Optional[dict] = None,
                 on_event: Optional[Callable[["Process", Optional[dict]], None]] = None):
        self.claude, self.files = claude, list(files)
        self.events: queue.Queue = queue.Queue()
        self.errors: deque = deque(maxlen=STDERR_LINES)
        self._write = threading.Lock()
        self.popen = subprocess.Popen(
            claude.argv() + args, cwd=str(cwd), env=child_env(env), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_NO_WINDOW, start_new_session=os.name != "nt")
        self._on_event = on_event
        self.readers = [threading.Thread(target=self._read, daemon=True, name="claude-code-out"),
                        threading.Thread(target=self._read_errors, daemon=True, name="claude-code-err")]
        for reader in self.readers:
            reader.start()

    def _read(self) -> None:
        try:
            for line in self.popen.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    self.errors.append(line.rstrip())
                    continue
                response = event.get("response") or {}
                if event.get("type") == "control_response" and response.get("request_id") == "init":
                    if response.get("subtype") == "success":
                        try:
                            self.claude.learn(response.get("response") or {})
                        except Exception:
                            logger.exception("Reading what Claude Code said about itself")
                elif event.get("type") == "result" and isinstance(event.get("modelUsage"), dict):
                    self.claude.learn_windows(event["modelUsage"])
                if self._on_event:
                    self._on_event(self, event)
                else:
                    self.events.put(event)
        finally:
            self.popen.wait()  # its end, and all it said on stderr, are known before anyone hears of it
            self.readers[1].join(timeout=5)
            for path in self.files:  # it read them when it started
                try:
                    os.remove(path)
                except OSError:
                    pass
            if self._on_event:
                self._on_event(self, None)
            else:
                self.events.put(None)  # the end of its output

    def _read_errors(self) -> None:
        for line in self.popen.stderr:
            self.errors.append(line.rstrip())

    def send(self, message: dict) -> None:
        with self._write:
            try:
                self.popen.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                self.popen.stdin.flush()
            except (OSError, ValueError):
                pass  # it ended: its end shows in its output

    def say(self, content) -> None:
        """A user message: text, or content blocks (text and images)."""
        self.send({"type": "user", "session_id": "", "parent_tool_use_id": None,
                   "message": {"role": "user", "content": content}})

    def answer(self, request_id, response: Optional[dict] = None, error: str = "") -> None:
        self.send({"type": "control_response", "response": (
            {"subtype": "error", "request_id": request_id, "error": error} if error else
            {"subtype": "success", "request_id": request_id, "response": response or {}})})

    def initialize(self) -> None:
        self.send({"type": "control_request", "request_id": "init", "request": {"subtype": "initialize", "hooks": None}})

    def alive(self) -> bool:
        return self.popen.poll() is None

    def close(self, wait: float = 30) -> None:
        """Its work is done: it ends on its own (it saves its session), and all it wrote is read."""
        try:
            self.popen.stdin.close()
        except OSError:
            pass
        try:
            self.popen.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            self.kill()
        for reader in self.readers:
            reader.join(timeout=5)

    def kill(self) -> None:
        if self.alive():
            kill_tree(self.popen)


def prompt_file(folder: Path, text: str, prefix: str) -> str:
    """A prompt in a file of its own, for --system-prompt-file and the like; deleted once its process ended."""
    import tempfile

    folder.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".md", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(text)
    return path
