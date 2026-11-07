"""The agent loop: one step at a time, every step written to the event log before the next.

A run pauses by persisting and returning (approvals, app actions); answering queues it
again and the loop picks up where the log says it stopped. After a crash, a call that
started but has no result is never repeated blindly unless the tool only reads.
"""

import concurrent.futures
import difflib
import json
import logging
import re
import threading
from dataclasses import replace
from typing import Callable, Dict, List, Optional

from . import context, permissions, transport
from . import signals as signal_format
from .exceptions import BrainError, classify
from .toolkits import Tool, ToolContext, ToolError, ToolResult, format_result, tool
from .toolkits.files import resolve
from .toolkits.tasks import task_progress
from .toolkits.todo import render as render_todo

logger = logging.getLogger(__name__)

TERMINAL = ("completed", "failed", "cancelled")
ACTIVE = ("queued", "working", "input_required")
STOPPED_CALL = "Stopped: the user stopped you while this call ran. It may not have finished."
STOP_GRACE = 0.5  # seconds a stopped run gives tools that noticed to end with what they have
STEP_BUDGET = {"turn": 40, "task": 200, "agent": 60, "subagent": 60}  # agents.STEPS: by access
RETRIES = (2, 8, 30)  # seconds between attempts at a provider that is busy or down
RETRIED = ("rate_limit", "server_error", "timeout", "network")
LISTED_PER_KIT = 20  # a toolkit with more tools to load is listed by count; tools_search finds them
SEARCH_LIMIT, LOAD_LIMIT, SUMMARY_CHARS = 20, 20, 120
APP_TOOLS = "this app's own"  # how MORE TOOLS names the app's actions
META_TOOLS = ("tools_search", "tools_load")
VERIFY_ROUNDS = 2
INTERRUPTED_CALL = ("The brain stopped while this call was running. It may or may not have finished: check its "
                    "effect before you repeat it.")
VERIFY_PROMPT = """You review a background task another assistant says it finished. Be skeptical: the author
tends to praise its own work. Check the work yourself with your tools (read the files, run the tests or
commands); do not trust the report. Start your answer with PASS or FAIL on the first line, then explain.
FAIL if any part of the goal is missing, broken or unverified.

Goal:
{goal}

The author's report:
{report}"""


class Toolset:
    """Every tool a run may call (``by_name``). Requests carry ``tools`` (the core ones and, when there are
    more, tools_search and tools_load), the same on every step so the provider's prompt cache keeps hitting;
    the others (``deferred``) are listed in the system prompt, loaded into the conversation with tools_load
    and called by name (the provider passes such calls on: 5/5 on 2026-11-07)."""

    def __init__(self, tools: List[Tool], deferred: List[Tool], kits: Optional[Dict[str, str]] = None):
        self.deferred, self.kits = deferred, kits or {}
        self.tools = tools + (meta_tools(self) if deferred else [])
        self.by_name: Dict[str, Tool] = {t.name: t for t in self.tools + deferred}
        self.sent = {t.name for t in self.tools}

    def schemas(self) -> List[dict]:
        return [t.schema() for t in self.tools]

    @staticmethod
    def kit_label(toolkit: str) -> str:
        return APP_TOOLS if toolkit == "actions" else toolkit

    def listing(self) -> List[str]:
        """The MORE TOOLS lines: each toolkit's deferred tools by name, or only how many for a big one."""
        groups: Dict[str, List[str]] = {}
        for t in self.deferred:
            groups.setdefault(t.toolkit, []).append(t.name)
        lines = []
        for kit, names in groups.items():
            about = self.kits.get(kit, "")
            if len(names) > LISTED_PER_KIT:
                lines.append(f"- {self.kit_label(kit)} ({len(names)} tools)" + (f": {about}" if about else ""))
            else:
                lines.append(f"- {self.kit_label(kit)}{f' ({about})' if about else ''}: {', '.join(names)}")
        return lines

    def search(self, query: str, limit: int) -> List[Tool]:
        """Tools ranked by the query's words: in the name counts most, then the toolkit, then the description
        and parameters (at the start of a word, so "remind" finds "reminders")."""
        words = [_stem(w) for w in re.findall(r"\w+", query.lower()) if len(w) >= 3 or w.isdigit()]  # not "a", "to"
        ranked = []
        for index, t in enumerate(self.tools + self.deferred):
            if t.name in META_TOOLS:
                continue
            kit = f"{t.toolkit} {self.kits.get(t.toolkit, '')}".lower()
            text = f"{t.description} {json.dumps(t.parameters, ensure_ascii=False)}".lower()
            score = sum(3 * (w in t.name.lower()) + 2 * (w in kit) + bool(re.search(rf"\b{re.escape(w)}", text))
                        for w in words)
            if score:
                ranked.append((-score, index, t))
        return [t for *_, t in sorted(ranked, key=lambda item: item[:2])[:limit]]

    def line(self, t: Tool) -> str:
        ready = "ready" if t.name in self.sent else "load it with tools_load"
        summary = t.description.splitlines()[0][:SUMMARY_CHARS] if t.description else ""
        return f"{t.name} ({self.kit_label(t.toolkit)}, {ready}): {summary}"


