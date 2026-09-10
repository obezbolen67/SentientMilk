from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import pathlib
import warnings
from copy import deepcopy
from ctypes import ArgumentError
from importlib import import_module
from pkgutil import iter_modules
from typing import Any, Callable, Dict, Optional, Tuple, get_args, get_origin, get_type_hints

import requests

from . import exceptions
from . import tools as tools_pkg
from .conversation import Conversation


class Settings:
    def __init__(self, persona=None, custom_tools_path=None, stream_include_usage=False):
        module_dir = pathlib.Path(__file__).parent
        self.persona = persona if persona else ""
        self.stream_include_usage = stream_include_usage
        self.custom_tools_path = custom_tools_path if custom_tools_path else module_dir / "custom_tools"


class LLM:
    def __init__(
        self,
        api_key=None,
        base_url=None,
        model: str = "",
        settings: Optional[Settings] = None,
        modules: Optional[Any] = None,
        request_timeout: Optional[Tuple[float, float]] = None,
        tool_event_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
        web_search_token: Optional[str] = None,
        WEB_SEARCH_TOKEN: Optional[str] = None,
        max_tool_rounds: int = 8,
    ):
        if not api_key or not base_url or not model:
            raise(exceptions.LLMError("Credentials are not set."))

        self.settings = settings if settings else Settings()
        
        self.base_url = base_url

        self.api_key = api_key
        
        self.modules = modules
        self._loaded_tools = {}
        self._tool_event_handler = tool_event_handler
        self.max_tool_rounds = max(1, int(max_tool_rounds))
        self.last_messages = []
        self.usage_rounds = []
        self._tools = self._get_tools()
        self._custom_tools = self._load_custom_tools()

        self._timeout: Tuple[float, float] = request_timeout if request_timeout else (10.0, 120.0)

        self._system_prompt = self._compose_system_prompt()
        
        self.model = model

        brave_token = web_search_token or WEB_SEARCH_TOKEN
        if brave_token:
            os.environ["BRAVE_API_KEY"] = brave_token


    def _format_tool_result(self, result: Any) -> str:
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                return str(result)
        return str(result)

    def _emit_tool_event(self, payload: Dict[str, Any]):
        if not self._tool_event_handler:
            return
        try:
            self._tool_event_handler(payload)
        except Exception as handler_error:
            logging.warning(f"Tool event handler raised an exception: {handler_error}")


    def _load_tool(self, tool_name, module = None, path = ""):
        if module:
            module = import_module(f"{module.__name__}.{tool_name}")
            self._loaded_tools.update({tool_name: module})
            return module
        elif path:
            tool_path = pathlib.Path(path) / f"{tool_name}.py"
            if not tool_path.exists():
                raise FileNotFoundError("No such tool.")
            spec = importlib.util.spec_from_file_location(f"custom_tool.{tool_name}", tool_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Couldn't load this {tool_name} tool")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._loaded_tools.update({tool_name: module})
            return module
        else:
            raise ArgumentError("Please specify at least path to module")
        


    def _load_custom_tools(self):
        tools = []
        custom_path = self.settings.custom_tools_path
        if not custom_path or not pathlib.Path(custom_path).exists():
            return tools
            
        for module_info in iter_modules([str(custom_path)]):
            try:
                module = self._load_tool(module_info.name, path=str(custom_path))
                if not hasattr(module, "run"):
                    warnings.warn(f"Tool {module_info.name} doesn't have entry point run(), skipping...")
                    continue
                module_run = module.run

                name = module_info.name
                description = getattr(module, "DESCRIPTION", "").strip()
                args_description = getattr(module, "ARGS_DESCRIPTION", {})

                if not description:
                    warnings.warn(f"Tool {name} does not have description. Check docs for valid tool format.")

                if len(inspect.signature(module_run).parameters) > 0 and not args_description:
                    warnings.warn(f"Args description missing for tool {name}")

                tools.append(self._describe_tool(name, description, args_description, module_run))
            except Exception as e:
                logging.warning(f"Failed to load custom tool {module_info.name}: {e}")
        return tools

    def _get_tools(self):
        tools = []
        for module_info in iter_modules(tools_pkg.__path__):
            module = self._load_tool(module_info.name, tools_pkg)
            if not hasattr(module, "run"):
                warnings.warn(f"Tool {module_info.name} doesn't have entry point run(), skipping...")
                continue
            module_run = module.run

            name = module_info.name
            description = getattr(module, "DESCRIPTION", "").strip()
            args_description = getattr(module, "ARGS_DESCRIPTION", {})

            if not description:
                warnings.warn(f"Tool {name} does not have description. Check docs for valid tool format.")

            if len(inspect.signature(module_run).parameters) > 0 and not args_description:
                warnings.warn(f"Args description missing for tool {name}")

            tools.append(self._describe_tool(name, description, args_description, module_run))
        return tools

    @staticmethod
    def _json_type(annotation: Any) -> str:
        origin = get_origin(annotation)
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if origin in (list, dict):
            annotation = origin
        elif origin is not None and args:
            annotation = args[0]
        return {
            int: "integer",
            float: "number",
            bool: "boolean",
            dict: "object",
            list: "array",
        }.get(annotation, "string")

    @classmethod
    def _json_schema(cls, annotation):
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is list:
            return {"type": "array", "items": cls._json_schema(args[0]) if args else {}}
        if origin is dict:
            return {"type": "object", "additionalProperties": cls._json_schema(args[1]) if args else {}}
        if origin is not None and args:
            return cls._json_schema(next((arg for arg in args if arg is not type(None)), str))
        return {"type": cls._json_type(annotation)}

    def _describe_tool(self, name, description, args_description, handler):
        signature = inspect.signature(handler)
        try:
            hints = get_type_hints(handler)
        except Exception:
            hints = {}
        properties = {}
        required = []
        for arg_name, argument in signature.parameters.items():
            annotation = hints.get(arg_name, argument.annotation)
            properties[arg_name] = {
                **self._json_schema(annotation),
                "description": args_description.get(arg_name, ""),
            }
            if argument.default is inspect._empty:
                required.append(arg_name)
        parameters = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required
        return {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        }
    
    def get_all_tools(self):
        """Get native tools + custom tools combined"""
        return self._tools + self._custom_tools

    @property
    def loaded_tools(self):
        """Public, read-only view of loaded tool names."""
        return tuple(sorted(self._loaded_tools))

    def _compose_system_prompt(self) -> str:
        persona_text = self.settings.persona or """
        You are a helpful, capable general-purpose assistant.
        You are able to run agentic tasks, interacting with enviroment through recursive tool calls.
        Best practice is to execute task until it's completed and don't bother user.
        """

        return (
            "---PERSONA\n" + persona_text + "\n---\n"
            "Group independent tool requests into one round (or use read_files). "
            "Wait for results before dependent actions. Reuse exact facts already in history; "
            "re-read when current state matters. No history is summarized or truncated.\n"
        )



    def completion(self, messages, stream=False, message_transform=None):
        """Complete a turn, optionally projecting messages for transport only.

        ``message_transform`` receives a deep copy. Durable ``Conversation``
        messages remain unchanged and continue to receive complete results.
        """
        self._conversation = messages if isinstance(messages, Conversation) else None
        if self._conversation is not None:
            self._conversation.recover_pending()
        messages = deepcopy(list(messages))
        if message_transform:
            messages = message_transform(messages)
            if not isinstance(messages, list):
                raise TypeError("message_transform must return a list of messages")
        if not messages or messages[0].get('content') != self._system_prompt:
            messages = [{"role": "system", "content": self._system_prompt}] + messages
        self.last_messages = messages
        self.usage_rounds = []

        all_tools = self.get_all_tools()
        
        if stream:
            return self._completion_stream(messages, all_tools)
        else:
            return self._completion_json(messages, all_tools)


    def _request_payload(self, messages, tools, stream):
        payload = {
            "model": self.model,
            "tools": tools or None,
            "messages": messages,
            "tool_choice": "auto" if tools else None,
            "stream": stream,
        }
        if stream and self.settings.stream_include_usage:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _record_message(self, messages, message):
        message = deepcopy(message)
        message.setdefault("role", "assistant")
        if self._conversation is not None:
            self._conversation.append(message)
        messages.append(message)

    @property
    def last_usage(self):
        """Totals are unknown unless every request reports the corresponding field."""
        def total(path):
            values = []
            for usage in self.usage_rounds:
                value = usage
                for key in path:
                    value = value.get(key) if isinstance(value, dict) else None
                if not isinstance(value, (int, float)):
                    return None
                values.append(value)
            return sum(values) if values else None
        return {
            "request_count": len(self.usage_rounds),
            "prompt_tokens": total(["prompt_tokens"]),
            "completion_tokens": total(["completion_tokens"]),
            "cached_tokens": total(["prompt_tokens_details", "cached_tokens"]),
            "reasoning_tokens": total(["completion_tokens_details", "reasoning_tokens"]),
            "rounds": deepcopy(self.usage_rounds),
        }

    @staticmethod
    def _merge_tool_delta(cache, delta_tool):
        index = int(delta_tool.get("index", len(cache)))
        current = cache.setdefault(index, {"index": index, "function": {"name": "", "arguments": ""}})
        for key in ("id", "type"):
            if delta_tool.get(key):
                current[key] = delta_tool[key]
        function = delta_tool.get("function") or {}
        if function.get("name"):
            current["function"]["name"] = function["name"]
        current["function"]["arguments"] += function.get("arguments") or ""

    def _execute_tool_calls(self, tool_calls, messages=None):
        results = []
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            tool_name = function.get("name", "")
            call_id = tool_call.get("id", "")
            raw_arguments = function.get("arguments") or "{}"
            arguments = raw_arguments
            event = {"tool_name": tool_name, "call_id": call_id, "arguments": arguments}
            module = self._loaded_tools.get(tool_name)
            if not module:
                message = f"Error: tool '{tool_name}' is not available."
                self._emit_tool_event({**event, "type": "tool_error", "error": "Tool not available"})
                results.append({"tool_call_id": call_id, "role": "tool", "name": tool_name, "content": message})
                if messages is not None:
                    self._record_message(messages, results[-1])
                continue
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                event["arguments"] = arguments
                self._emit_tool_event({**event, "type": "tool_start"})
                result = module.run(**arguments)
            except Exception as tool_error:
                logging.error("Tool '%s' failed: %s", tool_name, tool_error)
                result = {"error": str(tool_error), "type": tool_error.__class__.__name__}
                self._emit_tool_event({**event, "type": "tool_error", "error": str(tool_error)})
            else:
                self._emit_tool_event({**event, "type": "tool_end", "result": result})
            content = self._format_tool_result(result)
            results.append({"tool_call_id": call_id, "role": "tool", "name": tool_name, "content": content})
            if messages is not None:
                self._record_message(messages, results[-1])
        return results

    def _completion_stream(self, messages, tools):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
        }
        for round_index in range(self.max_tool_rounds + 1):
            self.usage_rounds.append(None)
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                data=json.dumps(self._request_payload(messages, tools, True)),
                timeout=self._timeout,
                stream=True,
            )
            message = yield from self._stream_round(response)
            self._record_message(messages, message)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return
            if round_index >= self.max_tool_rounds:
                raise RuntimeError(f"tool-call round limit exceeded ({self.max_tool_rounds})")
            self._execute_tool_calls(tool_calls, messages)

    @classmethod
    def _merge_response_field(cls, previous, value):
        """Reassemble structured streaming fields without discarding provider data."""
        if isinstance(value, str):
            return (previous or "") + value
        if isinstance(value, dict):
            result = deepcopy(previous) if isinstance(previous, dict) else {}
            for key, item in value.items():
                if key in ("id", "type", "format", "index"):
                    result[key] = deepcopy(item)
                elif item is not None:
                    result[key] = cls._merge_response_field(result.get(key), item)
            return result
        if isinstance(value, list):
            result = deepcopy(previous) if isinstance(previous, list) else []
            for item in value:
                if isinstance(item, dict) and "index" in item:
                    match = next((i for i, old in enumerate(result)
                                  if isinstance(old, dict) and old.get("index") == item["index"]), None)
                    if match is not None:
                        result[match] = cls._merge_response_field(result[match], item)
                        continue
                result.append(deepcopy(item))
            return result
        return deepcopy(value)

    def _stream_round(self, response):
        tool_cache = {}
        response_text = ""
        extra_fields = {}
        finish_reason = None
        try:
            response.raise_for_status()
            # SSE is UTF-8 regardless of requests' inferred charset.
            response.encoding = "utf-8"
            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                if line and line.strip() == "data: [DONE]":
                    break
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    logging.warning("Error parsing stream chunk: %s", line)
                    continue
                choice = (data.get("choices") or [{}])[0]
                if data.get("usage") is not None:
                    self.usage_rounds[-1] = deepcopy(data["usage"])
                delta = choice.get("delta") or {}
                for key, value in delta.items():
                    if key not in ("content", "tool_calls", "role") and value is not None:
                        extra_fields[key] = self._merge_response_field(extra_fields.get(key), value)
                response_text += delta.get("content") or ""
                for tool_delta in delta.get("tool_calls") or []:
                    self._merge_tool_delta(tool_cache, tool_delta)
                finish_reason = choice.get("finish_reason") or finish_reason
                yield data
        finally:
            if hasattr(response, "close"):
                response.close()
        if finish_reason is None:
            raise RuntimeError("Stream ended without a finish reason; incomplete response was not committed")
        tool_calls = [{k: v for k, v in tool_cache[index].items() if k != "index"} for index in sorted(tool_cache)]
        message = {"role": "assistant", "content": response_text, **extra_fields}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def _completion_json(self, messages, tools):
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        for round_index in range(self.max_tool_rounds + 1):
            self.usage_rounds.append(None)
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                data=json.dumps(self._request_payload(messages, tools, False)),
                timeout=self._timeout,
            )
            try:
                response.raise_for_status()
                completion = response.json()
            finally:
                if hasattr(response, "close"):
                    response.close()
            self.usage_rounds[-1] = deepcopy(completion.get("usage"))
            choice = (completion.get("choices") or [{}])[0]
            message = choice.get("message")
            if not isinstance(message, dict):
                raise RuntimeError("Provider returned no assistant message")
            self._record_message(messages, message)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return completion
            if round_index >= self.max_tool_rounds:
                raise RuntimeError(f"tool-call round limit exceeded ({self.max_tool_rounds})")
            self._execute_tool_calls(tool_calls, messages)
        raise RuntimeError(f"tool-call round limit exceeded ({self.max_tool_rounds})")
