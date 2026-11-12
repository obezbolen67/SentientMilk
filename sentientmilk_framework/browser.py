"""Her browser: a Chrome (or Edge) of her own, driven over the DevTools protocol, for the web as a person uses it.

It is the real browser with a profile of its own (``browser/profile``): sites see the Chrome they see from the
user, on the user's connection, and what she signs in to stays. It runs out of sight (headless, as people say:
on Windows on the brain's hidden desktop, desktops.py, in ordinary windows the user never sees) or on the user's
screen, where they watch her (``browser_headless``, and browser_open's ``headless`` for the moment); either way it
is driven the same, whether its windows are in front, behind others or minimized, and it ends with the brain.
Measured on Chrome 157 (2026-11-12): a fixed debugging port leaves ``navigator.webdriver`` false (port 0 and the
pipe set it, and the switch that hides it adds a warning bar). So: a fixed port on 127.0.0.1, ordinary windows,
Runtime never enabled but for a moment to read the console (the page's world is left alone: the brain reads pages
in an isolated world of its own, browser_page.js, and each frame of another site in one of its own), the pointer
moves before clicks and typing goes key by key.

Each chat (and each agent or task) has tabs of its own, t1, t2..., each in a window of its own so that every
page renders as the one in front. Tabs outlive the browser: it closes when idle out of sight and when the brain
stops, and a tab opens again at its address (and session cookies come back) when it is next used. When a site
needs the user (a sign-in, a check that she is human), the step ``show`` puts the browser on the user's screen
and she goes on there once they are done. See docs/architecture.md, 6.7.
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
FLAGS = ["--no-first-run", "--no-default-browser-check", "--hide-crash-restore-bubble", "--no-startup-window",
         "--disable-backgrounding-occluded-windows"]  # windows on top of each other all render
COOKIES = "sentientmilk-session-cookies.json"  # in the profile: session cookies kept while the browser is closed
COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "priority", "sourceScheme",
                 "sourcePort", "partitionKey"}
AUTO_ATTACH = {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True, "filter": [{"type": "iframe"}]}
FRAME = re.compile(r"^( *)⟦frame (\d+)⟧$", re.M)  # where a frame of another site goes in a view
FRAME_GONE = "That frame is not on the page any more: view the page again."
SAVES = {".pdf": "a PDF", ".png": "a picture", ".jpg": "a picture", ".jpeg": "a picture", ".webp": "a picture",
         ".html": "its HTML", ".htm": "its HTML", ".mhtml": "a web archive"}
SETTLE, QUIET, GRACE = 10.0, 0.35, 0.15  # s: at most, no change for, at least, after an act
LONG_REQUEST = 3.0  # s: a request open longer is a stream or a poll, not the page loading
LONG_LOAD = 30.0  # s: a load that never says it stopped is not waited for again
BUSY_TYPES = {"Document", "XHR", "Fetch", "Script"}  # requests that change the page when they come back
IDLE = 600  # s without a call: the browser closes, and opens again with its tabs when next used
READ_CHARS = 20_000
TAB_IDS = 10_000  # ids each tab of a conversation has before it could reach the next tab's
STEPS = ("click", "fill", "type", "key", "hover", "scroll", "drag", "upload", "wait", "open", "back", "forward",
         "reload", "dialog", "save", "close", "show")
CHANGES = 0.6  # a reply shows the whole page when more of it than this changed
BUSY_ELSEWHERE = ("Your browser is in use in another conversation right now, so it cannot move to or from the "
                  "user's screen: try again in a moment.")
MOVED = ("Your browser moved {where} (it started again there): your pages opened again at their addresses, so what "
         "was typed and not sent is gone.")
SHOWN = ("Your browser is on the user's screen at {urls}, and still yours. Tell them what to do there (sign in, the "
         "check, the payment) and to tell you when they are done; then go on with your browser tools as before, with "
         "what they did (a sign-in stays). It stays on their screen until browser_open headless=true.")
LEAD_ONLY = ("Only the lead can hand the browser to the user: say in your report what the user should do there "
             "(sign in at ...), or ask the lead with ask_lead.")
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


def _find(text: str, words: str) -> str:
    """The lines of a view with ``words``, and the lines they are in (by indentation)."""
    lines, words, keep = text.splitlines(), words.lower(), set()
    depth = lambda line: (len(line) - len(line.lstrip(" "))) // 2  # noqa: E731
    for index, line in enumerate(lines):
        if words not in line.lower():
            continue
        keep.add(index)
        level = depth(line)
        for up in range(index - 1, -1, -1):
            if level <= 0:
                break
            if depth(lines[up]) < level:
                keep.add(up)
                level = depth(lines[up])
    return "\n".join(line for index, line in enumerate(lines) if index in keep)


def _remote(value: dict) -> str:
    """A value the console was given, as words."""
    kind = value.get("type")
    if kind == "string":
        return value.get("value", "")
    if kind in ("number", "boolean", "bigint"):
        return str(value.get("unserializableValue") or value.get("value", value.get("description", "")))
    if kind == "undefined" or value.get("subtype") == "null":
        return kind if kind == "undefined" else "null"
    preview = value.get("preview")
    if preview and preview.get("properties") is not None:
        inner = [(p.get("name"), p.get("value", p.get("type", ""))) for p in preview["properties"]]
        more = ", …" if preview.get("overflow") else ""
        if preview.get("subtype") == "array":
            return "[" + ", ".join(str(v) for _, v in inner) + more + "]"
        return "{" + ", ".join(f"{k}: {v}" for k, v in inner) + more + "}"
    return value.get("description") or kind or ""


class Frame:
    """A frame of another site in a tab's page: a target of its own (Chrome runs it in another process), read in
    a world of the brain's own like the page."""

    def __init__(self, session: str, target: str, parent: str, key: int):
        self.session, self.target, self.parent, self.key = session, target, parent, key  # parent: a session
        self.context = None
        self.marked = None  # the parent world's context in which its iframe element carries ``key``


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
        self.remote: Dict[str, Frame] = {}  # session -> a frame of another site on the page
        self.where: Dict[str, Frame] = {}  # id -> the frame of another site it is in (others: the page's own)
        self.network: List[dict] = []  # the page's requests since it loaded
        self._request_at: Dict[str, int] = {}
        self.console: Optional[list] = None  # console messages while they are read
        self.mime = ""  # what the page is (application/pdf for a PDF)

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
            request, number = params.get("request") or {}, params.get("requestId")
            if params.get("type") in BUSY_TYPES:
                self.requests[number] = time.monotonic()
            redirect = params.get("redirectResponse")
            if params.get("type") == "Document" and params.get("frameId") == self.target and not redirect:
                self.network, self._request_at, self.mime = [], {}, ""  # a new page: its own requests
            if redirect and number in self._request_at:
                self.network[self._request_at[number]]["status"] = redirect.get("status")
            self._request_at[number] = len(self.network)
            self.network.append({"method": request.get("method", "GET"), "url": request.get("url", ""),
                                 "type": params.get("type", "Other")})
        elif method == "Network.responseReceived":
            response = params.get("response") or {}
            if params.get("requestId") in self._request_at:
                self.network[self._request_at[params["requestId"]]].update(status=response.get("status"),
                                                                            mime=response.get("mimeType", ""))
            if params.get("type") == "Document" and params.get("frameId") == self.target:
                self.mime = response.get("mimeType", "")
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.requests.pop(params.get("requestId"), None)
            if method == "Network.loadingFailed" and params.get("requestId") in self._request_at:
                self.network[self._request_at[params["requestId"]]]["error"] = (
                    "cancelled" if params.get("canceled") else params.get("blockedReason") or params.get("errorText"))
        elif method in ("Runtime.consoleAPICalled", "Runtime.exceptionThrown"):
            if self.console is not None:
                self.console.append((method, params))
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
        self.user_desktop: Optional[str] = None  # the user's screen (tests: a hidden desktop standing in for it)
        self._lock = threading.RLock()
        self.mode = "off"  # off, hidden (out of the user's sight), shown (on the user's screen)
        self.wanted: Optional[str] = None  # hidden or shown, as she or the user asked; None: browser_headless
        self.process: Optional[desktops.Process] = None
        self.wire: Optional[Wire] = None
        self.owners: Dict[str, dict] = {}  # "app/session" -> {"next", "current", "tabs": {name: Tab}}
        self._by_target: Dict[str, Tab] = {}
        self._by_session: Dict[str, Tab] = {}
        self._frame_sessions: Dict[str, Tab] = {}  # a frame of another site's session -> its tab
        self._frame_keys = itertools.count(1)
        self._downloads: Dict[str, dict] = {}
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
                    "shown": self._shown_wanted(), "profile": str(self.profile), "has_profile": self.profile.exists(),
                    "tabs": sum(len(owner["tabs"]) for owner in self.owners.values())}

    def _shown_wanted(self) -> bool:
        """Where it opens: on the user's screen or out of sight."""
        if self.wanted:
            return self.wanted == "shown"
        return not self.brain.config.values()["browser_headless"]

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
        if self.mode != "off" and (self.wire.closed.is_set() or self.process.poll() is not None):
            self._gone()

    def _gone(self) -> None:
        if self.wire:
            self.wire.close()
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.mode, self.process, self.wire = "off", None, None
        for owner in self.owners.values():
            for tab in owner["tabs"].values():
                tab.restore = tab.restore or (tab.url if tab.session and tab.url != "about:blank" else None)
                tab._reset()
        self._by_target.clear()
        self._by_session.clear()
        self._frame_sessions.clear()
        self._downloads.clear()

    def _ensure(self, key: str, shown: Optional[bool] = None) -> List[Tab]:
        """A running browser, where it is wanted (``shown``: where she asked for it now). The conversation's tabs
        that had pages when it moved, to open again."""
        self._check()
        if shown is not None:
            self.wanted = "shown" if shown else "hidden"
        if self.mode == "off":
            self._launch(self._shown_wanted())
            return []
        if shown is None or (self.mode == "shown") == shown:
            return []
        if self.calls > 1:
            raise ToolError(BUSY_ELSEWHERE)
        moved = [tab for tab in self._owner(key)["tabs"].values() if tab.session]
        self._shut()
        self._launch(shown)
        return moved

    def _launch(self, shown: bool) -> None:
        command = self.command()
        if not command:
            raise ToolError("There is no Chrome or Edge on this computer, so you have no browser: the user installs "
                            "one, or sets where it is in SentientMilk (Tools > Browser).")
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.folder / "downloads").mkdir(exist_ok=True)
        port = _free_port()
        args = [command, f"--user-data-dir={self.profile}", f"--remote-debugging-port={port}", *FLAGS,
                f"--window-size={WINDOW[0]},{WINDOW[1]}"]
        process = desktops.start(args, desktop=self.user_desktop if shown else self.desktop, tied=True)
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
            self._bring_cookies(wire)
        except Exception as exc:
            process.kill()
            raise ToolError(f"Your browser started but could not be reached: {exc}")
        self.process, self.wire, self.mode = process, wire, "shown" if shown else "hidden"
        if not self._threads:
            self._threads = True
            threading.Thread(target=self._handle_events, name="browser-events", daemon=True).start()
            threading.Thread(target=self._watch, name="browser-idle", daemon=True).start()

    def _keep_cookies(self) -> None:
        """Session cookies (a sign-in that lasts while the browser is open) wait in the profile while it is closed:
        for her it is still open, its tabs are."""
        try:
            cookies = self.wire.call("Storage.getCookies", timeout=5)["cookies"]
        except Exception:
            return
        kept = []
        for cookie in cookies:
            if not cookie.get("session"):
                continue
            kept.append({k: v for k, v in cookie.items() if k in COOKIE_FIELDS})
            if not cookie.get("domain", "").startswith("."):  # a host's own, not its subdomains'
                scheme = "https" if cookie.get("secure") else "http"
                kept[-1]["url"] = f"{scheme}://{kept[-1].pop('domain')}{cookie.get('path', '/')}"
        try:
            if kept:
                (self.profile / COOKIES).write_text(json.dumps(kept), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not keep the browser's session cookies: %s", exc)

    def _bring_cookies(self, wire: Wire) -> None:
        path = self.profile / COOKIES
        try:
            cookies = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            wire.call("Storage.setCookies", {"cookies": cookies}, timeout=10)
        except CdpError as exc:
            logger.warning("Could not bring back the browser's session cookies: %s", exc)
        path.unlink(missing_ok=True)

    def _watch(self) -> None:
        """An idle browser out of sight closes: its tabs open again at their addresses when next used (one on the
        user's screen stays, they may be looking at it)."""
        while not self.brain.stopping.wait(15):
            with self._lock:
                if self.mode == "hidden" and not self.calls and time.monotonic() - self.used > IDLE:
                    self._shut()
                    self.wanted = None  # as browser_headless says, when it opens again

    def _shut(self, keep: bool = True) -> None:
        """It closes (under the lock); ``keep``: its session cookies come back when it opens again."""
        if self.mode == "off":
            return
        if keep:
            self._keep_cookies()
        try:
            self.wire.call("Browser.close", timeout=5)
        except Exception:
            pass
        if self.process and not self.process.wait(10):
            self.process.kill()
        self._gone()
        self._save()

    def close(self) -> None:
        """The brain stops: her browser closes."""
        with self._lock:
            self._shut()

    def put(self, shown: bool) -> dict:
        """The panel's Show and Hide: her browser on the user's screen (to sign in to sites for her, or to watch
        her) or out of sight, from now on. Her pages there open again, and on a screen with none of hers a
        window of the user's own opens."""
        with self._lock:
            self._check()
            if self.calls:
                raise BrainError("busy", "She is using her browser right now: try again in a moment", http_status=409)
            if not self.command():
                raise BrainError("no_browser", "There is no Chrome or Edge on this computer", http_status=409)
            self.wanted = "shown" if shown else "hidden"
            if (self.mode == "shown") == shown and self.mode != "off":
                return self.status()
            moved = [tab for owner in self.owners.values() for tab in owner["tabs"].values() if tab.session]
            try:
                self._shut()
                if shown:
                    self._launch(True)
                    self._reopen(moved)
                    if not moved:
                        self.wire.call("Target.createTarget", {"url": "about:blank", "newWindow": True})
            except ToolError as exc:
                raise BrainError("no_browser", str(exc), http_status=409)
            return self.status()

    def _reopen(self, tabs) -> None:
        """Tabs that had pages before it moved get them again, not waited for (under the lock)."""
        for tab in tabs:
            try:
                self._live(tab)
                if tab.restore:
                    url, tab.restore = tab.restore, None
                    self.wire.call("Page.navigate", {"url": url}, tab.session, timeout=30, until=tab.held)
            except (CdpError, BrowserGone, ToolError) as exc:
                logger.info("A tab did not open again: %s", exc)

    def clear(self) -> dict:
        """Forget what she signed in to: her profile goes (her tabs keep their addresses)."""
        with self._lock:
            self._check()
            if self.calls:
                raise BrainError("busy", "She is using her browser right now: try again in a moment", http_status=409)
            self._shut(keep=False)
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
        tab = self._by_session.get(session) or self._frame_sessions.get(session)
        if tab is None:
            return
        if method == "Target.attachedToTarget":  # a frame of another site, in a process of its own
            info = params.get("targetInfo") or {}
            if info.get("type") == "iframe":
                frame = Frame(params["sessionId"], info["targetId"], session, next(self._frame_keys))
                tab.remote[frame.session] = frame
                self._frame_sessions[frame.session] = tab
                self._events.put(("frame", {"session": frame.session}))  # its own frames of other sites too
        elif method == "Target.detachedFromTarget":
            tab.remote.pop(params.get("sessionId"), None)
            self._frame_sessions.pop(params.get("sessionId"), None)
        elif session != tab.session:
            return
        elif method == "Page.javascriptDialogOpening":
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
        if self.mode == "off":
            return
        if method == "answer":
            self._quietly(self.wire.call, "Page.handleJavaScriptDialog", {"accept": True}, params["session"], 5)
        elif method == "frame":
            self._quietly(self.wire.call, "Target.setAutoAttach", AUTO_ATTACH, params["session"], 5)
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
                other.news.append(f"Tab {tab.name} ({tab.title or tab.url}) {self._closed_words()}.")
            self._save()

    def _closed_words(self) -> str:
        return "closed itself" if self.mode != "shown" else "was closed (by the page, or by the user on their screen)"

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
        wire.call("Target.setAutoAttach", AUTO_ATTACH, session)  # its frames of other sites
        tab.window = wire.call("Browser.getWindowForTarget", {"targetId": target})["windowId"]
        if resize:
            wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {"windowState": "normal"}})
            place = {"left": 0, "top": 0} if self.mode == "hidden" else {}  # on the user's screen: where Chrome puts it
            wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {
                **place, "width": WINDOW[0], "height": WINDOW[1]}})

    def _live(self, tab: Tab) -> None:
        """A page for the tab (under the lock); its address comes back in ``using``, outside the lock."""
        if tab.session and tab.target in self._by_target and not tab.crashed:
            return
        if tab.target:  # a page that crashed: a new one in its place
            self._by_target.pop(tab.target, None)
            self._by_session.pop(tab.session, None)
            for session in tab.remote:
                self._frame_sessions.pop(session, None)
            self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})
            tab.restore = tab.restore or (tab.url if tab.url != "about:blank" else None)
        tab._reset()
        # on the user's screen a new window stays behind what they are using: it never takes their keys
        target = self.wire.call("Target.createTarget", {"url": "about:blank", "newWindow": True,
                                                        "background": self.mode == "shown"})["targetId"]
        self._attach(tab, target)

    def _shown_window(self, tab: Tab) -> None:
        """A minimized window on the user's screen paints nothing, so a picture of it waits forever: it comes back
        (behind what they are using). Reading and acting need none of this."""
        if self.mode != "shown" or tab.window is None:
            return
        state = self.wire.call("Browser.getWindowBounds", {"windowId": tab.window})["bounds"].get("windowState")
        if state == "minimized":
            self.wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {"windowState": "normal"}})
            time.sleep(0.3)  # until it paints

    @contextlib.contextmanager
    def using(self, ctx, name: str = "", create: bool = False, new: bool = False, shown: Optional[bool] = None):
        """The conversation's tab ``name`` (or its current one; ``new``: a new one), live and held for a call;
        ``shown``: the browser on the user's screen (or out of sight) from now on."""
        from .toolkits.files import cwd

        key = _key(ctx.app, ctx.session)
        name = self._name(name)
        with self._lock:
            self.calls += 1
            self.used = time.monotonic()
        try:
            with self._lock:
                moved = self._ensure(key, shown)
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
                    raise ToolError(f"Tab {tab.name} {self._closed_words()}. "
                                    f"{self._tabs_line(key) or 'You have no tabs.'}")
                owner["current"] = tab.name
                tab.folder = cwd(ctx)
                self._live(tab)
                if moved:
                    tab.news.append(MOVED.format(where="to the user's screen" if self.mode == "shown"
                                                 else "out of the user's sight"))
                    self._reopen([t for t in moved if t is not tab])
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
                if tab.target and self.mode != "off":
                    self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})

    def seen(self, run: dict, arguments: dict) -> dict:
        """A browser call as the rules and the user see it: the site it acts on, and what each id is."""
        owner = self.owners.get(_key(run["app"], run["session"])) or {"tabs": {}, "current": None}
        tab = owner["tabs"].get(self._name(arguments.get("tab")) or owner["current"] or "")
        if arguments.get("url"):
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

    def _eval(self, tab: Tab, expression: str, timeout: float = 30.0, value: bool = True,
              frame: Optional[Frame] = None):
        """``expression`` in the brain's own world of the page, or of one of its frames of another site
        (installed there first, giving out ids from where the tab's are, so every world's ids differ); None when a
        dialog of the page opened meanwhile."""
        world = frame or tab
        if tab.ended:
            raise ToolError(f"Tab {tab.name} {self._closed_words()}.")
        if tab.dialog:
            raise ToolError(self._dialog_line(tab))
        if frame and tab.remote.get(frame.session) is not frame:
            raise ToolError(FRAME_GONE)
        for _ in range(4):
            try:
                if world.context is None:
                    made = self.wire.call("Page.createIsolatedWorld", {"frameId": world.target, "worldName": WORLD},
                                          world.session)
                    world.context = made["executionContextId"]
                    installed = self.wire.call("Runtime.evaluate", {
                        "expression": f"({PAGE_JS})({tab.next_id})", "contextId": world.context,
                        "returnByValue": True}, world.session, until=tab.held)
                    if installed is None:
                        if tab.ended:
                            raise ToolError(f"Tab {tab.name} {self._closed_words()}.")
                        return None
                    tab.next_id = max(tab.next_id, installed.get("result", {}).get("value") or 0)
                reply = self.wire.call("Runtime.evaluate", {
                    "expression": f"(__milk.sync({tab.next_id}), {expression})", "contextId": world.context,
                    "returnByValue": value, "awaitPromise": True}, world.session, timeout, until=tab.held)
            except CdpError as exc:  # the page changed under the call: its new document gets the world again
                if frame and "session" in str(exc).lower():
                    tab.remote.pop(frame.session, None)
                    raise ToolError(FRAME_GONE)
                if tab.ended or "session" in str(exc).lower():
                    tab.ended = True
                    raise ToolError(f"Tab {tab.name} {self._closed_words()}.")
                if any(word in str(exc).lower() for word in ("context", "frame", "target")):
                    world.context = None
                    time.sleep(0.1)
                    continue
                raise ToolError(f"The page could not be read: {exc}")
            if reply is None:
                if tab.ended:
                    raise ToolError(f"Tab {tab.name} {self._closed_words()}.")
                return None
            if "exceptionDetails" in reply:
                details = reply["exceptionDetails"]
                text = (details.get("exception") or {}).get("description") or details.get("text", "")
                if "__milk" in text:  # a new document came between the two calls
                    world.context = None
                    continue
                raise ToolError(f"The page could not be read: {text.splitlines()[0] if text else 'an error'}")
            return reply["result"].get("value") if value else reply["result"]
        raise ToolError("The page kept changing while it was read: try again.")

    def _mark(self, tab: Tab, parent: Optional[Frame] = None) -> None:
        """Each frame of another site in a world gets its key on its iframe element there, so the world's view
        says where the frame's own view goes."""
        world = parent or tab
        for frame in list(tab.remote.values()):
            if frame.parent != world.session:
                continue
            try:
                if world.context is None:
                    self._eval(tab, "0", frame=parent)
                if frame.marked == world.context:
                    continue
                owner = self.wire.call("DOM.getFrameOwner", {"frameId": frame.target}, world.session, 5)
                node = self.wire.call("DOM.resolveNode", {"backendNodeId": owner["backendNodeId"],
                                                          "executionContextId": world.context}, world.session, 5)
                handle = node["object"]["objectId"]
                self.wire.call("Runtime.callFunctionOn", {
                    "objectId": handle, "functionDeclaration": "function(key) { __milk.mark(this, key) }",
                    "arguments": [{"value": frame.key}]}, world.session, 5)
                self._quietly(self.wire.call, "Runtime.releaseObject", {"objectId": handle}, world.session, 5)
                frame.marked = world.context
            except (CdpError, ToolError, KeyError, TypeError):
                continue  # gone, or not loaded yet: the view says it is not readable

    def _frame_of(self, tab: Tab, key: int) -> Optional[Frame]:
        return next((frame for frame in tab.remote.values() if frame.key == key), None)

    def _in_frames(self, tab: Tab, text: str, kind: str, full: bool) -> str:
        """Each frame of another site's own view (``kind`` view or read) where it goes in ``text``."""
        def each(match):
            indent, frame = match.group(1), self._frame_of(tab, int(match.group(2)))
            try:
                inner = self._frame_text(tab, frame, kind, full) if frame else ""
            except ToolError:
                inner = ""
            if not inner.strip():
                return indent + "(nothing readable in it now: use a picture and point)"
            return "\n".join(indent + line for line in inner.splitlines())
        return FRAME.sub(each, text)

    def _frame_text(self, tab: Tab, frame: Frame, kind: str, full: bool, part: str = "") -> str:
        self._mark(tab, frame)
        if kind == "read":
            return self._in_frames(tab, self._eval(tab, "__milk.read()", frame=frame) or "", kind, full)
        data = self._eval(tab, f"__milk.view({json.dumps({'full': full, 'part': part})})", frame=frame)
        if not data or data.get("gone"):
            return ""
        self._took(tab, data, frame)
        return self._in_frames(tab, data["text"], kind, full)

    def _took(self, tab: Tab, data: dict, frame: Optional[Frame]) -> None:
        """What a view in a world gave out: ids, and what each is."""
        tab.next_id = max(tab.next_id, data["next"])
        tab.labels.update(data["labels"])
        for number in data["labels"]:
            if frame:
                tab.where[str(number)] = frame
            else:
                tab.where.pop(str(number), None)

    def _world_of(self, tab: Tab, target) -> Optional[Frame]:
        """The frame of another site an id is in (None: the page's own)."""
        frame = tab.where.get(_id(target))
        return frame if frame and tab.remote.get(frame.session) is frame else None

    def _offset(self, tab: Tab, frame: Optional[Frame]):
        """Where a frame of another site's own top left is in the tab's window."""
        x = y = 0.0
        while frame:
            parent = tab.remote.get(frame.parent)  # None: the page's own world
            here = self._eval(tab, f"__milk.offsetOf({frame.key})", frame=parent)
            if not here:
                raise ToolError(FRAME_GONE)
            x, y, frame = x + here[0], y + here[1], parent
        return x, y

    def _quiet_for(self, tab: Tab) -> Optional[float]:
        """Milliseconds since the page (or one of its frames of other sites) last changed."""
        quiet = self._eval(tab, "__milk.changed()", timeout=3)
        for frame in list(tab.remote.values()):
            if quiet is not None and frame.context is not None:
                try:
                    quiet = min(quiet, self._eval(tab, "__milk.changed()", timeout=3, frame=frame) or 0)
                except ToolError:
                    pass
        return quiet

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
                    quiet = self._quiet_for(tab)
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
        """The page as text with ids, its frames of other sites in it (only the lines with ``find``; only the
        part ``part``)."""
        frame, full = self._world_of(tab, part) if part else None, bool(find or part)
        self._mark(tab, frame)
        data = self._eval(tab, f"__milk.view({json.dumps({'full': full, 'part': _id(part)})})", frame=frame)
        if data is None:
            return {"text": "", "labels": {}, "title": tab.title, "url": tab.url, "next": tab.next_id}
        if data.get("gone"):
            raise ToolError(f"{part} is not on the page any more: view it again.")
        self._took(tab, data, frame)
        data["text"] = self._in_frames(tab, data["text"], "view", full)
        if find:
            data["text"] = _find(data["text"], find)
        if not frame:
            tab.title, tab.url = data["title"], data["url"]
        return data

    def _head(self, tab: Tab) -> List[str]:
        lines = [f"{tab.name} · {tab.title or '(no title)'} · {tab.url}" +
                 (" · on the user's screen" if self.mode == "shown" else "")]
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
        if tab.mime == "application/pdf":
            note = (note + " " if note else "") + ("This tab shows a PDF: the step save (text: a name ending .pdf) "
                                                   "keeps the document itself.")
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

    def open(self, ctx, url: str = "", new_tab: bool = False, headless: Optional[bool] = None) -> str:
        url = str(url or "").strip()
        shown = None if headless is None else not headless
        if not url:
            if shown is None:
                raise ToolError("url is empty: give the address to open (https://...).")
            owner = self.owners.get(_key(ctx.app, ctx.session)) or {"tabs": {}, "current": None}
            if not owner["tabs"].get(owner["current"] or ""):  # nothing to show yet: it opens there next time
                with self._lock:
                    self.wanted = "shown" if shown else "hidden"
                    busy = self.mode != "off" and (self.mode == "shown") != shown and self.calls
                    if self.mode != "off" and (self.mode == "shown") != shown and not busy:
                        self._shut()
                where = "on the user's screen" if shown else "out of the user's sight"
                when = "once another conversation is done with it" if busy else "from now on"
                return f"Your browser opens {where} {when}. You have no tab open: open a page with browser_open."
        with self.using(ctx, create=True, new=new_tab and bool(url), shown=shown) as tab:
            note = self._navigate(tab, url) if url else ""
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
        self._shown_window(tab)
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
            self._mark(page)
            text = self._in_frames(page, self._eval(page, "__milk.read()") or "", "read", True)
            if not text.strip() and page.mime == "application/pdf":
                text = ("This tab shows a PDF, which is drawn rather than written into the page: the step save (text: "
                        "a name ending .pdf) keeps the document itself.")
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

    def log(self, ctx, kind: str = "console", tab: str = "", find: str = "") -> str:
        """The page's console (its messages and errors) or its network requests, since it loaded."""
        kind = str(kind or "console").strip().lower()
        if kind not in ("console", "network"):
            raise ToolError("kind is console (the page's messages and errors) or network (its requests).")
        with self.using(ctx, tab) as page:
            if kind == "network":
                lines = [f"{r['method']} {r.get('error') or r.get('status') or '(waiting)'} {r['type'].lower()} "
                         f"{r['url']}" + (f" ({r['mime']})" if r.get("mime") else "") for r in list(page.network)]
            else:
                # the console keeps what the page said: Runtime tells it all when enabled, for a moment only
                page.console = []
                try:
                    self.wire.call("Runtime.enable", session=page.session, until=page.held)
                    for _, params in list(page.console):  # objects as JSON while they are still there
                        for arg in params.get("args", []):
                            if arg.get("objectId") and arg.get("type") == "object" and \
                                    arg.get("subtype") in (None, "array") and not arg.get("preview"):
                                try:
                                    shown = self.wire.call("Runtime.callFunctionOn", {
                                        "objectId": arg["objectId"], "returnByValue": True, "functionDeclaration":
                                        "function() { try { return JSON.stringify(this); } catch (e) { return "
                                        "String(this); } }"}, page.session, 5)
                                    arg.update(type="string", value=shown["result"].get("value") or "")
                                except (CdpError, ToolError):
                                    pass
                finally:
                    self._quietly(self.wire.call, "Runtime.disable", None, page.session, 5)
                    said, page.console = page.console, None
                lines = [self._console_line(method, params) for method, params in said]
            if find:
                lines = [line for line in lines if find.lower() in line.lower()]
            empty = (f"Nothing with {find!r}." if find else
                     "Nothing in the console since the page loaded." if kind == "console" else
                     "No requests since the page loaded.")
            return "\n".join(self._head(page) + (lines or [empty]))

    @staticmethod
    def _console_line(method: str, params: dict) -> str:
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            text = (details.get("exception") or {}).get("description") or details.get("text", "")
            where = f" ({details['url']}:{details.get('lineNumber', 0) + 1})" if details.get("url") else ""
            return f"[uncaught error] {text}{where}"
        kind = params.get("type", "log")
        text = " ".join(_remote(arg) for arg in params.get("args", []))
        frames = (params.get("stackTrace") or {}).get("callFrames") or []
        where = ""
        if kind in ("error", "warning", "assert", "trace") and frames and frames[0].get("url"):
            where = f" ({frames[0]['url']}:{frames[0].get('lineNumber', 0) + 1})"
        return f"[{kind}] {text}{where}"

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
                        return "\n".join(notes + [f"{said}: " + self.show(ctx, page)] +
                                         ([rest + ": go on once the user is done."] if rest else []))
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
                    words = self._closed_words()
                    self._closed_itself(page)
                return "\n".join(notes + [f"Tab {page.name} {words}."] + self._after_close(page))
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
            if tab.target and self.mode != "off":
                self._quietly(self.wire.call, "Target.closeTarget", {"targetId": tab.target})
        return f"{tab.name} closed"

    def show(self, ctx, tab: Tab) -> str:
        """Her browser on the user's screen at the tab, in front, for them to do what is theirs (a sign-in, a
        check, a payment); she goes on there once they are done."""
        if ctx.run["kind"] != "turn":
            raise ToolError(LEAD_ONLY)
        key = _key(ctx.app, ctx.session)
        with self._lock:
            moved = self._ensure(key, shown=True)
            if moved:
                self._live(tab)
                self._reopen([t for t in moved if t is not tab])
        if moved and tab.restore:
            url, tab.restore = tab.restore, None
            self._navigate(tab, url)
        self._quietly(self.wire.call, "Target.activateTarget", {"targetId": tab.target})  # in front: theirs to use
        return SHOWN.format(urls=f"{tab.name} ({tab.url})")

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
            found, frame, inner = self._eval(tab, f"__milk.at({x}, {y})") or {}, None, (x, y)
            while found.get("frame") and self._frame_of(tab, found["frame"]):  # a frame of another site's own
                frame, inner = self._frame_of(tab, found["frame"]), (found["x"], found["y"])
                found = self._eval(tab, f"__milk.at({inner[0]}, {inner[1]})", frame=frame) or {}
            tab.next_id = max(tab.next_id, found.get("next", 0))
            self._note_ids(tab, found.get("label", ""), frame)
            return {"x": x, "y": y, "point": True, "label": found.get("label") or "nothing there", "frame": frame}
        if not re.fullmatch(r"e?\d+", target, re.I):
            raise ToolError(f"{target!r} is not an id: ids look like e5 (from the latest view of this tab).")
        frame = self._world_of(tab, target)
        found = self._eval(tab, f"__milk.locate({_id(target)}, {json.dumps(hit_test)})", frame=frame)
        if found is None:
            raise ToolError(self._dialog_line(tab))
        if found.get("gone"):
            raise ToolError(f"{target} is not on the page (any more): the page changed, so use the ids of its latest "
                            "view (browser_view).")
        tab.next_id = max(tab.next_id, found.get("next", 0))
        self._note_ids(tab, found.get("covered", ""), frame)
        found["frame"] = frame
        if frame:  # where it is in the frame, and where the frame is in the window
            left, top = self._offset(tab, frame)
            found["x"], found["y"] = found["x"] + left, found["y"] + top
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

    def _note_ids(self, tab: Tab, words: str, frame: Optional[Frame]) -> None:
        """Ids a reply names (what covers a target, what is at a point) are in the world that gave them."""
        for number in re.findall(r"\be(\d+)\b", words or ""):
            if frame:
                tab.where[number] = frame

    def _click(self, tab: Tab, place: dict, button: str = "left", count: int = 1) -> None:
        x, y = place["x"], place["y"]
        self._move(tab, x, y)
        mask = {"left": 1, "right": 2, "middle": 4}[button]
        if button == "right":  # the page's own menu opens, Chrome's would stay open on the screen and do nothing
            self._eval(tab, "__milk.menu(false)", frame=place.get("frame"))
        try:
            for clicks in range(1, count + 1):
                for kind in ("mousePressed", "mouseReleased"):
                    self._input(tab, "Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": button,
                                                                  "buttons": mask if kind == "mousePressed" else 0,
                                                                  "clickCount": clicks})
                    if tab.dialog:
                        return
        finally:
            if button == "right" and not tab.dialog and not tab.ended:
                self._quietly(self._eval, tab, "__milk.menu(true)", 5.0, True, place.get("frame"))

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
        elif action == "save":
            return self._keep(ctx, tab, text or str(target or ""))
        else:
            raise ToolError(f"There is no step {action!r}. Steps: {', '.join(STEPS)}.")
        if not self._settle(tab, after=last or action not in ("fill", "hover", "scroll")):
            note = (note + "; " if note else "") + "the page is still busy (loading)"
        if tab.document != document:
            note = (note + "; " if note else "") + f"the page went to {tab.url}"
        return note

    def _keep(self, ctx, tab: Tab, name: str) -> str:
        """The page kept as a file in the working folder: a PDF (a PDF's own document), a picture of all of it,
        its HTML, or a web archive."""
        from .toolkits.files import resolve

        suffix = Path(name).suffix.lower()
        if not name or suffix not in SAVES:
            raise ToolError("save takes a file name ending .pdf, .png, .jpg, .webp, .html or .mhtml (text: "
                            "\"receipt.pdf\").")
        path = resolve(ctx, name, write=True)
        target, number = path, 1
        while target.exists():  # never over a file that is there
            target = path.with_name(f"{path.stem} ({number}){path.suffix}")
            number += 1
        if suffix == ".pdf" and tab.mime == "application/pdf":
            data = base64.b64decode(self._eval(tab, "fetch(location.href).then(r => r.blob()).then(b => new Promise("
                                                    "done => { const f = new FileReader(); f.onload = () => done("
                                                    "f.result.split(',')[1]); f.readAsDataURL(b); }))", timeout=120))
        elif suffix == ".pdf":
            data = base64.b64decode(self.wire.call("Page.printToPDF", {"printBackground": True}, tab.session,
                                                   timeout=120)["data"])
        elif suffix in (".html", ".htm"):
            data = (self._eval(tab, "(document.doctype ? new XMLSerializer().serializeToString(document.doctype) + "
                                    "'\\n' : '') + document.documentElement.outerHTML") or "").encode("utf-8")
        elif suffix == ".mhtml":
            data = self.wire.call("Page.captureSnapshot", {"format": "mhtml"}, tab.session, timeout=120)["data"]
            data = data.encode("utf-8")
        else:
            self._shown_window(tab)
            size = self.wire.call("Page.getLayoutMetrics", session=tab.session)["cssContentSize"]
            kind = {".jpg": "jpeg", ".jpeg": "jpeg"}.get(suffix, suffix[1:])
            data = base64.b64decode(self.wire.call("Page.captureScreenshot", {
                "format": kind, "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1}},
                tab.session, timeout=120)["data"])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise ToolError(f"{target} could not be written: {exc}")
        return f"saved {SAVES[suffix]} to {target} ({len(data):,} bytes)"

    def _fill(self, tab: Tab, element: str, place: dict, text: str) -> str:
        frame = place.get("frame")
        if place.get("select") or place.get("setter"):
            chosen = self._eval(tab, f"__milk.choose({element}, {json.dumps(text)})", frame=frame)
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
        if tab.dialog or not self._eval(tab, f"__milk.focus({element})", frame=frame):  # selected: typing replaces it
            return ""
        if text:
            self._type(tab, text)
        else:
            self._keys(tab, "Delete")
        shown = self._eval(tab, f"__milk.value({element})", frame=frame)
        if shown is not None and shown.replace("\r", "") != text and not (
                place.get("type") == "password" and len(shown) == len(text)):
            return f"it shows \"{shown[:200]}\" (the page changed what was typed)"
        return ""

    def _scroll(self, tab: Tab, target, direction: str, amount) -> str:
        direction = direction.strip().lower()
        element = _id(target) if target else ""
        frame = self._world_of(tab, target) if target else None
        if direction in ("top", "bottom"):
            moved = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, {json.dumps(direction)})",
                               frame=frame) or {}
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
            before = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, 0)", frame=frame) or {}
            height = self._eval(tab, "innerHeight") or WINDOW[1]
            self._move(tab, x, y)
            self._input(tab, "Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0,
                                                          "deltaY": pages * height * 0.85})
            after, still = before, 0
            for _ in range(30):  # until it stops moving (smooth scrolling takes a moment)
                time.sleep(0.05)
                now = self._eval(tab, f"__milk.scrollBy({json.dumps(element)}, 0)", frame=frame) or after
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
            frame = place.get("frame")
            handle = self._eval(tab, f"__milk.element({_id(target)})", value=False, frame=frame) or {}
            if not handle.get("objectId"):
                raise ToolError(f"{target} is not on the page any more: view it again.")
            self.wire.call("DOM.setFileInputFiles", {"files": [str(p) for p in paths], "objectId": handle["objectId"]},
                           (frame or tab).session)
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

    def _has(self, tab: Tab, text: str) -> bool:
        """Whether the page (or a frame of another site in it) shows ``text``."""
        expression = f"__milk.has({json.dumps(text)})"
        if self._eval(tab, expression, timeout=5):
            return True
        for frame in list(tab.remote.values()):
            try:
                if self._eval(tab, expression, timeout=5, frame=frame):
                    return True
            except ToolError:
                pass
        return False

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
            if self._has(tab, text):
                self._settle(tab, 3)
                return f"\"{text}\" shows"
            if ctx.pause(0.25):
                return f"stopped waiting: {ctx.interruption()}"
        raise ToolError(f"\"{text}\" did not show in {seconds:g} s.")
