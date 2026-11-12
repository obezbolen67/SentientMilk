"""Her browser: a Chrome (or Edge) of her own, driven over the DevTools protocol, for the web as a person uses it.

It is the real browser with a profile of its own (``browser/profile``): sites see the Chrome they see from the
user, on the user's connection, and what she signs in to stays. On Windows it runs on the brain's hidden desktop
(desktops.py), in ordinary windows the user never sees, and it ends with the brain. Measured on Chrome 157
(2026-11-12): a fixed debugging port leaves ``navigator.webdriver`` false (port 0 and the pipe set it, and the
switch that hides it adds a warning bar); a minimized window gives itself away (its size and pointer positions)
and stops a page's timers, a window on a hidden desktop does neither. So: a fixed port on 127.0.0.1, ordinary
windows, Runtime never enabled (the page's world is left alone: the brain reads pages in an isolated world of its
own, browser_page.js), the pointer moves before clicks and typing goes key by key.

Each chat (and each agent or task) has tabs of its own, t1, t2..., each in a window of its own so that every
page renders as the one in front. Tabs outlive the browser: it closes when idle and when the brain stops, and a
tab opens again at its address when it is next used. When a site needs the user (a sign-in, a check that she is
human), the step ``show`` opens her profile on the user's screen as a plain Chrome with nothing attached; her next
browser call closes it there and she goes on here, signed in. See docs/architecture.md, 6.7.
"""

import base64
import contextlib
import difflib
import io
import itertools
import json
import logging
import math
import os
import queue
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from . import desktops, transport
from .exceptions import BrainError
from .toolkits import ToolError, ToolResult

logger = logging.getLogger(__name__)

PAGE_JS = Path(__file__).with_name("browser_page.js").read_text(encoding="utf-8")
WORLD = "sentientmilk"
WINDOW = (1280, 900)  # each tab's window, in device-independent pixels
FLAGS = ["--no-first-run", "--no-default-browser-check", "--hide-crash-restore-bubble",
         "--disable-backgrounding-occluded-windows"]  # windows on top of each other all render
SETTLE, QUIET, GRACE = 10.0, 0.35, 0.15  # s: at most, no change for, at least, after an act
LONG_REQUEST = 3.0  # s: a request open longer is a stream or a poll, not the page loading
LONG_LOAD = 30.0  # s: a load that never says it stopped is not waited for again
BUSY_TYPES = {"Document", "XHR", "Fetch", "Script"}  # requests that change the page when they come back
IDLE = 600  # s without a call: the browser closes, and opens again with its tabs when next used
READ_CHARS = 20_000
TAB_IDS = 10_000  # ids each tab of a conversation has before it could reach the next tab's
STEPS = ("click", "fill", "type", "key", "hover", "scroll", "drag", "upload", "wait", "open", "back", "forward",
         "reload", "dialog", "close", "show")
CHANGES = 0.6  # a reply shows the whole page when more of it than this changed
USER_HAS_IT = ("The user has your browser open on their screen (to sign in somewhere for you): it is theirs until "
               "they close it. Tell them, or try again once they have.")
SHOWN_ELSEWHERE = ("Your browser is on the user's screen for a sign-in or a check in another conversation: try "
                   "again in a little while.")
BUSY_ELSEWHERE = ("Your browser is in use in another conversation right now, so it cannot go to the user's screen: "
                  "try show again in a moment.")
SHOWN = ("Your browser is on the user's screen now, as a plain Chrome, at {urls}. Tell them what to do there (sign "
         "in, the check, the payment) and to tell you when they are done. Then go on with any browser tool: it "
         "closes there and you go on here, with what they did (a sign-in stays).")
LEAD_ONLY = ("Only the lead can bring the browser to the user's screen: say in your report what the user should do "
             "there (sign in at ...), or ask the lead with ask_lead.")
GONE = "Your browser closed under the call (it opens again, with your tabs, at your next browser call)."
MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4, "win": 4, "shift": 8}
# key name -> (key, code, Windows virtual key, text)
KEYS = {"enter": ("Enter", "Enter", 13, "\r"), "return": ("Enter", "Enter", 13, "\r"), "tab": ("Tab", "Tab", 9, ""),
        "escape": ("Escape", "Escape", 27, ""), "esc": ("Escape", "Escape", 27, ""),
        "backspace": ("Backspace", "Backspace", 8, ""), "delete": ("Delete", "Delete", 46, ""),
        "space": (" ", "Space", 32, " "), "up": ("ArrowUp", "ArrowUp", 38, ""),
        "down": ("ArrowDown", "ArrowDown", 40, ""), "left": ("ArrowLeft", "ArrowLeft", 37, ""),
        "right": ("ArrowRight", "ArrowRight", 39, ""), "home": ("Home", "Home", 36, ""), "end": ("End", "End", 35, ""),
        "pageup": ("PageUp", "PageUp", 33, ""), "pagedown": ("PageDown", "PageDown", 34, ""),
        "insert": ("Insert", "Insert", 45, ""), **{f"f{n}": (f"F{n}", f"F{n}", 111 + n, "") for n in range(1, 13)}}
KEYS.update({f"arrow{name}": KEYS[name] for name in ("up", "down", "left", "right")})


class BrowserGone(Exception):
    """The browser ended (closed, crashed) under a call."""


class CdpError(Exception):
    pass


