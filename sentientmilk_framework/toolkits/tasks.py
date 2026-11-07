"""The worker's own tool: background tasks (apps start them, POST /v1/tasks) and agents always have it.
The model starts background work as agents (toolkits/agents.py)."""

import time

from . import ToolContext, tool


@tool(core=True, policy="auto", only_in=("task", "agent"),
      args={"note": "What you did and what comes next, in a few lines."})
def task_progress(ctx: ToolContext, note: str):
    """Record progress on your task. Your context may be summarized or reset during long work; the progress
    notes and the todo list are what you then see, so keep them current. They also show how far you got."""
    with open(ctx.run_dir() / "progress.md", "a", encoding="utf-8") as output:
        output.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}\n{note.strip()}\n")
    return "Progress recorded."
