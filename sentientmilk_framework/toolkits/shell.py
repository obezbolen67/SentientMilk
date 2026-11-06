"""Shell: run commands, in the foreground with a timeout or in the background as jobs."""

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import ToolContext, ToolError, Toolkit, cap, tool
from .files import cwd as working_folder
from .files import resolve

DEFAULT_TIMEOUT, MAX_TIMEOUT = 120, 600
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


def _folder(ctx: ToolContext, folder: str) -> Path:
    path = resolve(ctx, folder) if folder else working_folder(ctx)
    if not path.is_dir():
        raise ToolError(f"{path} is not a folder.")
    return path


@tool(rule_arg="command", args={
    "command": "The command line, in the shell named above.",
    "cwd": "Folder to run in (default: the working folder).",
    "timeout": f"Seconds before the command is stopped (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT}).",
    "background": "Start it as a job and return at once; use for servers, watchers and long builds."})
def shell_run(ctx: ToolContext, command: str, cwd: str = "", timeout: int = DEFAULT_TIMEOUT,
              background: bool = False):
    """Run a command in {shell}. Output (stdout and stderr together) comes back with the exit code.
    No shell state carries over between calls: pass cwd instead of cd, and set variables in the same command.
    Prefer files_read/files_search/files_edit over cat, grep and sed. Long or never-ending commands
    belong in background=true; then read their output with shell_output."""
    if not command.strip():
        raise ToolError("command is empty.")
    folder = _folder(ctx, cwd)
    line = command_line(ctx.brain.config.values()["shell"], command)
    if background:
        return _start_job(ctx, command, line, folder)
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    try:
        process = _popen(line, folder, stdout=subprocess.PIPE)
    except OSError as exc:
        raise ToolError(f"Could not start the shell: {exc}")
    try:
        output, _ = process.communicate(timeout=timeout)
        status = f"exit code {process.returncode}"
    except subprocess.TimeoutExpired:
        kill_tree(process)
        output, _ = process.communicate()
        status = f"stopped after {timeout} s (timeout); use background=true for long commands"
    text = (output or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
    return cap(ctx, f"[{status}]\n{text}".rstrip(), "shell")


def _start_job(ctx: ToolContext, command: str, line: list, folder: Path) -> str:
    log = ctx.run_dir() / f"job-{int(time.time() * 1000)}.log"
    job = ctx.store.add_job(ctx.run["id"], ctx.app, ctx.session, command, str(folder), str(log))
    output = open(log, "wb")
    try:
        process = _popen(line, folder, stdout=output)
    except OSError as exc:
        output.close()
        ctx.store.update_job(job, status="failed", ended=time.time())
        raise ToolError(f"Could not start the shell: {exc}")
    ctx.store.update_job(job, pid=process.pid)
    ctx.brain.jobs[job] = process
    threading.Thread(target=_watch, args=(ctx.brain, job, process, output), name=f"job-{job}",
                     daemon=True).start()
    return f"Started job {job}. Read its output with shell_output(job={job}); you get a note when it ends."


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


@tool(readonly=True, args={"job": "Job id from shell_run.", "since": "Skip this many lines (to read only new ones)."})
def shell_output(ctx: ToolContext, job: int, since: int = 0):
    """Output of a background job so far, and whether it is still running."""
    record = _job(ctx, job)
    lines = _lines(record["log"])
    start = max(0, int(since or 0))
    shown = lines[start:start + OUTPUT_LINES]
    status = record["status"] + (f", exit code {record['exit_code']}" if record["exit_code"] is not None else "")
    footer = f"[lines {start + 1}-{start + len(shown)} of {len(lines)}; job {job} is {status}]"
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
