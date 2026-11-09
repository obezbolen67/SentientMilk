"""Sessions: your conversations in this app (not your agents' or tasks'), to draw on what was said
there: list them, read one's summary or its plain turns, search them, rename or delete one."""

from .. import mentions
from . import ToolContext, ToolError, Toolkit, cap, tool

PAGE = 40  # turns a page; offset reads on
SNIPPET = 160  # of a match, around it; sessions_read shows the turn


def _find(ctx: ToolContext, session: str) -> dict:
    try:
        return mentions.find_session(ctx.brain, ctx.app, session)
    except ValueError as exc:
        raise ToolError(str(exc))


def _name(found: dict) -> str:
    return f'{found["id"]} "{mentions.label(found)}"'


@tool(readonly=True, args={"query": "Words in the title or first message (default: all of them)."})
def sessions_list(ctx: ToolContext, query: str = ""):
    """Your conversations in this app, newest first: id, title, turns, when it was last active and a line of
    its summary. Read one with sessions_read."""
    needle, rows = query.strip().casefold(), []
    for found in mentions.chats(ctx.brain, ctx.app):
        if needle not in f"{found['title'] or ''} {found['preview']} {found['id']}".casefold():
            continue
        said = sum(e["role"] == "user" for e in ctx.brain.history(ctx.app, found["id"]))
        line = (_name(found) + (" (this one)" if found["id"] == ctx.session else "")
                + f" · {mentions.plural(said, 'turn')} · last active {mentions.stamp(found['last_active'])}")
        known = mentions.summary(ctx.brain, ctx.app, found["id"])
        rows.append(line + (f" — {mentions.short(known, 120)}" if known else ""))
    return cap(ctx, "\n".join(rows), "sessions") or \
        (f"No conversation matches {query!r}." if needle else "You have no conversations yet.")


@tool(readonly=True, rule_arg="session", args={
    "session": "Its id or exact title.",
    "part": "summary (its card and every journal note about it) or turns (what was said, without tool calls).",
    "offset": "For turns: skip this many turns, to read on."})
def sessions_read(ctx: ToolContext, session: str, part: str = "summary", offset: int = 0):
    """Read one of your conversations, including this one: its summary, or its plain turns (user messages and
    your replies, without tool calls), a page at a time."""
    if part not in ("summary", "turns"):
        raise ToolError("part must be summary or turns.")
    found = _find(ctx, session)
    if part == "summary":
        text = mentions.card(ctx.brain, ctx.app, ctx.session, "session", found["id"])
        notes = mentions.journal_notes(ctx.brain, ctx.app, found["id"])
        if notes:
            text += "\n\nJournal notes:\n" + "\n".join(f"- {mentions.stamp(n['at'])}: {n['note']}" for n in notes)
        return text
    grouped = mentions.turns(ctx.brain, ctx.app, found["id"])
    start = max(0, int(offset or 0))
    page, lines = grouped[start:start + PAGE], []
    for number, entries in enumerate(page, start + 1):
        for index, entry in enumerate(entries):
            lead = f"{number}. " if index == 0 else " " * len(f"{number}. ")
            lines.append(f"{lead}{mentions.speaker(entry)}: {entry['text']}")
    if not grouped:
        return f"{_name(found)} has no turns."
    if start + len(page) < len(grouped):
        lines.append(f"[turns {start + 1}-{start + len(page)} of {len(grouped)}; more with offset={start + len(page)}]")
    return cap(ctx, "\n".join(lines), "turns") or f"{_name(found)} has {len(grouped)} turns; offset={start} is past them."


@tool(readonly=True, args={"query": "Words to find, e.g. 'oat milk' (any case)."})
def sessions_search(ctx: ToolContext, query: str):
    """Find words in the plain turns of your conversations, including this one: each match as session, turn and
    line around it. Read more of one with sessions_read(part="turns", offset=...)."""
    needle = query.strip().casefold()
    if not needle:
        raise ToolError("Give words to search for, e.g. query='oat milk'.")
    found = []
    for chat in mentions.chats(ctx.brain, ctx.app):
        for number, entries in enumerate(mentions.turns(ctx.brain, ctx.app, chat["id"]), 1):
            for entry in entries:
                text = " ".join(entry["text"].split())
                at = text.casefold().find(needle)
                if at < 0:
                    continue
                if len(text) > SNIPPET:
                    begin = max(0, at - SNIPPET // 3)
                    text = ("…" if begin else "") + text[begin:begin + SNIPPET] + "…"
                found.append(f"{_name(chat)} #{number} {mentions.speaker(entry)}: {text}")
    if not found:
        return f"No turn of your conversations has {query!r}."
    return cap(ctx, "\n".join(found), "search")


@tool(policy="auto", rule_arg="session", args={"session": "Its id or exact title.", "title": "The new title."})
def session_rename(ctx: ToolContext, session: str, title: str):
    """Give one of your conversations a new title (the user sees it in their list)."""
    found = _find(ctx, session)
    try:
        info = ctx.brain.update_session_settings(ctx.app, found["id"], {"title": title})
    except ValueError as exc:
        raise ToolError(str(exc))
    named = info["settings"].get("title", "")
    ctx.brain.notify(ctx.app, found["id"], "session.titled", {"session": found["id"], "title": named})
    return f'Renamed {found["id"]} to "{named}".'


@tool(policy="always", rule_arg="session", args={"session": "Its id or exact title."})
def session_delete(ctx: ToolContext, session: str):
    """Delete one of your conversations with its whole history, for good. The user is asked every time."""
    found = _find(ctx, session)
    if found["id"] == ctx.session:
        raise ToolError("That is the one you are in: it cannot be deleted from inside it.")
    if ctx.brain.session_busy(ctx.app, found["id"]):
        raise ToolError(f"You are working in it right now ({_name(found)} has a turn going on); try when it ends.")
    ctx.brain.delete_session(ctx.app, found["id"])
    ctx.brain.notify(ctx.app, found["id"], "session.deleted", {"session": found["id"]})
    return f"Deleted {_name(found)} and its history."


TOOLKIT = Toolkit("sessions", "Your conversations in this app: list, read, search, rename, delete.",
                  [sessions_list, sessions_read, sessions_search, session_rename, session_delete], part=True)
