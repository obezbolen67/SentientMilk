"""Schedule: work for later, once or repeating. At its time she runs with the saved instructions in a
conversation of its own; a reminder is a schedule whose instructions say what to tell the user."""

from datetime import datetime

from ..scheduler import calendar_zone
from . import ToolContext, ToolError, Toolkit, cap, tool

GUIDE = ("A schedule runs you later with its instructions, in a conversation of its own: once (an ISO time, or "
         "'in 20m') or repeating ('every 2h', or cron for clock times). A reminder is one of them, its instructions "
         'saying what to tell the user ("Tell the user it is time to water the plants."). Before creating one, know: '
         'once or repeating, which days, the exact clock time, and what to do. "Every morning" means daily but '
         'gives no time: ask for it; never invent one. A clock time alone means once, not daily. Use the local '
         'timezone in the message context unless the user names another. For daily or weekday times use cron, not '
         'every 1d (a fixed 24 hours). The instructions must stand alone: that run does not see this conversation. '
         'If it cannot run on time (the app is closed), it waits, and missed runs of a repeating one come as one. '
         'Change one with schedule_update rather than making another, and tell the user when it runs next.')


def _every(seconds: int) -> str:
    for unit, size in (('d', 86400), ('h', 3600)):
        if seconds % size == 0:
            return f'every {seconds // size}{unit}'
    return f'every {seconds // 60}m'


def describe(schedule: dict) -> str:
    zone = calendar_zone(schedule['timezone'])

    def at(stamp: float) -> str:
        return datetime.fromtimestamp(stamp, zone).strftime('%Y-%m-%d %H:%M %Z')

    if schedule['kind'] == 'at':
        rule = f"once at {at(datetime.fromisoformat(schedule['spec']).timestamp())}"
    else:
        rule = (_every(int(schedule['spec'])) if schedule['kind'] == 'every' else f"repeats on cron {schedule['spec']}")
    if schedule['next_at']:
        state = f"next {at(schedule['next_at'])}"
    elif schedule['kind'] == 'at' and schedule['last_at']:
        state = f"done, it ran at {at(schedule['last_at'])}"
    else:
        state = 'paused'
    return (f"Schedule {schedule['id']} \"{schedule['payload']['title']}\": {rule}, {state}; conversation "
            f"{schedule['execution_session']}. Instructions: {schedule['payload']['text']}")


@tool(policy="ask", only_in=("turn", "task", "agent"), guide=GUIDE, args={
    "when": "Once: an ISO local time ('2026-11-06T17:00') or 'in 20m' / 'in 2h' / 'in 1d'. Repeating: 'every 30m' "
            "/ 'every 2h', or a 5-field cron expression for clock times ('0 9 * * 1-5' = weekdays at 9:00). Times "
            "are the user's local time.",
    "text": "Complete standalone instructions: what to do then, and what to tell the user.",
    'timezone': 'IANA timezone, e.g. Europe/Warsaw; empty uses the local zone from context.',
    'title': 'A short name for it and its conversation.'})
def schedule_create(ctx: ToolContext, when: str, text: str, timezone: str = '', title: str = ''):
    """Schedule work for later, once or repeating, reminders included: at its time you run with these
    instructions in a conversation of its own, through this app."""
    try:
        session = ctx.run["options"].get("parent_session") or ctx.session  # an agent's is the lead's: it outlives it
        schedule = ctx.brain.scheduler.create(ctx.app, session, when, text, created_by="model",
                                              timezone=timezone, title=title)
    except ValueError as exc:
        raise ToolError(str(exc))
    return "Created. " + describe(schedule)


@tool(readonly=True)
def schedule_list(ctx: ToolContext):
    """Every schedule of this app: once or repeating, when it runs next (or that it is done or paused), its
    conversation and instructions."""
    return cap(ctx, "\n".join(describe(s) for s in ctx.store.schedules(ctx.app)), "schedules") or "No schedules."


@tool(policy="auto")
def schedule_delete(ctx: ToolContext, id: int):
    """Delete a schedule. Its conversation and what it reported stay."""
    schedule = ctx.store.schedule(int(id))
    if not schedule or schedule["app"] != ctx.app:
        raise ToolError(f"There is no schedule {id}.")
    ctx.brain.scheduler.delete(schedule["id"])
    return f"Deleted schedule {id}."


@tool(policy='ask', args={'id': 'Schedule id from schedule_list.',
    'when': "A new time or rule, as schedule_create takes it (once or repeating); empty keeps it.",
    'text': 'Replacement standalone instructions; empty keeps them.',
    'timezone': 'Replacement IANA timezone; empty keeps it.', 'title': 'Replacement name.',
    'enabled': {'type': 'boolean', 'description': 'False pauses it; true resumes it.'}})
def schedule_update(ctx: ToolContext, id: int, when: str = '', text: str = '', timezone: str = '',
                    title: str = '', enabled: bool = None):
    """Change one schedule of this app: its time (a one-off can become repeating and back), instructions or
    name, or pause and resume it. A run already going may finish."""
    found = ctx.store.schedule(id)
    if not found or found['app'] != ctx.app:
        raise ToolError(f'There is no schedule {id}.')
    changes = {key: value for key, value in {'when': when, 'text': text, 'timezone': timezone, 'title': title}.items() if value}
    if enabled is not None:
        changes['enabled'] = enabled
    if not changes:
        raise ToolError('Give a new time, instructions, name, timezone or enabled state.')
    try:
        return 'Updated. ' + describe(ctx.brain.scheduler.update(id, **changes))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


TOOLKIT = Toolkit("schedule", "Schedules: work for later, once or repeating; reminders are schedules too.",
                  [schedule_create, schedule_list, schedule_update, schedule_delete],
                  part=True)
