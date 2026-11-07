"""Memory: facts this app keeps across sessions. Each app has its own."""

import json

from . import ToolContext, ToolError, Toolkit, tool


def _need(**values):
    missing = [name for name, value in values.items() if not str(value or "").strip()]
    if missing:
        raise ToolError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")


@tool(policy="auto", args={"category": "user (who they are), preferences (how they like things) or projects.",
                           "key": "A short name for the fact, such as job or main_project.",
                           "value": "The fact as it stands now, in a sentence or two."})
def memory_save(ctx: ToolContext, category: str, key: str, value: str):
    """Remember a lasting fact for later conversations in this app: one that will still be true and useful
    another day. Who the user is (name, work, the people and pets in their life), what they like and how
    they want you to act, what they work on and want to achieve. Save it as soon as you learn it, even in
    passing or from what they do; they need not ask. Never save one-time things: what happened today, a
    setting changed once, a mood, a finished task, a mistake that was cleared up. Your journal already
    notes what happened in each session. Saving an existing key replaces it: update a fact rather than
    adding a near copy."""
    _need(category=category, key=key, value=value)
    ctx.store.remember(ctx.app, category.strip(), key.strip(), value)
    return f"Remembered {category}/{key}."


@tool(readonly=True)
def memory_get(ctx: ToolContext, category: str, key: str):
    """Look up one remembered item."""
    _need(category=category, key=key)
    value = ctx.store.recall(ctx.app, category.strip(), key.strip())
    return f"Nothing is remembered as {category}/{key}." if value is None else str(value)


@tool(readonly=True, args={"category": "Only this category (default: everything)."})
def memory_list(ctx: ToolContext, category: str = ""):
    """Everything remembered in this app, or in one category."""
    memories = ctx.store.memories(ctx.app)
    if category:
        memories = {category: memories.get(category, {})}
    if not any(memories.values()):
        return "Nothing is remembered yet."
    return json.dumps(memories, ensure_ascii=False, indent=1)


@tool(policy="auto")
def memory_forget(ctx: ToolContext, category: str, key: str):
    """Forget one remembered item."""
    _need(category=category, key=key)
    found = ctx.store.forget(ctx.app, category.strip(), key.strip())
    return f"Forgot {category}/{key}." if found else f"Nothing was remembered as {category}/{key}."


TOOLKIT = Toolkit("memory", "Long-term memory of this app.", [memory_save, memory_get, memory_list, memory_forget])
