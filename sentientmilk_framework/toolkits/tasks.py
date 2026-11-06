"""Tasks: background work that goes on while the conversation does, and survives restarts."""

import time

from . import ToolContext, ToolError, Toolkit, tool


def describe(run: dict) -> str:
    text = f"Task {run['id']} ({run['status']}): {run['options'].get('goal', '')[:200]}"
    if run["result"]:
        text += f"\nResult: {str(run['result'].get('reply', ''))[:1500]}"
    if run["error"]:
        text += f"\nError: {run['error'].get('message', '')}"
    return text


@tool(policy="auto", only_in=("turn",), args={
    "goal": "What the task must achieve, with every detail it needs: it does not see this conversation.",
    "toolkits": {"type": "array", "items": {"type": "string"}, "description": "Toolkits (default: yours)."},
    "verify": "Have a separate reviewer check the work before the task counts as done."})
def task_start(ctx: ToolContext, goal: str, toolkits: list = None, verify: bool = False):
    """Start a background task for work that takes long (many steps, minutes to hours) so the conversation
    can go on. You get a note with the result when it ends. Tell the user you started it."""
    if not goal.strip():
        raise ToolError("goal is empty.")
    run = ctx.brain.runs.start_task(ctx.app, ctx.session, goal.strip(), toolkits=toolkits, verify=bool(verify),
                                    parent=ctx.run["id"])
    return f"Started task {run}. You get a note when it finishes."


def _task(ctx: ToolContext, task: int) -> dict:
    run = ctx.store.run(int(task))
    if not run or run["kind"] != "task" or run["app"] != ctx.app:
        raise ToolError(f"There is no task {task}.")
    return run


@tool(readonly=True, args={"task": "Task id (default: your recent tasks)."})
def task_status(ctx: ToolContext, task: int = 0):
    """Status and result of a background task, or of your recent tasks."""
    if task:
        return describe(_task(ctx, task))
    runs = ctx.store.runs(app=ctx.app, kind="task", limit=10)
    return "\n\n".join(describe(run) for run in runs) or "No tasks yet."


@tool(policy="auto")
def task_cancel(ctx: ToolContext, task: int):
    """Stop a background task after its current step."""
    run = _task(ctx, task)
    ctx.brain.runs.cancel(run["id"])
    return f"Task {task} will stop after its current step."


@tool(policy="auto", only_in=("task",), args={"note": "What you did and what comes next, in a few lines."})
def task_progress(ctx: ToolContext, note: str):
    """Record progress on this task. Your context may be summarized or reset during long work; the progress
    notes and the todo list are what you then see, so keep them current."""
    with open(ctx.run_dir() / "progress.md", "a", encoding="utf-8") as output:
        output.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}\n{note.strip()}\n")
    return "Progress recorded."


TOOLKIT = Toolkit("tasks", "Background tasks.", [task_start, task_status, task_cancel, task_progress])
