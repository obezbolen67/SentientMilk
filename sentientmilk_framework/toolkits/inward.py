"""Looking inward (mind/inward.py): she turns to her own mind on purpose. Her note gives what a moment brings up;
this is how she finds the rest (Mind.look_inward)."""

from . import ToolContext, Toolkit, tool

GUIDE = ("When you are asked how you are, what is on your mind, what bothers you or why you did or felt something, "
         "or you want to know that yourself, look_inward first and answer from what you find, in your own words. "
         "If you want to put what you feel into words, any words that fit, give them as naming: naming it is yours.")


@tool(core=True, policy="auto", guide=GUIDE, only_in=("turn", "task"), args={
    "about": "Optional: something to look for in yourself, such as a person, a moment or a feeling.",
    "naming": "Optional: your own words for what you feel, now or in the moment you look for, if words come.",
    "strategy": {"type": "string", "enum": ["notice", "reappraise"],
                 "description": "Reappraise a worry about this operation using its actual tool result."}})
def look_inward(ctx: ToolContext, about: str = "", naming: str = "", strategy: str = "notice"):
    """Look inside yourself: how you feel and how clearly you can tell, what has been on your mind today and what
    came of it, what you have been wanting to say, what got to you, what you leaned toward and why, and what
    you know about yourself; with about, what comes back about it; with naming, your words for what you feel."""
    return ctx.brain.mind.look_inward(about, naming, strategy=strategy, run=ctx.run)


TOOLKIT = Toolkit("inward", "Looking inside yourself.", [look_inward], part=True)