def find_browser(configured: str = "") -> Optional[str]:
    """Chrome, else Edge: the one set in the panel, or where their installers put them."""
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    if os.name == "nt":
        roots = [os.environ.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for relative in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
            for root in roots:
                if root and (Path(root) / relative).is_file():
                    return str(Path(root) / relative)
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium"):
            path = Path(f"/Applications/{app}.app/Contents/MacOS/{app}")
            if path.is_file():
                return str(path)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def version_of(command: str) -> str:
    """Chrome's and Edge's version on Windows, from the folder beside the program (nothing started)."""
    try:
        folders = [p.name for p in Path(command).parent.iterdir() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", p.name)]
    except OSError:
        return ""
    return max(folders, key=lambda name: tuple(map(int, name.split("."))), default="")


def site_of(url: str) -> str:
    """The host a call acts on, as rules name it (example.com, localhost)."""
    url = str(url or "").strip()
    if url and not re.match(r"[a-z][a-z0-9+.-]*:", url, re.I):
        url = "https://" + url
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _key(app: str, session: str) -> str:
    return f"{app}/{session}"


def _id(target) -> str:
    """An id as the page knows it: "e5" -> "5"."""
    return str(target or "").strip().lower().lstrip("e")


class Wire:
    """The DevTools protocol over a WebSocket: calls from any thread; events go to ``on_event`` on the reading
    thread, which must never wait for a call."""

    def __init__(self, url: str, on_event):
        from websockets.sync.client import connect

        # entered as a context manager does (websockets 17 warns of a bare connect); closed by close()
        self.socket = connect(url, max_size=None, open_timeout=10, ping_interval=None).__enter__()
        self.on_event = on_event
        self.closed = threading.Event()
        self._send = threading.Lock()
        self._ids = itertools.count(1)
        self._waiting: Dict[int, list] = {}
        threading.Thread(target=self._read, name="browser-wire", daemon=True).start()

    def _read(self) -> None:
        try:
            for raw in self.socket:
                message = json.loads(raw)
                if "id" in message:
                    slot = self._waiting.pop(message["id"], None)
                    if slot:
                        slot[1] = message
                        slot[0].set()
                    continue
                try:
                    self.on_event(message.get("sessionId"), message.get("method", ""), message.get("params") or {})
                except Exception:
                    logger.exception("Browser event %s", message.get("method"))
        except Exception:
            pass
        finally:
            self.closed.set()
            for slot in list(self._waiting.values()):
                slot[0].set()

    def call(self, method: str, params: Optional[dict] = None, session: Optional[str] = None,
             timeout: float = 30.0, until: Optional[Callable[[], bool]] = None) -> Optional[dict]:
        """The result; None when ``until`` came true first (a dialog of the page holds the call)."""
        if self.closed.is_set():
            raise BrowserGone()
        number, slot = next(self._ids), [threading.Event(), None]
        self._waiting[number] = slot
        message = {"id": number, "method": method, "params": params or {}, **({"sessionId": session} if session else {})}
        try:
            with self._send:
                self.socket.send(json.dumps(message))
        except Exception as exc:
            self._waiting.pop(number, None)
            raise BrowserGone() from exc
        deadline = time.monotonic() + timeout
        while not slot[0].wait(0.05 if until else timeout):
            if until and until():
                return None  # its answer comes when the dialog closes, and is dropped
            if time.monotonic() > deadline:
                self._waiting.pop(number, None)
                raise ToolError(f"The browser did not answer in {timeout:.0f} s ({method}).")
        if slot[1] is None:
            raise BrowserGone()
        if "error" in slot[1]:
            raise CdpError(slot[1]["error"].get("message", "the browser refused"))
        return slot[1].get("result") or {}

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass


class Tab:
    """One of a conversation's pages, t1, t2...; it keeps its address while the browser is closed."""

    def __init__(self, owner: str, name: str, url: str = "about:blank", title: str = ""):
        self.owner, self.name, self.url, self.title = owner, name, url, title
        self.lock = threading.RLock()
        self.folder: Optional[Path] = None  # where its downloads go: the conversation's working folder
        # ids given out on its pages so far: a new page goes on from here, so old ids never hit; each tab of a
        # conversation counts from its own ten thousand (t2 from e10001), so an id seen in another tab misses too
        self.next_id = (int(name[1:]) - 1) * TAB_IDS if name[1:].isdigit() else 0
        self.closing = False  # closed by her (or the conversation went): not a page closing itself
        self.restore: Optional[str] = None  # the address it opens again at
        self.news: List[str] = []  # what happened that its next reply tells
        self._reset()

    def _reset(self) -> None:
        """No live page (yet, or the browser closed)."""
        self.target = self.session = self.window = None
        self.context = None  # the brain's isolated world on the page now
        self.document = 0  # the main frame's navigations
        self.loading, self.loading_since, self.crashed = False, 0.0, False
        self.ended = False  # the page closed itself (window.close)
        self.requests: Dict[str, float] = {}
        self.frames: set = set()
        self.dialog: Optional[dict] = None
        self.chooser = threading.Event()
        self.chooser_node: Optional[int] = None
        self.drag: Optional[dict] = None
        self.labels: Dict[str, str] = {}  # id -> what it is ('button "Sign in"'), for approvals and replies
        self.seen: Optional[tuple] = None  # (document, lines) of the latest view: a reply says what changed
        self.pointer = (WINDOW[0] / 2, WINDOW[1] / 3)
        self.picture: Optional[float] = None  # page pixels per pixel of its latest picture

    def held(self) -> bool:
        """A call to the page will not be answered now: a dialog holds it, or the page closed itself."""
        return self.dialog is not None or self.ended

    def event(self, method: str, params: dict) -> None:
        """On the reading thread: what the page did."""
        if method in ("Page.frameStartedLoading", "Page.frameRequestedNavigation", "Page.frameStartedNavigating"):
            if params.get("frameId") == self.target:
                self.loading, self.loading_since = True, time.monotonic()
        elif method == "Page.frameStoppedLoading" and params.get("frameId") == self.target:
            self.loading = False
        elif method == "Page.frameNavigated":
            frame = params["frame"]
            self.frames.add(frame["id"])
            if not frame.get("parentId"):
                self.context, self.url = None, frame.get("url", self.url)
                self.document += 1
                self.requests.clear()
        elif method == "Page.frameAttached":
            self.frames.add(params["frameId"])
        elif method == "Network.requestWillBeSent":
            if params.get("type") in BUSY_TYPES:
                self.requests[params["requestId"]] = time.monotonic()
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.requests.pop(params.get("requestId"), None)
        elif method == "Page.javascriptDialogClosed":
            self.dialog = None
        elif method == "Page.fileChooserOpened":
            self.chooser_node = params.get("backendNodeId")
            self.chooser.set()
        elif method == "Input.dragIntercepted":
            self.drag = params.get("data")
        elif method == "Inspector.targetCrashed":
            self.crashed = True


class Browser:
    def __init__(self, brain):
        self.brain = brain
        self.folder = brain.home / "browser"
        self.profile = self.folder / "profile"
        self.desktop = desktops.DESKTOP if desktops.WINDOWS else None  # where she browses (None: the user's)
        self.user_desktop: Optional[str] = None  # where the user's windows of it go (tests: a hidden one)
        self._lock = threading.RLock()
        self.mode = "off"  # off, hidden (hers, with the protocol), shown (on the user's screen), user (from the panel)
        self.process: Optional[desktops.Process] = None
        self.wire: Optional[Wire] = None
        self.shown_by: Optional[str] = None
        self.owners: Dict[str, dict] = {}  # "app/session" -> {"next", "current", "tabs": {name: Tab}}
        self._by_target: Dict[str, Tab] = {}
        self._by_session: Dict[str, Tab] = {}
        self._downloads: Dict[str, dict] = {}
        self._first: List[str] = []  # the window Chrome starts with, closed once a tab has its own
        self._events: "queue.Queue" = queue.Queue()  # the browser's own events, handled off the reading thread
        self.calls = 0  # browser calls under way
        self.used = time.monotonic()
        self._threads = False  # its own threads, from the first launch on
        self._load()

    # ============== What there is ==============

    def command(self) -> Optional[str]:
        return find_browser(self.brain.config.values()["browser_command"])

    def status(self) -> dict:
        command = self.command() or ""
        with self._lock:
            self._check()
            return {"command": command, "version": version_of(command) if command else "", "mode": self.mode,
                    "profile": str(self.profile), "has_profile": self.profile.exists(),
                    "tabs": sum(len(owner["tabs"]) for owner in self.owners.values())}

    def _load(self) -> None:
        try:
            saved = json.loads((self.folder / "tabs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, owner in saved.items():
            tabs = {}
            for name, tab in owner.get("tabs", {}).items():
                tabs[name] = Tab(key, name, tab.get("url") or "about:blank", tab.get("title", ""))
                tabs[name].restore = tab.get("url") if tab.get("url") not in (None, "", "about:blank") else None
            self.owners[key] = {"next": owner.get("next", len(tabs)), "current": owner.get("current"), "tabs": tabs}

    def _save(self) -> None:
        data = {key: {"next": owner["next"], "current": owner["current"],
                      "tabs": {name: {"url": tab.restore or tab.url, "title": tab.title}
                               for name, tab in owner["tabs"].items()}}
                for key, owner in self.owners.items() if owner["tabs"]}
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            temporary = self.folder / "tabs.json.tmp"
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.folder / "tabs.json")
        except OSError as exc:
            logger.warning("Could not keep the browser's tabs: %s", exc)

    # ============== The process ==============

    def _check(self) -> None:
        """Whether what was started still runs (under the lock)."""
        if self.mode in ("shown", "user") and (not self.process or self.process.poll() is not None):
            self.mode, self.process, self.shown_by = "off", None, None
        elif self.mode == "hidden" and (self.wire.closed.is_set() or self.process.poll() is not None):
            self._gone()

    def _gone(self) -> None:
        if self.wire:
            self.wire.close()
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.mode, self.process, self.wire = "off", None, None
        for owner in self.owners.values():
            for tab in owner["tabs"].values():
                tab.restore = tab.restore or (tab.url if tab.url != "about:blank" else None)
                tab._reset()
        self._by_target.clear()
        self._by_session.clear()
        self._downloads.clear()

    def _ensure(self, key: str) -> None:
        self._check()
        if self.mode == "user":
            raise ToolError(USER_HAS_IT)
        if self.mode == "shown":
            if self.shown_by != key:
                raise ToolError(SHOWN_ELSEWHERE)
            desktops.stop(self.process)  # they are done: it closes there (and keeps their sign-in)
            self.mode, self.process, self.shown_by = "off", None, None
        if self.mode == "off":
            self._launch()

    def _launch(self) -> None:
        command = self.command()
        if not command:
            raise ToolError("There is no Chrome or Edge on this computer, so you have no browser: the user installs "
                            "one, or sets where it is in SentientMilk (Tools > Browser).")
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.folder / "downloads").mkdir(exist_ok=True)
        port = _free_port()
        args = [command, f"--user-data-dir={self.profile}", f"--remote-debugging-port={port}", *FLAGS,
                f"--window-size={WINDOW[0]},{WINDOW[1]}", "about:blank"]
        process = desktops.start(args, desktop=self.desktop, tied=True)
        deadline, url = time.monotonic() + 30, None
        while url is None:
            if process.poll() is not None:
                raise ToolError("Your browser closed as it started: its profile may be open in another Chrome "
                                f"({self.profile}). The user closes that one, or clears your browser's data.")
            if time.monotonic() > deadline:
                process.kill()
                raise ToolError("Your browser did not start in 30 s.")
            try:
                url = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1).json()["webSocketDebuggerUrl"]
            except (requests.RequestException, ValueError, KeyError):
                time.sleep(0.1)
        try:
            wire = Wire(url, self._event)
            wire.call("Target.setDiscoverTargets", {"discover": True})
            wire.call("Browser.setDownloadBehavior", {"behavior": "allowAndName", "eventsEnabled": True,
                                                     "downloadPath": str(self.folder / "downloads")})
            self._first = [t["targetId"] for t in wire.call("Target.getTargets")["targetInfos"] if t["type"] == "page"]
        except Exception as exc:
            process.kill()
            raise ToolError(f"Your browser started but could not be reached: {exc}")
        self.process, self.wire, self.mode = process, wire, "hidden"
        if not self._threads:
            self._threads = True
            threading.Thread(target=self._handle_events, name="browser-events", daemon=True).start()
            threading.Thread(target=self._watch, name="browser-idle", daemon=True).start()

    def _watch(self) -> None:
        """An idle browser closes: its tabs open again at their addresses when next used."""
        while not self.brain.stopping.wait(15):
            with self._lock:
                if self.mode == "hidden" and not self.calls and time.monotonic() - self.used > IDLE:
                    self._close_hidden()

    def _close_hidden(self) -> None:
        if self.mode != "hidden":
            return
        try:
            self.wire.call("Browser.close", timeout=5)
        except Exception:
            pass
        if self.process and not self.process.wait(10):
            self.process.kill()
        self._gone()
        self._save()

    def close(self) -> None:
        """The brain stops: her browser closes (a window on the user's screen is theirs and stays)."""
        with self._lock:
            self._close_hidden()

    def open_for_user(self) -> dict:
        """Her profile in a plain Chrome on the user's screen, nothing attached, to sign in to sites for her."""
        with self._lock:
            self._check()
            if self.mode == "user":
                return self.status()
            if self.calls:
                raise BrainError("busy", "She is using her browser right now: try again in a moment", http_status=409)
            command = self.command()
            if not command:
                raise BrainError("no_browser", "There is no Chrome or Edge on this computer", http_status=409)
            self._close_hidden()
            if self.mode == "shown":
                desktops.stop(self.process)
            self.profile.mkdir(parents=True, exist_ok=True)
            self.process = desktops.start([command, f"--user-data-dir={self.profile}", "--no-first-run",
                                           "--no-default-browser-check"], desktop=self.user_desktop)
            self.mode, self.shown_by = "user", None
            return self.status()

    def clear(self) -> dict:
        """Forget what she signed in to: her profile goes (her tabs keep their addresses)."""
        with self._lock:
            self._check()
            if self.mode in ("shown", "user"):
                raise BrainError("busy", "Her browser is open on your screen: close it first", http_status=409)
            if self.calls:
                raise BrainError("busy", "She is using her browser right now: try again in a moment", http_status=409)
            self._close_hidden()
            deadline = time.monotonic() + 15
            while True:  # Chrome's helper processes let go of its files a moment after it ends
                shutil.rmtree(self.profile, ignore_errors=True)
                if not self.profile.exists() or time.monotonic() > deadline:
                    break
                time.sleep(0.25)
            if self.profile.exists():
                raise BrainError("busy", f"Could not delete {self.profile} (in use)", http_status=409)
            return self.status()

    # ============== Events ==============

    def _event(self, session: Optional[str], method: str, params: dict) -> None:
        """On the reading thread: a page's events at once, the browser's own to the events thread."""
        if not session:
            if method in ("Target.targetDestroyed", "Target.detachedFromTarget"):  # at once: a call may wait on it
                ended = self._by_target.get(params.get("targetId") or "") or self._by_session.get(
                    params.get("sessionId") or "")
                if ended and not ended.closing:
                    ended.ended = True
            self._events.put((method, params))
            return
        tab = self._by_session.get(session)
        if tab is None:
            return
        if method == "Page.javascriptDialogOpening":
            kind, message = params.get("type", "alert"), params.get("message", "")
            if kind in ("alert", "beforeunload"):  # nothing to decide: closed, and told
                tab.news.append(f"The page showed a message: \"{message}\" (closed)." if kind == "alert" else
                                "The page asked to stay as it had changes unsaved: it was left.")
                self._events.put(("answer", {"session": session}))
            else:
                tab.dialog = {"type": kind, "message": message, "default": params.get("defaultPrompt", "")}
        else:
            tab.event(method, params)

    def _handle_events(self) -> None:
        while not self.brain.stopping.is_set():
            try:
                method, params = self._events.get(timeout=1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    self._browser_event(method, params)
            except (BrowserGone, CdpError, ToolError):
                pass
            except Exception:
                logger.exception("Browser event %s", method)

    def _browser_event(self, method: str, params: dict) -> None:
        if self.mode != "hidden":
            return
        if method == "answer":
            self._quietly(self.wire.call, "Page.handleJavaScriptDialog", {"accept": True}, params["session"], 5)
        elif method == "Target.targetCreated":
            info = params["targetInfo"]
            opener = self._by_target.get(info.get("openerId") or "")
            if info.get("type") == "page" and opener and info["targetId"] not in self._by_target:
                self._adopt(opener, info["targetId"])
        elif method == "Target.targetInfoChanged":
            info = params["targetInfo"]
            tab = self._by_target.get(info["targetId"])
            if tab and (tab.url, tab.title) != (info.get("url") or tab.url, info.get("title") or ""):
                tab.url, tab.title = info.get("url") or tab.url, info.get("title") or ""
                self._save()
        elif method == "Target.targetDestroyed":
            tab = self._by_target.get(params["targetId"])
            if tab is not None:
                self._closed_itself(tab)
        elif method == "Browser.downloadWillBegin":
            tab = next((t for t in self._by_target.values()
                        if params.get("frameId") == t.target or params.get("frameId") in t.frames), None)
            name = Path(params.get("suggestedFilename") or "download").name or "download"
            self._downloads[params["guid"]] = {"tab": tab, "name": name, "done": False}
            if tab:
                tab.news.append(f"A download of {name} began.")
        elif method == "Browser.downloadProgress":
            download = self._downloads.get(params["guid"])
            if download and params.get("state") in ("completed", "canceled"):
                download["done"] = True
                self._downloaded(params["guid"], params["state"])

    def _closed_itself(self, tab: Tab) -> None:
        """The page closed itself (a sign-in window that is done): it is no tab of hers any more (under the lock;
        once, from the event or from the call that saw it)."""
        self._by_target.pop(tab.target, None)
        self._by_session.pop(tab.session, None)
        owner = self.owners.get(tab.owner)
        if owner and owner["tabs"].get(tab.name) is tab and not tab.closing:
            del owner["tabs"][tab.name]
            if owner["current"] == tab.name:
                owner["current"] = next(reversed(owner["tabs"]), None)
            for other in owner["tabs"].values():
                other.news.append(f"Tab {tab.name} ({tab.title or tab.url}) closed itself.")
            self._save()

    @staticmethod
    def _quietly(work, *args) -> None:
        try:
            work(*args)
        except Exception:
            pass

    def _downloaded(self, guid: str, state: str) -> None:
        """A finished download goes to the conversation's working folder, under its own name."""
        download = self._downloads.pop(guid, {})
        tab = download.get("tab")
        source = self.folder / "downloads" / guid
        if state != "completed":
            if tab:
                tab.news.append(f"The download of {download['name']} was cancelled.")
            source.unlink(missing_ok=True)
            return
        folder = tab.folder if tab and tab.folder else self.folder / "downloads"
        name = download["name"]
        target, number = folder / name, 1
        while target.exists():
            target = folder / f"{Path(name).stem} ({number}){Path(name).suffix}"
            number += 1
        try:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), target)
        except OSError as exc:
            if tab:
                tab.news.append(f"{name} downloaded but could not be put in {folder}: {exc}")
            return
        if tab:
            tab.news.append(f"Downloaded {name} to {target}.")

    def _adopt(self, opener: Tab, target: str) -> None:
        """A page the opener opened (a link to a new tab, a sign-in window): the conversation's next tab."""
        owner = self.owners.get(opener.owner)
        if owner is None:
            return
        tab = self._new_tab(opener.owner)
        try:
            self._attach(tab, target, resize=False)
        except (CdpError, BrowserGone, ToolError):
            del owner["tabs"][tab.name]
            return
        owner["current"] = tab.name
        tab.folder = opener.folder
        opener.news.append(f"It opened a new tab, {tab.name}: the tab your next calls go to.")
        self._save()

    # ============== Tabs ==============

    def _owner(self, key: str) -> dict:
        return self.owners.setdefault(key, {"next": 0, "current": None, "tabs": {}})

    def _new_tab(self, key: str) -> Tab:
        owner = self._owner(key)
        owner["next"] += 1
        tab = Tab(key, f"t{owner['next']}")
        owner["tabs"][tab.name] = tab
        return tab

    def _attach(self, tab: Tab, target: str, resize: bool = True) -> None:
        wire = self.wire
        session = wire.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        tab.target, tab.session = target, session
        self._by_target[target], self._by_session[session] = tab, tab
        wire.call("Page.enable", session=session)
        wire.call("Network.enable", session=session)
        wire.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, session)  # each page is the one in front
        tab.window = wire.call("Browser.getWindowForTarget", {"targetId": target})["windowId"]
        if resize:
            wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {"windowState": "normal"}})
            wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {
                "left": 0, "top": 0, "width": WINDOW[0], "height": WINDOW[1]}})

    def _live(self, tab: Tab) -> None:
        """A page for the tab (under the lock); its address comes back in ``using``, outside the lock."""
        if tab.session and tab.target in self._by_target and not tab.crashed:
            return
        if tab.target:  # a page that crashed: a new one in its place
            self._by_target.pop(tab.target, None)
            self._by_session.pop(tab.session, None)
            self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})
            tab.restore = tab.restore or (tab.url if tab.url != "about:blank" else None)
        tab._reset()
        target = self.wire.call("Target.createTarget", {"url": "about:blank", "newWindow": True})["targetId"]
        self._attach(tab, target)
        for first in self._first:
            self._quietly(self.wire.call, "Target.closeTarget", {"targetId": first})
        self._first = []

    @contextlib.contextmanager
    def using(self, ctx, name: str = "", create: bool = False, new: bool = False):
        """The conversation's tab ``name`` (or its current one; ``new``: a new one), live and held for a call."""
        from .toolkits.files import cwd

        key = _key(ctx.app, ctx.session)
        name = self._name(name)
        with self._lock:
            self.calls += 1
            self.used = time.monotonic()
        try:
            with self._lock:
                self._ensure(key)
                owner = self._owner(key)
                if new:
                    tab = self._new_tab(key)
                elif name:
                    tab = owner["tabs"].get(name)
                    if tab is None:
                        raise ToolError(f"There is no tab {name}. {self._tabs_line(key) or 'You have no tabs.'}")
                else:
                    tab = owner["tabs"].get(owner["current"] or "")
                    if tab is None:
                        if not create:
                            raise ToolError("You have no tab open: open a page with browser_open.")
                        tab = self._new_tab(key)
                if tab.ended:  # it closed itself since her last call
                    self._closed_itself(tab)
                    raise ToolError(f"Tab {tab.name} closed itself. {self._tabs_line(key) or 'You have no tabs.'}")
                owner["current"] = tab.name
                tab.folder = cwd(ctx)
                self._live(tab)
                if any(t.window == tab.window for t in self._by_target.values() if t is not tab):
                    self._quietly(self.wire.call, "Target.activateTarget", {"targetId": tab.target})
                self._save()
            with tab.lock:
                if tab.restore:
                    url, tab.restore = tab.restore, None
                    self._navigate(tab, url)
                yield tab
        except BrowserGone:
            with self._lock:
                self._check()
            raise ToolError(GONE)
        except CdpError as exc:
            raise ToolError(f"The browser refused: {exc}")
        finally:
            with self._lock:
                self.calls -= 1
                self.used = time.monotonic()

    @staticmethod
    def _name(name: str) -> str:
        name = str(name or "").strip().lower()
        return f"t{name}" if name.isdigit() else name

    def _tabs_line(self, key: str, besides: Optional[Tab] = None) -> str:
        tabs = [t for t in self._owner(key)["tabs"].values() if t is not besides]
        if not tabs:
            return ""
        return ("Your tabs: " if besides is None else "Your other tabs: ") + "; ".join(
            f"{t.name} {t.title or t.url}" for t in tabs)

    def forget(self, app: str, session: str) -> None:
        """A conversation (or agent) is gone: its tabs close."""
        with self._lock:
            owner = self.owners.pop(_key(app, session), None)
            if not owner:
                return
            self._save()
            for tab in owner["tabs"].values():
                tab.closing = True
                if tab.target and self.mode == "hidden":
                    self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})

    def seen(self, run: dict, arguments: dict) -> dict:
        """A browser call as the rules and the user see it: the site it acts on, and what each id is."""
        owner = self.owners.get(_key(run["app"], run["session"])) or {"tabs": {}, "current": None}
        tab = owner["tabs"].get(self._name(arguments.get("tab")) or owner["current"] or "")
        if "url" in arguments:
            site = site_of(arguments.get("url"))
        else:
            site = site_of(tab.restore or tab.url) if tab else ""
        shown = {**arguments, "site": site}
        if isinstance(arguments.get("steps"), list):
            shown["steps"] = [{**step, **({"about": tab.labels[_id(step["target"])]}
                                          if tab and _id(step.get("target")) in tab.labels else {})}
                              if isinstance(step, dict) else step for step in arguments["steps"]]
        return shown

    # ============== Pages ==============

    def _eval(self, tab: Tab, expression: str, timeout: float = 30.0, value: bool = True):
        """``expression`` in the brain's own world of the page (installed there first); None when a dialog of
        the page opened meanwhile."""
        if tab.ended:
            raise ToolError(f"Tab {tab.name} closed itself.")
        if tab.dialog:
            raise ToolError(self._dialog_line(tab))
        for _ in range(4):
            try:
                if tab.context is None:
                    world = self.wire.call("Page.createIsolatedWorld", {"frameId": tab.target, "worldName": WORLD},
                                           tab.session)
                    tab.context = world["executionContextId"]
                    installed = self.wire.call("Runtime.evaluate", {
                        "expression": f"({PAGE_JS})({tab.next_id})", "contextId": tab.context,
                        "returnByValue": True}, tab.session, until=tab.held)
                    if installed is None:
                        if tab.ended:
                            raise ToolError(f"Tab {tab.name} closed itself.")
                        return None
                    tab.next_id = max(tab.next_id, installed.get("result", {}).get("value") or 0)
                reply = self.wire.call("Runtime.evaluate", {"expression": expression, "contextId": tab.context,
                                                            "returnByValue": value, "awaitPromise": True},
                                       tab.session, timeout, until=tab.held)
            except CdpError as exc:  # the page changed under the call: its new document gets the world again
                if tab.ended or "session" in str(exc).lower():
                    tab.ended = True
                    raise ToolError(f"Tab {tab.name} closed itself.")
                if any(word in str(exc).lower() for word in ("context", "frame", "target")):
                    tab.context = None
                    time.sleep(0.1)
                    continue
                raise ToolError(f"The page could not be read: {exc}")
            if reply is None:
                if tab.ended:
                    raise ToolError(f"Tab {tab.name} closed itself.")
                return None
            if "exceptionDetails" in reply:
                details = reply["exceptionDetails"]
                text = (details.get("exception") or {}).get("description") or details.get("text", "")
                if "__milk" in text:  # a new document came between the two calls
                    tab.context = None
                    continue
                raise ToolError(f"The page could not be read: {text.splitlines()[0] if text else 'an error'}")
            return reply["result"].get("value") if value else reply["result"]
        raise ToolError("The page kept changing while it was read: try again.")

    def _input(self, tab: Tab, method: str, params: dict) -> None:
        """An event as from the user's own mouse or keyboard; a dialog it opens ends the wait for it."""
        if tab.ended:
            return
        try:
            self.wire.call(method, params, tab.session, until=tab.held)
        except CdpError as exc:
            if "session" not in str(exc).lower():
                raise
            tab.ended = True  # the click closed the page (a sign-in window that is done)

    def _settle(self, tab: Tab, budget: float = SETTLE, after: bool = True) -> bool:
        """Until the page has loaded and stopped changing (False: still busy after ``budget`` seconds). ``after``
        an act it waits at least QUIET too: what the act started late (a timer, then a request) shows by then."""
        start = time.monotonic()
        time.sleep(GRACE)
        while True:
            now = time.monotonic()
            if tab.dialog or tab.crashed or tab.ended or not tab.session:
                return True
            for request, since in list(tab.requests.items()):
                if now - since > 60:
                    tab.requests.pop(request, None)
            downloading = any(d["tab"] is tab and not d["done"] for d in list(self._downloads.values()))
            busy = (tab.loading and now - tab.loading_since < LONG_LOAD) or downloading or \
                any(now - since < LONG_REQUEST for since in list(tab.requests.values()))
            if not busy and (not after or now - start >= QUIET):
                try:
                    quiet = self._eval(tab, "__milk.changed()", timeout=3)
                    if quiet is None or quiet / 1000 >= QUIET:
                        return True
                except ToolError:
                    pass
            if now - start > budget:
                return False
            time.sleep(0.05)

    def _navigate(self, tab: Tab, url: str) -> str:
        if not re.match(r"[a-z][a-z0-9+.-]*:", url, re.I):
            url = "https://" + url
        tab.loading, tab.loading_since = True, time.monotonic()
        try:
            reply = self.wire.call("Page.navigate", {"url": url}, tab.session, timeout=60, until=tab.held) or {}
        except CdpError as exc:
            tab.loading = False
            raise ToolError(f"{url} could not be opened: {exc}")
        error = reply.get("errorText")
        if error and error != "net::ERR_ABORTED":  # aborted: it became a download, or the page went on elsewhere
            tab.loading = False
            raise ToolError(f"{url} could not be opened ({error}).")
        return "" if self._settle(tab, 30) else "The page is still loading."

    def _view(self, tab: Tab, find: str = "", part: str = "") -> dict:
        data = self._eval(tab, f"__milk.view({json.dumps({'find': find, 'part': _id(part)})})")
        if data is None:
            return {"text": "", "labels": {}, "title": tab.title, "url": tab.url, "next": tab.next_id}
        if data.get("gone"):
            raise ToolError(f"{part} is not on the page any more: view it again.")
        tab.next_id = max(tab.next_id, data["next"])
        tab.labels.update(data["labels"])
        tab.title, tab.url = data["title"], data["url"]
        return data

    def _head(self, tab: Tab) -> List[str]:
        lines = [f"{tab.name} · {tab.title or '(no title)'} · {tab.url}"]
        lines += [f"Meanwhile: {news}" for news in tab.news]
        tab.news = []
        if tab.dialog:
            lines.append(self._dialog_line(tab))
        return lines

    @staticmethod
    def _dialog_line(tab: Tab) -> str:
        dialog = tab.dialog or {}
        return (f"A dialog of the page waits ({dialog.get('type')}): \"{dialog.get('message', '')}\". Answer it with "
                "the step dialog (accept: true or false; text: a prompt's answer): the page does nothing until then.")

    def _whole(self, tab: Tab, data: dict, note: str = "") -> str:
        """The page as a whole, for open and view."""
        tab.seen = (tab.document, data["text"].splitlines())
        lines = self._head(tab) + ([note] if note else []) + [data["text"] or "(The page shows nothing.)"]
        other = self._tabs_line(tab.owner, besides=tab)
        return "\n".join(lines + ([other] if other else []))

    def _changes(self, tab: Tab, document: int, data: dict) -> str:
        """What an act changed: the page as a whole when it is another page or most of it changed."""
        lines = data["text"].splitlines()
        before = tab.seen
        tab.seen = (tab.document, lines)
        if not before or before[0] != document or tab.document != document:
            return "The page now:\n" + (data["text"] or "(The page shows nothing.)")
        changed = []
        for kind, a, b, c, d in difflib.SequenceMatcher(None, before[1], lines, autojunk=False).get_opcodes():
            if kind != "equal":
                changed += ["- " + line for line in before[1][a:b]] + ["+ " + line for line in lines[c:d]]
        if not changed:
            return "Nothing changed on the page."
        if len(changed) > CHANGES * max(len(lines), 1):
            return "The page now:\n" + data["text"]
        return "Changed (+ new, - gone):\n" + "\n".join(changed)

    # ============== The tools ==============

    def open(self, ctx, url: str, new_tab: bool = False) -> str:
        url = str(url or "").strip()
        if not url:
            raise ToolError("url is empty: give the address to open (https://...).")
        with self.using(ctx, create=True, new=new_tab) as tab:
            note = self._navigate(tab, url)
            return self._whole(tab, self._view(tab), note)

    def view(self, ctx, tab: str = "", find: str = "", part: str = "", picture: bool = False) -> ToolResult:
        with self.using(ctx, tab) as page:
            data = self._view(page, find=find, part=part)
            if find or part:
                text = data["text"] or (f"Nothing on the page has {find!r}." if find else "(It shows nothing.)")
                text = "\n".join(self._head(page) + [text])
            else:
                text = self._whole(page, data)
            if not picture:
                return ToolResult(text)
            image, size = self._picture(page)
            return ToolResult(text + f"\nThe picture is the tab's window as it is now ({size} pixels): point at what "
                                     "has no id with \"x,y\" in its pixels as a step's target.", images=[image])

    def _picture(self, tab: Tab):
        shot = self.wire.call("Page.captureScreenshot", {"format": "jpeg", "quality": 90}, tab.session)
        image = transport.encode_image("data:image/jpeg;base64," + shot["data"],
                                       self.brain.config.values()["image_pixels"])
        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[1]))) as picture:
            width, height = picture.size
        tab.picture = (self._eval(tab, "innerWidth") or width) / width
        return image, f"{width}x{height}"

    def read(self, ctx, tab: str = "", offset: int = 0) -> str:
        with self.using(ctx, tab) as page:
            text = self._eval(page, "__milk.read()") or ""
            start = max(0, int(offset or 0))
            part = text[start:start + READ_CHARS] or "(Nothing to read here.)"
            if start + READ_CHARS < len(text):
                part += (f"\n\n[Characters {start}-{start + READ_CHARS} of {len(text)}. Go on with "
                         f"offset={start + READ_CHARS}.]")
            return "\n".join(self._head(page) + [part])

    def script(self, ctx, code: str, tab: str = "") -> str:
        with self.using(ctx, tab) as page:
            document = page.document
            try:  # in the page's own world, so it reaches the page's variables
                reply = self.wire.call("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                                            "awaitPromise": True, "replMode": True,
                                                            "userGesture": True}, page.session, 60, until=page.held)
            except CdpError as exc:
                raise ToolError(f"The script could not run: {exc}")
            if reply is None:
                return "\n".join(self._head(page))
            if "exceptionDetails" in reply:
                details = reply["exceptionDetails"]
                raise ToolError("The script failed: " + ((details.get("exception") or {}).get("description")
                                                          or details.get("text", "")))
            result = reply["result"]
            value = result.get("value", result.get("description", result.get("type")))
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1, default=str)
            self._settle(page, 5)
            if page.document != document:
                text += f"\n(The page changed: it is {page.url} now. View it before you act.)"
            return "\n".join(self._head(page)[1:] + [text])

    def act(self, ctx, steps: list, tab: str = "") -> str:
        if not isinstance(steps, list) or not steps:
            raise ToolError("steps is empty: give the steps to do, e.g. [{\"action\": \"click\", \"target\": \"e5\"}].")
        notes: List[str] = []
        with self.using(ctx, tab) as page:
            if page.seen is None and not page.dialog:  # nothing to compare with yet: what it shows now
                page.seen = (page.document, self._view(page)["text"].splitlines())
            document, site = page.document, site_of(page.url)
            for number, step in enumerate(steps, 1):
                step = step if isinstance(step, dict) else {"action": str(step)}
                action = str(step.get("action", "")).strip().lower()
                target = step.get("target")
                said = f"{number}. {action}" + (f" {target}" if target else "") + \
                    (f" ({page.labels[_id(target)]})" if target and _id(target) in page.labels else "")
                rest = f"Steps {number + 1}-{len(steps)} did not run" if number < len(steps) else ""
                try:
                    if action == "show":
                        return "\n".join(notes + [f"{said}: " + self.show(ctx, page)])
                    if action == "close":
                        notes.append(f"{said}: " + self._close_tab(page))
                        return "\n".join(notes + ([rest + "."] if rest else []) + self._after_close(page))
                    note = self._step(ctx, page, action, step, last=number == len(steps))
                except ToolError as exc:
                    notes.append(f"{said}: {exc}")
                    if rest:
                        notes.append(rest + ".")
                    break
                notes.append(f"{said}: {note or 'done'}")
                coming = steps[number] if number < len(steps) and isinstance(steps[number], dict) else {}
                if page.dialog and str(coming.get("action", "")).strip().lower() != "dialog":  # unless she answers it
                    if rest:
                        notes.append(rest + ": the dialog waits.")
                    break
                if page.ended:
                    if rest:
                        notes.append(rest + ".")
                    break
                if rest and site_of(page.url) != site:  # what was allowed was for the site it started on
                    notes.append(f"{rest}: the tab went to another site ({site_of(page.url)}), so act again there.")
                    break
            if page.ended:
                with self._lock:
                    self._closed_itself(page)
                return "\n".join(notes + [f"Tab {page.name} closed itself."] + self._after_close(page))
            if page.dialog:
                return "\n".join(self._head(page) + notes)
            data = self._view(page)
            return "\n".join(self._head(page) + notes + [self._changes(page, document, data)])

    def _after_close(self, closed: Tab) -> List[str]:
        with self._lock:
            owner = self._owner(closed.owner)
            current = owner["tabs"].get(owner["current"] or "")
        return [f"Now in {current.name} · {current.title or current.url}"] if current else ["You have no tab open now."]

    def _close_tab(self, tab: Tab) -> str:
        with self._lock:
            owner = self._owner(tab.owner)
            owner["tabs"].pop(tab.name, None)
            tab.closing = True
            if owner["current"] == tab.name:
                owner["current"] = next(reversed(owner["tabs"]), None)
            self._save()
            if tab.target and self.mode == "hidden":
                self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})
        return f"{tab.name} closed"

    def show(self, ctx, tab: Tab) -> str:
        """Her browser on the user's screen (plain, nothing attached) at the conversation's pages."""
        if ctx.run["kind"] != "turn":
            raise ToolError(LEAD_ONLY)
        key = _key(ctx.app, ctx.session)
        with self._lock:
            if self.calls > 1:
                raise ToolError(BUSY_ELSEWHERE)
            owner = self._owner(key)
            urls = [tab.url] + [t.url for t in owner["tabs"].values() if t is not tab]
            urls = [url for url in urls if url and url != "about:blank"]
            command = self.command()
            self._close_hidden()
            self.process = desktops.start([command, f"--user-data-dir={self.profile}", "--no-first-run",
                                           "--no-default-browser-check", *urls], desktop=self.user_desktop)
            self.mode, self.shown_by = "shown", key
        return SHOWN.format(urls=", ".join(urls) or "a new tab")

    # ============== Steps ==============

    def _point(self, tab: Tab, target, hit_test: bool = True, shown: bool = True) -> dict:
        """Where a target is (an id, brought into view first; or "x,y" in the tab's latest picture)."""
        target = str(target or "").strip()
        if not target:
            raise ToolError("This step needs a target: an id from the view (e5) or a point \"x,y\" in a picture.")
        point = re.fullmatch(r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?", target)
        if point:
            if tab.picture is None:
                raise ToolError("A point is in a picture of the tab: view it with picture=true first, or use an id.")
            x, y = float(point.group(1)) * tab.picture, float(point.group(2)) * tab.picture
            found = self._eval(tab, f"__milk.at({x}, {y})") or {}
            tab.next_id = max(tab.next_id, found.get("next", 0))
            return {"x": x, "y": y, "point": True, "label": found.get("label") or "nothing there"}
        if not re.fullmatch(r"e?\d+", target, re.I):
            raise ToolError(f"{target!r} is not an id: ids look like e5 (from the latest view of this tab).")
        found = self._eval(tab, f"__milk.locate({_id(target)}, {json.dumps(hit_test)})")
        if found is None:
            raise ToolError(self._dialog_line(tab))
        if found.get("gone"):
            raise ToolError(f"{target} is not on the page (any more): the page changed, so use the ids of its latest "
                            "view (browser_view).")
        tab.next_id = max(tab.next_id, found.get("next", 0))
        if shown and found.get("hidden"):
            raise ToolError(f"{target} ({found['label']}) has no size on the page: it is not shown now.")
        if found.get("covered"):
            raise ToolError(f"{target} is covered by {found['covered']} (a banner or a dialog on top of it): close or "
                            "answer that first.")
        if found.get("disabled"):
            raise ToolError(f"{target} ({found['label']}) is disabled now: the page does not take it yet.")
        return found

    def _move(self, tab: Tab, x: float, y: float, buttons: int = 0) -> None:
        """The pointer goes there as a hand would: a few steps along the way."""
        start_x, start_y = tab.pointer
        distance = math.hypot(x - start_x, y - start_y)
        steps = max(3, min(12, int(distance / 60)))
        for index in range(1, steps + 1):
            ease = 0.5 - 0.5 * math.cos(index / steps * math.pi)
            self._input(tab, "Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": start_x + (x - start_x) * ease, "y": start_y + (y - start_y) * ease,
                "buttons": buttons, **({"button": "left"} if buttons else {})})
        tab.pointer = (x, y)

    def _click(self, tab: Tab, place: dict, button: str = "left", count: int = 1) -> None:
        x, y = place["x"], place["y"]
        self._move(tab, x, y)
        mask = {"left": 1, "right": 2, "middle": 4}[button]
        for clicks in range(1, count + 1):
            for kind in ("mousePressed", "mouseReleased"):
                self._input(tab, "Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": button,
                                                              "buttons": mask if kind == "mousePressed" else 0,
                                                              "clickCount": clicks})
                if tab.dialog:
                    return

    def _type(self, tab: Tab, text: str) -> None:
        for char in text:
            if tab.dialog:
                return
            if char == "\n":
                self._keys(tab, "enter")
                continue
            key = {"key": char, "text": char, "unmodifiedText": char}
            if char.isascii() and char.isalnum():
                key.update(code=("Digit" if char.isdigit() else "Key") + char.upper(),
                           windowsVirtualKeyCode=ord(char.upper()))
            self._input(tab, "Input.dispatchKeyEvent", {"type": "keyDown", **key})
            self._input(tab, "Input.dispatchKeyEvent", {"type": "keyUp", "key": char,
                                                        **({"code": key["code"]} if "code" in key else {})})

    def _keys(self, tab: Tab, text: str) -> None:
        chords = str(text or "").split()
        if not chords:
            raise ToolError("key needs text: the keys to press, e.g. Enter, Tab, Escape, ctrl+a, shift+Tab.")
        for chord in chords:
            parts = chord.split("+")
            modifiers = sum(MODIFIERS.get(p.lower(), 0) for p in parts[:-1])
            name = parts[-1]
            if any(p.lower() not in MODIFIERS for p in parts[:-1]) or not name:
                raise ToolError(f"{chord!r} is not a key: name keys like Enter, Tab, Escape, ctrl+a, shift+Tab.")
            if name.lower() in KEYS:
                key, code, vk, typed = KEYS[name.lower()]
            elif len(name) == 1:
                key, typed = (name.upper() if modifiers & 8 else name), name
                code = ("Digit" if name.isdigit() else "Key") + name.upper() if name.isascii() and name.isalnum() else ""
                vk = ord(name.upper()) if name.isascii() else 0
            else:
                raise ToolError(f"{name!r} is not a key: Enter, Tab, Escape, Backspace, Delete, Space, arrows "
                                "(up, down...), Home, End, PageUp, PageDown, F1-F12, or one character.")
            plain = typed and not modifiers & 7  # no ctrl, alt or meta: it types
            down = {"type": "keyDown" if plain else "rawKeyDown", "key": key, "code": code,
                    "windowsVirtualKeyCode": vk, "modifiers": modifiers}
            if plain:
                down.update(text=typed, unmodifiedText=typed)
            self._input(tab, "Input.dispatchKeyEvent", down)
            self._input(tab, "Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code,
                                                        "windowsVirtualKeyCode": vk, "modifiers": modifiers})

    def _step(self, ctx, tab: Tab, action: str, step: dict, last: bool = True) -> str:
        target, text = step.get("target"), step.get("text")
        text = "" if text is None else str(text)
        document = tab.document
        note = ""
        if action == "click":
            place = self._point(tab, target)
            button = str(step.get("button") or "left").lower()
            self._click(tab, place, button if button in ("left", "right", "middle") else "left",
                        2 if step.get("double") else 1)
            note = f"at {place['label']}" if place.get("point") else ""
        elif action == "fill":
            note = self._fill(tab, _id(target), self._point(tab, target), text)
        elif action in ("type", "key"):
            if target:
                self._click(tab, self._point(tab, target))
            if action == "type":
                self._type(tab, text)
            else:
                self._keys(tab, text)
        elif action == "hover":
            place = self._point(tab, target)
            self._move(tab, place["x"], place["y"])
        elif action == "scroll":
            note = self._scroll(tab, target, text or "down", step.get("amount"))
        elif action == "drag":
            self._drag(tab, target, step.get("to"))
        elif action == "upload":
            note = self._upload(ctx, tab, target, step.get("files") or ([text] if text else []))
        elif action == "wait":
            return self._wait(ctx, tab, text, step.get("amount"))
        elif action == "open":
            note = self._navigate(tab, text or str(target or ""))
        elif action in ("back", "forward"):
            history = self.wire.call("Page.getNavigationHistory", session=tab.session)
            index = history["currentIndex"] + (-1 if action == "back" else 1)
            if not 0 <= index < len(history["entries"]):
                raise ToolError(f"There is nothing to go {action} to in this tab.")
            tab.loading, tab.loading_since = True, time.monotonic()
            self.wire.call("Page.navigateToHistoryEntry", {"entryId": history["entries"][index]["id"]}, tab.session)
        elif action == "reload":
            tab.loading, tab.loading_since = True, time.monotonic()
            self.wire.call("Page.reload", session=tab.session)
        elif action == "dialog":
            if not tab.dialog:
                raise ToolError("No dialog is open.")
            accept = step.get("accept", True) not in (False, "false", "no", 0)
            self.wire.call("Page.handleJavaScriptDialog", {"accept": accept, **({"promptText": text} if text else {})},
                           tab.session)
            tab.dialog = None
            note = "accepted" if accept else "dismissed"
        else:
            raise ToolError(f"There is no step {action!r}. Steps: {', '.join(STEPS)}.")
        if not self._settle(tab, after=last or action not in ("fill", "hover", "scroll")):
            note = (note + "; " if note else "") + "the page is still busy (loading)"
        if tab.document != document:
            note = (note + "; " if note else "") + f"the page went to {tab.url}"
        return note

    def _fill(self, tab: Tab, element: str, place: dict, text: str) -> str:
        if place.get("select") or place.get("setter"):
            chosen = self._eval(tab, f"__milk.choose({element}, {json.dumps(text)})")
            if chosen is None:
                return "a dialog opened"
            if chosen.get("error"):
                raise ToolError(chosen["error"])
            return f"it shows \"{chosen['value']}\""
        if place.get("check"):
            wanted = text.strip().lower() not in ("false", "no", "off", "0", "unchecked", "not checked")
            if wanted != place.get("checked"):
                self._click(tab, place)
            return "checked" if wanted else "not checked"
        if place.get("file"):
            raise ToolError("It is a file input: give it files with the step upload (files: [paths]).")
        if not place.get("editable"):
            raise ToolError(f"It is {place['label']}, not a field to fill: click it, or fill a field.")
        self._click(tab, place)
        if tab.dialog or not self._eval(tab, f"__milk.focus({element})"):  # its text selected: typing replaces it
            return ""
        if text:
            self._type(tab, text)
        else:
            self._keys(tab, "Delete")
        shown = self._eval(tab, f"__milk.value({element})")
        if shown is not None and shown.replace("\r", "") != text and not (
                place.get("type") == "password" and len(shown) == len(text)):
            return f"it shows \"{shown[:200]}\" (the page changed what was typed)"
        return ""

    def _scroll(self, tab: Tab, target, direction: str, amount) -> str:
        direction = direction.strip().lower()
        element = _id(target) if target else ""
        if direction in ("top", "bottom"):
            moved = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, {json.dumps(direction)})") or {}
        elif direction in ("down", "up"):
            try:
                pages = float(amount or 1) * (1 if direction == "down" else -1)
            except (TypeError, ValueError):
                raise ToolError("amount is how many screens to scroll: a number such as 1 or 0.5.")
            if element:
                place = self._point(tab, target, hit_test=False)
                x, y = place["x"], place["y"]
            else:
                x, y = self._eval(tab, "[innerWidth / 2, innerHeight / 2]") or (WINDOW[0] / 2, WINDOW[1] / 2)
            before = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, 0)") or {}
            height = self._eval(tab, "innerHeight") or WINDOW[1]
            self._move(tab, x, y)
            self._input(tab, "Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0,
                                                          "deltaY": pages * height * 0.85})
            after, still = before, 0
            for _ in range(30):  # until it stops moving (smooth scrolling takes a moment)
                time.sleep(0.05)
                now = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, 0)") or after
                still = still + 1 if now.get("at") == after.get("at") else 0
                after = now
                if still >= 3:
                    break
            moved = {"moved": (after.get("at") or 0) - (before.get("at") or 0), "at": after.get("at"),
                     "end": after.get("end"), "gone": after.get("gone")}
        else:
            raise ToolError("scroll takes text down, up, top or bottom (amount: how many screens, 1 if not given).")
        if moved.get("gone"):
            raise ToolError(f"{target} is not on the page any more: view it again.")
        if not moved.get("moved"):
            return "it did not move (it is at its end, or that part does not scroll)"
        return f"moved {abs(moved['moved'])} px, now at {moved['at']} of {max(moved['end'] or 0, 0)}"

    def _drag(self, tab: Tab, target, to) -> None:
        if not to:
            raise ToolError("drag needs `to`: where it ends (an id or a point).")
        start, end = self._point(tab, target), self._point(tab, str(to), hit_test=False)
        self.wire.call("Input.setInterceptDrags", {"enabled": True}, tab.session)
        tab.drag = None
        try:
            self._move(tab, start["x"], start["y"])
            self._input(tab, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": start["x"], "y": start["y"],
                                                          "button": "left", "buttons": 1, "clickCount": 1})
            self._move(tab, end["x"], end["y"], buttons=1)
            time.sleep(0.05)
            if tab.drag:  # the page's own drag and drop: it goes on as the protocol's
                for kind in ("dragEnter", "dragOver", "drop"):
                    self._input(tab, "Input.dispatchDragEvent", {"type": kind, "x": end["x"], "y": end["y"],
                                                                 "data": tab.drag})
            self._input(tab, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end["x"], "y": end["y"],
                                                          "button": "left", "buttons": 0, "clickCount": 1})
        finally:
            self._quietly(self.wire.call, "Input.setInterceptDrags", {"enabled": False}, tab.session)

    def _upload(self, ctx, tab: Tab, target, files) -> str:
        from .toolkits.files import resolve

        if isinstance(files, str):
            files = [files]
        if not isinstance(files, list) or not files:
            raise ToolError("upload needs files: the paths of the files to give the page.")
        paths = [resolve(ctx, str(path)) for path in files]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise ToolError(f"No such file: {', '.join(missing)}")
        place = self._point(tab, target, hit_test=False, shown=False)
        if place.get("file"):
            handle = self._eval(tab, f"__milk.element({_id(target)})", value=False) or {}
            if not handle.get("objectId"):
                raise ToolError(f"{target} is not on the page any more: view it again.")
            self.wire.call("DOM.setFileInputFiles", {"files": [str(p) for p in paths], "objectId": handle["objectId"]},
                           tab.session)
        else:  # a button of the page's that opens the file picker: the picker is answered instead of shown
            tab.chooser.clear()
            self.wire.call("Page.setInterceptFileChooserDialog", {"enabled": True}, tab.session)
            try:
                self._click(tab, self._point(tab, target))
                if not tab.chooser.wait(5):
                    raise ToolError(f"{target} opened no file picker: find the page's file input (browser_view "
                                    "find=\"file input\") and upload there.")
                self.wire.call("DOM.setFileInputFiles", {"files": [str(p) for p in paths],
                                                         "backendNodeId": tab.chooser_node}, tab.session)
            finally:
                self._quietly(self.wire.call, "Page.setInterceptFileChooserDialog", {"enabled": False}, tab.session)
        return "gave it " + ", ".join(path.name for path in paths)

    def _wait(self, ctx, tab: Tab, text: str, amount) -> str:
        try:
            seconds = float(amount or (20 if text else 2))
        except (TypeError, ValueError):
            raise ToolError("amount is how many seconds to wait at most: a number.")
        if not text:
            if ctx.pause(seconds):
                return f"stopped waiting: {ctx.interruption()}"
            self._settle(tab)
            return f"waited {seconds:g} s"
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if tab.dialog:
                return "a dialog opened"
            if self._eval(tab, f"__milk.has({json.dumps(text)})", timeout=5):
                self._settle(tab, 3)
                return f"\"{text}\" shows"
            if ctx.pause(0.25):
                return f"stopped waiting: {ctx.interruption()}"
        raise ToolError(f"\"{text}\" did not show in {seconds:g} s.")
