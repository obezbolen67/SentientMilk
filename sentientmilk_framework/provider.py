"""One call to an OpenAI-compatible chat completions endpoint: messages in, one message out."""

import json
import logging
from copy import deepcopy
from typing import Callable, List, Optional, Tuple

import requests

from .thinking import thinking_request_options

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = (15.0, 180.0)


def usage_summary(usage: Optional[dict]) -> dict:
    """Token counts in one shape; cache hits come as DeepSeek or OpenAI report them."""
    usage = usage or {}
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    return {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": cached,
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}


def _merge(previous, value):
    """Reassemble streamed fields (reasoning_content and the like) without losing provider data."""
    if isinstance(value, str):
        return (previous or "") + value
    if isinstance(value, dict):
        result = deepcopy(previous) if isinstance(previous, dict) else {}
        for key, item in value.items():
            if key in ("id", "type", "format", "index"):
                result[key] = deepcopy(item)
            elif item is not None:
                result[key] = _merge(result.get(key), item)
        return result
    if isinstance(value, list):
        return (deepcopy(previous) if isinstance(previous, list) else []) + deepcopy(value)
    return deepcopy(value)


def _merge_tool_delta(cache: dict, delta: dict) -> None:
    index = int(delta.get("index", len(cache)))
    current = cache.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    for key in ("id", "type"):
        if delta.get(key):
            current[key] = delta[key]
    function = delta.get("function") or {}
    if function.get("name"):
        current["function"]["name"] = function["name"]
    current["function"]["arguments"] += function.get("arguments") or ""


class Provider:
    def __init__(self, base_url: str, api_key: str, model: str, *, thinking_mode: str = "default",
                 thinking_tokens: int = 4096, stream: bool = True):
        self.base_url, self.api_key, self.model, self.stream = base_url, api_key, model, stream
        self.options = thinking_request_options(base_url, thinking_mode, thinking_tokens)

    def complete(self, messages: List[dict], tools: Optional[List[dict]] = None,
                 on_text: Optional[Callable[[str], None]] = None, stopped=None) -> Tuple[dict, dict]:
        """The assistant message (as the provider sent it, reasoning included) and its usage. ``stopped``: an
        Event the caller sets when it no longer waits (a request is simply left behind here)."""
        payload = {"model": self.model, "messages": messages, **self.options}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        stream = self.stream and on_text is not None
        if stream:
            payload.update(stream=True, stream_options={"include_usage": True})
        response = requests.post(f"{self.base_url}/chat/completions", data=json.dumps(payload, ensure_ascii=False),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {self.api_key}"},
                                 timeout=REQUEST_TIMEOUT, stream=stream)
        try:
            try:
                response.raise_for_status()
            except requests.HTTPError:
                response.text  # read before it closes below: a 400's words on why reached no one
                raise
            if stream:
                return self._read_stream(response, on_text)
            completion = response.json()
        finally:
            response.close()
        message = ((completion.get("choices") or [{}])[0]).get("message")
        if not isinstance(message, dict):
            raise RuntimeError("The provider returned no assistant message")
        message.setdefault("role", "assistant")
        return message, usage_summary(completion.get("usage"))

    @staticmethod
    def _read_stream(response, on_text: Callable[[str], None]) -> Tuple[dict, dict]:
        text, extra, tools, usage, finished = "", {}, {}, None, False
        response.encoding = "utf-8"  # SSE is UTF-8 whatever charset requests guesses
        for line in response.iter_lines(chunk_size=None, decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            if line.strip() == "data: [DONE]":
                break
            try:
                chunk = json.loads(line[len("data: "):])
            except ValueError:
                logger.warning("Skipped an unreadable stream chunk: %.200s", line)
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            for key, value in delta.items():
                if key not in ("content", "tool_calls", "role") and value is not None:
                    extra[key] = _merge(extra.get(key), value)
            if delta.get("content"):
                text += delta["content"]
                on_text(delta["content"])
            for tool_delta in delta.get("tool_calls") or []:
                _merge_tool_delta(tools, tool_delta)
            finished = finished or bool(choice.get("finish_reason"))
        if not finished:
            raise RuntimeError("The provider's stream ended early; the incomplete reply was not kept")
        message = {"role": "assistant", "content": text, **extra}
        if tools:
            message["tool_calls"] = [tools[index] for index in sorted(tools)]
        return message, usage_summary(usage)
