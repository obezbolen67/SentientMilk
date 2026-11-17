"""What turns text into vectors: the stand-in tests use, and any OpenAI-compatible service (OpenRouter)."""

from types import SimpleNamespace

import numpy as np
import pytest
import requests

from sentientmilk_framework import BrainError, embeddings
from sentientmilk_framework.embeddings import ApiEmbedder, NotReady, StandIn


def test_the_stand_in_is_deterministic_and_alike_text_is_nearer():
    e = StandIn()
    a, b, c = e.embed(["a pixel art game idea", "an idea for a pixel game", "tax deadline"])
    assert np.allclose(np.linalg.norm(e.embed(["x y z", "w"]), axis=1), 1.0)
    assert a @ b > a @ c and np.array_equal(e.embed(["tax deadline"])[0], c)
    assert not np.array_equal(StandIn("other").embed(["tax deadline"])[0], c)  # another model, other vectors


class Service:
    """A stand-in /embeddings: answers each input with a vector, records what it was sent."""

    def __init__(self, monkeypatch):
        self.bodies, self.fail = [], []
        monkeypatch.setattr(requests, "post", self.post)
        monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)

    def post(self, url, json=None, headers=None, timeout=None):
        self.bodies.append({"url": url, "timeout": timeout, **json})
        status = self.fail.pop(0) if self.fail else 200

        def raise_for_status():
            if status >= 400:
                raise requests.HTTPError(f"{status}", response=SimpleNamespace(text=f"error {status}"))
        data = [{"index": i, "embedding": [float(len(text)), 1.0, 0.0]} for i, text in enumerate(json["input"])]
        return SimpleNamespace(status_code=status, raise_for_status=raise_for_status,
                               json=lambda: {"data": list(reversed(data)), "usage": {"cost": 0.001}})


def test_a_service_is_asked_in_batches_and_openrouter_never_keeps_her_chats(monkeypatch):
    service = Service(monkeypatch)
    e = ApiEmbedder("https://openrouter.ai/api/v1", "k", "qwen/qwen3-embedding-8b")
    rows = e.embed([f"text {i}" for i in range(130)])
    assert rows.shape == (130, 3) and [len(b["input"]) for b in service.bodies] == [64, 64, 2]
    assert service.bodies[0]["input_type"] == "search_document"
    assert service.bodies[0]["provider"] == {"data_collection": "deny"}
    assert service.bodies[0]["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert np.allclose(np.linalg.norm(rows, axis=1), 1.0) and e.spent == pytest.approx(0.003)
    e.embed(["hello"], query=True)
    assert service.bodies[-1]["input"][0].startswith("Instruct: ") and service.bodies[-1]["input_type"] == "search_query"
    e.embed(["hello"], query=True)
    assert len(service.bodies) == 4  # a query is embedded once: a turn's recall, her mind's and known share it


def test_another_service_gets_plain_openai_requests(monkeypatch):
    service = Service(monkeypatch)
    ApiEmbedder("https://api.openai.com/v1", "k", "text-embedding-3-small", dimensions=256).embed(["a"], query=True)
    assert "provider" not in service.bodies[0] and "input_type" not in service.bodies[0]
    assert service.bodies[0]["dimensions"] == 256 and service.bodies[0]["input"] == ["a"]


def test_indexing_waits_out_a_busy_service_but_a_turn_does_not(monkeypatch):
    service = Service(monkeypatch)
    e = ApiEmbedder(embeddings.DEFAULT_URL, "k", "m")
    service.fail = [429, 503]
    assert e.embed(["a"]).shape == (1, 3) and len(service.bodies) == 3
    service.fail = [429]
    with pytest.raises(NotReady):
        e.embed(["now"], query=True)  # a turn goes by words this once
    assert "429" in e.problem() and service.bodies[-1]["timeout"] == embeddings.QUERY_WAIT
    e.embed(["fine"])
    assert e.problem() is None


def test_without_a_key_nothing_is_sent_and_it_says_why(monkeypatch):
    service = Service(monkeypatch)
    e = embeddings.make({"embeddings": "api", "embeddings_base_url": "", "embeddings_api_key": "",
                         "base_url": "https://api.refuseless.com/v1", "api_key": "chat-key"})
    with pytest.raises(NotReady):
        e.embed(["a"])
    assert e.problem() == "no embeddings API key" and not service.bodies
    same = embeddings.make({"embeddings": "api", "embeddings_base_url": "https://openrouter.ai/api/v1",
                            "base_url": "https://openrouter.ai/api/v1/", "api_key": "chat-key"})
    assert same.api_key == "chat-key" and same.model == embeddings.DEFAULT_MODEL  # her chat model's key, same place
    assert embeddings.make({"embeddings": "off"}) is None


def test_embeddings_settings_are_checked_and_the_key_stays_secret(brain):
    with pytest.raises(BrainError):
        brain.client.update_config(embeddings="cloud")
    with pytest.raises(BrainError):
        brain.client.update_config(embeddings_base_url="ftp://x")
    brain.client.update_config(embeddings_base_url="https://openrouter.ai/api/v1/embeddings", embeddings_api_key="s")
    shown = brain.client.config()
    assert shown["embeddings_base_url"] == "https://openrouter.ai/api/v1" and shown["embeddings_api_key_set"]
    assert "embeddings_api_key" not in shown
