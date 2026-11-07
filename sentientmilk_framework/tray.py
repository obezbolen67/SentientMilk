"""The brain's milk carton in the notification area (Windows) while it runs.

The brain is a background service: it runs until it is stopped, from this icon or from the control
panel, and closing the panel leaves it running. The carton says that it runs and whether it is working
(a teal dot), opens the control panel (also on a double click) and stops the brain.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from PIL import Image, ImageDraw

from .client import panel_command

ICON = Path(__file__).parent / "assets" / "icon.ico"
SIZE = 32  # icon.ico's carton without sparkles; Windows scales it to the tray's size
WORKING = (61, 220, 210, 255)  # her shading's bright teal
RING = (24, 10, 20, 255)  # dark, so the dot reads on light and dark taskbars alike
TIP = 127  # characters Windows shows in a tooltip

logger = logging.getLogger(__name__)


def carton(working: bool) -> Image.Image:
    with Image.open(ICON) as icon:
        icon.size = (SIZE, SIZE)  # pick that size from the .ico
        image = icon.convert("RGBA")
    if working:
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 20, 31, 31), fill=RING)
        draw.ellipse((22, 22, 29, 29), fill=WORKING)
    return image


class Tray:
    def __init__(self, home: Path, stop: Callable[[], None]):
        self.home, self._stop = Path(home), stop
        self._icon = None
        self._state: Optional[Tuple[bool, str]] = None

    def show(self, model: str) -> bool:
        """Put the carton up; False where there is no notification area (no desktop, no pystray)."""
        try:
            import pystray
        except Exception as exc:  # a server without a desktop: the brain runs all the same
            logger.info("No tray icon: %s", exc)
            return False
        self._state = (False, model)
        menu = pystray.Menu(
            pystray.MenuItem("Open control panel", self._open_panel, default=True),
            pystray.MenuItem(lambda _item: self._status(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Stop the brain", self._stop_brain),
        )
        self._icon = pystray.Icon("SentientMilk", carton(False), self._title(), menu)
        threading.Thread(target=self._icon.run, name="sentientmilk-tray", daemon=True).start()
        return True

    def update(self, busy: bool, model: str) -> None:
        """Redraw when the brain starts or stops working, or its model changed."""
        if self._icon is None or (busy, model) == self._state:
            return
        self._state = (busy, model)
        self._icon.icon = carton(busy)
        self._icon.title = self._title()
        self._icon.update_menu()

    def close(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    def _status(self) -> str:
        busy, model = self._state
        return f"{'Working' if busy else 'Ready'} · {model}"

    def _title(self) -> str:
        busy, model = self._state
        return f"SentientMilk: {'working' if busy else 'ready'} ({model})"[:TIP]

    def _open_panel(self, _icon=None, _item=None) -> None:
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(panel_command(self.home), cwd=self.home, creationflags=flags)

    def _stop_brain(self, _icon=None, _item=None) -> None:
        self.close()
        self._stop()
