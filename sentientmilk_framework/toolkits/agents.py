"""Agents: copies of you that each work on one part of a job in the background (sentientmilk_framework/agents.py)."""

from . import ToolContext, Toolkit, tool

WORKERS = ("turn", "task")  # agents get none of these: no agents of agents


@tool(policy="auto", only_in=WORKERS, args={
    "name": "A short name to call it by, e.g. tests or docs-research.",
    "task": "Everything it needs, as it does not see this conversation: the goal, what you know already, where "
            "to look, its boundaries (what is not its part) and what to report.",
    "access": "read (the default): it can only look (search, read, browse), so several can safely work at "
              "once. write: it can also change files and run commands, each change approved like yours; give "
              "each writing agent its own files.",
    "toolkits": {"type": "array", "items": {"type": "string"},
                 "description": "Only these toolkits (default: all of yours that fit its access)."}})
def agent_start(ctx: ToolContext, name: str, task: str, access: str = "read", toolkits: list = None):
    """Start an agent: a copy of you with a fresh context that does one part of a job on its own, in the
    background, while you go on. Use agents for work that splits into parts that can go on their own
    (research several questions, check several places, build separate pieces) or for a long job that
    would fill your context; do the small things yourself. Start several in one reply to have them work at
    once. Collect their reports with agents_wait, or end your turn: you hear from each when it finishes."""
    agent = ctx.brain.agents.start(ctx.run, name, task, access, toolkits)
    return (f"Started agent {agent['name']} (#{agent['id']}, {agent['access']}). It works in the background; "
            "collect its report with agents_wait, or go on and it reaches you when it is done.")


@tool(policy="auto", only_in=WORKERS, args={"agent": "Its name (or #id).", "message": "What to tell it."})
def agent_message(ctx: ToolContext, agent: str, message: str):
    """Send a message to one of your agents. One that works reads it at its next step (to correct it or
    add something); one that finished takes it as a new request and goes on with all it knew."""
    return ctx.brain.agents.message(ctx.run, agent, message)


@tool(readonly=True, only_in=WORKERS, args={
    "agents": {"type": "array", "items": {"type": "string"},
               "description": "Names to wait for (default: all your agents that work)."},
    "timeout": "Seconds to wait at most (default 600, at most 1800)."})
def agents_wait(ctx: ToolContext, agents: list = None, timeout: int = 600):
    """Wait for your agents to finish and get their reports: those you name, or all that work. It ends
    early when the user sends you a message. A report reaches you only once: here, or as a note."""
    return ctx.brain.agents.wait(ctx, agents, timeout)


@tool(readonly=True, only_in=WORKERS, args={"agent": "Name one to see its todo list and its recent steps."})
def agents_status(ctx: ToolContext, agent: str = ""):
    """See your agents: what each one does now, how far it got and how it ended. Name one to watch it
    closely: its task, todo list, progress note and last steps with their results."""
    agents = ctx.brain.agents
    if agent:
        return agents.describe_details(ctx.app, agents.find(ctx.app, ctx.session, agent))
    found = agents.open(ctx.app, ctx.session)
    return "\n".join(agents.describe(a) for a in found) or "You have no agents now."


@tool(policy="auto", only_in=WORKERS, args={"agent": "Its name (or #id)."})
def agent_stop(ctx: ToolContext, agent: str):
    """Stop an agent at once and close it: for a part that is no longer needed or an agent that went wrong
    beyond saving (to correct one, send it a message instead). It reports nothing more."""
    found = ctx.brain.agents.find(ctx.app, ctx.session, agent)
    ctx.brain.agents.stop(ctx.app, found["id"])
    return f"Stopped agent {found['name']} (#{found['id']})."


TOOLKIT = Toolkit("agents", "Copies of you that work on parts of a job in the background.",
                  [agent_start, agent_message, agents_wait, agents_status, agent_stop])
