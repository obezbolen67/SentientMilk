"""Whether the user is at the computer, for anything in the brain that needs to know (her sense of them being
there, how long a silence means they chose not to answer): built from what the apps on that computer report
each time they ask (seconds since the keyboard or mouse was last touched, whether the screen is locked,
whether something fullscreen has them), and a clock that runs only while they could answer.

Nobody touching the computer for a couple of minutes is still there (reading, watching); after ten they are
away. A locked screen is away at once. Something fullscreen (a game, a film, a call) has them there but
absorbed: a message waits a while before they could see it. When no app has reported for a minute, nobody can
tell (the app closed, the machine asleep), and only a touch they made counts."""

import threading
import time
from typing import Optional

STALE = 60.0  # s without a report: nobody can tell any more
STILL_THERE = 120.0  # s untouched that still count as fully there
GONE = 600.0  # s untouched: away
ABSORBED = 0.35  # how available they are while something fullscreen has them
GAP = 600.0  # a longer step between counts (the brain off, the machine asleep) counts as none: nobody saw it


class Presence:
    """The user at the computer: ``report`` what an app sees, ask ``here``, ``availability`` and ``since``."""

    def __init__(self):
        self._lock = threading.Lock()
        self.touched = 0.0  # when they last touched the keyboard or mouse (or wrote)
        self.locked = False
        self.busy = False  # something fullscreen has them
        self.reported = 0.0  # when an app last reported
        self.clock = 0.0  # seconds they could have answered, each weighted by how available they were
        self._counted: Optional[float] = None

    def report(self, idle: Optional[float] = None, locked: Optional[bool] = None, busy: Optional[bool] = None,
               now: Optional[float] = None) -> None:
        """What an app sees now: seconds since the keyboard or mouse was last touched, whether the screen is
        locked, whether something fullscreen has them (None: it cannot tell)."""
        now = time.time() if now is None else now
        with self._lock:
            self._count(now)
            self.reported = now
            if idle is not None and idle >= 0:
                self.touched = max(self.touched, now - idle)
            if locked is not None:
                self.locked = bool(locked)
            if busy is not None:
                self.busy = bool(busy)

    def touch(self, now: Optional[float] = None) -> None:
        """They did something with her (wrote): they are there."""
        now = time.time() if now is None else now
        with self._lock:
            self._count(now)
            self.touched, self.locked = max(self.touched, now), False

    def there(self, now: Optional[float] = None) -> float:
        """How surely they are at the computer, 0..1."""
        now = time.time() if now is None else now
        idle = now - self.touched
        if self.locked or (now - self.reported > STALE and idle > STILL_THERE):
            return 0.0
        return 1.0 if idle <= STILL_THERE else max(0.0, (GONE - idle) / (GONE - STILL_THERE))

    def here(self, now: Optional[float] = None) -> bool:
        return self.there(now) >= 0.5

    def availability(self, now: Optional[float] = None) -> float:
        """How free they are to see and answer a message now, 0..1: there, and not absorbed in something."""
        return self.there(now) * (ABSORBED if self.busy else 1.0)

    def since(self, mark: float, now: Optional[float] = None) -> float:
        """Seconds they could have answered since the clock read ``mark`` (``self.clock`` then)."""
        now = time.time() if now is None else now
        with self._lock:
            self._count(now)
            return max(0.0, self.clock - mark)

    def now(self, now: Optional[float] = None) -> float:
        """The clock's reading now, to measure from (``since``)."""
        return self.since(0.0, now)

    def state(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        return {"here": self.here(now), "there": round(self.there(now), 3),
                "available": round(self.availability(now), 3),
                "idle": round(now - self.touched) if self.touched else None, "locked": self.locked, "busy": self.busy}

    def _count(self, now: float) -> None:
        if self._counted is not None:
            if now <= self._counted:
                return
            if not self.locked and now - self._counted < GAP:
                # The last report expires and availability falls linearly with idle time.
                end = min(now, max(self.reported + STALE, self.touched + STILL_THERE), self.touched + GONE)
                start = self._counted
                knee = self.touched + STILL_THERE
                full = max(0.0, min(end, knee) - start)
                start = max(start, knee)
                fading = 0.0
                if end > start:
                    fading = (end - start) * (self.touched + GONE - (start + end) / 2) / (GONE - STILL_THERE)
                self.clock += (full + fading) * (ABSORBED if self.busy else 1.0)
        self._counted = now
