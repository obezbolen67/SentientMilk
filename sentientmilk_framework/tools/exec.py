from __future__ import annotations

import subprocess
import time
from pathlib import Path

DESCRIPTION = """
Execute a shell command and capture its stdout/stderr output.
Supports optional working directory, timeout, and post-run settle wait.
"""

ARGS_DESCRIPTION = {
    "command": "Shell command to run (executed with the system shell).",
    "cwd": "Optional working directory. Defaults to current working directory.",
    "timeout": "Seconds before the command is terminated (default 120).",
    "settle_time": "Seconds to wait after completion before returning output (default 0)."
}


def run(command: str, cwd: str | None = None, timeout: int = 120, settle_time: float = 0.0):
    if not command or not command.strip():
        raise ValueError("Command must be a non-empty string.")

    workdir = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    if not workdir.exists():
        raise FileNotFoundError(f"Working directory does not exist: {workdir}")
    if not workdir.is_dir():
        raise NotADirectoryError(f"Working directory is not a directory: {workdir}")

    result = subprocess.run(
        command,
        shell=True,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if settle_time and settle_time > 0:
        time.sleep(settle_time)

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "cwd": str(workdir)
    }
