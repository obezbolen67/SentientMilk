import base64
import io
import json

import pytest
from PIL import Image

from sentientmilk_framework import signals, transport
from sentientmilk_framework.thinking import thinking_request_options


def data_url(size, kind="PNG"):
    output = io.BytesIO()
    Image.effect_noise(size, 60).convert("RGB").save(output, kind)
    return f"data:image/{kind.lower()};base64,{base64.b64encode(output.getvalue()).decode()}"


def image_side(url):
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        return max(image.size), image.format


def images(messages):
    return [block["image_url"]["url"] for m in messages if isinstance(m["content"], list)
            for block in m["content"] if block.get("type") == "image_url"]


def test_only_the_newest_screenshots_are_sent():
    small = data_url((40, 30))
    messages = [{"role": "user", "content": [{"type": "text", "text": f"turn {i}"},
                                             {"type": "image_url", "image_url": {"url": small}}]}
                for i in range(1000)]
    original = json.dumps(messages)
    projected = transport.prepare_messages(messages, 800 * 1024)
    assert json.dumps(messages) == original
    assert len(images(projected)) == transport.THUMBNAILS_KEPT + 1
    assert projected[0]["content"] == f"turn 0\n{transport.OMITTED_IMAGE}"
    assert image_side(images(projected)[-1])[1] == "JPEG"


def test_over_budget_drops_thumbnails_then_shrinks_the_newest():
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url((900, 600))}}]}
                for _ in range(4)]
    full = transport.prepare_messages(messages, 10 ** 9)
    size = len(json.dumps(full, separators=(",", ":")).encode())
    fewer = transport.prepare_messages(messages, size - 1)
    assert len(images(fewer)) == 3
    assert image_side(images(fewer)[-1])[0] == 768

    newest_only = transport.prepare_messages(messages[-1:], 10 ** 9)
    size = len(json.dumps(newest_only, separators=(",", ":")).encode())
    shrunk = transport.prepare_messages(messages[-1:], size - 1)
    assert image_side(images(shrunk)[0])[0] == 512

    with pytest.raises(transport.RequestPayloadTooLarge):
        transport.prepare_messages(messages, 100)


@pytest.mark.parametrize("base_url,mode,tokens,expected", [
    ("https://example.invalid/v1", "default", 4096, {}),
    ("https://example.invalid/v1", "high", 4096, {"reasoning_effort": "high"}),
    ("https://example.invalid/v1", "none", 4096, {"reasoning_effort": "none"}),
    ("https://openrouter.ai/api/v1", "low", 4096, {"reasoning": {"effort": "low"}}),
    ("https://openrouter.ai/api/v1", "none", 4096, {"reasoning": {"enabled": False}}),
    ("https://example.invalid/v1", "tokens", 8192, {"reasoning": {"max_tokens": 8192}}),
    ("https://openrouter.ai.evil.invalid/v1", "high", 4096, {"reasoning_effort": "high"}),
])
def test_thinking_budget_payload(base_url, mode, tokens, expected):
    assert thinking_request_options(base_url, mode, tokens) == expected


@pytest.mark.parametrize("mode,tokens", [("invalid", 4096), ("tokens", 0), ("tokens", True)])
def test_invalid_thinking_budget_is_rejected(mode, tokens):
    with pytest.raises(ValueError):
        thinking_request_options("https://example.invalid/v1", mode, tokens)


SPEC = signals.validate({"expression": {"options": {"arms_down": ["neutral", "smile"]}}, "tone": {"options": ["calm"]}})


@pytest.mark.parametrize("text, header, reply", [
    ('{"expression": "arms_down/smile"}\nHello', {"expression": "arms_down/smile"}, "Hello"),
    ('\n```json\n{"expression": "arms_down/smile"}\n```\nHi', {"expression": "arms_down/smile"}, "Hi"),
    ("plain reply", None, "plain reply"),
    ('{broken\nreply', None, '{broken\nreply'),
    ('["a"]\nx', None, '["a"]\nx'),
])
def test_signal_headers_split_off_the_reply(text, header, reply):
    assert signals.split(text) == (header, reply)


def test_signal_values_are_checked_against_the_declared_options():
    assert signals.check({"expression": "arms_down/smile", "tone": "calm"}, SPEC) == (
        {"expression": "arms_down/smile", "tone": "calm"}, [])
    values, problems = signals.check({"expression": "arms_up/smile"}, SPEC)
    assert values == {} and len(problems) == 2
    assert signals.check(None, SPEC)[1]


def test_streamed_text_never_shows_the_header():
    seen, text = [], []
    stream = signals.HeaderStream(seen.append, text.append)
    for piece in ['{"expr', 'ession": "arms_down/smile"}', "\nHel", "lo"]:
        stream.feed(piece)
    assert seen == [{"expression": "arms_down/smile"}] and "".join(text) == "Hello"
    seen.clear(), text.clear()
    stream.reset()
    for piece in ["No ", "header"]:
        stream.feed(piece)
    assert seen == [] and "".join(text) == "No header"

