"""Schedules: app-owned instructions, wake reminders and tasks, with named-zone calendar rules.

A wake schedule only tells the app (a notification); a task schedule starts a background
task. Missed fires while the brain was down run once at start (catch_up "once") or are
skipped ("skip"). The next time is always computed from the rule, so schedules never drift.
"""

import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone

logger = logging.getLogger(__name__)

MIN_EVERY = 60
_EVERY = re.compile(r"every\s+(\d+)\s*(m|min|mins|minutes?|h|hours?|d|days?)$", re.IGNORECASE)
_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))  # weekday 7 is Sunday too


def parse_cron(spec: str) -> Tuple[List[Set[int]], bool, bool]:
    """Sets of minutes, hours, days, months, weekdays (0 = Sunday), and whether day/weekday are restricted."""
    parts = spec.split()
    if len(parts) != 5:
        raise ValueError("A cron expression has 5 fields: minute hour day month weekday, e.g. '0 9 * * 1-5'")
    sets = []
    for index, (part, (low, high)) in enumerate(zip(parts, _FIELDS)):
        values: Set[int] = set()
        for piece in part.split(","):
            step = 1
            if "/" in piece:
                piece, step_text = piece.split("/", 1)
                step = int(step_text)
                if step < 1:
                    raise ValueError(f"Bad step in {part!r}")
            if piece == "*":
                start, end = low, 6 if index == 4 else high
            elif "-" in piece:
                start, end = (int(v) for v in piece.split("-", 1))
            else:
                start = end = int(piece)
                if step != 1:
                    end = high
            if not (low <= start <= high and low <= end <= high and start <= end):
                raise ValueError(f"{part!r} is out of range {low}-{high}")
            values.update(range(start, end + 1, step))
        sets.append({v % 7 for v in values} if index == 4 else values)
    return sets, parts[2] != "*", parts[4] != "*"


def calendar_zone(timezone: Optional[str] = None):
    if timezone is not None and not isinstance(timezone, str):
        raise ValueError('timezone must be an IANA name')
    try:
        return ZoneInfo(timezone) if timezone else get_localzone()
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError(f'Unknown timezone {timezone!r}; use an IANA name such as Europe/Warsaw') from exc


def _wall_time(moment: datetime, zone) -> Optional[datetime]:
    candidate = moment.replace(tzinfo=zone, fold=0)
    return candidate if datetime.fromtimestamp(candidate.timestamp(), zone).replace(tzinfo=None) == moment else None


def cron_next(spec: str, after: float, timezone: Optional[str] = None) -> Optional[float]:
    (minutes, hours, days, months, weekdays), day_set, weekday_set = parse_cron(spec)
    zone = calendar_zone(timezone)
    day = datetime.fromtimestamp(after, zone).date()
    for _ in range(366 * 5):
        if day.month in months:
            in_days, in_weekdays = day.day in days, day.isoweekday() % 7 in weekdays
            matches = (in_days or in_weekdays) if day_set and weekday_set else \
                (in_days if day_set else in_weekdays if weekday_set else True)
            if matches:
                for hour in sorted(hours):
                    for minute in sorted(minutes):
                        candidate = _wall_time(datetime(day.year, day.month, day.day, hour, minute), zone)
                        if candidate is not None and candidate.timestamp() > after:
                            return candidate.timestamp()
        day += timedelta(days=1)
    return None


def parse_when(when: str, now: float, timezone: Optional[str] = None) -> Tuple[str, str]:
    if not isinstance(when, str):
        raise ValueError('when must be an ISO time, interval or cron expression')
    zone = calendar_zone(timezone)
    when = (when or "").strip()
    every = _EVERY.match(when)
    if every:
        unit = every.group(2)[0].lower()
        seconds = int(every.group(1)) * {"m": 60, "h": 3600, "d": 86400}[unit]
        if seconds < MIN_EVERY:
            raise ValueError("Schedules repeat at most once a minute")
        return "every", str(seconds)
    try:
        moment = datetime.fromisoformat(when)
    except ValueError:
        moment = None
    if moment is not None:
        if moment.tzinfo is None:
            moment = _wall_time(moment, zone)
            if moment is None:
                raise ValueError(f'{when} does not exist in {zone}; choose a time outside the daylight-saving gap')
        stamp = moment.timestamp()
        if stamp <= now:
            raise ValueError(f"{when} is in the past (now is {datetime.fromtimestamp(now):%Y-%m-%d %H:%M})")
        return "at", moment.isoformat()
    try:
        parse_cron(when)
    except ValueError as exc:
        raise ValueError(f"Cannot read when={when!r}: give an ISO time like 2026-11-06T17:00, 'every 30m', "
                         f"or a cron expression. ({exc})")
    return "cron", when


