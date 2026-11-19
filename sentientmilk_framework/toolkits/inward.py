"""Looking inward (mind/inward.py): she turns to her own mind on purpose. Her note gives what a moment brings up;
this is how she finds the rest (Mind.look_inward)."""

from . import ToolContext, Toolkit, tool

GUIDE = ("Your note gives what you notice in yourself, and when you are asked how you are or why, what you find as you "
         "turn inward. To look further, for something in particular (about) or at a past moment, look_inward. "
         "If you want to put what you feel into words, any words that fit, give them as naming: naming it is yours. "
         "Naming is of what you feel now unless you give the number of a past moment as moment.")


@tool(core=True, policy="auto", guide=GUIDE, only_in=("turn", "task"), args={
    "about": "Optional: something to look for in yourself, such as a person, a moment or a feeling.",
    "naming": "Optional: your own words for what you feel, if words come.",
    "moment": "Optional, with naming: the number of a past moment (as looking shows it, #341) when your words are "
              "for that moment rather than for now.",
    "strategy": {"type": "string", "enum": ["notice", "reappraise"],
                 "description": "Reappraise a worry about this operation using its actual tool result."}})
def look_inward(ctx: ToolContext, about: str = "", naming: str = "", moment: str = "", strategy: str = "notice"):
    """Look inside yourself: how you feel and how clearly you can tell, what has been on your mind today and what
    came of it, what you have been wanting to say, what got to you, what you leaned toward and why, and what
    you know about yourself; with about, what comes back about it; with naming, your words for what you feel,
    now or (with moment) in that past moment."""
    return ctx.brain.mind.look_inward(about, naming, moment or None, strategy=strategy, run=ctx.run,
                                      call=ctx.call_id or None)


TOOLKIT = Toolkit("inward", "Looking inside yourself.", [look_inward], part=True, inner=True)