def _stem(word: str) -> str:
    """Enough of English for tool search: reminded, reminders and reminding find remind."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def meta_tools(toolset: Toolset) -> List[Tool]:
    @tool(readonly=True, args={"query": "What you want to do, in a few words (empty: list every tool).",
                               "limit": f"How many to show (default 5, at most {SEARCH_LIMIT})."})
    def tools_search(ctx: ToolContext, query: str = "", limit: int = 5):
        """Find tools by what they do, among all of yours: those sent with each request (ready) and those
        to load first. An empty query lists them all, by toolkit."""
        if not query.strip():
            groups: Dict[str, List[str]] = {}
            for t in toolset.tools + toolset.deferred:
                if t.name not in META_TOOLS:
                    groups.setdefault(toolset.kit_label(t.toolkit), []).append("  " + toolset.line(t))
            return "\n".join(f"{kit}:\n" + "\n".join(lines) for kit, lines in groups.items())
        found = toolset.search(query, max(1, min(int(limit or 5), SEARCH_LIMIT)))
        return "\n".join(toolset.line(t) for t in found) or "No tool matches. Try other words, or an empty query."

    @tool(readonly=True, args={"names": {"type": "array", "items": {"type": "string"},
                                         "description": "Names from MORE TOOLS or tools_search."}})
    def tools_load(ctx: ToolContext, names: list):
        """Load tools so you can use them: shows how to call each (description and parameters). Then call
        them by name, like your other tools."""
        names = [str(name) for name in names or []][:LOAD_LIMIT]
        unknown = [name for name in names if name not in toolset.by_name]
        found = [toolset.by_name[name] for name in names if name in toolset.by_name and name not in META_TOOLS]
        if not found:
            raise ToolError(f"Unknown tools: {unknown or names}. Find tools with tools_search.")
        head = "Loaded. Call them by name from now on, like your other tools."
        if unknown:
            head += f" Not found: {', '.join(unknown)} (find tools with tools_search)."
        return head + "\n" + json.dumps([t.schema()["function"] for t in found], ensure_ascii=False, indent=1)

    return [tools_search, tools_load]


def build_toolset(kits: dict, profile: dict, kind: str, shell: str) -> Toolset:
    tools: List[Tool] = []
    for name in profile["toolkits"]:
        kit = kits.get(name)
        if kit:
            tools += [replace(t, description=t.description.replace("{shell}", shell)) for t in kit.tools]
    for action in profile.get("actions", []):
        tools.append(Tool(name=action["name"], description=action.get("description", ""),
                          parameters=action.get("parameters") or {"type": "object", "properties": {}},
                          func=None, readonly=bool(action.get("readonly")), policy=action.get("policy", "auto"),
                          toolkit="actions", core=bool(action.get("core")),
                          action=True, only_in=("turn", "agent")))  # the app runs those of a live turn and of agents
    mode = profile.get("mode")
    tools = [t for t in tools
             if (t.only_in is None or kind in t.only_in)
             and not permissions.removed(t.name, profile["rules"])
             and (mode != "readonly" or (t.readonly and not t.action))
             and (mode != "review" or (not t.action and t.name not in ("files_edit", "files_write")))]
    if kind in ("task", "agent"):
        tools.append(task_progress)  # every worker keeps notes that outlive its context
    unique = list({t.name: t for t in tools}.values())
    return Toolset([t for t in unique if t.core], [t for t in unique if not t.core],
                   {name: kit.description for name, kit in kits.items()})


def _arguments(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ToolError(f"The arguments are not valid JSON ({exc}). Send a JSON object.")
    if not isinstance(value, dict):
        raise ToolError("The arguments must be a JSON object.")
    return value


def _in_thread(work: Callable, *args, **kwargs) -> concurrent.futures.Future:
    """``work`` on a thread of its own, which nothing waits for at exit: a stopped run leaves it behind."""
    future: concurrent.futures.Future = concurrent.futures.Future()

    def run():
        try:
            future.set_result(work(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
    threading.Thread(target=run, name="sentientmilk-work", daemon=True).start()
    return future


class Stopped(Exception):
    """The run was cancelled while it worked: the model writing (what it wrote so far is dropped), or
    about to wait for answers."""


class Loop:
    def __init__(self, brain):
        self.brain = brain

    # ============== One run ==============

    def execute(self, run_id: int) -> None:
        brain, store = self.brain, self.brain.store
        run = store.run(run_id)
        if not run or run["status"] in TERMINAL:
            return
        emit = self._emitter(run_id)
        try:
            store.update_run(run_id, status="working")
            profile = brain.profile(run["app"], run["session"], run["options"].get("profile"))
            if not brain.config.values()["api_key"]:
                raise BrainError("config_missing", "SentientMilk has no provider API key",
                                 "Open the SentientMilk control panel (run sentientmilk) and set it under Provider.")
            if run["kind"] == "compact":
                return self._compact_now(run, profile, emit)
            self._log_input(run, profile)
            toolset, plugins = brain.toolset(profile, run["kind"]), brain.plugins.version
            while True:
                run = store.run(run_id)
                if run["options"].get("cancel"):
                    return self._end(run, "cancelled", emit)
                if self._settle(run, profile, toolset, emit):
                    return  # waiting for the user or the app
                if brain.plugins.version != plugins:  # a plugin came, went or changed: the next step has it
                    profile = brain.profile(run["app"], run["session"], run["options"].get("profile"))
                    toolset, plugins = brain.toolset(profile, run["kind"]), brain.plugins.version
                steps = sum(1 for e in store.run_events(run_id) if e["type"] == "assistant")
                if steps >= run["options"].get("max_steps", STEP_BUDGET[run["kind"]]):
                    raise BrainError("budget", f"Stopped after {steps} steps (the step budget)",
                                     "Progress is kept; start a new task to continue.")
                if run["kind"] in ("turn", "task"):
                    self.brain.agents.take_mail(run)  # what its agents sent meanwhile
                self._take_messages(run, emit)
                message, usage = self._think(run, profile, toolset, emit)
                store.add_event(run["app"], run["session"], run_id, "assistant", {"message": message, "usage": usage})
                self._count(run_id, usage)
                if usage.get("prompt_tokens"):  # what the session holds now, as the provider counted it
                    store.update_session(run["app"], run["session"], "state",
                                         lambda state: {**state, "context_tokens": usage["prompt_tokens"]})
                if message.get("tool_calls"):
                    continue
                if self._finish(run, profile, message, emit):
                    return
        except Stopped:
            self._end(store.run(run_id), "cancelled", emit)
        except Exception as exc:
            error = classify(exc)
            if error.type == "unknown":
                logger.exception("Run %s failed", run_id)
            self._end(store.run(run_id), "failed", emit, error=error)

    def _unless_stopped(self, run_id: int, work: Callable, *args, **kwargs):
        """``work`` on its own thread; a stop ends the wait at once (Stopped) and leaves the work behind."""
        stopped = self.brain.runs.attention(run_id).stopped
        future = _in_thread(work, *args, **kwargs)
        while True:
            try:
                return future.result(timeout=0.1)
            except concurrent.futures.TimeoutError:
                if stopped.is_set():
                    raise Stopped()

    def _take_messages(self, run: dict, emit) -> None:
        """Messages the user sent while the run worked (steering) join the log before the next model call."""
        runs, store = self.brain.runs, self.brain.store
        with runs.steer_lock:
            items = store.run(run["id"])["options"].get("steer") or []
            if items:
                store.update_run_options(run["id"], lambda options: {**options, "steer": []})
            runs.attention(run["id"]).settle()
        if items:
            content, display = context.input_content(items, {}, reminders=[])
            store.add_event(run["app"], run["session"], run["id"], "input", {"content": content, "display": display})
            emit({"type": "steered", "text": display or ""})

    def _emitter(self, run_id: int) -> Callable[[dict], None]:
        def emit(event: dict) -> None:
            self.brain.bus.publish(("run", run_id), {"run": run_id, **event})
        return emit

    def _log_input(self, run: dict, profile: dict) -> None:
        options = run["options"]
        if options.get("input") is None or any(e["type"] == "input" for e in self.brain.store.run_events(run["id"])):
            return
        reminders = []
        if profile["signals"] and run["kind"] == "turn":
            reminders.append(signal_format.FORMAT_REMINDER)
        if options.get("reply") == "optional":
            reminders.append(signal_format.OPTIONAL_REPLY)
        content, display = context.input_content(options["input"], options.get("context") or {}, reminders=reminders)
        self.brain.store.add_event(run["app"], run["session"], run["id"], "input",
                                   {"content": content, "display": display})
        self.brain.store.update_run_options(run["id"], lambda now: {**now, "input": None})  # the event keeps it

    def _count(self, run_id: int, usage: dict) -> None:
        run = self.brain.store.run(run_id)
        total = run["usage"] or {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        total["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens", "cached_tokens"):
            total[key] += usage.get(key) or 0
        self.brain.store.update_run(run_id, usage=total)

    # ============== Tool calls ==============

    def _settle(self, run: dict, profile: dict, toolset: Toolset, emit) -> bool:
        """Run what the last model message asked for; True when the run must wait for answers."""
        store = self.brain.store
        events = store.run_events(run["id"])
        last = next((e for e in reversed(events) if e["type"] == "assistant"), None)
        if not last or not last["message"].get("tool_calls"):
            return False
        done = {e["call_id"] for e in events if e["type"] == "tool"}
        started = {e["call_id"] for e in events if e["type"] == "tool_start"}
        answers = {e["call_id"]: e for e in events if e["type"] == "approval"}
        results = {e["call_id"]: e for e in events if e["type"] == "action_result"}
        asked = {(e["call_id"], e["type"]) for e in events if e["type"] in ("approval_request", "action_request")}
        ready, waiting = [], False
        for call in last["message"]["tool_calls"]:
            if call["id"] in done:
                continue
            try:
                name, tool_, arguments = self._resolve_call(call, toolset)
            except ToolError as exc:
                self._result(run, call, call["function"]["name"], {}, ToolResult(f"Error: {exc}"), "error", emit)
                continue
            if call["id"] in started and not tool_.readonly:
                self._result(run, call, name, arguments, ToolResult(INTERRUPTED_CALL), "error", emit)
                continue
            decision = permissions.decide(tool_, arguments, profile["rules"], profile.get("cwd"))
            must_ask = decision == "always"  # an "always allow" is this once, and apps may not answer for the user
            decision = "ask" if must_ask else decision
            if decision == "ask" and run["kind"] == "subagent":
                decision = "off"  # helpers cannot ask the user
            if decision == "off":
                self._result(run, call, name, arguments,
                             ToolResult(f"Refused: {name} is not allowed here{' for these arguments' if tool_.rule_arg else ''}."),
                             "error", emit)
                continue
            if decision == "ask":
                answer = answers.get(call["id"])
                if answer is None:
                    waiting = True
                    if (call["id"], "approval_request") not in asked:
                        self._ask(run, "approval", call, name, arguments, emit, always_ask=must_ask)
                    continue
                if answer["decision"] == "deny":
                    reason = f" Their reason: {answer['reason']}" if answer.get("reason") else ""
                    self._result(run, call, name, arguments,
                                 ToolResult(f"The user did not allow this call.{reason}"), "error", emit)
                    continue
                if answer["decision"] == "always" and not must_ask:
                    self.brain.allow_always(run["app"], permissions.always_rule(tool_, arguments, profile.get("cwd")))
            if tool_.action:  # the app runs it
                if call["id"] in results:
                    answer = results[call["id"]]
                    self._result(run, call, name, arguments, format_result(answer["result"]),
                                 answer.get("status", "ok"), emit)
                    self._attach(run, answer.get("images") or [])
                else:  # the app runs it as soon as it is asked: only once the calls before it are done
                    if not waiting and not ready and (call["id"], "action_request") not in asked:
                        self._ask(run, "action", call, name, arguments, emit)
                    waiting = True  # with nothing asked yet, the step settles again after the calls before it
                continue
            if waiting:  # an earlier call waits for an answer: this one runs after it, in the model's order
                continue
            ready.append((call, name, tool_, arguments))
        self._run_tools(run, profile, ready, emit)
        if not waiting:
            return False
        with self.brain.runs.pause_lock:
            answered = not self.brain.runs.waiting(run["id"])  # answers that came while tools ran
            stopped = bool(store.run(run["id"])["options"].get("cancel"))  # a stop that came meanwhile
            if not answered and not stopped:
                store.update_run(run["id"], status="input_required")
        if stopped:
            raise Stopped()
        if answered:
            return self._settle(run, profile, toolset, emit)
        emit({"type": "paused", "status": "input_required"})
        self.brain.runs.paused(store.run(run["id"]))
        return True

    def _resolve_call(self, call: dict, toolset: Toolset):
        """Any tool of the run may be called, sent with the request or not: loading only shows the model
        how (a call with wrong arguments shows the parameters, see _run_tools)."""
        name = (call.get("function") or {}).get("name", "")
        arguments = _arguments(call)
        tool_ = toolset.by_name.get(name)
        if tool_ is None:
            close = difflib.get_close_matches(name, list(toolset.by_name), n=3, cutoff=0.6)
            hint = f" Did you mean {', '.join(close)}?" if close else ""
            more = " Find tools with tools_search." if "tools_search" in toolset.by_name else \
                f" Your tools: {', '.join(toolset.by_name)}."
            raise ToolError(f"There is no tool {name!r}.{hint}{more}")
        return name, tool_, arguments

    def _ask(self, run: dict, kind: str, call: dict, name: str, arguments: dict, emit, always_ask: bool = False) -> None:
        """``always_ask``: the user must answer, even in an app that allows everything on its own."""
        request = {"call_id": call["id"], "name": name, "arguments": arguments,
                   **({"always_ask": True} if always_ask else {})}
        self.brain.store.add_event(run["app"], run["session"], run["id"], f"{kind}_request", request)
        emit({"type": f"{kind}.requested", **request})

    def _run_tools(self, run: dict, profile: dict, ready: list, emit) -> None:
        """Run the calls (read-only ones together), each on its own thread. A stop ends the step at once: calls
        still running get a stopped result and are left behind, the rest do not run, and the run ends."""
        if not ready:
            return
        attention = self.brain.runs.attention(run["id"])
        attachments: List[str] = []

        def work(item):
            call, name, tool_, arguments = item
            ctx = ToolContext(self.brain, run, profile, call["id"], emit, attention)
            try:
                return format_result(tool_.func(ctx, **arguments)), "ok"
            except ToolError as exc:
                return ToolResult(f"Error: {exc}"), "error"
            except TypeError as exc:  # wrong or missing arguments: how to call it, for a schema it may not have
                return ToolResult(f"Error: {exc}. Its parameters: "
                                  f"{json.dumps(tool_.parameters, ensure_ascii=False)}"), "error"
            except Exception as exc:
                logger.exception("Tool %s failed", name)
                return ToolResult(f"Error: {type(exc).__name__}: {exc}"), "error"

        def together(items) -> None:
            futures = []
            for call, name, _, arguments in items:
                self.brain.store.add_event(run["app"], run["session"], run["id"], "tool_start",
                                           {"call_id": call["id"], "name": name})
                emit({"type": "tool.start", "call_id": call["id"], "name": name, "arguments": arguments})
            futures = [_in_thread(work, item) for item in items]
            pending = set(futures)
            while pending:
                _, pending = concurrent.futures.wait(pending, timeout=0.1)
                if pending and attention.stopped.is_set():
                    concurrent.futures.wait(pending, timeout=STOP_GRACE)
                    break
            for (call, name, _, arguments), future in zip(items, futures):
                result, status = future.result() if future.done() else (ToolResult(STOPPED_CALL), "error")
                self._result(run, call, name, arguments, result, status, emit)
                attachments.extend(result.images)

        groups: List[list] = []  # in the model's order: reads next to each other run together
        for item in ready:
            if item[2].readonly and groups and groups[-1][-1][2].readonly:
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            if attention.stopped.is_set():  # not started: the model learns they did not run
                for call, name, _, arguments in group:
                    self._result(run, call, name, arguments, ToolResult(STOPPED_CALL), "error", emit)
            else:
                together(group)
        self._attach(run, attachments)
        if attention.stopped.is_set():
            raise Stopped()

    def _attach(self, run: dict, images: List[str]) -> None:
        """Images from tool results reach the model as one user message after the results."""
        if images:
            blocks = [{"type": "text", "text": "[Images from your tool calls]"}] + \
                     [{"type": "image_url", "image_url": {"url": url}} for url in images]
            self.brain.store.add_event(run["app"], run["session"], run["id"], "attachment", {"content": blocks})

    def _result(self, run, call, name, arguments, result: ToolResult, status: str, emit) -> None:
        self.brain.store.add_event(run["app"], run["session"], run["id"], "tool", {
            "call_id": call["id"], "name": name, "arguments": arguments, "content": result.text, "status": status})
        emit({"type": "tool.end", "call_id": call["id"], "name": name, "arguments": arguments, "status": status,
              "result": result.text[:2000]})

    # ============== Thinking ==============

    def _think(self, run: dict, profile: dict, toolset: Toolset, emit):
        brain = self.brain
        settings = brain.config.values()
        provider = brain.provider(run["options"].get("model") or profile["model"])
        system = context.system_prompt(profile, brain.session_snapshot(profile), brain.shell_label(),
                                       toolset.by_name, toolset.listing())

        def text(delta):
            emit({"type": "text.delta", "text": delta})
        stream = None  # apps with signals: the header line is split off the streamed text
        if profile["signals"] and run["kind"] == "turn":
            stream = signal_format.HeaderStream(lambda header: emit({"type": "signals", "signals": header}), text)
        feed = stream.feed if stream else text
        stopped = brain.runs.attention(run["id"]).stopped

        def on_text(delta):  # the request is left behind on a stop; this ends it at its next words
            if stopped.is_set():
                raise Stopped()
            feed(delta)
        compacted = False
        for attempt in range(len(RETRIES) + 1):
            messages = self._messages(run, profile, system)
            try:
                sent = transport.prepare_messages([{"role": "system", "content": system}] + messages,
                                                  settings["request_budget"], support_images=settings["vision"])
            except transport.RequestPayloadTooLarge:
                if compacted:
                    raise
                self.compact(run, profile, force=True)
                compacted = True
                continue
            if stream:
                stream.reset()
            try:
                return self._unless_stopped(run["id"], provider.complete, sent, toolset.schemas(), on_text=on_text)
            except Stopped:
                raise
            except Exception as exc:
                error = classify(exc)
                too_long = error.type == "payload_too_large" or (
                    error.http_status == 400 and "context" in (error.details or "").lower())
                if too_long and not compacted:
                    self.compact(run, profile, force=True)
                    compacted = True
                    continue
                if error.type not in RETRIED or attempt == len(RETRIES):
                    raise error from exc
                logger.warning("Provider problem (%s); retrying in %s s", error.type, RETRIES[attempt])
                emit({"type": "retry", "error": error.as_dict(), "wait": RETRIES[attempt]})
                if stopped.wait(RETRIES[attempt]):
                    raise Stopped()
        raise BrainError("payload_too_large", "The conversation does not fit even after compaction")

    def _messages(self, run: dict, profile: dict, system: str) -> List[dict]:
        store = self.brain.store
        window = profile["context_window"]
        for _ in range(3):
            compaction = store.last_compaction(run["app"], run["session"])
            events = [e for e in store.events(run["app"], run["session"], after=compaction["upto"] if compaction else 0)
                      if e["type"] != "compaction"]
            messages = context.project(events, compaction)
            tokens = context.estimate_tokens(messages, system)
            if tokens > context.COMPACT_AT * window:
                self.compact(run, profile)
                continue
            if tokens > context.CLEAR_AT * window:
                ids = context.clearable(events, window, tokens)
                if ids:
                    cleared = set(ids)
                    after = context.estimate_tokens(context.project(
                        events + [{"id": 0, "type": "clearing", "ids": ids}], compaction), system)
                    store.add_event(run["app"], run["session"], run["id"], "clearing",
                                    {"ids": sorted(cleared), "after": after})
                    self._emitter(run["id"])({"type": "cleared", "results": len(cleared)})
                    continue
            return messages
        return messages

    # ============== Compaction ==============

    def compact(self, run: dict, profile: dict, force: bool = False, keep: Optional[int] = None) -> bool:
        """Summarize the older part of the session (all of it with ``keep`` 0); the raw events stay in the log.
        False when there was nothing to summarize."""
        brain, store = self.brain, self.brain.store
        app, session = run["app"], run["session"]
        previous = store.last_compaction(app, session)
        events = [e for e in store.events(app, session, after=previous["upto"] if previous else 0)
                  if e["type"] != "compaction"]
        if keep is None:
            keep = int(context.KEEP_RECENT * profile["context_window"] * 4 * (0.3 if force else 1))
        elif not events:
            return False
        cut = context.choose_cut(events, keep)
        if cut == 0 and not previous:
            return False
        older = events[:cut]
        self._emitter(run["id"])({"type": "compacting"})  # it takes a model call: apps can show it
        state = store.session(app, session)["state"]
        if run["options"].get("context_mode") == "reset":
            summary = context.handoff(brain.home / "runs" / str(run["id"]), state.get("todo", []), profile.get("cwd"))
        else:
            transcript = context.transcript_for_summary(older, previous)
            limit = profile["context_window"] * 2  # characters: the summary request itself must fit
            if len(transcript) > limit:
                transcript = context.transcript_for_summary(older, previous, per_result=300)[-limit:]
            provider = brain.provider(profile["light_model"])
            message, _ = self._unless_stopped(run["id"], provider.complete,
                                              [{"role": "system", "content": context.COMPACT_PROMPT},
                                               {"role": "user", "content": transcript}])
            summary = (message.get("content") or "").strip() or transcript[-8000:]
            excerpts = []
            room = profile["context_window"]  # characters, about a quarter of the window: they must not overflow it
            for path in context.recent_files(older):
                try:
                    target = resolve(ToolContext(brain, run, profile), path)
                except ToolError:
                    continue
                text = context.file_excerpt(target)
                if text and len(text) <= room:
                    excerpts.append(f"### {target}\n```\n{text}\n```")
                    room -= len(text)
            if excerpts:
                summary += "\n\n## Files you read recently (their current start)\n" + "\n\n".join(excerpts)
            if state.get("todo"):
                summary += "\n\n## Your todo list\n" + render_todo(state["todo"])
        upto = older[-1]["id"] if older else (previous["upto"] if previous else 0)
        store.add_event(app, session, run["id"], "compaction", {"summary": summary, "upto": upto})
        brain.refresh_snapshot(profile)
        brain.journal.request(app, session)
        self._emitter(run["id"])({"type": "compacted"})
        return True

    def _compact_now(self, run: dict, profile: dict, emit) -> None:
        """A compact run: the whole session summed up now, and how full the context is after."""
        brain, store = self.brain, self.brain.store
        app, session = run["app"], run["session"]
        before = store.session(app, session)["state"].get("context_tokens", 0)
        compacted = self.compact(run, profile, keep=0)
        after = before
        if compacted:
            compaction = store.last_compaction(app, session)
            events = [e for e in store.events(app, session, after=compaction["upto"]) if e["type"] != "compaction"]
            turn_tools = brain.toolset(profile, "turn")
            system = context.system_prompt(profile, brain.session_snapshot(profile), brain.shell_label(),
                                           turn_tools.by_name, turn_tools.listing())
            after = context.estimate_tokens(context.project(events, compaction), system)
            store.update_session(app, session, "state", lambda state: {**state, "context_tokens": after})
        self._end(store.run(run["id"]), "completed", emit, extra={"compacted": compacted, "before": before,
                                                                    "after": after})

    # ============== Ending ==============

    def _finish(self, run: dict, profile: dict, message: dict, emit) -> bool:
        """Handle the final reply; False when a reviewer sent the task back to work."""
        content = message.get("content") or ""
        values: dict = {}
        if profile["signals"] and run["kind"] == "turn":
            header, reply = signal_format.split(content)
            values, problems = signal_format.check(header, profile["signals"])
            if problems:
                self.brain.note(run["app"], run["session"], "About your last reply: " + " ".join(problems) +
                                " Start every final reply with the signals JSON line.")
        else:
            reply = content.strip()
        silent = run["options"].get("reply") == "optional" and signal_format.is_silent(reply)
        if silent:
            reply = ""
        if run["kind"] == "task" and run["options"].get("verify"):
            rounds = run["options"].get("verify_rounds", 0)
            if rounds < VERIFY_ROUNDS:
                verdict = self.brain.runs.review(run, reply)
                self.brain.store.update_run_options(run["id"], lambda options: {**options, "verify_rounds": rounds + 1})
                if not verdict.lstrip().upper().startswith("PASS"):
                    self.brain.note(run["app"], run["session"],
                                    f"A reviewer checked your work and it did not pass:\n{verdict}\nFix this, then report again.")
                    return False
        self._end(run, "completed", emit, reply=reply, signals=values, silent=silent)
        return True

    def _end(self, run: dict, status: str, emit, reply: str = "", signals: Optional[dict] = None,
             silent: bool = False, error: Optional[BrainError] = None, extra: Optional[dict] = None) -> None:
        store = self.brain.store
        result = {"reply": reply, "signals": signals or {}, "silent": silent, **(extra or {})}
        with self.brain.runs.steer_lock:  # a message that came too late goes back to the app, unread
            unread = store.run(run["id"])["options"].get("steer") or []
            if unread:
                result["unread"] = unread
            store.add_event(run["app"], run["session"], run["id"], "end",
                            {"status": status, **result, "error": error.as_dict() if error else None})
            self.brain.agents.ending({**run, "status": status, "result": result,
                                      "error": error.as_dict() if error else None})
            store.update_run(run["id"], status=status, result=result, error=error.as_dict() if error else None)
        final = store.run(run["id"])
        if error:
            emit({"type": "error", "status": status, "error": error.as_dict()})
        else:
            emit({"type": "done", "status": status, **result, "usage": final["usage"]})
        self.brain.runs.finished(final)
