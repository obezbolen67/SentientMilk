"""A stand-in provider for tests (SentientMilk's and apps'): queue replies, read what was sent.

    provider = FakeProvider().install(monkeypatch)
    provider.replies += ["Hello", tool_call("files_read", {"path": "a.txt"}), "Done"]

A reply is text, an assistant message dict, an HTTP status (int) to fail with, or a function
of the request payload returning one of those. Streaming requests get a real SSE stream.
Journal notes are written in the background at unpredictable moments, so they are answered
with ``journal_note`` and recorded in ``journal_requests``, never taken from ``replies``.
"""

import json
from types import SimpleNamespace
from typing import Any, List, Sequence

import requests

PROVIDER_URL = "https://provider.invalid/v1"


def tool_call(name: str, arguments: dict, call_id: str = "", content: str = "") -> dict:
    call_id = call_id or f"call_{name}_{abs(hash(json.dumps(arguments, sort_keys=True))) % 10**8}"
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def tool_calls(*calls: tuple) -> dict:
    """Several calls in one message: tool_calls(("a", {...}), ("b", {...}))."""
    message = {"role": "assistant", "content": "", "tool_calls": []}
    for index, (name, arguments) in enumerate(calls):
        message["tool_calls"].append({"id": f"call_{index}_{name}", "type": "function",
                                      "function": {"name": name, "arguments": json.dumps(arguments)}})
    return message


class _Failure:
    def __init__(self, status: int):
        self.status_code, self.text, self.url = status, f"fake error {status}", PROVIDER_URL

    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code}", response=self)

    def close(self):
        pass


class _Stream:
    def __init__(self, message: dict, usage: dict):
        self.message, self.usage, self.encoding = message, usage, None

    def raise_for_status(self):
        pass

    def close(self):
        pass

    def iter_lines(self, chunk_size=None, decode_unicode=False):
        content = self.message.get("content") or ""
        half = len(content) // 2
        for piece in (content[:half], content[half:]):
            if piece:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]})
        if self.message.get("reasoning_content"):
            yield "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": self.message["reasoning_content"]}}]})
        for index, call in enumerate(self.message.get("tool_calls") or []):
            yield "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
                {"index": index, "id": call["id"], "type": "function",
                 "function": {"name": call["function"]["name"], "arguments": call["function"]["arguments"]}}]}}]})
        yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        yield "data: " + json.dumps({"choices": [], "usage": self.usage})
        yield "data: [DONE]"


class FakeProvider:
    def __init__(self, url: str = PROVIDER_URL):
        self.url = url
        self.replies: List[Any] = []
        self.sent: List[dict] = []
        self.usage = {"prompt_tokens": 100, "completion_tokens": 10, "prompt_cache_hit_tokens": 60}
        self.journal_note = "Talked with the user."
        self.journal_requests: List[dict] = []
        self.title = "A chat"
        self.title_requests: List[dict] = []

    def install(self, monkeypatch, claude_code: Sequence[str] = ()) -> "FakeProvider":
        """``claude_code``: the command line of a stand-in Claude Code; empty: the brain finds none (a test
        never reaches the user's own)."""
        from .claudecode import ClaudeCode

        monkeypatch.setattr(ClaudeCode, "argv", lambda self: list(claude_code))
        real = requests.post

        def post(url, *args, **kwargs):
            if not url.startswith(self.url):
                return real(url, *args, **kwargs)
            return self.respond(json.loads(kwargs["data"]))

        monkeypatch.setattr(requests, "post", post)
        return self

    def respond(self, payload: dict):
        from .journal import PROMPT
        from .titles import PROMPT as TITLE_PROMPT

        if payload["messages"][0].get("content") == TITLE_PROMPT:
            self.title_requests.append(payload)
            return SimpleNamespace(raise_for_status=lambda: None, close=lambda: None, json=lambda: {
                "choices": [{"message": {"role": "assistant", "content": self.title}}]})
        if payload["messages"][0].get("content") == PROMPT:
            self.journal_requests.append(payload)
            return SimpleNamespace(raise_for_status=lambda: None, close=lambda: None, json=lambda: {
                "choices": [{"message": {"role": "assistant", "content": self.journal_note}}]})
        self.sent.append(payload)
        reply = self.replies.pop(0) if self.replies else "OK"
        if callable(reply):
            reply = reply(payload)
        if isinstance(reply, int):
            return _Failure(reply)
        message = {"role": "assistant", "content": reply} if isinstance(reply, str) else dict(reply)
        if payload.get("stream"):
            return _Stream(message, self.usage)
        return SimpleNamespace(raise_for_status=lambda: None, close=lambda: None,
                               json=lambda: {"choices": [{"finish_reason": "stop", "message": message}],
                                             "usage": self.usage})

    def last_user_text(self) -> str:
        """The text of the newest user message of the last request."""
        message = next(m for m in reversed(self.sent[-1]["messages"]) if m["role"] == "user")
        content = message["content"]
        return content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content)
