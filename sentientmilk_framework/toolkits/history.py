"""The original event log of the session a run belongs to."""

import json
import re

from . import ToolContext, ToolError, Toolkit, ToolResult, tool

PAGE, PREVIEW, SNIPPET, EVENT_CHARS = 40, 400, 160, 12_000
TYPES = ("input", "assistant", "tool", "note", "attachment")
BASE64 = re.compile(r'data:[^,\s"<>]+;base64,[A-Za-z0-9+/=]+')
GUIDE = ("Your original session history survives compaction and cleared tool results. If a reference, constraint "
         "or result is missing, use history_search to find it and history_read to recover the original event. "
         "Trust the original records; do not repeat a mutating tool merely to retrieve its previous result.")


def _render(event: dict) -> str:
    record = dict(event)
    if event["type"] == "assistant":
        record["message"] = {key: value for key, value in event["message"].items()
                             if key in ("role", "content", "tool_calls", "refusal")}
    return BASE64.sub("[base64 data omitted]", json.dumps(record, ensure_ascii=False, indent=2))


@tool(readonly=True, core=True, guide=GUIDE, args={
    "event": "An immutable event id from this session; 0 lists bounded event previews instead.",
    "offset": "With event: skip this many characters (12,000 per page). Otherwise skip useful events (40 per page)."})
def history_read(ctx: ToolContext, event: int = 0, offset: int = 0):
    """Read your own session's original inputs, replies, tool calls/results, notes and attachments. Page the
    previews or recover one by id, paging its text with the next offset shown. Original images are restored on
    its first page. Hidden reasoning is excluded."""
    start = max(0, int(offset or 0))
    if event > 0:
        found = ctx.store.event(event)
        if not found or (found["app"], found["session"]) != (ctx.app, ctx.session):
            raise ToolError(f"No history event {event} in this session.")
        content = (found.get("message") or {}).get("content") if found["type"] == "assistant" \
            else found.get("content")
        images = [block["image_url"]["url"] for block in content
                  if block.get("type") == "image_url"] if not start and isinstance(content, list) else []
        text = _render(found)
        page = text[start:start + EVENT_CHARS]
        if not page:
            return f"Offset {start} is past history event {event}'s {len(text)} characters."
        end = start + len(page)
        if start or end < len(text):
            page += f"\n\n[History event {event}: characters {start + 1}-{end} of {len(text)}.]"
            if end < len(text):
                page += f"\nNext page: history_read(event={event}, offset={end})"
        return ToolResult(page, images) if images else page
    events = ctx.store.events(ctx.app, ctx.session, types=TYPES)
    page = events[start:start + PAGE]
    if not page:
        return f"Offset {start} is past this session's {len(events)} history events." if events else \
            "No history events in this session."
    lines = []
    for found in page:
        text = " ".join(_render(found).split())
        lines.append(f"Event {found['id']} ({found['type']}): {text[:PREVIEW]}" + ("…" if len(text) > PREVIEW else ""))
    lines.append(f"[History events {start + 1}-{start + len(page)} of {len(events)}. "
                 "Read one original record (and restore its images) with history_read(event=ID).]")
    if start + len(page) < len(events):
        lines.append(f"Next page: history_read(offset={start + len(page)})")
    return "\n".join(lines)


@tool(readonly=True, core=True, args={
    "query": "Words to find in original events of this session (any case).",
    "offset": "Skip this many matching events; each page contains up to 40."})
def history_search(ctx: ToolContext, query: str, offset: int = 0):
    """Find text in your own session's original history, including tool arguments/results, and return snippets
    with immutable event ids. Read the full original with history_read(event=ID)."""
    needle = query.strip().casefold()
    if not needle:
        raise ToolError("Give words to search for, e.g. query='original constraint'.")
    matches = []
    for found in ctx.store.events(ctx.app, ctx.session, types=TYPES):
        text = " ".join(_render(found).split())
        at = text.casefold().find(needle)
        if at < 0:
            continue
        begin = max(0, at - SNIPPET // 3)
        snippet = ("…" if begin else "") + text[begin:begin + SNIPPET] + \
            ("…" if begin + SNIPPET < len(text) else "")
        matches.append(f"Event {found['id']} ({found['type']}): {snippet}")
    if not matches:
        return "No history event in this session matches the query."
    start = max(0, int(offset or 0))
    page = matches[start:start + PAGE]
    if not page:
        return f"Offset {start} is past the {len(matches)} matching history events."
    page.append("Read an original record with history_read(event=ID).")
    if start + PAGE < len(matches):
        page.append(f"Next page: history_search with the same query and offset={start + PAGE}.")
    return "\n".join(page)


TOOLKIT = Toolkit("history", "Recover the original history of your own session, even after compaction.",
                  [history_read, history_search], part=True)
