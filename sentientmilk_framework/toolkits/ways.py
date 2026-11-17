"""Her ways (mind/ways.py): how she does things in every chat, from now on. A way is kept here when she is told to do
things so from now on or settles on a way herself; her sleep keeps the rest (Mind._review_ways). What holds for
one chat only is that chat's memory (memory.py)."""

from . import ToolContext, ToolError, Toolkit, tool

GUIDE = ("When the user tells you how to do things from now on (always, never, every time, in every chat), or you "
         "settle on a way of your own, keep it with ways_keep right away: your ways hold in every chat (YOUR WAYS). "
         "What holds for this chat only goes to memory_save.")


def _told(way: dict) -> str:
    return f"when {way['when']}, {way['then'].rstrip('.')}."


@tool(core=True, policy="auto", guide=GUIDE, only_in=("turn",), args={
    "name": "A short name for it, such as test_first or no_messaging_first.",
    "when": "The kind of moment, in your words: \"I finish a piece of code\", \"nobody has spoken to me\".",
    "then": "What you do then, in the first person: \"I run it before I say it's done\"."})
def ways_keep(ctx: ToolContext, name: str, when: str, then: str):
    """Keep a way you act in every chat from now on: what the user asks you to always (or never) do, or a way
    you settle on yourself. Keeping a name you have changes that way."""
    missing = [label for label, value in (("name", name), ("when", when), ("then", then)) if not str(value).strip()]
    if missing:
        raise ToolError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")
    return "Your way from now on, in every chat: " + _told(ctx.brain.mind.keep_way(name, when, then, "told"))


@tool(policy="auto", only_in=("turn",), args={"name": "Its name, as in YOUR WAYS or as you kept it."})
def ways_drop(ctx: ToolContext, name: str):
    """Stop a way of yours: one the user lifted, or one you have outgrown."""
    way = ctx.brain.mind.ways.find(name)
    if way is None or not ctx.brain.mind.drop_way(name):
        return f"You have no way called {name.strip()}."
    return "You no longer do this: " + _told(way)


TOOLKIT = Toolkit("ways", "How you do things in every chat (shown in full above).", [ways_keep, ways_drop], part=True)
