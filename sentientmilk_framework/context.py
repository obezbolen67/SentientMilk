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
from typing import Dict, Iterable, List, Optional

from . import signals as signal_format
from .toolkits.todo import render as render_todo

SUMMARY_PREFIX = "[Summary of the earlier conversation, written when it no longer fit]\n"
CLEARED = ("[Result cleared to save space ({chars:,} characters). Get it again with a tool if you need it; calling "
           "one that changes something does that again.]")
# Results this long stay whole: what a call did and measured ("patched 6/6", "hands at 399,605") is the record
# of the work and costs little; clearing all but the newest 5 made the model measure the same things again
# (a Roblox turn, 2026-11-09: 113 of the 146 cleared results were this short, about 6k tokens in all).
SHORT_RESULT = 1000
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
TOOLS = """## YOUR TOOLS
All you can do, by toolkit, with what to know about using it. The user sets you up in SentientMilk's control
panel and in this app's settings (models, super agents, plugins, skills, MCP servers): whatever they say they
made, installed or set up for you is here, as something you can do."""
PARTS = """Toolkits marked [part of you] are parts of you: they live inside you (SentientMilk keeps them), not
on the screen or in the user's files. When the user talks about one, in any words ("your helper", "the agent
I made you", "your notes"), they mean the part here: see it and use it only with its tools, never by looking
for it on the screen or in files. What its tools show is the whole truth about it: when they show nothing,
there is nothing to find elsewhere, not on the screen and not in files or folders (SentientMilk's own
included). When the user speaks of something they do not show, find what they mean among what you can do
here (often something you make yourself) and do it; if nothing fits, say what you see and ask."""
LOADING = """Tools after "load:" are not sent with each request: load them with tools_load (it shows how to
call them), then call them by name like the others. ? marks an optional parameter. tools_search finds tools
by what they do."""
CHANGED = "Your tools changed since this app last used them (YOUR TOOLS has them as they are now):"

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


def tools_section(toolmap: List[dict]) -> Optional[str]:
    """YOUR TOOLS: every toolkit of the run (Toolset.toolmap) with its tools and, under it, the guides of its
    tools (a rule comes only with its tool). One place for what the model can do, so what the user says maps
    to it; parts of the model are marked, and are never looked for on the computer."""
    if not toolmap:
        return None
    lines = [TOOLS]
    if any(group["part"] for group in toolmap):
        lines.append(PARTS)
    if any(group["load"] for group in toolmap):
        lines.append(LOADING)
    for group in toolmap:
        head = f"- {group['kit']}" + (" [part of you]" if group["part"] else "") + \
            (f" [{group['origin']}]" if group.get("origin") else "") + \
            (f" ({group['about']})" if group["about"] else "") + ":"
        tools = [", ".join(group["ready"])] if group["ready"] else []
        if group["kit"].startswith("mcp:"):
            # an MCP server's tools, each with what it is for: their names alone did not show that a game
            # editor's server had its docs, play input and walking (2026-11-09), and a count showed nothing
            lines.append(head + " " + "; ".join(tools + (["load:"] if group["load"] else [])))
            lines += [f"  - {entry}" for entry in group["load"]]
            lines += ["  " + line for guide in group["guides"] for line in guide.splitlines()]
            continue
        if group["load"]:
            tools.append("load: " + ", ".join(group["load"]))
        lines.append(head + " " + "; ".join(tools))
        lines += ["  " + line for guide in group["guides"] for line in guide.splitlines()]
    return "\n".join(lines)


def tools_changed(before: dict, after: dict) -> str:
    """What changed between two views of an app's tools (Loop._tool_news), as a note; "" for nothing to say."""
    lines = []
    for kit, now in after.items():
        then = before.get(kit)
        if then is None:
            lines.append(f"- new: {kit}: {', '.join(now['tools'])}")
            continue
        added = [name for name in now["tools"] if name not in then["tools"]]
        gone = [name for name in then["tools"] if name not in now["tools"]]
        if added:
            lines.append(f"- {kit}: new {', '.join(added)}")
        if gone:
            lines.append(f"- {kit}: gone {', '.join(gone)}")
        lines += [f"- {kit}, now: {line}" for line in now["guides"] if line not in then["guides"]]
        lines += [f"- {kit}, no longer: {line[:160]}" for line in then["guides"] if line not in now["guides"]]
    lines += [f"- gone: {kit}" for kit in before if kit not in after]
    return "\n".join([CHANGED] + lines) if lines else ""


