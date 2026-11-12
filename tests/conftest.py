import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentientmilk_framework import BrainClient
from sentientmilk_framework import loop as loop_module
from sentientmilk_framework.claudecode import ClaudeCode
from sentientmilk_framework.server import start
from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider

FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")

SIGNALS = {"expression": {"description": "how you look", "options": {"arms_down": ["neutral", "smile"],
                                                                     "one_arm": ["neutral"]}}}
MILK = {"name": "Milk", "environment": "A desktop character.", "persona": "You are Milk.", "signals": SIGNALS,
        "toolkits": ["memory", "todo", "journal", "web", "tasks", "schedule"], "callbacks": True}  # as MilkChan


def wait_for(check, timeout=10.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out waiting")


@pytest.fixture(autouse=True)
def stand_in_claude_code(tmp_path, monkeypatch):
    """Never the user's own Claude Code: a stand-in (fake_claude.py) that logs how it was started and what it
    was told (claude_log)."""
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "claude.log"))
    monkeypatch.setattr(ClaudeCode, "argv", lambda self: [sys.executable, str(FAKE_CLAUDE)])


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A brain server with a faked provider; queue replies in ``brain.provider.replies``."""
    monkeypatch.setattr(loop_module, "RETRIES", (0, 0, 0))
    provider = FakeProvider().install(monkeypatch, claude_code=[sys.executable, str(FAKE_CLAUDE)])
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    server = start(home)
    client = BrainClient(server.url, server.token)
    client.update_config(api_key="sk-test-secret", base_url=PROVIDER_URL)
    client.declare_app("milk", **MILK)
    client.declare_app("cli", name="CLI", environment="A terminal.",
                       toolkits=["files", "shell", "web", "todo", "memory", "journal", "agents", "tasks", "schedule"])
    client.update_session("cli", "main", cwd=str(work), roots=[str(work)])
    yield SimpleNamespace(client=client, server=server, provider=provider, home=home, work=work,
                          brain=server.brain, store=server.brain.store)
    server.close()


def claude_log(tmp_path) -> list:
    """What the stand-in Claude Code logged: each start ({args, cwd, mcp, system, appended, provider}) and
    what it was told ({said}, {meanwhile}, {tools}), in order."""
    path = tmp_path / "claude.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def claude_starts(tmp_path) -> list:
    """The stand-in's starts for work (not its questions about itself)."""
    return [entry for entry in claude_log(tmp_path) if "args" in entry and "--model" in entry["args"]]


def turn(brain, app, text, **kwargs):
    events = []
    result = brain.client.turn(app, kwargs.pop("session", "main"), text, on_event=events.append, **kwargs)
    result["events"] = events
    return result
