"""Memory, in two kinds, and both always in context (context.snapshot); no app has to ask for it:

- memory: lasting facts, shared by every app (one user, one brain): who the user is, what they like and how
  they want things done, what they work on. Each entry says which app saved it.
- session memory: this session only, kept in its state like the todo list: instructions to follow here and
  what to keep in mind while the work goes on. It outlasts compaction, a return to a message puts it back
  as it was then, and it ends with the session. The agents and tasks working for the session follow it;
  only the session's own turns change it.

What happened is the journal's (written by the brain); the plan for the work at hand is the todo list's.
"""

import json

from . import ToolContext, ToolError, Toolkit, tool

KEY = "A short name for it, such as job or main_project."


def _need(**values):
    missing = [name for name, value in values.items() if not str(value or "").strip()]
    if missing:
        raise ToolError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")


def session_memory(state: dict) -> dict:
    """A session's memory, {key: value}, from its state."""
    return state.get("session_memory") or {}


@tool(core=True, policy="auto", args={"category": "user (who they are), preferences (how they like things) or projects.",
                                      "key": KEY, "value": "The fact as it stands now, in a sentence or two."},
      guide="When you learn something lasting about the user (their name too), save each fact with memory_save "
            "right away, unasked; it is in YOUR MEMORY in every app and chat from then on. Memory is for what stays true; one-time "
            "events and changes are not worth keeping, and what holds only for this session goes to "
            "session_memory_save.")
def memory_save(ctx: ToolContext, category: str, key: str, value: str):
    """Remember a lasting fact, for every app and every later chat: one that will still be true and useful
    another day. Who the user is (name, work, the people and pets in their life), what they like and how
    they want you to act everywhere, what they work on and want to achieve. Save it as soon as you learn it,
    even in passing or from what they do; they need not ask. Never save one-time things: what happened
    today, a setting changed once, a mood, a finished task, a mistake that was cleared up (your journal
    notes what happened), nor what holds only in this session (session_memory_save). Saving an existing
    key replaces it: update a fact rather than adding a near copy."""
    _need(category=category, key=key, value=value)
    ctx.store.remember(ctx.app, category.strip(), key.strip(), value)
    return f"Remembered {category.strip()}/{key.strip()} for every app and chat."


@tool(readonly=True, args={"category": "Only this category (default: everything)."})
def memory_list(ctx: ToolContext, category: str = ""):
    """Your memory as it is now, with what other apps and chats saved since this one began (YOUR MEMORY
    shows it as it was then)."""
    memories = ctx.store.memories()
    if category:
        memories = {category: memories.get(category, {})}
    if not any(memories.values()):
        return "Nothing is remembered yet."
    return json.dumps(memories, ensure_ascii=False, indent=1)


@tool(policy="auto")
def memory_forget(ctx: ToolContext, category: str, key: str):
    """Forget one lasting fact, in every app: it is wrong or no longer true."""
    _need(category=category, key=key)
    found = ctx.store.forget(category.strip(), key.strip())
    return f"Forgot {category}/{key}." if found else f"Nothing was remembered as {category}/{key}."


@tool(core=True, policy="auto", only_in=("turn",), args={
    "key": "A short name for it, such as reply_language or no_push.",
    "value": "What to follow or keep in mind, in a sentence or two, as it stands now."},
      guide="When the user tells you how to work in this session (what to do or avoid, what to use, how to "
            "answer), or you settle something you must keep to here, save it with session_memory_save right "
            "away: it stays in THIS SESSION'S MEMORY through compaction, where the conversation alone may not.")
def session_memory_save(ctx: ToolContext, key: str, value: str):
    """Remember something for this session only: an instruction to follow while it lasts ("answer in
    English here", "don't push until I say", "use the staging server"), or what the work here needs kept
    in mind (a decision, a name, an address, a constraint). It is in THIS SESSION'S MEMORY from then on,
    whole even when older context is summarized, and it ends with the session; the agents and tasks working
    for it follow it too. What should hold in every chat goes to memory_save instead, and the steps of the
    work to todo_write. Saving an existing key replaces it."""
    _need(key=key, value=value)
    key = key.strip()

    def change(state):
        state["session_memory"] = {**session_memory(state), key: value.strip()}
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)
    return f"Remembered for this session: {key}: {value.strip()}"


@tool(policy="auto", only_in=("turn",))
def session_memory_forget(ctx: ToolContext, key: str):
    """Forget one thing of this session's memory: it no longer holds (the user lifted the instruction, the
    decision changed)."""
    _need(key=key)
    key, found = key.strip(), []

    def change(state):
        kept = session_memory(state)
        found.append(kept.pop(key, None) is not None)
        state["session_memory"] = kept
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)
    return f"Forgot {key} for this session." if found[0] else f"This session's memory has no {key}."


TOOLKIT = Toolkit("memory", "What you remember: lasting facts shared by every app, and this session's memory "
                            "(both shown in full above).",
                  [memory_save, memory_list, memory_forget, session_memory_save, session_memory_forget], part=True)