def system_prompt(profile: dict, snapshot: dict, shell: str, tools: Iterable[str] = (),
                  toolmap: Iterable[dict] = (), skills: str = "") -> str:
    """``tools``: the names of every tool the run has; ``toolmap``: its toolkits (Toolset.toolmap), shown as
    YOUR TOOLS with each tool's guide; ``skills``: the SKILLS section (Skills.prompt), for a run that has
    skill_use."""
    tools, toolmap = set(tools), list(toolmap)
    called = f"In this app you are called {profile['name']}. " if profile.get("name") else ""
    parts = [IDENTITY.format(called=called), profile["persona"]]  # the persona is who the model is
    if profile.get("environment"):
        parts.append("## ENVIRONMENT\n" + profile["environment"])
    computer = computer_section(profile, shell)
    if computer:
        parts.append(computer)
    parts.append(RULES)
    if profile.get("instructions"):
        parts.append("## THIS SESSION\n" + profile["instructions"])
    if snapshot.get("memory"):
        parts.append("## WHAT YOU REMEMBER IN THIS APP\n" + snapshot["memory"])
    if snapshot.get("journal"):
        parts.append("## RECENT NOTES FROM YOUR OTHER SESSIONS (oldest first)\n" + snapshot["journal"])
    section = tools_section(toolmap)
    if section:
        parts.append(section)
    if skills and "skill_use" in tools:
        parts.append(skills)
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
    texts, images, display, cards = [head], [], [], []
    for item in items:
        if item["type"] == "mention":
            cards.append(item["card"])  # after what the user wrote
        elif item["type"] == "text":
            texts.append(item["text"])
            display.append(item["text"])
        elif item["type"] == "skill":  # the user's /name, its instructions filled in (Skills.expand)
            texts.append(item["text"])
            display.append(f"/{item['name']} {item.get('arguments', '')}".rstrip())
        elif item["type"] == "event":
            data = f" {json.dumps(item['data'], ensure_ascii=False)}" if item.get("data") else ""
            texts.append(f"[Event: {item['name']}] {item.get('text', '')}{data}".rstrip())
        elif item["type"] == "image":
            images.append(item["url"])
    tail = "\n".join(f"[{reminder}]" for reminder in reminders)
    text = "\n".join(texts + (["", *cards] if cards else []))
    # what the user said; "" for a message of attached files only (still theirs: shown, a place to return to)
    said = "\n".join(display) or ("" if any(item.get("attached") for item in items) else None)
    if not images:
        return (text + ("\n\n" + tail if tail else "")), said
    blocks = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks, said


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


def _assistant(message: dict, reasoning: bool = True) -> dict:
    keys = ("tool_calls", "reasoning_content", "reasoning", "reasoning_details") if reasoning else ("tool_calls",)
    kept = {key: message[key] for key in keys if message.get(key)}
    return {"role": "assistant", "content": message.get("content") or "", **kept}


def _turn_start(events: List[dict]) -> int:
    """Where the current turn starts: the first message of the run the newest message belongs to (a
    steering message joins its run), or the newest message when it came from no run."""
    inputs = [index for index, event in enumerate(events) if event["type"] == "input"]
    if not inputs:
        return 0
    run = events[inputs[-1]].get("run")
    return next((index for index in inputs if run is not None and events[index].get("run") == run), inputs[-1])


def note_text(event: dict) -> str:
    return f"[Note: {event['text']}]"


def project(events: List[dict], compaction: Optional[dict]) -> List[dict]:
    """Model messages for the events after the last compaction, deterministic for the same log.

    Reasoning goes back only with the current turn's replies: DeepSeek needs it there to go on with its
    tool calls (a 400 without it), and older reasoning only costs tokens. Once the provider counted it
    (2026-11-07), it was a third of a long session's prompt: 24k of 63k tokens."""
    messages: List[dict] = []
    start = _turn_start(events)
    if compaction:
        messages.append({"role": "user", "content": SUMMARY_PREFIX + compaction["summary"]})
    cleared = {i for e in events if e["type"] == "clearing" for i in e["ids"]}
    pending: List[str] = []
    held: List[dict] = []

    def settle():
        for call_id in pending:
            messages.append({"role": "tool", "tool_call_id": call_id, "content": INTERRUPTED})
        pending.clear()

    for index, event in enumerate(events):
        kind = event["type"]
        if kind == "input":
            settle()
            _add_user(messages, event["content"])
        elif kind == "assistant":
            settle()
            message = _assistant(event["message"], reasoning=index >= start)
            messages.append(message)
            pending[:] = [call["id"] for call in message.get("tool_calls", [])]
        elif kind == "tool":
            if event["call_id"] not in pending:
                continue
            content = _cleared(event) if event["id"] in cleared else event["content"]
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
    return [e["id"] for e in results if len(_text(e.get("content"))) > SHORT_RESULT]


def _text(content) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _cleared(event: dict) -> str:
    return CLEARED.format(chars=len(_text(event.get("content"))))


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

