"""MCP host: the brain uses MCP servers; each server is toolkit ``mcp:<name>``.

Servers are listed in ``<home>/mcp.json``:

    {"servers": {"notes": {"command": "uv", "args": ["run", "notes-server"], "env": {"DIR": "D:/notes"}},
                 "github": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}}}

The ``mcp`` package (``pip install sentientmilk-framework[mcp]``) is async only and a Client
cannot leave the task that opened it, so one thread runs an event loop with one long-lived
task per server; brain threads hand calls to it and wait. Elicitation (a server asking the
user something mid-call) becomes a question to the app. A call has no time limit: one still
running after shell.WAIT seconds (or when the user sends a message) goes on as a job, as a command
does, which she reads, the user sees and either of them stops; its result comes as a note.
"""

import asyncio
import base64
import concurrent.futures
import json
import logging
import os
import re
import tempfile
import threading
import time
from functools import partial
from typing import Dict, Optional

from .loop import TERMINAL
from .toolkits import (
    MESSAGE_FROM_USER,
    STOPPED_BY_USER,
    Tool,
    ToolContext,
    ToolError,
    Toolkit,
    ToolResult,
    cap,
)
from .toolkits.shell import WAIT

logger = logging.getLogger(__name__)

CONFIG_FILE = "mcp.json"
RECONNECT_TRIES = 5  # waits 1, 2, 4, 8, 16 s, as Claude Code does
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


HIDDEN = "<set>"


