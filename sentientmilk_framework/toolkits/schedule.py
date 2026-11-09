"""Schedule: reminders and recurring tasks that fire at a time, on cron, or every N minutes."""

import time

from . import ToolContext, ToolError, Toolkit, tool


def describe(schedule: dict) -> str:
    spec = f"every {int(schedule['spec']) // 60} min" if schedule["kind"] == "every" else \
        f"{schedule['kind']} {schedule['spec']}"
    upcoming = time.strftime("%Y-%m-%d %H:%M", time.localtime(schedule["next_at"])) if schedule["next_at"] else "never"
    return (f"Schedule {schedule['id']}: {spec} -> {schedule['payload']['mode']}: "
            f"{schedule['payload']['text'][:200]} (next {upcoming}{'' if schedule['enabled'] else ', disabled'})")


@tool(policy="ask", only_in=("turn", "task", "agent"), args={
    "when": "An ISO local time ('2026-11-06T17:00'), 'every 30m' / 'every 2h' / 'every 1d', or a 5-field cron "
            "expression ('0 9 * * 1-5' = weekdays at 9:00). Times are the user's local time.",
    "text": "For a reminder: what to remind about. For a task: the full goal.",
    "mode": {"type": "string", "enum": ["wake", "task"],
             "description": "wake: remind (the app is told; no work is done). task: run a background task."}})
def schedule_create(ctx: ToolContext, when: str, text: str, mode: str = "wake"):
    """Schedule a reminder or a recurring background task. The app decides how to show reminders."""
    if mode not in ("wake", "task"):
        raise ToolError("mode must be 'wake' or 'task'.")
    try:
        session = ctx.run["options"].get("parent_session") or ctx.session  # an agent's is the lead's: it outlives it
        schedule = ctx.brain.scheduler.create(ctx.app, session, when, text, mode, created_by="model")
    except ValueError as exc:
        raise ToolError(str(exc))
    return "Created. " + describe(schedule)


@tool(readonly=True)
def schedule_list(ctx: ToolContext):
    """Every schedule of this app."""
    return "\n".join(describe(s) for s in ctx.store.schedules(ctx.app)) or "No schedules."


@tool(policy="auto")
def schedule_delete(ctx: ToolContext, id: int):
    """Delete a schedule."""
    schedule = ctx.store.schedule(int(id))
    if not schedule or schedule["app"] != ctx.app:
        raise ToolError(f"There is no schedule {id}.")
    ctx.brain.scheduler.delete(schedule["id"])
    return f"Deleted schedule {id}."


TOOLKIT = Toolkit("schedule", "Reminders and recurring tasks.", [schedule_create, schedule_list, schedule_delete],
                  part=True)
