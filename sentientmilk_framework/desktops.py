"""Programs the brain starts out of the user's sight: on a hidden Windows desktop of its own, where windows are
real (pages render and lay out as on the screen) but never show, and nothing takes the user's focus.

Python's subprocess cannot name a desktop (STARTUPINFO.lpDesktop), so on Windows processes start through
CreateProcessW. ``tied`` ones are in a job that ends with the brain, so none is left running invisibly after a
crash. Elsewhere programs start as usual (their windows show).
"""

import os
import subprocess
import time
from typing import List, Optional

WINDOWS = os.name == "nt"
DESKTOP = "SentientMilk"  # the brain's hidden desktop

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p]
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    GENERIC_ALL, CREATE_SUSPENDED, CREATE_NO_WINDOW = 0x10000000, 0x00000004, 0x08000000
    STILL_ACTIVE, WM_CLOSE, KILL_ON_JOB_CLOSE, EXTENDED_LIMITS = 259, 0x0010, 0x2000, 9
    ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                                                            "OtherOperationCount", "ReadTransferCount",
                                                            "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

_desktops: dict = {}  # name -> handle, open while the brain runs (a desktop goes with its last handle)
_job = None


def hidden(name: str = DESKTOP):
    """The hidden desktop's handle (made the first time)."""
    if name not in _desktops:
        handle = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), f"Could not make the hidden desktop {name}")
        _desktops[name] = handle
    return _desktops[name]


def _tied_job():
    """A job whose processes end when the brain does: its handle closes with the brain's process."""
    global _job
    if _job is None:
        job = kernel32.CreateJobObjectW(None, None)
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(job, EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits))
        _job = job
    return _job


class Process:
    """A started program: ``pid``, ``poll()`` (None while it runs), ``wait(timeout)``, ``kill()``."""

    def __init__(self, pid: int, handle=None, popen: Optional[subprocess.Popen] = None, desktop: Optional[str] = None):
        self.pid, self._handle, self._popen, self.desktop = pid, handle, popen, desktop

    def poll(self) -> Optional[int]:
        if self._popen is not None:
            return self._popen.poll()
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code))
        return None if code.value == STILL_ACTIVE else code.value

    def wait(self, timeout: float) -> bool:
        """True once it has ended (within ``timeout`` seconds)."""
        if self._popen is not None:
            try:
                self._popen.wait(timeout)
                return True
            except subprocess.TimeoutExpired:
                return False
        kernel32.WaitForSingleObject(self._handle, int(max(0.0, timeout) * 1000))
        return self.poll() is not None

    def kill(self) -> None:
        if self.poll() is not None:
            return
        if self._popen is not None:
            self._popen.kill()
        else:
            kernel32.TerminateProcess(self._handle, 1)


def start(args: List[str], desktop: Optional[str] = None, tied: bool = False) -> Process:
    """Start ``args``; on Windows on ``desktop`` (a hidden desktop's name; None: the user's), ``tied`` to the
    brain's life. Its windows show as usual elsewhere."""
    if not WINDOWS:
        return Process(0, popen=subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL, start_new_session=True))
    info = STARTUPINFOW()
    info.cb = ctypes.sizeof(info)
    if desktop:
        hidden(desktop)
        info.lpDesktop = f"WinSta0\\{desktop}"
    process = PROCESS_INFORMATION()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
    if not kernel32.CreateProcessW(None, line, None, None, False, CREATE_SUSPENDED | CREATE_NO_WINDOW, None, None,
                                   ctypes.byref(info), ctypes.byref(process)):
        raise OSError(ctypes.get_last_error(), f"Could not start {args[0]}")
    if tied:
        kernel32.AssignProcessToJobObject(_tied_job(), process.hProcess)  # before it can start children
    kernel32.ResumeThread(process.hThread)
    kernel32.CloseHandle(process.hThread)
    return Process(process.dwProcessId, process.hProcess, desktop=desktop)


def close_windows(process: Process) -> int:
    """Ask a program to close as its user would (WM_CLOSE to each of its windows): it saves what it keeps. The
    number of windows asked; elsewhere than Windows it is asked to end."""
    if not WINDOWS or process._popen is not None:
        if process.poll() is None:
            process._popen.terminate()
        return 1
    found = windows_of(process)
    for window in found:
        user32.PostMessageW(window, WM_CLOSE, 0, 0)
    return len(found)


def windows_of(process: Process) -> List[int]:
    """Its visible windows, on the desktop it was started on."""
    if not WINDOWS or process._popen is not None:
        return []
    found: List[int] = []

    def each(window, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == process.pid and user32.IsWindowVisible(window):
            found.append(window)
        return True
    callback = ENUM(each)
    desktop = hidden(process.desktop) if process.desktop else user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    user32.EnumDesktopWindows(desktop, callback, 0)
    return found


def stop(process: Process, timeout: float = 10.0) -> None:
    """Close it as its user would, and end it when it does not within ``timeout`` seconds."""
    if process.poll() is not None:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        close_windows(process)  # again while it runs: a program just started may have no window yet
        process.wait(0.5)
    process.kill()
