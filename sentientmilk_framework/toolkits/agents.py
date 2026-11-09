"""Agents: copies of you that each work on one part of a job in the background (sentientmilk_framework/agents.py)."""

from . import ToolContext, Toolkit, tool

WORKERS = ("turn", "task")  # the lead's tools: agents get none of these, no agents of agents


@tool(policy="auto", only_in=WORKERS, args={
    "name": "A short name to call it by, e.g. tests or docs-research.",
    "task": "Everything it needs, as it does not see this conversation: the goal, what you know already, where "
            "to look, its boundaries (what is not its part, which files are its own) and what to report.",
    "super_agent": "true: a super agent, a stronger model (Claude, through Claude Code), for writing or changing "
                   "code and for problems that need deep thinking. Only when your rules say you have super "
                   "agents."})
def agent_start(ctx: ToolContext, name: str, task: str, super_agent: bool = False):
    """Start an agent: a copy of you with a fresh context that does one part of a job on its own, in the
    background, while you go on. It has all your tools (it loads the ones it needs, as you do) and your
    rules; it knows only what you write in the task. Use agents for work that splits into parts that can go
    on their own (research several questions, check several places, build separate pieces) or for a long
    job that would fill your context; do the small things yourself. Start several in one reply to have
    them work at once. Collect their reports with agents_wait, or end your turn: you hear from each when it
    finishes, and when it asks you something."""
    agent = ctx.brain.agents.start(ctx.run, name, task, super_agent=bool(super_agent))
    kind = f"super agent ({agent['super']})" if agent["super"] else "agent"
    return (f"Started {kind} {agent['name']} (#{agent['id']}). It works in the background; collect its report "
            "with agents_wait, or go on and it reaches you when it is done.")


@tool(policy="auto", only_in=WORKERS, args={"agent": "Its name (or #id).", "message": "What to tell it."})
def agent_message(ctx: ToolContext, agent: str, message: str):
    """Send a message to one of your agents: to answer its question, correct it or add something. One that
    works reads it at its next step; one that finished takes it as a new request and goes on with all it
    knew."""
    return ctx.brain.agents.message(ctx.run, agent, message)


@tool(readonly=True, only_in=WORKERS, args={
    "agents": {"type": "array", "items": {"type": "string"},
               "description": "Names to wait for (default: all your agents that work)."},
    "timeout": "Seconds to wait at most (default 600, at most 1800)."})
def agents_wait(ctx: ToolContext, agents: list = None, timeout: int = 600):
    """Wait for your agents to finish and get their reports: those you name, or all that work. It ends
    early when one asks you something or the user sends you a message. A report, question or progress
    update reaches you only once: here, or as a note."""
    return ctx.brain.agents.wait(ctx, agents, timeout)


@tool(readonly=True, only_in=WORKERS, args={"agent": "Name one to see its todo list and its recent steps."})
def agents_status(ctx: ToolContext, agent: str = ""):
    """See your agents: what each one does now, how far it got and how it ended. Name one to watch it
    closely: its task, todo list, progress note and last steps with their results."""
    agents = ctx.brain.agents
    if agent:
        return agents.describe_details(ctx.app, agents.find(ctx.app, ctx.session, agent))
    found = agents.open(ctx.app, ctx.session)
    none = "You have no agents now: none waits around, you start each one for a job (agent_start)."
    if ctx.profile.get("super"):  # where a model looks for "the super agent the user made"
        none += f" super_agent=true makes a super agent ({ctx.profile['super']}, through Claude Code)."
    return "\n".join(agents.describe(a) for a in found) or none


@tool(policy="auto", only_in=WORKERS, args={"agent": "Its name (or #id)."})
def agent_stop(ctx: ToolContext, agent: str):
    """Stop an agent at once and delete it, with its session: when its part is done and you need nothing
    more from it, or it went wrong beyond saving (to correct one, send it a message instead)."""
    found = ctx.brain.agents.find(ctx.app, ctx.session, agent)
    ctx.brain.agents.stop(ctx.app, found["id"])
    return f"Stopped agent {found['name']} (#{found['id']}); it is gone."


@tool(core=True, readonly=True, only_in=("agent",), args={"question": "What you need to know, with the options "
                                                                      "you see."})
def ask_lead(ctx: ToolContext, question: str):
    """Ask the you that started you (the lead) and wait for its answer: when the task is unclear or you need
    a decision that is not yours. It knows the whole conversation and can ask the user."""
    return ctx.brain.agents.ask(ctx, question)


TOOLKIT = Toolkit("agents", "Copies of you that work on parts of a job in the background.",
                  [agent_start, agent_message, agents_wait, agents_status, agent_stop, ask_lead])
