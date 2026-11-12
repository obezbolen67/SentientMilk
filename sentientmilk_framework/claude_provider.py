"""The brain thinking with Claude through the user's own Claude Code (config ``provider`` "claude_code").

The loop stays the loop: it makes the messages from the session's log, runs her tools, asks the user, and calls
``complete`` for one message at a time, as with an API service. Claude Code holds a conversation of its own, so
one is kept warm for each conversation the loop has, and goes on while what the loop sends goes on from what it
told and got from it (messages compared by what they say: pictures left out, as the loop shrinks and drops old
ones). Her tools are Claude Code's through an MCP server the host serves over the control protocol (type sdk):
when Claude calls them, ``complete`` returns the calls; the next ``complete`` brings their results, and the user
messages after them (her notes, pictures from the tools, the user's words) go in as messages sent while the calls
waited, which Claude Code gives Claude right after the results.

A conversation at the end of a turn can go on in a new process (``--resume``): when its prompt, tools or model
changed, after it waited long enough to be ended, after a brain restart (where each ended is kept, in
claude-code/conversations.json). When nothing goes on from what the loop sends (it cleared old results,
compacted, returned to before, or the session thought with an API service until now), a new Claude Code session
starts with what came before as a record in its first message. Calls without tools (titles, compaction, notes)
are one process each. Each process sees only what SentientMilk gives it: her prompt, her tools, none of the
user's Claude Code settings, CLAUDE.md, MCP servers or tools (--safe-mode, --restricted, --tools "").
"""

import hashlib
import json
import logging
import queue
import threading
import time
from typing import Callable, List, Optional, Tuple

from . import transport
from .claudecode import Process, failure, outdated, prompt_file
from .exceptions import BrainError

logger = logging.getLogger(__name__)

SERVER = "milk"
PREFIX = f"mcp__{SERVER}__"  # how Claude Code names her tools
IDLE = 600  # seconds a conversation at the end of a turn stays warm (it goes on in a new process after)
WAITING = 3600  # seconds one waiting for its tools' results stays warm (an approval may take a while)
RECORD_AGE = 30 * 24 * 3600  # Claude Code deletes sessions after 30 days by default
BASE = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--include-partial-messages", "--tools", "", "--restricted", "--safe-mode", "--strict-mcp-config",
        "--disable-slash-commands", "--system-prompt-snapshot", "off"]
ENV = {"ENABLE_TOOL_SEARCH": "false",  # her tools are all there, as the loop sends them
       "MCP_TOOL_TIMEOUT": str(7 * 24 * 3600 * 1000)}  # a call waits for the user's approval as long as it takes
RECORD = ("[This conversation went on in a new Claude Code session, so what came before is here as a record, "
          "oldest first: the user's messages and notes, your replies, your tool calls and their results. Go on "
          "from its end as yourself, and call tools as you always do (the record's notation is only a record).]")
GO_ON = "[Your tool calls' results are in: go on.]"


class Gone(Exception):
    """The Claude Code session a conversation was to go on with is gone (Claude Code deletes old ones)."""


def key(message: dict) -> str:
    """What a message says, to tell whether a conversation goes on: its pictures and the words that stand in
    for dropped ones left out (the loop shrinks older pictures and drops the oldest at every step)."""
    content = message.get("content")
    text = content if isinstance(content, str) else "\n".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
    for marker in (transport.OMITTED_IMAGE, transport.DISABLED_IMAGE):
        text = text.replace(marker, "")
    calls = [[c.get("id"), (c.get("function") or {}).get("name"), (c.get("function") or {}).get("arguments")]
             for c in message.get("tool_calls") or []]
    said = json.dumps([message.get("role"), " ".join(text.split()), calls, message.get("tool_call_id")],
                      ensure_ascii=False)
    return hashlib.sha1(said.encode("utf-8")).hexdigest()[:20]


def _hash(value) -> str:
    return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if b.get("type") == "text" else "[a picture]"
                     for b in content or [] if isinstance(b, dict))


