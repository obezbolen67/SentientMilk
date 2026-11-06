"""Schedules: fire at a time, on a cron expression, or every N minutes, in the machine's local time.

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

logger = logging.getLogger(__name__)

MAX_PER_APP = 50
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


def cron_next(spec: str, after: float) -> Optional[float]:
    (minutes, hours, days, months, weekdays), day_set, weekday_set = parse_cron(spec)
    start = datetime.fromtimestamp(after).replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = start.date()
    for _ in range(366 * 5):
        if day.month in months:
            in_days, in_weekdays = day.day in days, day.isoweekday() % 7 in weekdays
            matches = (in_days or in_weekdays) if day_set and weekday_set else \
                (in_days if day_set else in_weekdays if weekday_set else True)
            if matches:
                for hour in sorted(hours):
                    for minute in sorted(minutes):
                        candidate = datetime(day.year, day.month, day.day, hour, minute)
                        if candidate >= start:
                            return candidate.timestamp()
        day += timedelta(days=1)
    return None


def parse_when(when: str, now: float) -> Tuple[str, str]:
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
        stamp = moment.timestamp()  # naive times are local
        if stamp <= now:
            raise ValueError(f"{when} is in the past (now is {datetime.fromtimestamp(now):%Y-%m-%d %H:%M})")
        return "at", moment.isoformat(timespec="minutes")
    try:
        parse_cron(when)
    except ValueError as exc:
        raise ValueError(f"Cannot read when={when!r}: give an ISO time like 2026-11-06T17:00, 'every 30m', "
                         f"or a cron expression. ({exc})")
    return "cron", when


def next_fire(kind: str, spec: str, after: float, created: float) -> Optional[float]:
    if kind == "at":
        stamp = datetime.fromisoformat(spec).timestamp()
        return stamp if stamp > after else None
    if kind == "every":
        period = int(spec)
        return created + period * max(1, math.floor((after - created) / period) + 1)
    return cron_next(spec, after)


class Scheduler:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def create(self, app: str, session: str, when: str, text: str, mode: str = "wake", *,
               created_by: str = "app", catch_up: str = "once") -> dict:
        if mode not in ("wake", "task"):
            raise ValueError("mode must be wake or task")
        if catch_up not in ("once", "skip"):
            raise ValueError("catch_up must be once or skip")
        if not text or not text.strip():
            raise ValueError("text is empty")
        if len(self.store.schedules(app)) >= MAX_PER_APP:
            raise ValueError(f"This app already has {MAX_PER_APP} schedules; delete some first")
        now = time.time()
        kind, spec = parse_when(when, now)
        upcoming = next_fire(kind, spec, now, now)
        schedule_id = self.store.add_schedule(app=app, session=session, kind=kind, spec=spec,
                                              payload={"mode": mode, "text": text.strip()}, next_at=upcoming,
                                              catch_up=catch_up, created_by=created_by, enabled=1)
        self._wake.set()
        return self.store.schedule(schedule_id)

    def delete(self, schedule_id: int) -> bool:
        found = self.store.delete_schedule(schedule_id)
        self._wake.set()
        return found

    def set_enabled(self, schedule_id: int, enabled: bool) -> dict:
        schedule = self.store.schedule(schedule_id)
        if not schedule:
            raise ValueError(f"There is no schedule {schedule_id}")
        now = time.time()
        upcoming = next_fire(schedule["kind"], schedule["spec"], now, schedule["created"]) if enabled else None
        self.store.update_schedule(schedule_id, enabled=int(enabled), next_at=upcoming)
        self._wake.set()
        return self.store.schedule(schedule_id)

    def start(self) -> None:
        self._stop.clear()
        now = time.time()
        for schedule in self.store.schedules(enabled_only=True):
            if schedule["next_at"] and schedule["next_at"] <= now:
                if schedule["catch_up"] == "once":
                    self._fire(schedule, late=True)
                self._advance(schedule, now)
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
            now = time.time()
            upcoming = [s for s in self.store.schedules(enabled_only=True) if s["next_at"]]
            for schedule in upcoming:
                if schedule["next_at"] <= now:
                    self._fire(schedule)
                    self._advance(schedule, now)
            future = [s["next_at"] for s in self.store.schedules(enabled_only=True) if s["next_at"]]
            wait = min([60.0] + [max(0.05, at - time.time()) for at in future])
            self._wake.wait(wait)
            self._wake.clear()

    def _advance(self, schedule: dict, now: float) -> None:
        upcoming = next_fire(schedule["kind"], schedule["spec"], now, schedule["created"])
        self.store.update_schedule(schedule["id"], last_at=now, next_at=upcoming, enabled=int(upcoming is not None))

    def _fire(self, schedule: dict, late: bool = False) -> None:
        payload = schedule["payload"]
        data = {"schedule": schedule["id"], "mode": payload["mode"], "text": payload["text"], "late": late}
        try:
            if payload["mode"] == "task":
                data["task"] = self.brain.runs.start_task(schedule["app"], schedule["session"], payload["text"])
            self.brain.notify(schedule["app"], schedule["session"], "schedule.fired", data)
        except Exception:
            logger.exception("Schedule %s could not fire", schedule["id"])
