"""The brain is a background service: it runs until it is stopped, and its milk carton in the notification
area shows that it runs, whether it is working, opens the control panel and stops it."""

import subprocess
import sys
import threading
import types

import pytest

from sentientmilk_framework import config, server, tray


class FakeIcon:
    """pystray.Icon, recorded: tests put up no real icon."""

    made = []

    def __init__(self, name, icon=None, title="", menu=None):
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.ran, self.stopped, self.menu_updates = threading.Event(), False, 0
        FakeIcon.made.append(self)

    def run(self):
        self.ran.set()

    def stop(self):
        self.stopped = True

    def update_menu(self):
        self.menu_updates += 1


class FakeItem:
    def __init__(self, text, action, default=False, enabled=True):
        self.text, self.action, self.default, self.enabled = text, action, default, enabled

    def label(self):
        return self.text(self) if callable(self.text) else self.text


class FakeMenu:
    SEPARATOR = FakeItem("-", None)

    def __init__(self, *items):
        self.items = items


@pytest.fixture
def pystray(monkeypatch):
    module = types.ModuleType("pystray")
    module.Icon, module.MenuItem, module.Menu = FakeIcon, FakeItem, FakeMenu
    monkeypatch.setitem(sys.modules, "pystray", module)
    FakeIcon.made.clear()
    return module


def entries(icon):
    return [item for item in icon.menu.items if item is not FakeMenu.SEPARATOR]


def test_the_carton_says_the_brain_runs_and_whether_it_is_working(pystray, tmp_path):
    shown = tray.Tray(tmp_path, stop=lambda: None)
    assert shown.show("deepseek-v4.1-flash-fast")
    icon = FakeIcon.made[0]
    assert icon.ran.wait(2)  # its own thread: the brain goes on
    assert icon.icon.size == (32, 32) and icon.icon.mode == "RGBA"
    left, top, right, bottom = icon.icon.getbbox()
    assert max(right - left, bottom - top) >= 31  # the carton fills the tray's tiny square, no margins
    assert icon.title == "SentientMilk: ready (deepseek-v4.1-flash-fast)"
    ready = icon.icon.tobytes()
    shown.update(busy=True, model="deepseek-v4.1-flash-fast")
    assert icon.title.startswith("SentientMilk: working") and icon.icon.tobytes() != ready  # a dot on the carton
    assert [item.label() for item in entries(icon) if not item.enabled] == ["Working · deepseek-v4.1-flash-fast"]
    updates = icon.menu_updates
    shown.update(busy=True, model="deepseek-v4.1-flash-fast")  # nothing changed: nothing redrawn
    assert icon.menu_updates == updates
    shown.update(busy=False, model="glm-5.3")
    assert icon.icon.tobytes() == ready and icon.title == "SentientMilk: ready (glm-5.3)"
    shown.update(busy=False, model="m" * 200)
    assert len(icon.title) <= 127  # Windows' limit for a tooltip
    shown.close()
    assert icon.stopped


def test_the_carton_opens_the_control_panel_and_stops_the_brain(pystray, tmp_path, monkeypatch):
    started, stops = [], []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda command, **options: started.append((command, options)))
    shown = tray.Tray(tmp_path, stop=lambda: stops.append(True))
    shown.show("deepseek-v4.1-flash-fast")
    icon = FakeIcon.made[0]
    opening = next(item for item in entries(icon) if item.default)  # also a double click on the icon
    assert opening.label() == "Open control panel"
    opening.action(icon, opening)
    command, options = started[0]
    assert command[-2:] == ["--home", str(tmp_path)] and "serve" not in command
    if sys.platform == "win32":
        assert options["creationflags"] & subprocess.CREATE_NEW_CONSOLE  # the panel gets its own window
    stopping = next(item for item in entries(icon) if item.label() == "Stop the brain")
    stopping.action(icon, stopping)
    assert stops == [True] and icon.stopped


def test_without_a_notification_area_the_brain_runs_all_the_same(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pystray", None)  # importing it fails
    shown = tray.Tray(tmp_path, stop=lambda: None)
    assert not shown.show("deepseek-v4.1-flash-fast")
    shown.update(busy=True, model="deepseek-v4.1-flash-fast")
    shown.close()


def test_the_brain_serves_with_its_carton_until_it_is_stopped_never_on_idle(tmp_path, monkeypatch):
    assert "idle_exit_minutes" not in config.DEFAULTS  # a service: it never stops on its own
    seen = []

    class Carton:
        def __init__(self, home, stop):
            self.stop = stop
            seen.append(("made", home))

        def show(self, model):
            seen.append(("shown", model))
            self.stop()  # the user stops it from the tray
            return True

        def update(self, busy, model):
            pass

        def close(self):
            seen.append(("closed",))

    monkeypatch.setattr(server, "Tray", Carton)
    done = threading.Thread(target=server.serve, args=(tmp_path / "brain",), daemon=True)
    done.start()
    done.join(20)
    assert not done.is_alive()
    assert seen[0] == ("made", tmp_path / "brain") and seen[1][0] == "shown" and seen[-1] == ("closed",)
    assert not (tmp_path / "brain" / "server.json").exists()  # withdrawn: apps see it is down
