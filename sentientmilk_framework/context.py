"""What the model sees: a stable system block, the history projected from the event log, the newest input.

Rule: between compactions the projection only grows at the end, so the provider's
prefix cache keeps hitting. Clearing and compaction are the only rewrites of the past
(the image rule in transport.py touches the last few image turns, a measured trade-off).
"""

import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import signals as signal_format
from .toolkits.todo import render as render_todo

SUMMARY_PREFIX = "[Summary of the earlier conversation, written when it no longer fit]\n"
CLEARED = "[Result cleared to save space. Call {name} again with the same arguments if you need it.]"
INTERRUPTED = "[No result: the call was interrupted.]"
KEPT_RESULTS = 5  # tool results never cleared
CLEAR_AT, CLEAR_STEP, COMPACT_AT, KEEP_RECENT = 0.5, 0.1, 0.75, 0.1  # fractions of the context window
JOURNAL_CHARS, MEMORY_CHARS = 6_000, 8_000

IDENTITY = """## WHO YOU ARE
{called}The description below is you. Read it as "you", even where it says "she" or "he" or uses
your name: it is who you are, not a role you play. Think as yourself: your reasoning is your own inner
voice, in the first person, with your feelings, habits and way of seeing things. Never plan how to
act, play or portray someone, and never step outside yourself to talk about "the character".
How you speak follows the description."""

RULES = """## HOW YOU WORK
- Use your tools on your own whenever they help; do not ask for permission first. When a tool needs the
  user's approval, they are asked for you.
- Look before you act: search and read before you change anything.
- Verify after you act: run it, test it, read the result. Say what you verified and what you did not.
- Keep going until the request is done or you are truly blocked; then say exactly what blocks you.
- When a tool fails, read the error and fix the call; do not repeat a call that failed the same way.
- Notes in square brackets in user messages are not from the user: they tell you the time, events and
  finished tasks.
- Never talk about yourself as "an AI" or "a language model": you are who WHO YOU ARE says."""
TODO_RULE = "- For work with three or more steps, keep a todo list with todo_write and keep it current."
MEMORY_RULE = ("- When you learn something lasting about the user, save it with memory_save right away, unasked. "
               "Memory is for what stays true; one-time events and changes are not worth keeping.")

COMPACT_PROMPT = """You summarize the earlier part of a conversation between the user and you, so you can
continue without it; YOU marks what you said and did, and the tools you used. Write the summary to
yourself, in the second person ("you read the files"), never about "the assistant". Write these sections:
1. User requests: every request and instruction from the user, quoted when short.
2. Goal and current state: what is being worked on and how far it got.
3. Decisions: what was decided and why.
4. Files, URLs and ids: every path, URL, id or name that still matters, and what it is.
5. Errors and fixes: problems met and how they were solved.
6. Open problems.
7. Next steps.
Be specific and complete. Leave out chatter and raw tool output that no longer matters.
Write in the language of the conversation."""


# ============== System block ==============

def computer_section(profile: dict, shell: str) -> Optional[str]:
    if not {"files", "shell"} & set(profile["toolkits"]):
        return None
    lines = ["## YOUR COMPUTER", f"OS: {platform.system()} {platform.release()}"]
    if "shell" in profile["toolkits"]:
        lines.append(f"Shell for shell_run: {shell}")
    if profile.get("cwd"):
        lines.append(f"Working folder: {profile['cwd']}")
    lines.append("Folders open to you: " + (", ".join(profile["roots"]) or "none"))
    return "\n".join(lines)


def system_prompt(profile: dict, snapshot: dict, deferred: List[dict], shell: str) -> str:
    called = f"In this app you are called {profile['name']}. " if profile.get("name") else ""
    parts = [IDENTITY.format(called=called), profile["persona"]]  # the persona is who the model is
    if profile.get("environment"):
        parts.append("## ENVIRONMENT\n" + profile["environment"])
    computer = computer_section(profile, shell)
    if computer:
        parts.append(computer)
    parts.append(RULES + "".join("\n" + rule for kit, rule in (("todo", TODO_RULE), ("memory", MEMORY_RULE))
                                 if kit in profile["toolkits"]))
    if profile.get("instructions"):
        parts.append("## THIS SESSION\n" + profile["instructions"])
    if snapshot.get("memory"):
        parts.append("## WHAT YOU REMEMBER IN THIS APP\n" + snapshot["memory"])
    if snapshot.get("journal"):
        parts.append("## RECENT NOTES FROM YOUR OTHER SESSIONS (oldest first)\n" + snapshot["journal"])
    if deferred:
        parts.append("## MORE TOOLS\nThese tools exist too. Get their parameters with tools_describe, then call them "
                     "with tools_call:\n" + "\n".join(f"- {t['name']}: {t['summary']}" for t in deferred))
    if profile.get("signals"):
        parts.append(signal_format.prompt_section(profile["signals"]))
    return "\n\n".join(parts)


