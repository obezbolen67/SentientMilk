"""Journal: search the brain's short notes about past sessions in every app."""

import time

from . import ToolContext, Toolkit, cap, tool


def line(note: dict) -> str:
    return f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(note['at']))}, {note['app']}] {note['note']}"


@tool(readonly=True, args={"query": "Words to look for (default: the newest notes)."})
def journal_search(ctx: ToolContext, query: str = ""):
    """Search your journal: your short notes about what happened in your sessions across all apps (other
    chats, finished tasks), newest first; the 20 newest are kept. With words, also what comes back to you of
    any time: your own memories of what happened (they live longer than the notes)."""
    notes = ctx.store.notes(query.strip())
    own = ctx.brain.mind.look_back(query) if query.strip() else []
    if not notes and not own:
        return "No journal notes match, and nothing comes back." if query else "The journal is empty."
    found = "\n".join(line(note) for note in notes)
    if own:
        found += ("\n\n" if found else "") + "What comes back to you:\n" + "\n".join(own)
    return cap(ctx, found, "journal")


TOOLKIT = Toolkit("journal", "Your short notes about past chats, in every app.", [journal_search], part=True)
