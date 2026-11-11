"""Memory, in two scopes, both always whole in context (context.snapshot); no app has to ask for it, and the
model never has to list it: what another chat or app changes later reaches a session as a note
(Brain.memory_news). Two tools, ``memory_save`` and ``memory_forget``, with a ``scope``:

- everywhere: lasting facts, shared by every app (one user, one brain): who the user is, what they like and
  how they want things done, what they work on. Each entry says which app saved it.
- session: this session only, kept in its state like the todo list: instructions to follow here and what
  to keep in mind while the work goes on. It outlasts compaction, a return to a message puts it back as it
  was then, and it ends with the session. The agents and tasks working for the session follow it; only the
  session's own turns change it.

What happened is the journal's (written by the brain); the plan for the work at hand is the todo list's.
"""

from . import ToolContext, ToolError, Toolkit, tool

SCOPE = {"type": "string", "enum": ["everywhere", "session"],
         "description": "everywhere (default): a lasting fact, for every app and chat. session: only this session, "
                        "such as an instruction for it."}
CATEGORY = "For scope everywhere: user (who they are), preferences (how they like things) or projects."
GUIDE = ("When you learn something lasting about the user (their name too), save each fact with memory_save right "
         "away, unasked; it is in YOUR MEMORY in every app and chat from then on. Memory is for what stays true; "
         "one-time events and changes are not worth keeping. When the user tells you how to work in this session "
         "only (what to do or avoid, what to use, how to answer), or you settle something you must keep to here, "
         "save it with scope session right away: it stays in THIS SESSION'S MEMORY through compaction, where the "
         "conversation alone may not.")


def _need(**values):
    missing = [name for name, value in values.items() if not str(value or "").strip()]
    if missing:
        raise ToolError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")


def _scope(ctx: ToolContext, scope: str, category: str) -> bool:
    """True for the session's memory; checks what each scope needs."""
    if scope not in ("everywhere", "session"):
        raise ToolError("scope is everywhere (a lasting fact) or session (this session only).")
    if scope == "session" and ctx.run["kind"] != "turn":
        raise ToolError("Only the session's own turns change its memory: say in your report what it should keep.")
    if scope == "everywhere":
        _need(category=category)
    return scope == "session"


def session_memory(state: dict) -> dict:
    """A session's memory, {key: value}, from its state."""
    return state.get("session_memory") or {}


def is_session_call(event: dict) -> bool:
    """A logged call that changed the session's memory, not lasting memory (rewind undoes those)."""
    return event.get("name") in ("memory_save", "memory_forget") and \
        (event.get("arguments") or {}).get("scope") == "session"


def seen(ctx: ToolContext, category: str, key: str, value=None) -> None:
    """This session knows its own change from the call's result: its next turn need not hear it as news."""
    def change(state):
        taken = state.get("snapshot") or {}
        if "seen" in taken:
            kept = [item for item in taken["seen"] if (item[0], item[1]) != (category, key)]
            taken["seen"] = kept + ([[category, key, value]] if value is not None else [])
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change, create=False)


@tool(core=True, policy="auto", guide=GUIDE, args={
    "key": "A short name for it, such as job, main_project, reply_language or no_push.",
    "value": "The fact or the instruction as it stands now, in a sentence or two.",
    "category": CATEGORY, "scope": SCOPE})
def memory_save(ctx: ToolContext, key: str, value: str, category: str = "", scope: str = "everywhere"):
    """Remember something. Scope everywhere (the default): a lasting fact, for every app and every later
    chat, one that will still be true and useful another day: who the user is (name, work, the people and
    pets in their life), what they like and how they want you to act everywhere, what they work on and want
    to achieve. Save it as soon as you learn it, even in passing or from what they do; they need not ask.
    Never save one-time things: what happened today, a setting changed once, a mood, a finished task, a
    mistake that was cleared up (your journal notes what happened). Scope session: only this session, while
    it lasts: an instruction to follow here ("answer in English here", "don't push until I say", "use the
    staging server") or what the work here must keep in mind (a decision, a name, an address); the agents
    and tasks working for it follow it too, and it ends with the session. The steps of the work go to
    todo_write. Saving an existing key replaces it: update rather than adding a near copy."""
    _need(key=key, value=value)
    key, category = key.strip(), category.strip()
    if _scope(ctx, scope, category):
        def change(state):
            state["session_memory"] = {**session_memory(state), key: value.strip()}
            return state
        ctx.store.update_session(ctx.app, ctx.session, "state", change)
        ctx.brain.chat_memory_changed(ctx.app, ctx.session)
        return f"Remembered for this session: {key}: {value.strip()}"
    ctx.store.remember(ctx.app, category, key, value)
    seen(ctx, category, key, value)
    return f"Remembered {category}/{key} for every app and chat."


@tool(policy="auto", args={"key": "Its name, as in YOUR MEMORY or THIS SESSION'S MEMORY.", "category": CATEGORY,
                           "scope": SCOPE})
def memory_forget(ctx: ToolContext, key: str, category: str = "", scope: str = "everywhere"):
    """Forget something that no longer holds: a lasting fact that is wrong or no longer true (in every app),
    or with scope session, an instruction the user lifted or a decision that changed here."""
    _need(key=key)
    key, category = key.strip(), category.strip()
    if _scope(ctx, scope, category):
        found = []

        def change(state):
            kept = session_memory(state)
            found.append(kept.pop(key, None) is not None)
            state["session_memory"] = kept
            return state
        ctx.store.update_session(ctx.app, ctx.session, "state", change)
        if found[0]:
            ctx.brain.chat_memory_changed(ctx.app, ctx.session)
        return f"Forgot {key} for this session." if found[0] else f"This session's memory has no {key}."
    found = ctx.store.forget(category, key)
    seen(ctx, category, key)
    return f"Forgot {category}/{key}." if found else f"Nothing was remembered as {category}/{key}."


TOOLKIT = Toolkit("memory", "What you remember: lasting facts shared by every app, and this session's memory "
                            "(both shown in full above).", [memory_save, memory_forget], part=True)
