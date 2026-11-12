"""The user's own Chrome, through SentientMilk's extension (extension/): her tabs there have the user's sign-ins.

The extension connects to the brain on 127.0.0.1 (``browser_extension_port``) with the code the panel shows
(the port and a token of its own, kept in ``browser/extension.json``), from its own origin only. Then the
connection is a DevTools protocol connection like her own browser's (browser.Wire): page commands go to
chrome.debugger, and the extension answers what a browser does (tabs, windows, downloads) itself.
"""

import hmac
import json
import logging
import secrets
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

EXTENSION_ID = "nchdmjacdboinhpkleiaehgiiopnjeba"  # fixed by the key in its manifest
FOLDER = Path(__file__).with_name("extension")


class Bridge:
    def __init__(self, browser, port: int):
        self.browser, self.wanted_port = browser, port
        self.port: Optional[int] = None
        self.error = ""
        self.server = None
        self.agent = ""  # the browser it is in, as it says
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
        from websockets.sync.server import serve

        try:
            self.server = serve(self._serve, "127.0.0.1", self.wanted_port, max_size=None, ping_interval=None)
        except OSError as exc:  # another brain, or another program, has the port
            self.error = f"port {self.wanted_port} is taken ({exc.strerror or exc})"
            logger.warning("The extension's connection could not listen: %s", self.error)
            return
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, name="browser-extension", daemon=True).start()

    def close(self) -> None:
        if self.server:
            self.server.shutdown()

    def code(self) -> str:
        """What the user gives the extension: where the brain is, and the token."""
        return f"{self.port}-{self.token}" if self.port else ""

    def connect_url(self) -> str:
        """The extension's page that takes the code (the panel's Connect opens it in the user's Chrome)."""
        return f"chrome-extension://{EXTENSION_ID}/popup.html#code={self.code()}"

    def _serve(self, connection) -> None:
        from .browser import Wire

        if connection.request.headers.get("Origin", "") != f"chrome-extension://{EXTENSION_ID}":
            return connection.close(1008, "only SentientMilk's extension connects here")
        try:
            hello = json.loads(connection.recv(timeout=10)).get("hello") or {}
        except Exception:
            return connection.close(1008, "no hello")
        if not hmac.compare_digest(str(hello.get("token", "")).encode(), self.token.encode()):
            return connection.close(1008, "wrong code: paste the one SentientMilk shows (Tools > Her browser)")
        connection.send(json.dumps({"welcome": True}))
        self.agent = str(hello.get("agent", ""))
        wire = Wire(None, lambda session, method, params: self.browser._event(session, method, params, user=True),
                    socket=connection)
        self.browser.linked(wire)
        wire.closed.wait()
        self.browser.unlinked(wire)