def blocks(content) -> list:
    """A message's content as Claude's content blocks (pictures as data URLs or links become image blocks)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    found = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            found.append({"type": "text", "text": block["text"]})
        elif block.get("type") == "image_url":
            url = (block.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                head, _, data = url.partition(",")
                found.append({"type": "image", "source": {"type": "base64", "data": data,
                                                          "media_type": head[5:].split(";")[0] or "image/png"}})
            elif url:
                found.append({"type": "image", "source": {"type": "url", "url": url}})
    return found


def record(messages: List[dict]) -> list:
    """What a new Claude Code session starts with when what the loop sends goes on from no session: what came
    before as a record, then what is new (the user messages at the end, pictures and all)."""
    end = len(messages)
    while end and messages[end - 1]["role"] == "user":
        end -= 1
    lines = []
    for message in messages[:end]:
        role, text = message["role"], _text(message.get("content")).strip()
        if role == "user":
            lines.append(f"<user>\n{text}\n</user>")
        elif role == "assistant":
            calls = "".join(f"\n<call tool=\"{(c.get('function') or {}).get('name', '')}\" id=\"{c.get('id', '')}\">"
                            f"{(c.get('function') or {}).get('arguments', '')}</call>"
                            for c in message.get("tool_calls") or [])
            lines.append(f"<you>\n{text}{calls}\n</you>")
        elif role == "tool":
            lines.append(f"<result id=\"{message.get('tool_call_id', '')}\">\n{text}\n</result>")
    new = [b for m in messages[end:] for b in blocks(m.get("content"))]
    return [{"type": "text", "text": RECORD + "\n\n" + "\n\n".join(lines)}] + (new or [{"type": "text", "text": GO_ON}])


def _usage(usage: dict) -> dict:
    cached = usage.get("cache_read_input_tokens") or 0
    return {"prompt_tokens": (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
            + cached, "completion_tokens": usage.get("output_tokens"), "cached_tokens": cached,
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("thinking_tokens")}


class Conversation:
    """One Claude Code process and what it was told and said (``seen``: the loop's messages, as keys)."""

    def __init__(self, claude, settings: tuple, seen: Optional[List[str]] = None, session: str = ""):
        self.claude, self.settings = claude, settings
        self.seen: List[str] = list(seen or [])
        self.session, self.resumed = session, bool(session)
        self.process: Optional[Process] = None
        self.events: queue.Queue = queue.Queue()
        self.tools: List[dict] = []
        self.lock = threading.Lock()
        self.calls: dict = {}  # tool use id -> (request id, MCP id) of a tools/call waiting for its result
        self.results: dict = {}  # tool use id -> result the loop gave before Claude Code asked for it
        self.waiting: List[str] = []  # the tool use ids of its last message: their results come next
        self.ended = True  # at the end of a turn: nothing asked of it, it can go on in another process
        self.busy, self.used = False, time.time()
        self.limit: Optional[dict] = None  # the plan's last rate limit news

    # ============== The process ==============

    def start(self, system: str, tools: List[dict], model: str, effort: Optional[str], once: bool = False) -> None:
        claude = self.claude
        self.tools = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                       "inputSchema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                      for t in tools]
        prompt = prompt_file(claude.folder, system, "system-")
        args = BASE + ["--system-prompt-file", prompt, "--model", model]
        if effort:
            args += ["--effort", effort]
        if once:
            args += ["--no-session-persistence"]
        else:  # her tools: the host's MCP server, asked over stdio; the loop decides about each call itself
            args += ["--mcp-config", json.dumps({"mcpServers": {SERVER: {"type": "sdk", "name": SERVER}}}),
                     "--permission-mode", "manual", "--permission-prompts", "host",
                     "--permission-prompt-tool", "stdio"]
        if self.session:
            args += ["--resume", self.session]
        self.process = Process(claude, args, claude.folder, files=[prompt], env=ENV, on_event=self._event)
        self.process.initialize()

    def alive(self) -> bool:
        return self.process is not None and self.process.alive()

    def end(self) -> None:
        if self.process is not None:
            self.process.kill()

    def _event(self, process: Process, event: Optional[dict]) -> None:
        """Claude Code's output, on its reader thread: what it asks is answered at once (it may ask while
        nobody waits for its words), the rest waits for ``read``."""
        if event is not None and event.get("type") == "control_request":
            request, request_id = event.get("request") or {}, event.get("request_id")
            subtype = request.get("subtype")
            if subtype == "can_use_tool":  # the loop decides about her calls (rules, the user) before it runs them
                process.answer(request_id, {"behavior": "allow", "updatedInput": request.get("input") or {}})
            elif subtype == "mcp_message":
                self._mcp(process, request_id, request.get("message") or {})
            else:
                process.answer(request_id, error=f"SentientMilk does not answer {subtype}")
            return
        self.events.put(event)

    def _mcp(self, process: Process, request_id, message: dict) -> None:
        method, mid = message.get("method"), message.get("id")
        reply: dict = {"jsonrpc": "2.0", "id": mid}
        if method == "initialize":
            reply["result"] = {"protocolVersion": (message.get("params") or {}).get("protocolVersion", "2025-06-18"),
                               "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER, "version": "1"}}
        elif method == "tools/list":
            reply["result"] = {"tools": self.tools}
        elif method == "tools/call":
            use = ((message.get("params") or {}).get("_meta") or {}).get("claudecode/toolUseId", "")
            with self.lock:
                result = self.results.pop(use, None)
                if result is None:  # the loop runs it: its result comes with the next complete()
                    self.calls[use] = (request_id, mid)
                    return
            reply["result"] = result
        elif mid is None or method == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": f"SentientMilk does not serve {method}"}
        process.answer(request_id, {"mcp_response": reply})

    def _give(self, use: str, result: dict) -> None:
        with self.lock:
            waiting = self.calls.pop(use, None)
            if waiting is None:  # it has not asked yet (it runs the calls one by one)
                self.results[use] = result
                return
        self.process.answer(waiting[0], {"mcp_response": {"jsonrpc": "2.0", "id": waiting[1], "result": result}})

    # ============== Going on ==============

    def takes(self, tail: List[dict]) -> bool:
        """Whether the messages after what it saw go on from where it is."""
        if not tail:
            return False
        results = [m for m in tail[:len(self.waiting)] if m["role"] == "tool"]
        if self.waiting and {m.get("tool_call_id") for m in results} != set(self.waiting):
            return False
        return all(m["role"] == "user" for m in tail[len(self.waiting):]) and (self.ended or bool(self.waiting))

    def feed(self, tail: List[dict]) -> None:
        """The loop's new messages: its tools' results, and what came after them as a message of the user's
        (sent first: Claude Code gives it to Claude with the results)."""
        said = [b for m in tail if m["role"] == "user" for b in blocks(m.get("content"))]
        if said:
            self.process.say(said)
            self.ended = False
        for message in tail:
            if message["role"] == "tool":
                self._give(message.get("tool_call_id", ""),
                           {"content": [{"type": "text", "text": _text(message.get("content"))}]})
        self.waiting = []

    def say(self, content: list) -> None:
        self.process.say(content)
        self.ended = False

    def read(self, on_text: Optional[Callable[[str], None]], stopped) -> Tuple[dict, dict]:
        """Claude's next message: one that calls tools as soon as it is written, else the turn's end."""
        parts: dict = {}
        texts: List[str] = []
        usage: dict = {}
        stop, error, started = None, None, False
        while True:
            if stopped is not None and stopped.is_set():
                raise BrainError("cancelled", "The run was stopped")
            try:
                event = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                errors = list(self.process.errors)
                if self.resumed and not started and any("No conversation found" in line for line in errors):
                    raise Gone()
                if outdated(errors):
                    raise BrainError("provider_error", "This Claude Code is too old for SentientMilk",
                                     "Run claude update in a terminal, then try again.")
                raise BrainError("provider_error", "Claude Code stopped before it answered", "\n".join(errors) or None)
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                started = True
                self.session = event.get("session_id") or self.session
            elif kind == "rate_limit_event":
                self.limit = event.get("rate_limit_info") or self.limit
            elif kind == "assistant" and event.get("error"):
                error = event["error"]
            elif kind == "stream_event":
                streamed = event.get("event") or {}
                what = streamed.get("type")
                if what == "message_start":
                    parts, stop = {}, None
                    usage = (streamed.get("message") or {}).get("usage") or {}
                elif what == "content_block_start":
                    parts[streamed.get("index")] = {**(streamed.get("content_block") or {}), "json": ""}
                elif what == "content_block_delta":
                    part, delta = parts.get(streamed.get("index")), streamed.get("delta") or {}
                    if part is None:
                        continue
                    if delta.get("type") == "text_delta":
                        part["text"] = part.get("text", "") + delta.get("text", "")
                        if on_text:
                            on_text(delta.get("text", ""))
                    elif delta.get("type") == "input_json_delta":
                        part["json"] += delta.get("partial_json", "")
                elif what == "message_delta":
                    stop = (streamed.get("delta") or {}).get("stop_reason")
                    usage = streamed.get("usage") or usage
                elif what == "message_stop":
                    message = self._message(parts)
                    if stop == "tool_use" and message.get("tool_calls"):
                        self.waiting = [call["id"] for call in message["tool_calls"]]
                        return message, _usage(usage)
                    texts.append(message["content"])
            elif kind == "result":
                self.ended = True
                if error or event.get("is_error"):
                    raise failure(error or "unknown", str(event.get("result") or ""), self.limit)
                return {"role": "assistant", "content": "\n\n".join(t for t in texts if t)}, _usage(usage)

    @staticmethod
    def _message(parts: dict) -> dict:
        text, calls = "", []
        for index in sorted(parts, key=lambda i: (i is None, i)):
            part = parts[index]
            if part.get("type") == "text":
                text += part.get("text", "")
            elif part.get("type") == "tool_use":
                try:
                    arguments = json.dumps(json.loads(part["json"] or "{}"), ensure_ascii=False)
                except ValueError:
                    arguments = part["json"]  # the loop says what is wrong with them
                name = part.get("name", "")
                calls.append({"id": part.get("id", ""), "type": "function",
                              "function": {"name": name[len(PREFIX):] if name.startswith(PREFIX) else name,
                                           "arguments": arguments}})
        message = {"role": "assistant", "content": text}
        if calls:
            message["tool_calls"] = calls
        return message


class Conversations:
    """The warm conversations, and the Claude Code sessions of those that ended at the end of a turn."""

    def __init__(self, claude):
        self.claude = claude
        self.path = claude.folder / "conversations.json"
        self.live: List[Conversation] = []
        self.lock = threading.Lock()
        self.saving = threading.Lock()
        self.ended: dict = self._load()  # Claude Code session id -> {"seen": [...], "at": when}
        self.janitor: Optional[threading.Thread] = None
        self.closing = threading.Event()

    def _load(self) -> dict:
        try:
            ended = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(ended, dict):
            return {}
        return {session: kept for session, kept in ended.items()
                if isinstance(kept, dict) and time.time() - kept.get("at", 0) < RECORD_AGE}

    def _save(self) -> None:
        with self.lock:
            data = json.dumps(self.ended)
        with self.saving:  # one writer at a time: the newest is written last
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(data, encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                logger.warning("Could not keep where her Claude Code conversations ended", exc_info=True)

    def take(self, settings: tuple, keys: List[str], messages: List[dict]) -> Tuple[Conversation, int]:
        """A conversation for ``messages`` (busy now) and how many of them it has: a warm one that goes on to
        them, else one that goes on with the session of one that ended there, else a new one."""
        if self.janitor is None:
            self.janitor = threading.Thread(target=self._sweep, daemon=True, name="claude-code-janitor")
            self.janitor.start()
        moved = []
        with self.lock:
            for conversation in list(self.live):
                count = len(conversation.seen)
                if conversation.busy or keys[:count] != conversation.seen or not conversation.takes(messages[count:]):
                    continue
                if conversation.settings == settings and conversation.alive():
                    conversation.busy, conversation.used = True, time.time()
                    return conversation, count
                if conversation.ended and conversation.session:  # prompt, tools or model changed: a new process
                    self.live.remove(conversation)
                    moved.append(conversation)
                    self.ended[conversation.session] = {"seen": conversation.seen, "at": time.time()}
            best = max(((session, kept) for session, kept in self.ended.items()
                        if len(kept["seen"]) < len(keys) and keys[:len(kept["seen"])] == kept["seen"]
                        and all(m["role"] == "user" for m in messages[len(kept["seen"]):])),
                       key=lambda item: len(item[1]["seen"]), default=None)
            if best:
                del self.ended[best[0]]
                conversation = Conversation(self.claude, settings, best[1]["seen"], best[0])
            else:
                conversation = Conversation(self.claude, settings)
            conversation.busy = True
            self.live.append(conversation)
        for old in moved:
            if old.process is not None:
                old.process.close(wait=10)  # its session is whole on disk; the new process goes on with it
        if best:
            self._save()
        return conversation, len(conversation.seen)

    def give_back(self, conversation: Conversation) -> None:
        with self.lock:
            conversation.busy, conversation.used = False, time.time()
        if conversation.ended and conversation.session:
            self._save_ended(conversation)

    def drop(self, conversation: Conversation) -> None:
        """It went wrong or was stopped: its process ends and nothing goes on with it."""
        conversation.end()
        with self.lock:
            if conversation in self.live:
                self.live.remove(conversation)

    def forget(self, conversation: Conversation) -> None:
        """It goes on from its session's end: that end is no place to go on from any more."""
        with self.lock:
            gone = self.ended.pop(conversation.session, None)
        if gone is not None:
            self._save()

    def _save_ended(self, conversation: Conversation) -> None:
        with self.lock:
            self.ended[conversation.session] = {"seen": conversation.seen, "at": time.time()}
        self._save()

    def _sweep(self) -> None:
        """Warm conversations nobody went on with for a while end (those at a turn's end can go on later)."""
        while not self.closing.wait(30):
            now, done = time.time(), []
            with self.lock:
                for conversation in list(self.live):
                    idle = now - conversation.used
                    if conversation.busy or (conversation.alive() and idle < (IDLE if conversation.ended else WAITING)):
                        continue
                    self.live.remove(conversation)
                    done.append(conversation)
            for conversation in done:
                if conversation.ended and conversation.session and conversation.process is not None:
                    conversation.process.close(wait=10)  # its session is kept: a later turn goes on with it
                else:
                    conversation.end()

    def close(self) -> None:
        self.closing.set()
        with self.lock:
            live, self.live = self.live, []
        for conversation in live:
            conversation.end()  # a turn's end is on disk already; one in the middle starts over from the record
        for conversation in live:  # its reader deletes its prompt file once it ended
            if conversation.process is not None:
                conversation.process.readers[0].join(timeout=5)


class ClaudeCodeProvider:
    """``complete`` as Provider's, on Claude Code."""

    def __init__(self, claude, model: str):
        values = claude.brain.config.values()
        known = model in (values["claude_model"], values["claude_light_model"]) or model.startswith("claude-") \
            or claude.model(model) is not None
        self.claude = claude
        self.model = model if known else values["claude_model"]  # one of an API service's: Claude's own instead
        self.effort = claude.effort(self.model, values["claude_effort"])

    def complete(self, messages: List[dict], tools: Optional[List[dict]] = None,
                 on_text: Optional[Callable[[str], None]] = None, stopped=None) -> Tuple[dict, dict]:
        problem = self.claude.problem()
        if problem:
            raise problem
        system, rest = "", list(messages)
        if rest and rest[0]["role"] == "system":
            system, rest = rest[0]["content"], rest[1:]
        if not tools:
            return self._once(_text(system), rest, on_text, stopped)
        pool = self.claude.pool()
        settings = (_hash(system), _hash(tools), self.model, self.effort)
        keys = [key(m) for m in rest]
        for attempt in (1, 2):
            conversation, count = pool.take(settings, keys, rest)
            try:
                if conversation.process is None:
                    conversation.start(_text(system), tools, self.model, self.effort)
                tail = rest[count:]
                if count == 0 and any(m["role"] != "user" for m in tail):
                    conversation.say(record(tail))
                else:
                    conversation.feed(tail)
                pool.forget(conversation)
                message, usage = conversation.read(on_text, stopped)
                conversation.seen = keys + [key(message)]
                pool.give_back(conversation)
                return message, usage
            except Gone:
                pool.drop(conversation)  # its session is gone: the next attempt starts one from the record
            except BaseException:
                pool.drop(conversation)
                raise
        raise BrainError("provider_error", "Claude Code could not go on with this conversation")

    def _once(self, system: str, messages: List[dict], on_text, stopped) -> Tuple[dict, dict]:
        conversation = Conversation(self.claude, ())
        conversation.start(system, [], self.model, self.effort, once=True)
        try:
            if all(m["role"] == "user" for m in messages):
                conversation.say([b for m in messages for b in blocks(m.get("content"))])
            else:
                conversation.say(record(messages))
            return conversation.read(on_text, stopped)
        finally:
            conversation.process.close(wait=5)
