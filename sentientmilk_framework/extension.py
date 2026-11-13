"""The user's own Chrome, through SentientMilk's extension (extension/): her browser, with the user's sign-ins.

The extension connects to the brain on 127.0.0.1 (``browser_extension_port``) from its own origin only. The brain
speaks first (who it is, its protocol, a nonce); the extension answers with proof of the code the panel shows
(the port and a token of its own, kept in ``browser/extension.json``), never the token itself, so a program that
took the port learns nothing. Then the connection is a DevTools protocol connection (browser.Wire): page
commands go to chrome.debugger, and the extension answers what a browser does (tabs, windows, downloads) itself.

One browser at a time: another one with the extension is refused (BUSY) unless the user chose it there (Connect,
or the panel's Connect), which takes over (the old one hears REPLACED). The same extension connecting again
replaces its old connection, which may be dead without having said so (pings find those too).
"""

import hmac
import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from . import __version__

logger = logging.getLogger(__name__)
WIRE_LOG = logging.getLogger("sentientmilk_framework.wire")  # the browser's sockets (browser.py too)
WIRE_LOG.setLevel(logging.INFO)  # never their frames, at any level: what the user typed for her travels in them

EXTENSION_ID = "nchdmjacdboinhpkleiaehgiiopnjeba"  # fixed by the key in its manifest
FOLDER = Path(__file__).with_name("extension")
PROTOCOL = 2  # how the extension and the brain talk: a mismatch stops with what to update (2: sign-in boxes)
# close codes, the extension's to show: the code, the protocol, another browser has it, another took it, Disconnect
WRONG_CODE, OUTDATED, BUSY, REPLACED, DISCONNECTED = 4001, 4002, 4003, 4004, 4100
RETRY = 10  # s between tries for the port while another program has it


def proof(token: str, nonce: str) -> str:
    return hmac.new(token.encode(), nonce.encode(), "sha256").hexdigest()


class Bridge:
    def __init__(self, browser, port: int):
        self.browser, self.wanted_port = browser, port
        self.port: Optional[int] = None
        self.error = ""
        self.server = None
        self.current: Optional[dict] = None  # the extension connected now: wire, instance, name, version
        self.disconnected = False  # the user pressed Disconnect in the extension (until it connects again)
        self.confirmed = 0.0  # when the connect page last opened in the browser already connected (monotonic)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        path = browser.folder / "extension.json"
        try:
            self.token = json.loads(path.read_text(encoding="utf-8"))["token"]
        except (OSError, ValueError, KeyError):
            self.token = secrets.token_urlsafe(24)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"token": self.token}), encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not keep the extension's code: %s", exc)

    def start(self) -> None:
        if not self._listen():  # another brain, or another program, has the port: until it lets go
            threading.Thread(target=self._retry, name="browser-extension-port", daemon=True).start()

    def _listen(self) -> bool:
        from websockets.sync.server import serve

        try:
            server = serve(self._serve, "127.0.0.1", self.wanted_port, max_size=None, ping_interval=20,
                           ping_timeout=20, logger=WIRE_LOG)
        except OSError as exc:
            if not self.error:
                logger.warning("The extension's connection could not listen on port %s: %s", self.wanted_port, exc)
            self.error = f"port {self.wanted_port} is taken by another program (SentientMilk tries again every {RETRY} s)"
            return False
        if self._closing.is_set():
            server.socket.close()
            return True
        self.server, self.port, self.error = server, server.socket.getsockname()[1], ""
        threading.Thread(target=server.serve_forever, name="browser-extension", daemon=True).start()
        return True

    def _retry(self) -> None:
        while not self._closing.wait(RETRY) and not self._listen():
            pass

    def close(self) -> None:
        self._closing.set()
        if self.server:
            self.server.shutdown()

    def code(self) -> str:
        """What the user gives the extension: where the brain is, and the token."""
        return f"{self.port}-{self.token}" if self.port else ""

    def connect_url(self) -> str:
        """The extension's page that takes the code (the panel's Connect opens it in the user's Chrome)."""
        return f"chrome-extension://{EXTENSION_ID}/popup.html#code={self.code()}"

    def status(self) -> dict:
        now = self.current
        return {"browser": now["name"] if now else "", "extension": now["version"] if now else "",
                "disconnected": self.disconnected and not now, "code": self.code(), "folder": str(FOLDER),
                "error": self.error}

    def _serve(self, connection) -> None:
        from .browser import Wire

        if connection.request.headers.get("Origin", "") != f"chrome-extension://{EXTENSION_ID}":
            return connection.close(1008, "only SentientMilk's extension connects here")
        nonce = secrets.token_hex(16)
        connection.send(json.dumps({"sentientmilk": {"protocol": PROTOCOL, "version": __version__, "nonce": nonce}}))
        try:
            hello = json.loads(connection.recv(timeout=10)).get("hello") or {}
        except Exception:
            return connection.close(1008, "no hello")
        if hello.get("protocol") != PROTOCOL:  # 0.13's sent the code itself, and shows this reason as it is
            return connection.close(OUTDATED, f"This extension is older than SentientMilk {__version__}: "
                                              "reload it in chrome://extensions")
        if not hmac.compare_digest(str(hello.get("proof", "")).encode(), proof(self.token, nonce).encode()):
            return connection.close(WRONG_CODE, "wrong code")
        name, instance = str(hello.get("name") or "a browser")[:40], str(hello.get("instance", ""))
        with self._lock:
            old = self.current
            if old and old["instance"] != instance and not hello.get("take"):
                return connection.close(BUSY, old["name"])  # the extension says which browser has her
            connection.send(json.dumps({"welcome": {"version": __version__}}))
            wire = Wire(None, self._event, socket=connection)
            self.current = {"wire": wire, "instance": instance, "name": name,
                            "version": str(hello.get("version", ""))[:20]}
            self.disconnected = False
        if old:  # off the way: a dead connection takes its close timeout to close
            threading.Thread(target=old["wire"].socket.close, args=(REPLACED, name), daemon=True).start()
        self.browser.linked(wire)
        wire.closed.wait()
        disconnected = connection.close_code == DISCONNECTED
        with self._lock:
            if self.current and self.current["wire"] is wire:
                self.current, self.disconnected = None, disconnected
        self.browser.unlinked(wire, disconnected)

    def _event(self, session, method: str, params: dict) -> None:
        if method == "Extension.connectPage":
            self.confirmed = time.monotonic()
        elif method != "Extension.ping":  # it only keeps the extension awake
            self.browser._event(session, method, params)