def next_fire(kind: str, spec: str, after: float, created: float, timezone: Optional[str] = None) -> Optional[float]:
    try:
        if kind == 'at':
            stamp = datetime.fromisoformat(spec).timestamp()
            upcoming = stamp if stamp > after else None
        elif kind == 'every':
            period = int(spec)
            upcoming = created + period * max(1, math.floor((after - created) / period) + 1)
        else:
            upcoming = cron_next(spec, after, timezone)
        if upcoming is not None:
            datetime.fromtimestamp(upcoming, calendar_zone(timezone))
        return upcoming
    except (OverflowError, OSError, ZeroDivisionError) as exc:
        raise ValueError('The time or interval is outside the supported calendar range') from exc


class Scheduler:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def create(self, app: str, session: str, when: str, text: str, mode: str = "wake", *,
               created_by: str = "app", catch_up: str = "once", timezone: Optional[str] = None,
               title: str = '') -> dict:
        if mode not in ("app", "wake", "task"):
            raise ValueError("mode must be app, wake or task")
        if catch_up not in ("once", "skip"):
            raise ValueError("catch_up must be once or skip")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is empty")
        if not isinstance(title, str):
            raise ValueError('title must be text')
        if mode == 'app' and not self.store.app(app):
            raise ValueError(f'The app {app!r} is not registered')
        now = time.time()
        kind, spec = parse_when(when, now, timezone)
        upcoming = next_fire(kind, spec, now, now, timezone)
        if upcoming is None:
            raise ValueError('The rule has no future occurrence')
        payload = {'mode': mode, 'text': text.strip()}
        if mode == 'app' or timezone:
            payload['timezone'] = calendar_zone(timezone).key
        if mode == 'app':
            payload['title'] = (title.strip() or text.strip().splitlines()[0])[:80]
        schedule_id = self.store.add_schedule(app=app, session=session, kind=kind, spec=spec,
                                              payload=payload, next_at=upcoming,
                                              catch_up=catch_up, created_by=created_by, enabled=1)
        schedule = self.store.schedule(schedule_id)
        if mode == 'app':
            self.brain.notify(app, schedule['execution_session'], 'session.titled',
                              {'title': payload['title'], 'session': schedule['execution_session']})
        self._wake.set()
        return schedule

    def delete(self, schedule_id: int) -> bool:
        found = self.store.delete_schedule(schedule_id)
        self._wake.set()
        return found

    def set_enabled(self, schedule_id: int, enabled: bool) -> dict:
        return self.update(schedule_id, enabled=enabled)

    def update(self, schedule_id: int, **changes) -> dict:
        if not changes:
            raise ValueError('Give the schedule fields to change')
        if set(changes) - {'when', 'text', 'title', 'timezone', 'catch_up', 'enabled'}:
            raise ValueError('Unknown schedule fields')
        schedule = self.store.schedule(schedule_id)
        if not schedule:
            raise ValueError(f"There is no schedule {schedule_id}")
        payload = dict(schedule['payload'])
        enabled = changes.get('enabled', schedule['enabled'])
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be true or false')
        catch_up = changes.get('catch_up', schedule['catch_up'])
        if catch_up not in ('once', 'skip'):
            raise ValueError('catch_up must be once or skip')
        for key in ('text', 'title'):
            if key in changes:
                if not isinstance(changes[key], str) or not changes[key].strip():
                    raise ValueError(f'{key} is empty')
                payload[key] = changes[key].strip()[:80] if key == 'title' else changes[key].strip()
        if 'timezone' in changes:
            payload['timezone'] = calendar_zone(changes['timezone']).key
        now = time.time()
        kind, spec = parse_when(changes['when'], now, payload.get('timezone')) if 'when' in changes else \
            (schedule['kind'], schedule['spec'])
        created = now if 'when' in changes else schedule['created']
        recalculate = enabled != schedule['enabled'] or bool(set(changes) & {'when', 'timezone'})
        upcoming = (next_fire(kind, spec, now, created, payload.get('timezone')) if recalculate else schedule['next_at']) \
            if enabled else None
        if enabled and upcoming is None:
            raise ValueError('The rule has no future occurrence; choose a new time')
        cancel = not enabled or bool(set(changes) & {'when', 'timezone', 'text'})
        self.store.update_schedule(schedule_id, kind=kind, spec=spec, payload=payload, enabled=int(enabled),
                                   next_at=upcoming, created=created, catch_up=catch_up, cancel_pending=cancel)
        if payload['mode'] == 'app':
            self.store.update_session(schedule['app'], payload['session'], 'settings',
                                      lambda settings: {**settings, 'title': payload['title'], 'schedule': schedule_id},
                                      create=enabled)
            self.brain.notify(schedule['app'], payload['session'], 'schedule.updated', {'schedule': schedule_id})
        self._wake.set()
        return self.store.schedule(schedule_id)

    def start(self) -> None:
        self._stop.clear()
        now = time.time()
        self.tick(now, startup=True)
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Returns once the loop is done: a fire in progress still advances its schedule, then nothing
        writes (the brain closes the store next)."""
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                healthy = self.tick(time.time())
                future = [s["next_at"] for s in self.store.schedules(enabled_only=True) if s["next_at"]]
                wait = min([60.0] + [max(0.05, at - time.time()) for at in future])
                if not healthy:
                    wait = max(1.0, wait)
            except Exception:
                logger.exception('Scheduler storage unavailable; retrying')
                wait = 1.0
            self._wake.wait(wait)
            self._wake.clear()

    def tick(self, now: Optional[float] = None, startup: bool = False) -> bool:
        now = time.time() if now is None else now
        healthy = True
        for schedule in self.store.schedules(enabled_only=True):
            if schedule['next_at'] is None or schedule['next_at'] > now:
                continue
            try:
                skip = startup and schedule['catch_up'] == 'skip'
                if schedule['payload']['mode'] == 'app':
                    following = next_fire(schedule['kind'], schedule['spec'], now, schedule['created'],
                                          schedule['payload'].get('timezone'))
                    notification = self.store.queue_schedule(schedule['id'], schedule['next_at'], now, following,
                                                              late=startup or now - schedule['next_at'] > 60,
                                                              skip=skip)
                    if notification:
                        self.brain.bus.publish(('app', schedule['app']), notification)
                else:
                    if not skip:
                        self._fire(schedule, late=startup)
                    self._advance(schedule, now)
            except Exception:
                healthy = False
                logger.exception('Schedule %s could not advance; it remains due for retry', schedule['id'])
        return healthy

    def _advance(self, schedule: dict, now: float) -> None:
        upcoming = next_fire(schedule["kind"], schedule["spec"], now, schedule["created"],
                              schedule['payload'].get('timezone'))
        self.store.update_schedule(schedule["id"], last_at=now, next_at=upcoming, enabled=int(upcoming is not None))

    def _fire(self, schedule: dict, late: bool = False) -> None:
        """Legacy wake/task delivery; app occurrences use the transactional queue in tick()."""
        payload = schedule["payload"]
        data = {"schedule": schedule["id"], "mode": payload["mode"], "text": payload["text"], "late": late}
        try:
            if payload["mode"] == "task":
                data["task"] = self.brain.runs.start_task(schedule["app"], schedule["session"], payload["text"],
                                                           schedule=schedule["id"])
            self.brain.notify(schedule["app"], schedule["session"], "schedule.fired", data)
        except Exception:
            logger.exception("Schedule %s could not fire", schedule["id"])
