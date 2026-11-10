"""Schedule: reminders and recurring tasks that fire at a time, on cron, or every N minutes."""

from datetime import datetime

from ..scheduler import calendar_zone
from . import ToolContext, ToolError, Toolkit, tool

GUIDE = ('Before creating a schedule, determine one-off versus recurring, the requested days, exact clock '
    'time, timezone and complete instructions. "Every morning" means daily but supplies no clock time: '
    'ask for the missing time; never invent one. A clock time alone does not imply daily recurrence. '
    'Use the local timezone in the message context unless '
    'the user specifies another. For daily/weekday wall times use cron, not every 1d (a fixed 24 hours). '
    'Instructions must stand alone. App schedules run through this app in their own persistent conversation; '
    'if the app is closed they wait, and missed occurrences coalesce instead of piling up. Use schedule_update '
    'to change an existing schedule, and confirm the exact rule, zone and destination conversation.')


def describe(schedule: dict) -> str:
    spec = f"every {int(schedule['spec']) // 60} min" if schedule["kind"] == "every" else \
        f"{schedule['kind']} {schedule['spec']}"
    zone = calendar_zone(schedule['payload'].get('timezone'))
    upcoming = datetime.fromtimestamp(schedule['next_at'], zone).strftime('%Y-%m-%d %H:%M %Z') \
        if schedule['next_at'] else 'never'
    destination = f"; conversation {schedule['execution_session']} ({zone})" if schedule['payload']['mode'] == 'app' else ''
    return (f"Schedule {schedule['id']}: {spec} -> {schedule['payload']['mode']}: "
            f"{schedule['payload']['text'][:200]} (next {upcoming}{'' if schedule['enabled'] else ', disabled'}){destination}")


@tool(policy="ask", only_in=("turn", "task", "agent"), guide=GUIDE, args={
    "when": "An ISO local time ('2026-11-06T17:00'), 'every 30m' / 'every 2h' / 'every 1d', or a 5-field cron "
            "expression ('0 9 * * 1-5' = weekdays at 9:00). Times are the user's local time.",
    "text": "Complete standalone instructions, including what result to deliver.",
    'timezone': 'IANA timezone, e.g. Europe/Warsaw; empty uses the local zone from context.',
    'title': 'A short name for this scheduled conversation.',
    "mode": {"type": "string", "enum": ['app', "wake", "task"],
             "description": 'app (default): this app executes in a dedicated conversation. '
                            'wake/task: legacy reminder/background execution.'}})
def schedule_create(ctx: ToolContext, when: str, text: str, mode: str = "app", timezone: str = '', title: str = ''):
    """Schedule standalone instructions for this app in their own conversation, once or on a recurring rule."""
    try:
        session = ctx.run["options"].get("parent_session") or ctx.session  # an agent's is the lead's: it outlives it
        schedule = ctx.brain.scheduler.create(ctx.app, session, when, text, mode, created_by="model",
                                              timezone=timezone, title=title)
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


@tool(policy='ask', args={'id': 'Schedule id from schedule_list.',
    'when': 'A replacement ISO time, interval or cron expression; empty keeps the rule.',
    'text': 'Replacement standalone instructions; empty keeps them.',
    'timezone': 'Replacement IANA timezone; empty keeps it.', 'title': 'Replacement conversation title.',
    'enabled': {'type': 'boolean', 'description': 'False pauses future/pending work; true resumes it.'}})
def schedule_update(ctx: ToolContext, id: int, when: str = '', text: str = '', timezone: str = '',
                     title: str = '', enabled: bool = None):
    """Reschedule, change, pause or resume one schedule of this app. An already-running occurrence may finish."""
    found = ctx.store.schedule(id)
    if not found or found['app'] != ctx.app:
        raise ToolError(f'There is no schedule {id}.')
    changes = {key: value for key, value in {'when': when, 'text': text, 'timezone': timezone, 'title': title}.items() if value}
    if enabled is not None:
        changes['enabled'] = enabled
    if not changes:
        raise ToolError('Give a replacement rule, instructions, title, timezone or enabled state.')
    try:
        return 'Updated. ' + describe(ctx.brain.scheduler.update(id, **changes))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


TOOLKIT = Toolkit("schedule", "App-owned scheduled instructions, reminders and recurring tasks.",
                  [schedule_create, schedule_list, schedule_update, schedule_delete],
                  part=True)
