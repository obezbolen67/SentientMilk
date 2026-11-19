"""This session's memory: what the chat keeps to while it lasts, always whole in its context (context.snapshot),
kept in its state like the todo list: instructions to follow here and what the work must keep in mind. It
outlasts compaction, a return to a message puts it back as it was then, and it ends with the session. The
agents and tasks working for the session follow it; only the session's own turns change it.

What lasts beyond a chat is her long-term memory's (recall.py): every past chat comes back by meaning.
"""

from . import ToolContext, ToolError, Toolkit, tool

GUIDE = ("When the user tells you how to work in this chat (what to do or avoid, what to use, how to answer), or "
         "you settle something you must keep to here, save it with memory_save right away: it stays in THIS "
         "SESSION'S MEMORY through compaction, where the conversation alone may not. How to do things from now on, "
         "in every chat, is a way of yours (ways_keep). What you learn about the user you need not save: your past "
         "chats come back to you by meaning.")


def _need(**values):
    missing = [name for name, value in values.items() if not str(value or "").strip()]
    if missing:
        raise ToolError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")


def session_memory(state: dict) -> dict:
    """A session's memory, {key: value}, from its state."""
    return state.get("session_memory") or {}


def is_session_call(event: dict) -> bool:
    """A logged call that changed the session's memory (a return gives the chat its memory as the message found
    it: rewind.py)."""
    return event.get("name") in ("memory_save", "memory_forget")


@tool(core=True, policy="auto", guide=GUIDE, only_in=("turn",), args={
    "key": "A short name for it, such as reply_language, no_push or staging_server.",
    "value": "The instruction or the fact as it stands now, in a sentence or two."})
def memory_save(ctx: ToolContext, key: str, value: str):
    """Keep something in this chat's memory while the chat lasts: an instruction to follow here ("answer in
    English here", "don't push until I say", "use the staging server") or what the work here must keep in mind
    (a decision, a name, an address). The agents and tasks working for this chat follow it too. The steps of
    the work go to todo_write. Saving an existing key replaces it: update rather than adding a near copy."""
    _need(key=key, value=value)
    key = key.strip()

    def change(state):
        state["session_memory"] = {**session_memory(state), key: value.strip()}
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)
    ctx.brain.chat_memory_changed(ctx.app, ctx.session)
    return f"Remembered for this chat: {key}: {value.strip()}"


@tool(policy="auto", only_in=("turn",), args={"key": "Its name, as in THIS SESSION'S MEMORY."})
def memory_forget(ctx: ToolContext, key: str):
    """Take something out of this chat's memory: an instruction the user lifted or a decision that changed."""
    _need(key=key)
    key, found = key.strip(), []

    def change(state):
        kept = session_memory(state)
        found.append(kept.pop(key, None) is not None)
        state["session_memory"] = kept
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)
    if found[0]:
        ctx.brain.chat_memory_changed(ctx.app, ctx.session)
    return f"Forgot {key} for this chat." if found[0] else f"This chat's memory has no {key}."


TOOLKIT = Toolkit("memory", "This chat's memory (shown in full above).", [memory_save, memory_forget], part=True, inner=True)
