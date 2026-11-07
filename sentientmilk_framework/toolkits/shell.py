"""Shell: run commands. A command still running after WAIT seconds is not stopped: it goes on as a
background job, so the model gets control back without guessing durations (it cannot know a
download is slow, and asked for longer waits it always does), and gets a note when the job ends.
A model that needs the result waits for it with shell_output(wait=...); in a turn of an app that
calls back (its end starts a new turn) it waits briefly and is told to end its turn instead."""

import os
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import MESSAGE_FROM_USER, STOPPED_BY_USER, ToolContext, ToolError, Toolkit, cap, tool
from .files import cwd as working_folder
from .files import resolve

WAIT, MAX_WAIT = 30, 600  # seconds shell_run waits before a command becomes a job; the longest shell_output wait
OUTPUT_LINES = 200
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def shell_name(setting: str) -> str:
    return setting or ("powershell" if os.name == "nt" else "bash")


def command_line(setting: str, command: str) -> list:
    name = shell_name(setting)
    if name in ("powershell", "pwsh"):
        # PowerShell 5.1 writes in the console code page unless told otherwise.
        prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; "
        return ["powershell.exe" if name == "powershell" else "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-Command", prefix + command]
    if name == "cmd":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return [name, "-c", command]


def _popen(command: list, folder: Path, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            creationflags=_NO_WINDOW, start_new_session=os.name != "nt", **kwargs)


def kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                       creationflags=_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


# What a reviewer's shell may run. shortcut: a word list, not a sandbox (a test run can still write
# files); it keeps a reviewer told to check from fixing things. A real sandbox if reviewers ever run untrusted.
LOOKING = {"get-content", "gc", "cat", "type", "get-childitem", "gci", "ls", "dir", "get-item", "gi", "tree",
           "select-string", "sls", "select-object", "select", "measure-object", "measure", "sort-object",
           "where-object", "format-list", "fl", "format-table", "ft", "out-string", "test-path", "resolve-path",
           "get-location", "pwd", "get-filehash", "compare-object", "get-command", "rg", "grep", "findstr",
           "head", "tail", "wc", "more", "echo", "write-output", "pytest", "py.test", "mypy", "eslint"}