def snapshot(store, profile: dict) -> dict:
    """App memory and journal as of now: refreshed only at session start and at compaction."""
    from .toolkits.journal import line

    result = {"at": time.time(), "memory": "", "journal": ""}
    if "memory" in profile["toolkits"]:
        memories = store.memories(profile["app"])
        if memories:
            text = json.dumps(memories, ensure_ascii=False, indent=1)
            result["memory"] = text if len(text) <= MEMORY_CHARS else (
                "Categories: " + ", ".join(f"{name} ({len(items)} items)" for name, items in memories.items())
                + "\nRead them with memory_list.")
    if profile["journal"]["read"]:
        lines, size = [], 0
        for note in store.notes(limit=200):
            if note["app"] == profile["app"] and note["session"] == profile["session"]:
                continue  # this session's own history is in context already
            entry = line(note)
            if size + len(entry) > JOURNAL_CHARS:
                break
            lines.append(entry)
            size += len(entry)
        result["journal"] = "\n".join(reversed(lines))
    return result


# ============== Inputs ==============

def input_content(items: List[dict], context: Dict[str, str], *, reminders: List[str]) -> tuple:
    """(content for the model, text for the transcript). Time and context lead, reminders close it."""
    stamp = time.strftime("%Y-%m-%d %H:%M (%A)")
    head = "[Context: " + " | ".join([f"time: {stamp}"] + [f"{k}: {v}" for k, v in context.items()]) + "]"
    texts, images, display = [head], [], []
    for item in items:
        if item["type"] == "text":
            texts.append(item["text"])
            display.append(item["text"])
        elif item["type"] == "event":
            data = f" {json.dumps(item['data'], ensure_ascii=False)}" if item.get("data") else ""
            texts.append(f"[Event: {item['name']}] {item.get('text', '')}{data}".rstrip())
        elif item["type"] == "image":
            images.append(item["url"])
    tail = "\n".join(f"[{reminder}]" for reminder in reminders)
    text = "\n".join(texts)
    if not images:
        return (text + ("\n\n" + tail if tail else "")), ("\n".join(display) or None)
    blocks = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks, ("\n".join(display) or None)


# ============== History ==============

def _add_user(messages: List[dict], content) -> None:
    """Consecutive user messages are merged: some providers reject two in a row."""
    if messages and messages[-1]["role"] == "user":
        previous = messages[-1]["content"]
        if isinstance(previous, str) and isinstance(content, str):
            messages[-1]["content"] = previous + "\n\n" + content
        else:
            messages[-1]["content"] = _blocks(previous) + _blocks(content)
        return
    messages.append({"role": "user", "content": content})


def _blocks(content) -> list:
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def _assistant(message: dict) -> dict:
    kept = {key: message[key] for key in ("tool_calls", "reasoning_content", "reasoning", "reasoning_details")
            if message.get(key)}
    return {"role": "assistant", "content": message.get("content") or "", **kept}


def note_text(event: dict) -> str:
    return f"[Note: {event['text']}]"


def project(events: List[dict], compaction: Optional[dict]) -> List[dict]:
    """Model messages for the events after the last compaction, deterministic for the same log."""
    messages: List[dict] = []
    if compaction:
        messages.append({"role": "user", "content": SUMMARY_PREFIX + compaction["summary"]})
    cleared = {i for e in events if e["type"] == "clearing" for i in e["ids"]}
    pending: List[str] = []
    held: List[dict] = []

    def settle():
        for call_id in pending:
            messages.append({"role": "tool", "tool_call_id": call_id, "content": INTERRUPTED})
        pending.clear()

    for event in events:
        kind = event["type"]
        if kind == "input":
            settle()
            _add_user(messages, event["content"])
        elif kind == "assistant":
            settle()
            message = _assistant(event["message"])
            messages.append(message)
            pending[:] = [call["id"] for call in message.get("tool_calls", [])]
        elif kind == "tool":
            if event["call_id"] not in pending:
                continue
            content = CLEARED.format(name=event["name"]) if event["id"] in cleared else event["content"]
            messages.append({"role": "tool", "tool_call_id": event["call_id"], "content": content})
            pending.remove(event["call_id"])
            if not pending:
                for note in held:
                    _add_user(messages, _held_content(note))
                held.clear()
        elif kind in ("note", "attachment"):
            if pending:
                held.append(event)  # never between a tool call and its result
            else:
                _add_user(messages, _held_content(event))
    if not pending:
        for note in held:
            _add_user(messages, _held_content(note))
    return messages


