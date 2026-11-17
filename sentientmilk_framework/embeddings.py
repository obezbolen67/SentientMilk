"""What turns text into vectors for her long-term memory (recall.py, mind/memory.py): any OpenAI-compatible
``/embeddings`` service, OpenRouter by default (the user chose it, 2026-11-17; the model was picked by
measuring on her own history: scripts/recall_eval.py and the spec's "Measured"), or a stand-in for tests.

Rows come back L2-normalized float32, so a dot product is the cosine. An embedder's ``name`` says which model
and how many dimensions: vectors of two names are never compared. A query (``query=True``) is embedded once
and kept, so the recall of a turn, her mind's recall and how known a message is cost one call between them.

On OpenRouter a request goes only to providers that neither keep nor train on what is sent
(``provider.data_collection = "deny"``): these are her chats.
"""

import logging
import re
import time
import zlib
from collections import OrderedDict
from typing import List, Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "mongodb/voyage-4-large"  # the best of eight of OpenRouter's on her history (spec, "Measured")
BATCH = 64
MAX_CHARS = 8000  # what one input may be: a unit is 1,600 characters; a longer query is cut to this
QUERY_WAIT = 4.0  # s: a turn's recall waits no longer for the service; then it is by words only
KEPT_QUERIES = 64
# Qwen3 embeddings find best with an instruction on the query side (its model card)
INSTRUCTED = {"qwen3-embedding": "Instruct: Given a message, find the past conversation it is about\nQuery: "}
WORDS = re.compile(r"[^\W_]+", re.UNICODE)


class NotReady(Exception):
    """It cannot embed now (no key, the service failed): search goes by words."""


def unit(rows) -> np.ndarray:
    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class Embedder:
    name = ""
    dim = 0

    def __init__(self):
        self._kept: "OrderedDict[str, np.ndarray]" = OrderedDict()

    def embed(self, texts: List[str], query: bool = False) -> np.ndarray:
        """``texts`` as unit rows; ``query``: what is searched with (each kept, the newest 64)."""
        if not query:
            return self._embed(texts, False)
        missing = [t for t in dict.fromkeys(texts) if t not in self._kept]
        if missing:
            for text, row in zip(missing, self._embed(missing, True)):
                self._kept[text] = row
                while len(self._kept) > KEPT_QUERIES:
                    self._kept.popitem(last=False)
        return np.stack([self._kept[t] for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def _embed(self, texts: List[str], query: bool) -> np.ndarray:
        raise NotImplementedError

    def problem(self) -> Optional[str]:
        """None when it can embed now; else what stands in the way, in words."""
        return None


class StandIn(Embedder):
    """Deterministic vectors from hashed words and their letter trigrams: alike text is near. For tests;
    another ``model`` gives other vectors."""

    def __init__(self, model: str = "default", dim: int = 256):
        super().__init__()
        self.name, self.dim, self._seed = f"stand-in:{model}@{dim}", dim, model.encode()
        self.calls: List[List[str]] = []

    def _embed(self, texts: List[str], query: bool) -> np.ndarray:
        self.calls.append(list(texts))
        rows = np.zeros((len(texts), self.dim), np.float32)
        for row, text in zip(rows, texts):
            for word in WORDS.findall(text.lower()):
                padded = f"#{word}#"
                for token in [word] + [padded[i:i + 3] for i in range(len(padded) - 2)]:
                    code = zlib.crc32(self._seed + token.encode())
                    row[code % self.dim] += 1.0 if code & 0x80000000 else -1.0
        return unit(rows)


class ApiEmbedder(Embedder):
    """Any OpenAI-compatible ``/embeddings``; OpenRouter gets ``input_type`` and its no-data-collection rule."""

    def __init__(self, base_url: str, api_key: str, model: str, dimensions: int = 0):
        super().__init__()
        self.base_url, self.api_key, self.model, self.dimensions = base_url.rstrip("/"), api_key, model, dimensions
        self.name = f"api:{model}@{dimensions or 'full'}"
        self.openrouter = "openrouter.ai" in base_url
        self.prefix = next((p for k, p in INSTRUCTED.items() if k in model.lower()), "")
        self.failed: Optional[str] = None  # the last error, until a call goes through
        self.spent = 0.0  # what it cost so far, as OpenRouter counts it (credits = dollars)

    def problem(self) -> Optional[str]:
        return "no embeddings API key" if not self.api_key else self.failed

    def _embed(self, texts: List[str], query: bool) -> np.ndarray:
        if not self.api_key:
            raise NotReady("no embeddings API key")
        rows = []
        for start in range(0, len(texts), BATCH):
            rows += self._post([(self.prefix if query else "") + (t[:MAX_CHARS].strip() or "-")
                                for t in texts[start:start + BATCH]], query)
        if rows and not self.dim:
            self.dim = len(rows[0])
        return unit(rows) if rows else np.zeros((0, self.dim), np.float32)

    def _post(self, inputs: List[str], query: bool) -> list:
        body = {"model": self.model, "input": inputs, "encoding_format": "float",
                **({"dimensions": self.dimensions} if self.dimensions else {}),
                **({"input_type": "search_query" if query else "search_document",
                    "provider": {"data_collection": "deny"}} if self.openrouter else {})}
        waits = () if query else (2, 4, 8)  # a turn does not wait out retries: it goes by words this once
        for wait in (*waits, None):
            try:
                response = requests.post(f"{self.base_url}/embeddings", json=body, timeout=QUERY_WAIT if query else 60,
                                         headers={"Authorization": f"Bearer {self.api_key}"})
                if response.status_code in (429, 500, 502, 503, 504, 529) and wait is not None:
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                answer = response.json()
                data = sorted(answer["data"], key=lambda item: item.get("index", 0))
                self.spent += float((answer.get("usage") or {}).get("cost") or 0.0)
                self.failed = None
                return [item["embedding"] for item in data]
            except (requests.RequestException, KeyError, ValueError) as exc:
                if wait is not None and not isinstance(exc, requests.HTTPError):
                    time.sleep(wait)
                    continue
                detail = getattr(getattr(exc, "response", None), "text", "") or str(exc)
                self.failed = f"the embeddings service failed: {' '.join(detail.split())[:200]}"
                raise NotReady(self.failed) from exc
        raise NotReady(self.failed or "the embeddings service failed")


def make(values: dict) -> Optional[Embedder]:
    """Her embedder from the brain's settings; None when ``embeddings`` is off. Without a key of its own, a
    service at the same address as her chat model's uses that key."""
    if values.get("embeddings") == "off":
        return None
    base = values.get("embeddings_base_url") or DEFAULT_URL
    key = values.get("embeddings_api_key") or (values.get("api_key", "") if base.rstrip("/") ==
                                               (values.get("base_url") or "").rstrip("/") else "")
    return ApiEmbedder(base, key, values.get("embeddings_model") or DEFAULT_MODEL,
                       int(values.get("embeddings_dimensions") or 0))
