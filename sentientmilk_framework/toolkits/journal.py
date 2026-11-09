"""Journal: search the brain's short notes about past sessions in every app."""

import time

from . import ToolContext, Toolkit, cap, tool


def line(note: dict) -> str:
    return f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(note['at']))}, {note['app']}] {note['note']}"


@tool(readonly=True, args={"query": "Words to look for (default: the newest notes)."})
def journal_search(ctx: ToolContext, query: str = ""):
    """Search your journal: short notes about what happened in your sessions across all apps (other chats,
    finished tasks), newest first. Every note is kept."""
    notes = ctx.store.notes(query.strip())
    if not notes:
        return "No journal notes match." if query else "The journal is empty."
    return cap(ctx, "\n".join(line(note) for note in notes), "journal")


TOOLKIT = Toolkit("journal", "Your short notes about past chats, in every app.", [journal_search], part=True)