def _held_content(event: dict):
    return note_text(event) if event["type"] == "note" else event["content"]


def estimate_tokens(messages: List[dict], system: str = "") -> int:
    """About 4 characters a token, 300 per image (measured: about 250 at any size): good enough for
    thresholds, no tokenizer needed."""
    chars, images = len(system), 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "image_url":
                    images += 1
                else:
                    chars += len(block.get("text", ""))
        else:
            chars += len(content or "")
        chars += len(json.dumps(message.get("tool_calls", ""), ensure_ascii=False)) if message.get("tool_calls") else 0
        chars += len(message.get("reasoning_content") or "")
    return chars // 4 + images * 300


# ============== Shrinking ==============

def clearable(events: List[dict], window: int, tokens: int) -> List[int]:
    """Tool results to clear: all but the newest KEPT_RESULTS. After a clearing, the next waits until the
    context grew by another CLEAR_STEP of the window, so the past changes rarely, not at every step."""
    clearings = [e for e in events if e["type"] == "clearing"]
    if clearings and tokens < clearings[-1].get("after", 0) + CLEAR_STEP * window:
        return []
    cleared = {i for e in clearings for i in e["ids"]}
    results = [e for e in events if e["type"] == "tool" and e["id"] not in cleared][:-KEPT_RESULTS or None]
    return [e["id"] for e in results]


def _size(event: dict) -> int:
    if event["type"] == "input":
        content = event["content"]
        return len(content) if isinstance(content, str) else sum(len(b.get("text", "")) + 1200 * (b["type"] == "image_url")
                                                                  for b in content)
    if event["type"] == "assistant":
        return len(json.dumps(event["message"], ensure_ascii=False))
    if event["type"] in ("tool", "note"):
        return len(event.get("content") or event.get("text") or "")
    return 0


def choose_cut(events: List[dict], keep_chars: int) -> int:
    """Index of the first event kept as is; it starts an input or a model message, never a tool result."""
    kept, cut = 0, len(events)
    for index in range(len(events) - 1, -1, -1):
        kept += _size(events[index])
        if kept > keep_chars:
            break
        cut = index
    while cut < len(events) and events[cut]["type"] not in ("input", "assistant"):
        cut += 1
    if cut == 0:  # everything is recent: still summarize all but the newest step
        cut = max((i for i, e in enumerate(events) if e["type"] in ("input", "assistant")), default=len(events))
    return cut


def transcript_for_summary(events: List[dict], previous: Optional[dict], per_result: int = 1500) -> str:
    lines = [f"EARLIER SUMMARY:\n{previous['summary']}"] if previous else []
    for event in events:
        kind = event["type"]
        if kind == "input":
            content = event["content"]
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") if b["type"] == "text" else "[image]" for b in content)
            lines.append(f"USER: {text}")
        elif kind == "assistant":
            message = event["message"]
            line = f"YOU: {message.get('content') or ''}".rstrip()
            for call in message.get("tool_calls") or []:
                line += f"\n  -> {call['function']['name']}({call['function']['arguments'][:500]})"
            lines.append(line)
        elif kind == "tool":
            content = event["content"]
            shown = content if len(content) <= per_result else content[:per_result] + f" [... {len(content):,} chars]"
            lines.append(f"RESULT of {event['name']}: {shown}")
        elif kind == "note":
            lines.append(f"NOTE: {event['text']}")
    return "\n\n".join(lines)


def recent_files(events: List[dict], limit: int = 5) -> List[str]:
    paths: List[str] = []
    for event in reversed(events):
        if event["type"] == "tool" and event["name"] == "files_read" and event.get("status") == "ok":
            path = (event.get("arguments") or {}).get("path")
            if path and path not in paths:
                paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def file_excerpt(path: Path, lines: int = 150, chars: int = 6000) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as source:
            text = "".join(next(source, "") for _ in range(lines))
    except OSError:
        return None
    return text[:chars]


def handoff(run_dir: Path, todo: list, cwd: Optional[str]) -> str:
    """What a task's fresh context starts from after a reset: progress notes, plan, recent commits."""
    parts = ["Your context was reset to make room. Continue the task from here."]
    progress = run_dir / "progress.md"
    if progress.exists():
        parts.append("## Your progress notes\n" + progress.read_text(encoding="utf-8")[-12_000:])
    if todo:
        parts.append("## Your todo list\n" + render_todo(todo))
    if cwd and (Path(cwd) / ".git").exists():
        try:
            log = subprocess.run(["git", "log", "--oneline", "-20"], cwd=cwd, capture_output=True, text=True,
                                 timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            if log.strip():
                parts.append("## Recent commits\n" + log.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return "\n\n".join(parts)