LOOKING_SUBCOMMANDS = {
    "git": ("status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "grep", "describe", "shortlog"),
    "ruff": ("check",), "npm": ("test", "t", "ls", "run test"), "pnpm": ("test", "ls"), "yarn": ("test",),
    "cargo": ("test", "check"), "go": ("test", "vet"), "dotnet": ("test",), "pip": ("list", "show", "freeze")}
PYTHONS = {"python", "python3", "py"}
WRITING_OPTIONS = {"--output", "--fix", "--write", "--pre", "--open-files-in-pager"}  # and git grep -O
NOT_LOOKING = ";&><`$(){}\n\r"
LOOKING_HELP = ("In review you may only look: read and search (Get-Content, Get-ChildItem, Select-String, rg), "
                "git status/diff/log/show, and run tests and linters (pytest, npm test, cargo test, ruff check). "
                "No redirection, chaining, ( ), { } or $; the exit code comes back on its own.")


def looking_only(command: str) -> str:
    """Empty when every part of the pipeline only looks; otherwise what does not."""
    command = re.sub(r"^\s*&\s+", "", command)  # PowerShell's call operator, to run a quoted path
    bad = sorted({c for c in command if c in NOT_LOOKING})
    if bad:
        return f"it uses {' '.join(repr(c) for c in bad)}"
    for part in command.split("|"):
        try:
            words = [word.strip("\"'") for word in shlex.split(part, posix=False)]
        except ValueError:
            return "its quotes do not close"
        if not words:
            return "a part of the pipeline is empty"
        first = Path(words[0]).name.lower().removesuffix(".exe")
        rest = words[1:]
        if first in PYTHONS:
            while rest[:1] and rest[0] in ("-I", "-B", "-u", "-E", "-s"):
                rest = rest[1:]
            if rest[:1] != ["-m"] or len(rest) < 2:
                return f"{words[0]} runs a script; only python -m with a test runner or linter"
            first, rest = rest[1].lower(), rest[2:]
        if first == "git":
            while rest[:1] and rest[0] in ("-C", "--no-pager"):
                rest = rest[2:] if rest[0] == "-C" else rest[1:]
        writing = next((w for w in rest if w.split("=")[0] in WRITING_OPTIONS or w.startswith("-O")), None)
        if writing:
            return f"{writing} writes"
        if rest in (["--version"], ["--help"]):
            continue
        if first in LOOKING:
            continue
        line = " ".join(rest).lower()
        if not any(line == sub or line.startswith(sub + " ") for sub in LOOKING_SUBCOMMANDS.get(first, ())):
            return f"{' '.join(words[:2])} may change things"
    return ""


def _folder(ctx: ToolContext, folder: str) -> Path:
    path = resolve(ctx, folder) if folder else working_folder(ctx)
    if not path.is_dir():
        raise ToolError(f"{path} is not a folder.")
    return path


@tool(core=True, rule_arg="command", args={
    "command": "The command line, in the shell named above.",
    "cwd": "Folder to run in (default: the working folder).",
    "timeout": f"Seconds to wait for it, at most {WAIT}; still running then, it goes on as a background job.",
    "background": "Start it as a job and return at once: for servers, watchers and anything you know is long."})
def shell_run(ctx: ToolContext, command: str, cwd: str = "", timeout: int = WAIT,
              background: bool = False):
    """Run a command in {shell}. Output (stdout and stderr together) comes back with the exit code; a
    command still running after timeout goes on as a background job, so you can work on while it runs.
    No shell state carries over between calls: pass cwd instead of cd, and set variables in the same command.
    Prefer files_read/files_search/files_edit over cat, grep and sed."""
    if not command.strip():
        raise ToolError("command is empty.")
    if ctx.profile.get("mode") == "review":
        why = looking_only(command)
        if why:
            raise ToolError(f"Not run: {why}. {LOOKING_HELP}")
    folder = _folder(ctx, cwd)
    line = command_line(ctx.brain.config.values()["shell"], command)
    log = ctx.run_dir() / f"job-{time.time_ns()}.log"  # a file, not a pipe: the command may outlive the call
    output = open(log, "wb")
    try:
        process = _popen(line, folder, stdout=output)
    except OSError as exc:
        output.close()
        raise ToolError(f"Could not start the shell: {exc}")
    if background:
        job = _keep_as_job(ctx, command, folder, log, process, output)
        if ctx.called_back:
            return (f"Started job {job}; you are called back when it ends (a new turn, with its last lines). End "
                    f"your turn now unless you have other work meanwhile: do not wait for it. shell_output(job={job}) "
                    "shows its output so far.")
        return f"Started job {job}. Read its output with shell_output(job={job}); you get a note when it ends."
    timeout = max(1, min(int(timeout or WAIT), WAIT))
    deadline = time.monotonic() + timeout
    while True:
        try:
            code = process.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            pass
        if ctx.attention.stopped.is_set():  # the user stopped her: the command ends with her
            kill_tree(process)
            output.close()
            so_far = "\n".join(_lines(str(log))[-40:])
            log.unlink(missing_ok=True)
            return cap(ctx, f"[stopped: {STOPPED_BY_USER} The command was ended.]\n{so_far}".rstrip(), "shell")
        if ctx.attention.woken.is_set() or time.monotonic() >= deadline:
            why = MESSAGE_FROM_USER if ctx.attention.woken.is_set() else f"Still running after {timeout} s."
            job = _keep_as_job(ctx, command, folder, log, process, output)
            so_far = "\n".join(_lines(str(log))[-40:])
            if ctx.called_back:
                return cap(ctx, f"[{why} It goes on as background job {job}, and you are called back when it ends "
                                f"(a new turn, with its last lines). End your turn now and tell the user it runs, "
                                f"unless you have other work meanwhile: do not wait for it. "
                                f"shell_output(job={job}) shows its output so far, shell_stop(job={job}) stops it."
                                f"]\n{so_far}".rstrip(), "shell")
            return cap(ctx, f"[{why} It goes on as background job {job}. You get a note "
                            f"when it ends; shell_output(job={job}) shows its output (wait=... waits for the end), "
                            f"shell_stop(job={job}) stops it. "
                            f"Work on meanwhile, or tell the user it is running.]\n{so_far}".rstrip(), "shell")
    output.close()
    text = "\n".join(_lines(str(log)))
    log.unlink(missing_ok=True)
    return cap(ctx, f"[exit code {code}]\n{text}".rstrip(), "shell")


def _keep_as_job(ctx: ToolContext, command: str, folder: Path, log: Path, process: subprocess.Popen,
                 output) -> int:
    """Track a running command as a job: it can be read and stopped, and its end leaves a note."""
    job = ctx.store.add_job(ctx.run["id"], ctx.app, ctx.session, command, str(folder), str(log))
    ctx.store.update_job(job, pid=process.pid)
    ctx.brain.jobs[job] = process
    threading.Thread(target=_watch, args=(ctx.brain, job, process, output), name=f"job-{job}",
                     daemon=True).start()
    return job


def _watch(brain, job: int, process: subprocess.Popen, output) -> None:
    code = process.wait()
    output.close()
    record = brain.store.job(job)
    stopped = record["status"] == "stopping"
    brain.store.update_job(job, status="stopped" if stopped else "finished", exit_code=code, ended=time.time())
    brain.jobs.pop(job, None)
    tail = "\n".join(_lines(record["log"])[-15:])
    brain.note(record["app"], record["session"],
               f"Background job {job} {'was stopped' if stopped else f'finished with exit code {code}'}: "
               f"{record['command']}\nLast lines:\n{tail}")
    brain.notify(record["app"], record["session"], "job.finished",
                 {"job": job, "exit_code": code, "command": record["command"]})


def _lines(path: str) -> list:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").splitlines()
    except OSError:
        return []


def _job(ctx: ToolContext, job: int) -> dict:
    record = ctx.store.job(int(job))
    if not record or record["app"] != ctx.app:
        raise ToolError(f"There is no job {job}.")
    return record


@tool(core=True, readonly=True, args={"job": "Job id from shell_run.", "since": "Skip this many lines (to read only new ones).",
                            "wait": f"Seconds to wait for the job to end first (max {MAX_WAIT}); 0 reads at once."})
def shell_output(ctx: ToolContext, job: int, since: int = 0, wait: int = 0):
    """Output of a background job so far, and whether it is still running."""
    record = _job(ctx, job)
    deadline = time.time() + ctx.wait_limit(max(0, min(int(wait or 0), MAX_WAIT)))
    woke = ""
    while record["status"] in ("running", "stopping") and time.time() < deadline:
        if ctx.pause(0.5):
            woke = ctx.interruption()
            break
        record = _job(ctx, job)
    lines = _lines(record["log"])
    start = max(0, int(since or 0))
    shown = lines[start:start + OUTPUT_LINES]
    status = record["status"] + (f", exit code {record['exit_code']}" if record["exit_code"] is not None else "")
    footer = f"[lines {start + 1}-{start + len(shown)} of {len(lines)}; job {job} is {status}]"
    if woke:
        footer += f" Stopped waiting: {woke}"
    elif ctx.called_back and record["status"] == "running" and wait:
        footer += (" Do not wait for it: you are called back when it ends. End your turn now unless you have "
                   "other work meanwhile.")
    if start + len(shown) < len(lines):
        footer += f" More with since={start + len(shown)}."
    return cap(ctx, "\n".join(shown + [footer]), "job")


@tool(readonly=False, policy="auto", args={"job": "Job id from shell_run."})
def shell_stop(ctx: ToolContext, job: int):
    """Stop a background job and everything it started."""
    record = _job(ctx, job)
    process = ctx.brain.jobs.get(record["id"])
    if record["status"] != "running" or process is None:
        return f"Job {job} is not running ({record['status']})."
    ctx.store.update_job(record["id"], status="stopping")
    kill_tree(process)
    return f"Stopped job {job}."


TOOLKIT = Toolkit("shell", "Run commands on the user's computer.", [shell_run, shell_output, shell_stop])
