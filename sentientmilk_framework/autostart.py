"""Start with Windows: an app's entry in the current user's Run key, the list Task Manager shows as
Startup apps. Turning an app off there is respected: it reads as off here, and turning it on here clears it.
Every app uses this (SentientMilk's panel, MilkChan's settings), each under its own name.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional

AVAILABLE = os.name == "nt"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"  # Task Manager's on/off


def windowless(executable: Path) -> Path:
    """The program beside ``executable`` that opens no console (python.exe -> pythonw.exe, NAME.exe ->
    NAMEw.exe), or ``executable`` itself when there is none."""
    twin = executable.with_name(f"{executable.stem}w{executable.suffix}")
    return twin if twin.exists() else executable


def enabled(name: str) -> bool:
    """Starts with Windows: the entry is there and Task Manager has not turned it off (an odd first byte)."""
    if not AVAILABLE or _read(RUN, name) is None:
        return False
    approved = _read(APPROVED, name)
    return not (isinstance(approved, bytes) and approved[:1] and approved[0] % 2)


def set_enabled(name: str, argv: Optional[List[str]]) -> None:
    """Start ``argv`` at sign-in as ``name``, or no longer (None). Raises OSError when the registry refuses."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as key:
        if argv:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, subprocess.list2cmdline([str(part) for part in argv]))
        else:
            _delete(key, name)
    try:  # this choice replaces one made in Task Manager
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED, 0, winreg.KEY_SET_VALUE) as key:
            _delete(key, name)
    except FileNotFoundError:
        pass


def _read(path: str, name: str):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def _delete(key, name: str) -> None:
    import winreg

    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass
