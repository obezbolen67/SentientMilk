import time
from types import SimpleNamespace

import pytest

from sentientmilk_framework import BrainClient
from sentientmilk_framework import loop as loop_module
from sentientmilk_framework.server import start
from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider

SIGNALS = {"expression": {"description": "how you look", "options": {"arms_down": ["neutral", "smile"],
                                                                     "one_arm": ["neutral"]}}}
MILK = {"name": "Milk", "environment": "A desktop character.", "persona": "You are Milk.", "signals": SIGNALS,
        "toolkits": ["memory", "todo", "journal", "web", "tasks", "schedule"]}


def wait_for(check, timeout=10.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out waiting")


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A brain server with a faked provider; queue replies in ``brain.provider.replies``."""
    monkeypatch.setattr(loop_module, "RETRIES", (0, 0, 0))
    provider = FakeProvider().install(monkeypatch)
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


def turn(brain, app, text, **kwargs):
    events = []
    result = brain.client.turn(app, kwargs.pop("session", "main"), text, on_event=events.append, **kwargs)
    result["events"] = events
    return result