def public(config: dict) -> dict:
    """Header and environment values hidden unless they only name an environment variable."""
    hidden = {}
    for name, spec in config["servers"].items():
        spec = dict(spec)
        for key in ("env", "headers"):
            if key in spec:
                spec[key] = {k: v if _VARIABLE.fullmatch(v.split()[-1] if v.split() else "") else HIDDEN
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
        self.running: Optional[tuple] = None  # (tool, started) of the call it works on


class _Call:
    """An MCP call that went on as a job: shell.stop cancels it, which frees its server for the next call."""

    def __init__(self, loop, future: concurrent.futures.Future):
        self.loop, self.future = loop, future

    def cancel(self) -> None:
        future = self.future
        self.loop.call_soon_threadsafe(lambda: future.task.cancel() if hasattr(future, "task") else future.cancel())


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
        """Replace the servers; a value still reading ``<set>`` keeps the stored secret, so a
        configuration read from public() can be changed and sent back."""
        config = validate(config)
        stored = self.config()["servers"]
        for name, spec in config.get("servers", {}).items():
            for key in ("env", "headers"):
                kept = stored.get(name, {}).get(key, {})
                for item, value in spec.get(key, {}).items():
                    if value == HIDDEN and item in kept:
                        spec[key][item] = kept[item]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=self.path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
        os.chmod(temporary, 0o600)  # headers may hold tokens
        os.replace(temporary, self.path)
        self.stop()
        self.start()
        return public(config)

    def effective(self) -> Dict[str, dict]:
        """The servers to run: the plugins' and the user's (mcp.json wins a name both use)."""
        return {**self.brain.plugins.mcp_servers(), **self.config()["servers"]}

    def servers(self):
        return [name for name, spec in self.effective().items() if spec.get("enabled", True)]

    def restart(self) -> None:
        self.stop()
        self.start()

    # ============== Lifecycle ==============

    def start(self) -> None:
        servers = {name: spec for name, spec in self.effective().items() if spec.get("enabled", True)}
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
        names = self.effective()
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
                            _drain(server, "The MCP server was closed before this call ran.")
                            return
                        operation, future = item
                        if future.done():  # cancelled while it waited its turn
                            continue
                        future.task = asyncio.ensure_future(operation(client))
                        try:
                            future.set_result(await future.task)
                        except asyncio.CancelledError:
                            future.cancel()
                            if asyncio.current_task().cancelling():
                                raise
                        except Exception as exc:
                            future.set_exception(exc)
            except Exception as exc:
                server.state, server.error = "failed", f"{type(exc).__name__}: {exc}"
                logger.warning("MCP server %s failed: %s", server.name, server.error)
            if attempt < RECONNECT_TRIES:
                await asyncio.sleep(2 ** attempt)
                server.state = "connecting"
        _drain(server, f"The MCP server could not be reached: {server.error}")

    async def _elicit(self, server: _Server, context, params):
        from mcp import types

        ctx = server.current
        if ctx is None or ctx.run["kind"] == "subagent" or self.brain.store.run(ctx.run["id"])["status"] in TERMINAL:
            return types.ElicitResult(action="decline")
        future = self.brain.runs.ask_question(ctx, server.name, getattr(params, "message", ""),
                                              getattr(params, "requested_schema", None) or getattr(params, "requestedSchema", None))
        answer = await asyncio.wrap_future(future)
        return types.ElicitResult(action=answer.get("action", "decline"), content=answer.get("content"))

    # ============== Tools ==============

    def for_claude(self, kits) -> Dict[str, dict]:
        """The connected servers among ``kits`` (``mcp:<name>``) as Claude Code's --mcp-config takes them: a super
        agent has the lead's MCP tools, under the same names (mcp__<server>__<tool>), so the rules and the apps
        read its calls as hers. A server the lead does not have (failed, untrusted, turned off) is left out."""
        servers = {}
        for name, server in list(self._servers.items()):
            if server.state != "connected" or f"mcp:{name}" not in kits:
                continue
            spec = server.spec
            if "command" in spec:  # shortcut: a server's cwd is not passed on (Claude Code has none); add when one needs it
                servers[name] = {"type": "stdio", "command": spec["command"], "args": spec.get("args", []),
                                 "env": {key: _expand(value) for key, value in spec.get("env", {}).items()}}
            else:
                servers[name] = {"type": "http", "url": spec["url"],
                                 "headers": {key: _expand(value) for key, value in spec.get("headers", {}).items()}}
        return servers

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

    def _wait(self, future: concurrent.futures.Future, ctx: ToolContext):
        """The call's result, or None when it goes on as a job: after WAIT s, or when the user sends a message.
        The user's stop ends it, and frees the server for the next call."""
        deadline = time.monotonic() + WAIT
        while True:
            try:
                return future.result(timeout=0.2)
            except concurrent.futures.TimeoutError:
                if ctx.attention.stopped.is_set():
                    _Call(self._loop, future).cancel()
                    raise ToolError(STOPPED_BY_USER)
                if ctx.attention.woken.is_set() or time.monotonic() >= deadline:
                    return None
            except concurrent.futures.CancelledError:
                raise ToolError(STOPPED_BY_USER)

    def _as_job(self, ctx: ToolContext, server: _Server, label: str, arguments: dict,
                future: concurrent.futures.Future) -> str:
        """A call still running goes on as a job; when it ends, its result is the job's output and her note."""
        why = MESSAGE_FROM_USER if ctx.attention.woken.is_set() else f"Still running after {WAIT} s."
        if not hasattr(future, "task") and server.running:  # one call at a time: say what holds it up
            why += (f" It has not started: the server is still busy with {server.running[0]} (for "
                    f"{int(time.time() - server.running[1])} s), and it takes one call at a time.")
        log = ctx.run_dir() / f"job-{time.time_ns()}.log"
        log.touch()
        command = f"{label} {json.dumps(arguments, ensure_ascii=False)}"
        job = ctx.store.add_job(ctx.run["id"], ctx.app, ctx.session, command, "", str(log))
        self.brain.jobs[job] = _Call(self._loop, future)

        def finish():
            from .toolkits.shell import job_ended

            try:
                text, images, failed = _content(future.result())
                text = text or "(no output)"
            except concurrent.futures.CancelledError:
                text, images, failed = STOPPED_BY_USER, [], True
            except Exception as exc:
                text, images, failed = f"{type(exc).__name__}: {exc}", [], True
            for number, url in enumerate(images, 1):
                head, data = url.split(",", 1)
                picture = log.with_name(f"{log.stem}-{number}.{head.split('/')[1].split(';')[0]}")
                picture.write_bytes(base64.b64decode(data))
                text += f"\n[Picture {number}: {picture}; files_read shows it]"
            log.write_text(text, encoding="utf-8")
            job_ended(self.brain, job, 1 if failed else 0)

        threading.Thread(target=finish, name=f"job-{job}", daemon=True).start()
        read = (f" shell_output(job={job}) shows its result once it is done, shell_stop(job={job}) stops it."
                if "shell" in (ctx.profile.get("toolkits") or []) else "")
        if ctx.called_back:
            return (f"[{why} It goes on as background job {job}, and you are called back when it ends (a new "
                    f"turn, with its result). End your turn now and tell the user it runs, unless you have other "
                    f"work meanwhile: do not wait for it.{read}]")
        return f"[{why} It goes on as background job {job}; you get a note with its result when it ends.{read}]"

    def _call(self, server_name: str, name: str, ctx: ToolContext, **arguments):
        server = self._servers.get(server_name)
        if not server or server.state != "connected" or not self._loop:
            raise ToolError(f"The MCP server {server_name} is not connected right now.")

        label = tool_name(server_name, name)

        async def operation(client):
            server.current, server.running = ctx, (label, time.time())
            try:
                return await client.call_tool(name, arguments)
            finally:
                server.current = server.running = None

        future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(server.queue.put_nowait, (operation, future))
        result = self._wait(future, ctx)
        if result is None:
            return self._as_job(ctx, server, label, arguments, future)
        text, images, failed = _content(result)
        if failed:
            raise ToolError(text or f"{name} failed")
        return ToolResult(cap(ctx, text or "(no output)", "mcp"), images)


def _content(result) -> tuple:
    """(text, images as data URLs, failed) of a call's result."""
    from mcp import types

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
    return "\n".join(texts), images, bool(getattr(result, "is_error", False))


def _drain(server: _Server, reason: str) -> None:
    """Calls still waiting for a server that is gone fail, rather than wait for ever."""
    while server.queue and not server.queue.empty():
        item = server.queue.get_nowait()
        if item and not item[1].done():
            item[1].set_exception(ToolError(reason))
