import json
import sys
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sentientmilk_framework import BrainClient, embeddings
from sentientmilk_framework import loop as loop_module
from sentientmilk_framework.claudecode import ClaudeCode
from sentientmilk_framework.recall import SETTINGS
from sentientmilk_framework.server import start
from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider, install_embedder, quiet_mind

FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")

SIGNALS = {"expression": {"description": "how you look", "options": {"arms_down": ["neutral", "smile"],
                                                                     "one_arm": ["neutral"]}}}
MILK = {"name": "Milk", "environment": "A desktop character.", "persona": "You are Milk.", "signals": SIGNALS,
        "toolkits": ["memory", "todo", "web", "tasks", "schedule"], "callbacks": True}  # as MilkChan
# words that say nothing of what a message is about (Meaning gives them no direction of their own)
STOP = frozenset("""the and was were what that this these those you your yours they them their she her hers his him
its our ours for are with have has had not but can could did does doing done from who why how when where which
will would there here about been just like into than then also some any all get got one out yes now well very
really too more most much many let lets okay sure please thanks thank want wanted know think said say""".split())


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
def brain(tmp_path, monkeypatch, request):
    """A brain server with a faked provider; queue replies in ``brain.provider.replies``. Her mind is quiet
    unless the test is marked ``mind``."""
    if "mind" not in request.keywords:
        quiet_mind(monkeypatch)
    monkeypatch.setattr(loop_module, "RETRIES", (0, 0, 0))
    provider = FakeProvider().install(monkeypatch, claude_code=[sys.executable, str(FAKE_CLAUDE)])
    install_embedder(monkeypatch)
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    server = start(home)
    client = BrainClient(server.url, server.token)
    client.update_config(api_key="sk-test-secret", base_url=PROVIDER_URL)
    client.declare_app("milk", **MILK)
    client.declare_app("cli", name="CLI", environment="A terminal.",
                       toolkits=["files", "shell", "web", "todo", "memory", "agents", "tasks", "schedule"])
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


class Meaning(embeddings.Embedder):
    """A test embedder that knows what means the same: words of one concept share a direction (weighing most),
    and each word has a direction of its own, so the same words are alike too, as with a real model."""

    CONCEPTS = {"game": ("game", "platformer", "pixel", "level"), "pet": ("pet", "cat", "dog", "passed", "died"),
                "tax": ("tax", "taxes", "deadline", "invoice"), "greeting": ("hi", "hello", "hey"),
                "job": ("job", "interpreter", "translator", "translates", "work")}

    def __init__(self, name="meaning@64", problem=None):
        super().__init__()
        self.name, self.dim, self._problem, self.calls = name, 64, problem, []

    def problem(self):
        return self._problem

    def _embed(self, texts, query):
        if self._problem:
            raise embeddings.NotReady(self._problem)
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            words = set(embeddings.WORDS.findall(text.lower()))
            row = np.zeros(self.dim, np.float32)
            for n, kin in enumerate(self.CONCEPTS.values()):
                row[n] = 5.0 * bool(words & set(kin))
            for word in words - STOP:
                row[8 + zlib.crc32(word.encode()) % (self.dim - 8)] += 1.0
            rows.append(row)
        return embeddings.unit(rows)


def use(brain, embedder):
    """Her long-term memory (and her mind's) embeds with ``embedder`` from now on."""
    recall = brain.brain.recall
    recall.embedder = embedder
    recall._settings = tuple(brain.brain.config.values().get(key) for key in SETTINGS)
    brain.brain.mind.memory.embedder = embedder
    return embedder


def turn(brain, app, text, **kwargs):
    events = []
    result = brain.client.turn(app, kwargs.pop("session", "main"), text, on_event=events.append, **kwargs)
    result["events"] = events
    return result
