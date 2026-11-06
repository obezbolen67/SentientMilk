"""MCP host: the brain uses MCP servers; each server is toolkit ``mcp:<name>``.

Servers are listed in ``<home>/mcp.json``:

    {"servers": {"notes": {"command": "uv", "args": ["run", "notes-server"], "env": {"DIR": "D:/notes"}},
                 "github": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}}}

The ``mcp`` package (``pip install sentientmilk-framework[mcp]``) is async only and a Client
cannot leave the task that opened it, so one thread runs an event loop with one long-lived
task per server; brain threads hand calls to it and wait. Elicitation (a server asking the
user something mid-call) becomes a question to the app. The SDK does not implement the
Tasks extension yet: long MCP calls belong in background tasks.
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import tempfile
import threading
from functools import partial
from typing import Dict, Optional

from .toolkits import Tool, ToolContext, ToolError, Toolkit, ToolResult, cap

logger = logging.getLogger(__name__)

CONFIG_FILE = "mcp.json"
RECONNECT_TRIES = 5  # waits 1, 2, 4, 8, 16 s, as Claude Code does
CALL_TIMEOUT = 600
QUESTION_TIMEOUT = 600
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def tool_name(server: str, name: str) -> str:
    return _UNSAFE.sub("_", f"mcp__{server}__{name}")[:64]


def _expand(value: str) -> str:
    return _VARIABLE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def validate(config) -> dict:
    if not isinstance(config, dict) or not isinstance(config.get("servers", {}), dict):
        raise ValueError('MCP settings must be {"servers": {name: {...}}}')
    for name, spec in config.get("servers", {}).items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError(f"MCP server name {name!r}: use 1-32 letters, digits, '_' or '-'")
        if not isinstance(spec, dict) or ("command" in spec) == ("url" in spec):
            raise ValueError(f"MCP server {name}: give either command (stdio) or url (HTTP)")
        for key in ("args",):
            if key in spec and not all(isinstance(a, str) for a in spec[key]):
                raise ValueError(f"MCP server {name}: {key} must be a list of strings")
        for key in ("env", "headers"):
            if key in spec and not (isinstance(spec[key], dict) and all(isinstance(v, str) for v in spec[key].values())):
                raise ValueError(f"MCP server {name}: {key} must map names to strings")
        if "enabled" in spec and not isinstance(spec["enabled"], bool):
            raise ValueError(f"MCP server {name}: enabled must be true or false")
    return {"servers": dict(config.get("servers", {}))}


def public(config: dict) -> dict:
    """Header and environment values hidden unless they only name an environment variable."""
    hidden = {}
    for name, spec in config["servers"].items():
        spec = dict(spec)
        for key in ("env", "headers"):
            if key in spec:
                spec[key] = {k: v if _VARIABLE.fullmatch(v.split()[-1] if v.split() else "") else "<set>"
                             for k, v in spec[key].items()}
        hidden[name] = spec
    return {"servers": hidden}


class _Server:
    def __init__(self, name: str, spec: dict):
        self.name, self.spec = name, spec
        self.state, self.error, self.tools = "connecting", None, []
        self.queue: Optional[asyncio.Queue] = None
        self.task: Optional[asyncio.Task] = None
        self.current: Optional[ToolContext] = None


class McpHost:
    def __init__(self, brain):
        self.brain = brain
        self.path = brain.home / CONFIG_FILE
        self._servers: Dict[str, _Server] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.problem: Optional[str] = None

    # ============== Settings ==============

    def config(self) -> dict:
        if not self.path.exists():
            return {"servers": {}}
        try:
            return validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.error("MCP settings %s are unreadable: %s", self.path, exc)
            return {"servers": {}}

    def set_config(self, config: dict) -> dict:
        config = validate(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=self.path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
        os.chmod(temporary, 0o600)  # headers may hold tokens
        os.replace(temporary, self.path)
        self.stop()
        self.start()
        return public(config)

    def servers(self):
        return [name for name, spec in self.config()["servers"].items() if spec.get("enabled", True)]

    # ============== Lifecycle ==============

    def start(self) -> None:
        servers = {name: spec for name, spec in self.config()["servers"].items() if spec.get("enabled", True)}
        if not servers:
            return
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.problem = "MCP needs the mcp package: pip install sentientmilk-framework[mcp]"
            logger.warning(self.problem)
            return
        with self._lock:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, name="mcp", daemon=True)
            self._thread.start()
            for name, spec in servers.items():
                server = self._servers[name] = _Server(name, spec)
                asyncio.run_coroutine_threadsafe(self._open(server), self._loop)

    def stop(self) -> None:
        with self._lock:
            loop, servers = self._loop, list(self._servers.values())
            self._servers, self._loop = {}, None
        if not loop:
            return
        for server in servers:
            if server.queue:
                loop.call_soon_threadsafe(server.queue.put_nowait, None)
        loop.call_soon_threadsafe(loop.stop)

    def reconnect(self, name: str) -> None:
        server = self._servers.get(name)
        if not server or not self._loop:
            raise ValueError(f"No MCP server {name!r} is configured")
        if server.queue:
            self._loop.call_soon_threadsafe(server.queue.put_nowait, None)
        fresh = self._servers[name] = _Server(name, server.spec)
        asyncio.run_coroutine_threadsafe(self._open(fresh), self._loop)

    def status(self) -> dict:
        names = self.config()["servers"]
        result = {}
        for name, spec in names.items():
            server = self._servers.get(name)
            if not spec.get("enabled", True):
                result[name] = {"state": "disabled"}
            elif server is None:
                result[name] = {"state": "failed", "error": self.problem or "not started"}
            else:
                result[name] = {"state": server.state, "error": server.error, "tools": len(server.tools)}
        return result

    # ============== Inside the event loop ==============

    def _client(self, server: _Server, stack):
        from mcp import Client, StdioServerParameters

        spec = server.spec
        options = {"elicitation_callback": partial(self._elicit, server)}
        if "command" in spec:
            env = {key: _expand(value) for key, value in spec.get("env", {}).items()}
            if os.name == "nt":  # Windows programs need these, the SDK's minimal environment may lack them
                env = {**{k: os.environ[k] for k in ("SYSTEMROOT", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP",
                                                     "TMP", "PATHEXT", "COMSPEC") if k in os.environ}, **env}
            return Client(StdioServerParameters(command=spec["command"], args=spec.get("args", []), env=env or None,
                                                cwd=spec.get("cwd")), **options)
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        http = httpx2.AsyncClient(headers={k: _expand(v) for k, v in spec.get("headers", {}).items()},
                                  timeout=httpx2.Timeout(30.0, read=300.0))
        stack.push_async_callback(http.aclose)
        return Client(streamable_http_client(spec["url"], http_client=http), **options)

    async def _open(self, server: _Server) -> None:
        from contextlib import AsyncExitStack

        server.queue = asyncio.Queue()
        for attempt in range(RECONNECT_TRIES + 1):
            try:
                async with AsyncExitStack() as stack:
                    client = await stack.enter_async_context(self._client(server, stack))
                    tools, cursor = [], None
                    while True:
                        page = await client.list_tools(cursor=cursor)
                        tools += page.tools
                        cursor = getattr(page, "next_cursor", None)
                        if not cursor:
                            break
                    server.tools, server.state, server.error = tools, "connected", None
                    logger.info("MCP server %s connected with %d tools", server.name, len(tools))
                    while True:
                        item = await server.queue.get()
                        if item is None:
                            server.state = "closed"
                            return
                        operation, future = item
                        try:
                            future.set_result(await operation(client))
                        except Exception as exc:
                            future.set_exception(exc)
            except Exception as exc:
                server.state, server.error = "failed", f"{type(exc).__name__}: {exc}"
                logger.warning("MCP server %s failed: %s", server.name, server.error)
            if attempt < RECONNECT_TRIES:
                await asyncio.sleep(2 ** attempt)
                server.state = "connecting"

    async def _elicit(self, server: _Server, context, params):
        from mcp import types

        ctx = server.current
        if ctx is None or ctx.run["kind"] == "subagent":
            return types.ElicitResult(action="decline")
        future = self.brain.runs.ask_question(ctx, server.name, getattr(params, "message", ""),
                                              getattr(params, "requested_schema", None) or getattr(params, "requestedSchema", None))
        try:
            answer = await asyncio.wait_for(asyncio.wrap_future(future), QUESTION_TIMEOUT)
        except asyncio.TimeoutError:
            return types.ElicitResult(action="cancel")
        return types.ElicitResult(action=answer.get("action", "decline"), content=answer.get("content"))

    # ============== Tools ==============

    def toolkits(self) -> Dict[str, Toolkit]:
        kits = {}
        for name, server in list(self._servers.items()):
            if server.state != "connected":
                continue
            tools = []
            for item in server.tools:
                annotations = getattr(item, "annotations", None)
                schema = getattr(item, "input_schema", None) or getattr(item, "inputSchema", None) or \
                    {"type": "object", "properties": {}}
                tools.append(Tool(name=tool_name(name, item.name), description=item.description or "",
                                  parameters=schema, func=partial(self._call, name, item.name),
                                  readonly=bool(getattr(annotations, "read_only_hint", None) or
                                                getattr(annotations, "readOnlyHint", None)),
                                  policy="ask"))
            kits[f"mcp:{name}"] = Toolkit(f"mcp:{name}", f"Tools of the MCP server {name}.", tools)
        return kits

    def _call(self, server_name: str, name: str, ctx: ToolContext, **arguments):
        from mcp import types

        server = self._servers.get(server_name)
        if not server or server.state != "connected" or not self._loop:
            raise ToolError(f"The MCP server {server_name} is not connected right now.")

        async def operation(client):
            server.current = ctx
            try:
                return await client.call_tool(name, arguments)
            finally:
                server.current = None

        future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(server.queue.put_nowait, (operation, future))
        try:
            result = future.result(timeout=CALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise ToolError(f"{name} took longer than {CALL_TIMEOUT} s; run long MCP work as a background task.")
        texts, images = [], []
        for block in result.content or []:
            if isinstance(block, types.TextContent):
                texts.append(block.text)
            elif isinstance(block, types.ImageContent):
                mime = getattr(block, "mime_type", None) or getattr(block, "mimeType", "image/png")
                images.append(f"data:{mime};base64,{block.data}")
            else:
                texts.append(f"[{getattr(block, 'type', 'other')} content]")
        structured = getattr(result, "structured_content", None)
        if structured is not None and not texts:
            texts.append(json.dumps(structured, ensure_ascii=False))
        text = "\n".join(texts)
        if getattr(result, "is_error", False):
            raise ToolError(text or f"{name} failed")
        return ToolResult(cap(ctx, text or "(no output)", "mcp"), images)
