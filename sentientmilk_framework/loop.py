"""The agent loop: one step at a time, every step written to the event log before the next.

A run pauses by persisting and returning (approvals, app actions); answering queues it
again and the loop picks up where the log says it stopped. After a crash, a call that
started but has no result is never repeated blindly unless the tool only reads.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Callable, Dict, List, Optional

from . import context, permissions, transport
from . import signals as signal_format
from .exceptions import BrainError, classify
from .toolkits import Tool, ToolContext, ToolError, ToolResult, format_result, tool
from .toolkits.files import resolve
from .toolkits.todo import render as render_todo

logger = logging.getLogger(__name__)

TERMINAL = ("completed", "failed", "cancelled")
STEP_BUDGET = {"turn": 40, "task": 200, "subagent": 60}
RETRIES = (2, 8, 30)  # seconds between attempts at a provider that is busy or down
RETRIED = ("rate_limit", "server_error", "timeout", "network")
CANCEL_CHECK = 0.3  # seconds between looks at a stop while the model writes
DEFER_AT = 40  # more tools than this: MCP tools are listed, not sent (see tools_describe)
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
    def __init__(self, tools: List[Tool], deferred: List[Tool]):
        self.tools, self.deferred = tools, deferred
        self.by_name: Dict[str, Tool] = {t.name: t for t in deferred + tools}
        self.deferred_names = {t.name for t in deferred}

    def schemas(self) -> List[dict]:
        return [t.schema() for t in self.tools]

    def summaries(self) -> List[dict]:
        return [{"name": t.name, "summary": t.description.split("\n")[0][:160]} for t in self.deferred]


def meta_tools(deferred: List[Tool]) -> List[Tool]:
    @tool(readonly=True, args={"names": {"type": "array", "items": {"type": "string"},
                                         "description": "Tool names from the MORE TOOLS list."}})
    def tools_describe(ctx: ToolContext, names: list):
        """Show the description and parameters of tools from the MORE TOOLS list."""
        found = {t.name: t for t in deferred}
        unknown = [name for name in names if name not in found]
        if unknown:
            raise ToolError(f"Unknown tools: {unknown}. Pick names from the MORE TOOLS list.")
        return json.dumps([found[name].schema()["function"] for name in names], ensure_ascii=False, indent=1)

    @tool(readonly=False, policy="auto", args={"name": "A tool from the MORE TOOLS list.",
                                               "arguments": {"type": "object", "description": "Its arguments."}})
    def tools_call(ctx: ToolContext, name: str, arguments: dict = None):
        """Call a tool from the MORE TOOLS list (read its parameters with tools_describe first)."""
        raise ToolError("tools_call is handled by the brain")  # unwrapped in Loop._call

    return [tools_describe, tools_call]


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
                          toolkit="actions",
                          action=True, only_in=("turn",)))  # only a turn has the app there to run it
    mode = profile.get("mode")
    tools = [t for t in tools
             if (t.only_in is None or kind in t.only_in)
             and not permissions.removed(t.name, profile["rules"])
             and (mode != "readonly" or (t.readonly and not t.action))
             and (mode != "review" or (not t.action and t.name not in ("files_edit", "files_write")))]
    unique = list({t.name: t for t in tools}.values())
    if len(unique) <= DEFER_AT:
        return Toolset(unique, [])
    deferred = [t for t in unique if t.toolkit.startswith("mcp:")]
    offered = [t for t in unique if not t.toolkit.startswith("mcp:")]
    return Toolset(offered + meta_tools(deferred), deferred)


def _arguments(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ToolError(f"The arguments are not valid JSON ({exc}). Send a JSON object.")
    if not isinstance(value, dict):
        raise ToolError("The arguments must be a JSON object.")
    return value


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
            self._log_input(run, profile)
            toolset = brain.toolset(profile, run["kind"])
            while True:
                run = store.run(run_id)
                if run["options"].get("cancel"):
                    return self._end(run, "cancelled", emit)
                if self._settle(run, profile, toolset, emit):
                    return  # waiting for the user or the app
                steps = sum(1 for e in store.run_events(run_id) if e["type"] == "assistant")
                if steps >= run["options"].get("max_steps", STEP_BUDGET[run["kind"]]):
                    raise BrainError("budget", f"Stopped after {steps} steps (the step budget)",
                                     "Progress is kept; start a new task to continue.")
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
        self.brain.store.update_run(run["id"], options={**options, "input": None})  # the event keeps it now

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
                        self._ask(run, "approval", call, name, arguments, emit)
                    continue
                if answer["decision"] == "deny":
                    reason = f" Their reason: {answer['reason']}" if answer.get("reason") else ""
                    self._result(run, call, name, arguments,
                                 ToolResult(f"The user did not allow this call.{reason}"), "error", emit)
                    continue
                if answer["decision"] == "always":
                    self.brain.allow_always(run["app"], permissions.always_rule(tool_, arguments, profile.get("cwd")))
            if tool_.action:  # the app runs it
                if call["id"] in results:
                    answer = results[call["id"]]
                    self._result(run, call, name, arguments, format_result(answer["result"]),
                                 answer.get("status", "ok"), emit)
                    self._attach(run, answer.get("images") or [])
                else:
                    waiting = True
                    if (call["id"], "action_request") not in asked:
                        self._ask(run, "action", call, name, arguments, emit)
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
        name = (call.get("function") or {}).get("name", "")
        arguments = _arguments(call)
        if name == "tools_call" and "tools_call" in toolset.by_name:
            name, arguments = arguments.get("name", ""), arguments.get("arguments") or {}
            if name not in toolset.deferred_names:
                raise ToolError(f"{name!r} is not in the MORE TOOLS list.")
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be an object.")
        tool_ = toolset.by_name.get(name)
        if tool_ is None or (name in toolset.deferred_names and call["function"]["name"] != "tools_call"):
            available = ", ".join(t.name for t in toolset.tools)
            raise ToolError(f"There is no tool {name!r}. Available: {available}.")
        return name, tool_, arguments

    def _ask(self, run: dict, kind: str, call: dict, name: str, arguments: dict, emit) -> None:
        self.brain.store.add_event(run["app"], run["session"], run["id"], f"{kind}_request",
                                   {"call_id": call["id"], "name": name, "arguments": arguments})
        emit({"type": f"{kind}.requested", "call_id": call["id"], "name": name, "arguments": arguments})

    def _run_tools(self, run: dict, profile: dict, ready: list, emit) -> None:
        if not ready:
            return
        attachments: List[str] = []

        def one(item):
            call, name, tool_, arguments = item
            ctx = ToolContext(self.brain, run, profile, call["id"], emit)
            self.brain.store.add_event(run["app"], run["session"], run["id"], "tool_start",
                                       {"call_id": call["id"], "name": name})
            emit({"type": "tool.start", "call_id": call["id"], "name": name, "arguments": arguments})
            try:
                result, status = format_result(tool_.func(ctx, **arguments)), "ok"
            except ToolError as exc:
                result, status = ToolResult(f"Error: {exc}"), "error"
            except TypeError as exc:  # wrong or missing arguments
                result, status = ToolResult(f"Error: {exc}. Check the tool's parameters."), "error"
            except Exception as exc:
                logger.exception("Tool %s failed", name)
                result, status = ToolResult(f"Error: {type(exc).__name__}: {exc}"), "error"
            self._result(run, call, name, arguments, result, status, emit)
            attachments.extend(result.images)

        readonly = [item for item in ready if item[2].readonly]
        others = [item for item in ready if not item[2].readonly]
        if len(readonly) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(readonly))) as pool:
                list(pool.map(one, readonly))
        else:
            others = readonly + others
        for item in others:
            one(item)
        self._attach(run, attachments)

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
        system = context.system_prompt(profile, brain.session_snapshot(profile), toolset.summaries(),
                                       brain.shell_label())

        def text(delta):
            emit({"type": "text.delta", "text": delta})
        stream = None  # apps with signals: the header line is split off the streamed text
        if profile["signals"] and run["kind"] == "turn":
            stream = signal_format.HeaderStream(lambda header: emit({"type": "signals", "signals": header}), text)
        feed, looked = stream.feed if stream else text, [0.0]

        def on_text(delta):  # a stop is seen within CANCEL_CHECK, not only once the reply is done
            if time.monotonic() - looked[0] >= CANCEL_CHECK:
                looked[0] = time.monotonic()
                if brain.store.run(run["id"])["options"].get("cancel"):
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
                return provider.complete(sent, toolset.schemas(), on_text=on_text)
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
                time.sleep(RETRIES[attempt])
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

    def compact(self, run: dict, profile: dict, force: bool = False) -> None:
        """Summarize the older part of the session; the raw events stay in the log."""
        brain, store = self.brain, self.brain.store
        app, session = run["app"], run["session"]
        previous = store.last_compaction(app, session)
        events = [e for e in store.events(app, session, after=previous["upto"] if previous else 0)
                  if e["type"] != "compaction"]
        keep = int(context.KEEP_RECENT * profile["context_window"] * 4 * (0.3 if force else 1))
        cut = context.choose_cut(events, keep)
        if cut == 0 and not previous:
            return
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
            message, _ = provider.complete([{"role": "system", "content": context.COMPACT_PROMPT},
                                            {"role": "user", "content": transcript}])
            summary = (message.get("content") or "").strip() or transcript[-8000:]
            excerpts = []
            for path in context.recent_files(older):
                try:
                    target = resolve(ToolContext(brain, run, profile), path)
                except ToolError:
                    continue
                text = context.file_excerpt(target)
                if text:
                    excerpts.append(f"### {target}\n```\n{text}\n```")
            if excerpts:
                summary += "\n\n## Files you read recently (their current start)\n" + "\n\n".join(excerpts)
            if state.get("todo"):
                summary += "\n\n## Your todo list\n" + render_todo(state["todo"])
        upto = older[-1]["id"] if older else (previous["upto"] if previous else 0)
        store.add_event(app, session, run["id"], "compaction", {"summary": summary, "upto": upto})
        brain.refresh_snapshot(profile)
        brain.journal.request(app, session)
        self._emitter(run["id"])({"type": "compacted"})

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
                self.brain.store.update_run(run["id"], options={**run["options"], "verify_rounds": rounds + 1})
                if not verdict.lstrip().upper().startswith("PASS"):
                    self.brain.note(run["app"], run["session"],
                                    f"A reviewer checked your work and it did not pass:\n{verdict}\nFix this, then report again.")
                    return False
        self._end(run, "completed", emit, reply=reply, signals=values, silent=silent)
        return True

    def _end(self, run: dict, status: str, emit, reply: str = "", signals: Optional[dict] = None,
             silent: bool = False, error: Optional[BrainError] = None) -> None:
        store = self.brain.store
        result = {"reply": reply, "signals": signals or {}, "silent": silent}
        store.add_event(run["app"], run["session"], run["id"], "end",
                        {"status": status, **result, "error": error.as_dict() if error else None})
        store.update_run(run["id"], status=status, result=result, error=error.as_dict() if error else None)
        final = store.run(run["id"])
        if error:
            emit({"type": "error", "status": status, "error": error.as_dict()})
        else:
            emit({"type": "done", "status": status, **result, "usage": final["usage"]})
        self.brain.runs.finished(final)
