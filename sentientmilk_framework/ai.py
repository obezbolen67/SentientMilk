from ast import mod
from ctypes import ArgumentError
import requests
import re
import json
import inspect
import pathlib
import os
from . import exceptions
from . import tools as tools_pkg
from importlib import import_module
import importlib.util
from pkgutil import iter_modules


from typing import Optional, Any, Tuple, Callable, Dict
import logging
import warnings

class Settings:
    def __init__(self, persona=None, custom_tools_path=None):
        module_dir = pathlib.Path(__file__).parent
        self.persona = persona if persona else ""
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
    ):
        if not api_key or not base_url or not model:
            raise(exceptions.LLMError("Credentials are not set."))

        self.settings = settings if settings else Settings()
        
        self.base_url = base_url

        self.api_key = api_key
        
        self.modules = modules
        self._loaded_tools = {}
        self._tools = self._get_tools()
        self._custom_tools = self._load_custom_tools()
        self._tool_event_handler = tool_event_handler

        self._timeout: Tuple[float, float] = request_timeout if request_timeout else (10.0, 120.0)

        self._system_prompt = self._compose_system_prompt()
        
        self.model = model

        brave_token = web_search_token or WEB_SEARCH_TOKEN
        if brave_token:
            os.environ["BRAVE_API_KEY"] = brave_token


    def _format_tool_result(self, result: Any) -> str:
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result)
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
                module_run = module.run
                if not hasattr(module, "run"):
                    warnings.warn(f"Tool {module_info.name} doesn't have entry point run(), skipping...")
                    continue

                name = module_info.name
                description = getattr(module, "DESCRIPTION", "").strip()
                args_description = getattr(module, "ARGS_DESCRIPTION", {})

                if not description:
                    warnings.warn(f"Tool {name} does not have description. Check docs for valid tool format.")

                if len(inspect.signature(module_run).parameters) > 0 and not args_description:
                    warnings.warn(f"Args description missing for tool {name}")

                required = []

                tool = {
                    "type": "function",
                    "function": {                    
                        "name": name,
                        "description": description,
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                }
                for arg_name, arg in inspect.signature(module_run).parameters.items():
                    tool['function']['parameters']['properties'].update({arg_name: {"type": "string", "description": args_description.get(arg_name, "")}})
                    if arg.default is inspect._empty:
                        required.append(arg_name)
                if len(required) > 0:
                    tool['function']['parameters']['required'] = required
                 

                tools.append(tool)
            except Exception as e:
                logging.warning(f"Failed to load custom tool {module_info.name}: {e}")
        return tools

    def _get_tools(self):
        tools = []
        for module_info in iter_modules(tools_pkg.__path__):
            module = self._load_tool(module_info.name, tools_pkg)
            module_run = module.run
            if not hasattr(module, "run"):
                warnings.warn(f"Tool {module_info.name} doesn't have entry point run(), skipping...")
                continue

            name = module_info.name
            description = getattr(module, "DESCRIPTION", "").strip()
            args_description = getattr(module, "ARGS_DESCRIPTION", {})

            if not description:
                warnings.warn(f"Tool {name} does not have description. Check docs for valid tool format.")

            if len(inspect.signature(module_run).parameters) > 0 and not args_description:
                warnings.warn(f"Args description missing for tool {name}")

            required = []

            tool = {
                "type": "function",
                "function": {                    
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
            for arg_name, arg in inspect.signature(module_run).parameters.items():
                tool['function']['parameters']['properties'].update({arg_name: {"type": "string", "description": args_description.get(arg_name, "")}})
                if arg.default is inspect._empty:
                    required.append(arg_name)
            if len(required) > 0:
                tool['function']['parameters']['required'] = required
             

            tools.append(tool)
        return tools
    
    def get_all_tools(self):
        """Get native tools + custom tools combined"""
        return self._tools + self._custom_tools

    def _compose_system_prompt(self) -> str:
        persona_text = self.settings.persona or """
        You are a helpful, capable general-purpose assistant.
        You are able to run agentic tasks, interacting with enviroment through recursive tool calls.
        Best practice is to execute task until it's completed and don't bother user.
        """

        return (
            "---PERSONA\n" + persona_text + "\n---\n"
        )



    def completion(self, messages, stream=False):
        if len(messages) > 0 and not messages[0]['content'] == self._system_prompt:
            messages = [{"role": "system", "content": self._system_prompt}] + messages

        all_tools = self.get_all_tools()
        
        if stream:
            return self._completion_stream(messages, all_tools)
        else:
            return self._completion_json(messages, all_tools)


    def _completion_stream(self, messages, tools):

        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}"
        }

        tool_calls = []

        response = requests.post(
        f"{self.base_url}/chat/completions", 
        headers=headers, 
        data=json.dumps({
            "model": self.model,
            "tools": tools if tools else None,
            "messages": messages,
            "tool_choice": "auto" if tools else None,
            "stream": True
        }),
        timeout=self._timeout,
        stream=True)
        response.raise_for_status()
        
        
        resp = ""

        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if not line:
                continue
            if line.strip() == "data: [DONE]":    
                break
            
            try:
                if line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
                    logging.debug(f"JSON DATA: {data}")
                    
                    resp += data['choices'][0]['delta']['content'] if data['choices'][0]['delta'].get('content', None) else ""
                    delta = data['choices'][0]['delta']

                    for tool in delta.get("tool_calls", []):
                        if len(tool_calls) > 0:
                            for cache_tool in tool_calls:
                                if cache_tool.get('index') == tool.get('index'):
                                    if tool['function']['arguments']:
                                        cache_tool['function']['arguments'] += tool['function']['arguments'] 
                                else:
                                    tool_calls.append(tool)
                        else:
                            tool_calls.append(tool)
                    

                    if data['choices'][0].get('finish_reason', None):
                        if data['choices'][0]['finish_reason'] == 'tool_calls':
                            messages.append({
                                "role": "assistant",
                                "content": resp,
                                "tool_calls": tool_calls
                            })
                            
                            # Process all tool calls and collect results
                            tool_results = []
                            for tool in tool_calls:
                                tool_name = tool.get("function").get("name")
                                tool_call_id = tool.get("id", "")
                                arguments = json.loads(tool.get("function").get("arguments", "{}"))

                                module = self._loaded_tools.get(tool_name, None)
                                if not module:
                                    logging.warning(f"Requested tool '{tool_name}' is not loaded")
                                    tool_results.append({
                                        "tool_call_id": tool_call_id,
                                        "role": "tool",
                                        "name": tool_name,
                                        "content": f"Error: tool '{tool_name}' is not available."
                                    })
                                    self._emit_tool_event({
                                        "type": "tool_error",
                                        "tool_name": tool_name,
                                        "arguments": arguments,
                                        "error": "Tool not available"
                                    })
                                    continue

                                self._emit_tool_event({
                                    "type": "tool_start",
                                    "tool_name": tool_name,
                                    "arguments": arguments
                                })
                                try:
                                    result = module.run(**arguments)
                                except Exception as tool_error:
                                    logging.error(f"Tool '{tool_name}' failed: {tool_error}")
                                    result = {
                                        "error": str(tool_error),
                                        "type": tool_error.__class__.__name__
                                    }
                                    self._emit_tool_event({
                                        "type": "tool_error",
                                        "tool_name": tool_name,
                                        "arguments": arguments,
                                        "error": str(tool_error)
                                    })
                                else:
                                    self._emit_tool_event({
                                        "type": "tool_end",
                                        "tool_name": tool_name,
                                        "arguments": arguments,
                                        "result": result
                                    })

                                # Format result with clear instruction for the model
                                result_content = self._format_tool_result(result)
                                if tool_name == "update_sprite" and isinstance(result, dict) and result.get("success"):
                                    result_content = f"SUCCESS: Sprite updated successfully. Now respond to the user with text."
                                
                                tool_results.append({
                                    "tool_call_id": tool_call_id,
                                    "role": "tool",
                                    "name": tool_name,
                                    "content": result_content
                                })
                            
                            # Add all tool results to messages
                            messages.extend(tool_results)
                            
                            tool_calls = []
                            yield from self._completion_stream(messages, tools)
                            return
                        elif data['choices'][0]['finish_reason'] == 'stop':
                            messages.append({"role": "assistant", "content": resp})
                            resp = ""
                    
                    yield data
                    
            except json.JSONDecodeError:
                logging.warning(f"Error parsing chunk: {line}")
                continue

    def _completion_json(self, messages, tools):

        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        response = requests.post(f"{self.base_url}/chat/completions", 
        headers=headers, 
        data=json.dumps({
            "model": self.model,
            "tools": tools if tools else None,
            "messages": messages,
            "tool_choice": "auto" if tools else None,
            "stream": False
        }),
        timeout=self._timeout)
        response.raise_for_status()
        
        try:
            completion = response.json()
            for choice in completion.get("choices", []):
                resp = choice.get('message').get("content", "")
                if choice.get("finish_reason") == "tool_calls":
                    tool_calls = choice.get("message", {}).get("tool_calls", [])

                    messages.append({
                        "role": "assistant",
                        "content": resp or "",
                        "tool_calls": tool_calls
                    })
                    
                    # Process all tool calls and collect results
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("function").get("name")
                        tool_call_id = tool_call.get("id", "")
                        arguments = json.loads(tool_call.get("function").get("arguments", "{}"))

                        module = self._loaded_tools.get(tool_name, None)
                        if not module:
                            logging.warning(f"Requested tool '{tool_name}' is not loaded")
                            tool_results.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": f"Error: tool '{tool_name}' is not available."
                            })
                            self._emit_tool_event({
                                "type": "tool_error",
                                "tool_name": tool_name,
                                "arguments": arguments,
                                "error": "Tool not available"
                            })
                            continue

                        self._emit_tool_event({
                            "type": "tool_start",
                            "tool_name": tool_name,
                            "arguments": arguments
                        })
                        try:
                            result = module.run(**arguments)
                        except Exception as tool_error:
                            logging.error(f"Tool '{tool_name}' failed: {tool_error}")
                            result = {
                                "error": str(tool_error),
                                "type": tool_error.__class__.__name__
                            }
                            self._emit_tool_event({
                                "type": "tool_error",
                                "tool_name": tool_name,
                                "arguments": arguments,
                                "error": str(tool_error)
                            })
                        else:
                            self._emit_tool_event({
                                "type": "tool_end",
                                "tool_name": tool_name,
                                "arguments": arguments,
                                "result": result
                            })

                        # Format result with clear instruction for the model
                        result_content = self._format_tool_result(result)
                        if tool_name == "update_sprite" and isinstance(result, dict) and result.get("success"):
                            result_content = f"SUCCESS: Sprite updated successfully. Now respond to the user with text."
                        
                        tool_results.append({
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": result_content
                        })
                    
                    # Add all tool results to messages
                    messages.extend(tool_results)
                    
                    return self._completion_json(messages, tools)
                    
                        
        except Exception as e:
            logging.error(f"Error during completion: {e}")
            return {"error": str(e)}
        return response.json()