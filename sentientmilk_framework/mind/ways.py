"""Her ways: how she does things, wherever she is (design: docs/superpowers/specs/2026-11-17-ways-design.md).

What a person keeps of how to act is not a memory that has to come back: it is how they act. A way is an if-then
(when I finish a piece of code, I run it before I say it's done; when nobody has spoken to me, I don't message
first), as personality's stable part is a person's if-then signature (Mischel & Shoda 1995). She takes one on
when she is told to do things so from now on or settles on it herself (a decided if-then makes the response
follow the moment: Gollwitzer & Sheeran 2006), or she falls into one, doing the same in the same kind of moment
(habits are context-response links built by repetition: Wood & Rünger 2016). Each night her sleep goes over the
day against her ways (procedural memory consolidates in sleep: Walker & Stickgold 2004): kept, a way grows
toward a habit, fast at first and then slower (Lally et al. 2010: an asymptote, a median of 66 days, and a
missed day does not undo it); broken, it loses a little; not met for a month, it fades, and the faintest go.

Her ways are in every prompt of her turns (Mind.ways_section) and her thoughts (THINK), never recalled by
meaning; nothing in code holds her to them.
"""

import re
from typing import Dict, Iterable, List, Optional

DAY = 86400.0
START = {"told": 0.5, "decided": 0.5, "habit": 0.3}  # how strong a way is when she takes it on
GAIN = 0.25  # kept, it moves this share of the way to a full habit
LAPSE = 0.15  # broken, it loses this share
UNUSED = 30 * DAY  # not met this long...
FADE = 0.05  # ...it fades this share a night
GONE = 0.1  # fainter than this, it is gone
HABIT = 0.7  # this strong, it is a habit of hers
TEXT_CHARS = 300


def key(name: str) -> str:
    """A way's name as it is kept: "Sign Replies" and "sign_replies" are one way."""
    return re.sub(r"[^\w]+", "_", str(name or "").strip().lower()).strip("_")[:40]


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())[:TEXT_CHARS]


class Ways:
    def __init__(self, saved: Optional[dict] = None):
        self.known: List[dict] = list((saved or {}).get("known") or [])

    def to_dict(self) -> dict:
        return {"known": self.known}

    def find(self, name: str) -> Optional[dict]:
        wanted = key(name)
        return next((way for way in self.known if wanted and way["name"] == wanted), None)

    def keep(self, name: str, when: str, then: str, source: str, now: float) -> dict:
        """She takes on a way (or changes one she has, by its name): ``when`` the kind of moment, ``then`` what she
        does in it; ``source``: told, decided or habit."""
        when = re.sub(r"^when(ever)?\b[\s,:]*", "", _clean(when), flags=re.IGNORECASE)
        way = self.find(name)
        if way is None:
            way = {"name": key(name), "source": source if source in START else "decided",
                   "strength": START.get(source, START["decided"]), "since": now, "last": now, "kept": 0, "broken": 0}
            self.known.append(way)
        way.update(when=when, then=_clean(then))
        return way

    def drop(self, name: str) -> bool:
        way = self.find(name)
        if way is not None:
            self.known.remove(way)
        return way is not None

    def review(self, kept: Iterable[str], broken: Iterable[str], now: float, new: Iterable[dict] = (),
               dropped: Iterable[str] = (), reworded: Iterable[dict] = ()) -> bool:
        """A night's going over the day: the ways she kept and broke when their moment came, ways she took on
        and did not keep yet ({name, when, then, from: told or habit}), ways she was told to stop and ways of hers
        said again plainly ({name, when, then}: the same way, its strength and record kept). Whether anything
        changed."""
        changed = False
        for names, kept_it in ((kept, True), (broken, False)):
            for name in names or ():
                way = self.find(name)
                if way is None:
                    continue
                if kept_it:
                    way["strength"] += GAIN * (1.0 - way["strength"])
                else:
                    way["strength"] *= 1.0 - LAPSE
                way["kept" if kept_it else "broken"] += 1
                way["last"], changed = now, True
        for item in new or ():
            if isinstance(item, dict) and key(item.get("name")) and _clean(item.get("when")) \
                    and _clean(item.get("then")) and self.find(item["name"]) is None:
                self.keep(item["name"], item["when"], item["then"], "told" if item.get("from") == "told" else "habit",
                          now)
                changed = True
        for item in reworded or ():  # words that could be misread (a "she" who could be anyone), said plainly
            way = self.find(item.get("name")) if isinstance(item, dict) else None
            if way is not None and _clean(item.get("when")) and _clean(item.get("then")):
                before = (way["when"], way["then"])
                self.keep(way["name"], item["when"], item["then"], way["source"], now)
                changed = changed or (way["when"], way["then"]) != before
        for name in dropped or ():
            changed = self.drop(name) or changed
        return changed

    def fade(self, now: float) -> List[str]:
        """A night: a way not met for a month fades a little; the faintest go (their names)."""
        gone = []
        for way in list(self.known):
            if now - way.get("last", now) > UNUSED:
                way["strength"] *= 1.0 - FADE
                if way["strength"] < GONE:
                    self.known.remove(way)
                    gone.append(way["name"])
        return gone

    def _ranked(self) -> List[dict]:
        return sorted(self.known, key=lambda way: -way["strength"])

    def lines(self) -> List[str]:
        """Each way as she keeps it in mind, the strongest first."""
        return [f"When {way['when']}: {way['then']}" for way in self._ranked()]

    def section(self) -> str:
        """YOUR WAYS, for her system prompt ("" with none): habits and what she took on lately."""
        if not self.known:
            return ""
        habits = [way for way in self._ranked() if way["strength"] >= HABIT]
        lately = [way for way in self._ranked() if way["strength"] < HABIT]
        parts = ["## YOUR WAYS\nHow you do things, in every chat: ways you were told or took on, and habits you fell "
                 "into. They are you, not rules to recite: keep to them without being reminded."]
        for head, group in (("Habits of yours (you do them without thinking):", habits),
                            ("What you took on lately (it still takes keeping in mind):", lately)):
            if group:
                parts.append(head + "\n" + "\n".join(f"- When {way['when']}: {way['then']}" for way in group))
        return "\n".join(parts)

    def listed(self) -> List[Dict]:
        """For apps and the panel: every way, the strongest first."""
        return [{**way, "strength": round(way["strength"], 3)} for way in self._ranked()]
