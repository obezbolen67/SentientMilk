import json

import pytest

import sentientmilk_framework.ai as ai_module
from sentientmilk_framework import LLM, Settings


class FakeResponse:
    def __init__(self, *, payload=None, events=None):
        self._payload = payload
        self._events = events or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self, **_kwargs):
        for event in self._events:
            yield "data: " + json.dumps(event)
        yield "data: [DONE]"


def make_llm(tmp_path, handler=None, max_tool_rounds=8):
    return LLM(
        api_key="test",
        base_url="https://example.invalid/v1",
        model="test-model",
        settings=Settings(custom_tools_path=tmp_path / "missing"),
        tool_event_handler=handler,
        max_tool_rounds=max_tool_rounds,
    )


def test_non_streaming_events_keep_the_provider_call_id(monkeypatch, tmp_path):
    first = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-123",
                    "type": "function",
                    "function": {"name": "read", "arguments": json.dumps({"file": str(tmp_path / "x.txt")})},
                }],
            },
        }]
    }
    second = {"choices": [{"finish_reason": "stop", "message": {"content": "done"}}]}
    (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
    responses = iter([FakeResponse(payload=first), FakeResponse(payload=second)])
    monkeypatch.setattr(ai_module.requests, "post", lambda *args, **kwargs: next(responses))
    events = []

    result = make_llm(tmp_path, events.append).completion([{"role": "user", "content": "read"}])

    assert result == second
    assert [event["call_id"] for event in events] == ["call-123", "call-123"]
    assert [event["type"] for event in events] == ["tool_start", "tool_end"]


def test_streaming_preserves_parallel_tool_calls(monkeypatch, tmp_path):
    first_events = [
        {"choices": [{"finish_reason": None, "delta": {"tool_calls": [
            {"index": 0, "id": "a", "type": "function", "function": {"name": "read", "arguments": '{"file":"'}},
            {"index": 1, "id": "b", "type": "function", "function": {"name": "read", "arguments": '{"file":"'}},
        ]}}]},
        {"choices": [{"finish_reason": "tool_calls", "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": str(tmp_path / "a.txt").replace("\\", "\\\\") + '"}'}},
            {"index": 1, "function": {"arguments": str(tmp_path / "b.txt").replace("\\", "\\\\") + '"}'}},
        ]}}]},
    ]
    final_events = [{"choices": [{"finish_reason": "stop", "delta": {"content": "done"}}]}]
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    responses = iter([FakeResponse(events=first_events), FakeResponse(events=final_events)])
    monkeypatch.setattr(ai_module.requests, "post", lambda *args, **kwargs: next(responses))
    events = []

    chunks = list(make_llm(tmp_path, events.append).completion([{"role": "user", "content": "read both"}], stream=True))

    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "done"
    assert [(e["type"], e["call_id"]) for e in events] == [
        ("tool_start", "a"), ("tool_end", "a"),
        ("tool_start", "b"), ("tool_end", "b"),
    ]


def test_tool_round_limit_stops_recursive_model_loops(monkeypatch, tmp_path):
    payload = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": "", "tool_calls": [{
                "id": "loop",
                "type": "function",
                "function": {"name": "read", "arguments": json.dumps({"file": str(tmp_path / "x.txt")})},
            }]},
        }]
    }
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ai_module.requests, "post", lambda *args, **kwargs: FakeResponse(payload=payload))

    with pytest.raises(RuntimeError, match="tool-call round limit"):
        make_llm(tmp_path, max_tool_rounds=2).completion([{"role": "user", "content": "loop"}])

