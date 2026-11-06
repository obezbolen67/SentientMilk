"""Agents: helpers with a fresh context that investigate and report back."""

from . import ToolContext, Toolkit, tool

AGENT_TOOLKITS = {"type": "array", "items": {"type": "string"},
                  "description": "Toolkits the helper may use (default: every read-only one you have)."}


@tool(readonly=True, policy="auto", only_in=("turn", "task"), args={
    "goal": "What to find out, with all the context the helper needs; it does not see this conversation.",
    "toolkits": AGENT_TOOLKITS})
def agent_run(ctx: ToolContext, goal: str, toolkits: list = None):
    """Hand an investigation to a helper with a fresh context: broad searches across many files or pages,
    research questions, reviews. It can only read, works on its own and returns a short report (about
    2,000 tokens), which keeps your own context small. Several agent_run calls in one reply run in
    parallel. Do not use it for small lookups you can do with one or two tool calls."""
    return ctx.brain.runs.subagent(ctx.run, goal, toolkits)


TOOLKIT = Toolkit("agents", "Helpers that investigate in their own context.", [agent_run])
