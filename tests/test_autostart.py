"""Start with Windows: the Run key entry, Task Manager's off switch, and the panel's switch."""

import os
import secrets
import sys

import pytest
from textual.widgets import Switch

from sentientmilk_framework import autostart, cli, client

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows' Startup apps")


@pytest.fixture
def run_key(monkeypatch):
    """A throwaway key in place of the real Run key: tests never touch what starts with Windows."""
    import winreg

    base = rf"Software\SentientMilkTests\{secrets.token_hex(4)}"
    monkeypatch.setattr(autostart, "RUN", base + r"\Run")
    monkeypatch.setattr(autostart, "APPROVED", base + r"\Approved")
    yield base
    for key in (base + r"\Run", base + r"\Approved", base, r"Software\SentientMilkTests"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:  # gone already, or another run's keys are in it
            pass


def turned_off_in_task_manager(name):
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.APPROVED, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, bytes([3]) + bytes(11))  # as Task Manager writes it


def test_an_app_starts_with_windows_until_turned_off_here_or_in_task_manager(run_key):
    assert not autostart.enabled("Tiny")
    autostart.set_enabled("Tiny", [r"C:\Program Files\Tiny\Tinyw.exe", "--home", r"C:\Users\me\.tiny", "start"])
    assert autostart._read(autostart.RUN, "Tiny") == r'"C:\Program Files\Tiny\Tinyw.exe" --home C:\Users\me\.tiny start'
    assert autostart.enabled("Tiny")
    turned_off_in_task_manager("Tiny")
    assert not autostart.enabled("Tiny")  # Windows would not start it: it reads as off
    autostart.set_enabled("Tiny", ["Tiny.exe"])  # on again here: Task Manager's off goes
    assert autostart.enabled("Tiny") and autostart._read(autostart.APPROVED, "Tiny") is None
    autostart.set_enabled("Tiny", None)
    assert not autostart.enabled("Tiny") and autostart._read(autostart.RUN, "Tiny") is None
    autostart.set_enabled("Tiny", None)  # already off: nothing to do


def test_windows_starts_the_brain_with_no_console(tmp_path, monkeypatch):
    (tmp_path / "SentientMilk.exe").touch()
    assert autostart.windowless(tmp_path / "SentientMilk.exe") == tmp_path / "SentientMilk.exe"  # no twin: itself
    (tmp_path / "SentientMilkw.exe").touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SentientMilk.exe"))
    home = tmp_path / "home"
    assert client.start_command(home) == [str(tmp_path / "SentientMilkw.exe"), "-m", "sentientmilk_framework",
                                          "--home", str(home), "start"]


def test_start_brings_the_brain_up_and_leaves_the_recorded_command_alone(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(cli, "connect", started.append)
    cli.main(["--home", str(tmp_path), "start"])
    assert started == [tmp_path.resolve()]
    assert not (tmp_path / client.LAUNCH_FILE).exists()  # the windowless program never becomes the brain's


def test_the_panel_switch_is_windows_own(brain, run_key):
    from test_panel import run

    async def scenario(panel, pilot):
        switch = panel.query_one("#autostart", Switch)
        assert switch.value is False
        switch.value = True
        await pilot.pause(0.2)
        assert autostart.enabled("SentientMilk")
        assert autostart._read(autostart.RUN, "SentientMilk").endswith(f"--home {brain.home} start")
        turned_off_in_task_manager("SentientMilk")
        panel.load_overview()
        await pilot.pause(0.1)
        assert switch.value is False  # as Task Manager left it, and nothing written back
        assert autostart._read(autostart.RUN, "SentientMilk") is not None
        switch.value = True
        await pilot.pause(0.2)
        assert autostart.enabled("SentientMilk")
        switch.value = False
        await pilot.pause(0.2)
        assert autostart._read(autostart.RUN, "SentientMilk") is None
    run(brain, scenario)
