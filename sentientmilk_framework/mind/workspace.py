"""What is on her mind now: one workspace every process writes to and reads from (life.py).

What is active for her (a thought, what she means to say, a task of hers going, something she put off, what a
chat is about, what is around her, a feeling she named, what she knows of herself) is entered here by whatever
made it active, keyed by the record it stands for; the records stay where they are. Each reader takes what is
about the matter at hand first, then what is most active, as many as her span holds: a global workspace, its
contents competing for a few places (Baars 1988; Dehaene & Naccache 2001; about four chunks: Cowan 2001), the
competition biased toward what the moment is about (Desimone & Duncan 1995). Unfinished goals stay in it and
keep drawing attention while they are used (current concerns: Klinger 1975).

How active an item is follows its uses, as ACT-R's base level: ln of the summed decaying traces of its uses,
each t^-d (Anderson & Schooler 1991: the power law of forgetting follows how often things recur in the world;
d = 0.5, ACT-R's default fitted across many studies). Uses are kept as their count, first and last, the rest
approximated over the item's lifetime (Petrov 2006), so a record does not grow."""

import math
import sqlite3
import threading
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

from ..vectors import Vectors
from .memory import ago

DECAY = 0.5  # ACT-R's base-level decay d
KINDS = ("asked", "thought", "intends", "doing", "put off", "named", "self")
SOON = 1.0  # s: a use this close counts as now (t^-d is unbounded at 0)
CURRENT = ("intends", "doing")  # what she means to do now
SCHEMA = """CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
    text TEXT NOT NULL, episode INTEGER, n INTEGER NOT NULL, first REAL NOT NULL, last REAL NOT NULL);"""


class Workspace:
    """Kept in her mind's database beside her moments; each item's words have a vector of their own (``vectors``,
    embedded by the sweep that embeds her moments, and before a reader looks), so a cue meets what she put off,
    means or knows of herself in its own words, not in the whole turn it came from."""

    def __init__(self, db: sqlite3.Connection, lock: threading.RLock):
        self._db, self._lock = db, lock
        with lock:
            db.executescript(SCHEMA)
        self.vectors = Vectors(db, "workspace", lock)

    @property
    def items(self) -> Dict[str, dict]:
        with self._lock:
            return {row["key"]: dict(row) for row in self._db.execute("SELECT * FROM workspace")}

    def enter(self, key: str, kind: str, text: str, now: float, episode: Optional[int] = None) -> dict:
        """A process made this active (again): a use, its words and what it stands for as they are now."""
        if kind not in KINDS:
            raise ValueError(f"not a kind of item: {kind}")
        text = " ".join(text.split())
        with self._lock:
            if self._db.execute("SELECT 1 FROM workspace WHERE key = ?", (key,)).fetchone() is None:
                self._db.execute("INSERT INTO workspace (key, kind, text, episode, n, first, last) "
                                 "VALUES (?, ?, ?, ?, 1, ?, ?)", (key, kind, text, episode, now, now))
            else:
                self._db.execute("UPDATE workspace SET kind = ?, episode = ?, n = n + 1, last = MAX(last, ?) "
                                 "WHERE key = ?", (kind, episode, now, key))
                # its words only when they changed: new words, a new meaning to embed
                self._db.execute("UPDATE workspace SET text = ? WHERE key = ? AND text != ?", (text, key, text))
            return dict(self._db.execute("SELECT * FROM workspace WHERE key = ?", (key,)).fetchone())

    def link(self, key: str, episode: Optional[int]) -> None:
        """What an item stands for, kept since (a message's moment is kept when her turn ends): no use."""
        with self._lock:
            self._db.execute("UPDATE workspace SET episode = ? WHERE key = ?", (episode, key))

    def use(self, keys: Iterable[str], now: float) -> None:
        """These were put before her (given to her cortex, or her thought): each a use."""
        with self._lock:
            self._db.executemany("UPDATE workspace SET n = n + 1, last = MAX(last, ?) WHERE key = ?",
                                 [(now, key) for key in keys])

    def leave(self, key: str) -> None:
        """Done with: it is no longer on her mind (what came of it is in her memory)."""
        with self._lock:
            self._db.execute("DELETE FROM workspace WHERE key = ?", (key,))

    def leave_kind(self, kind: str, keep: Iterable[str] = ()) -> None:
        """Every item of ``kind`` but those in ``keep`` leaves (its records are gone)."""
        kept = set(keep)
        with self._lock:
            gone = [(row["key"],) for row in self._db.execute("SELECT key FROM workspace WHERE kind = ?", (kind,))
                    if row["key"] not in kept]
            self._db.executemany("DELETE FROM workspace WHERE key = ?", gone)

    def likeness(self, vector: Optional[np.ndarray], model: str, scale: Callable[[float], float]) -> Dict[str, float]:
        """Each item's likeness in meaning to a cue's ``vector`` (of ``model``), by its own words: ``scale`` takes
        the cosine to 0..1 above the floor the reader's kind of cue is measured against. Items whose words have
        no vector yet are not alike."""
        if vector is None:
            return {}
        with self._lock:
            keys = {row["id"]: row["key"] for row in self._db.execute("SELECT id, key FROM workspace")}
        found = self.vectors.nearest(vector, model, len(keys), set(keys)) if keys else []
        return {keys[row]: scale(cosine) for row, cosine in found}

    @staticmethod
    def activation(item: dict, now: float) -> float:
        """ACT-R's base level with Petrov's (2006) hybrid: the last use exactly, the other n-1 spread over the
        item's lifetime."""
        d = DECAY
        last = max(SOON, now - item["last"])
        life = max(last, now - item["first"])
        total = last ** -d
        if item["n"] > 1:  # the earlier uses spread evenly between its first and last (all at once: as old as the last)
            total += (item["n"] - 1) * ((life ** (1 - d) - last ** (1 - d)) / ((1 - d) * (life - last))
                                        if life > last else last ** -d)
        return math.log(total)

    def before_her(self, now: float, span: int, likeness: Optional[Dict[str, float]] = None,
                   carried: Iterable[str] = ()) -> List[dict]:
        """What comes before her, as many as ``span`` holds. With a cue (``likeness``: by key, 0..1 above her own
        floor for what is related): what she means to do now (her wish, her tasks: an intention stays more
        active than other material while it waits, Goschke & Kuhl 1993), then what the cue is about, the most
        alike first; the rest stays out, since a memory's base level alone brings nothing back without its
        context, and something put off comes when something calls it up (McDaniel & Einstein 2000). With no
        cue (looking inward): the most active. ``carried``: what the reader gives her anyway."""
        skip = set(carried)
        pool = [item for key, item in self.items.items() if key not in skip]
        if likeness is None:
            return sorted(pool, key=lambda item: -self.activation(item, now))[:max(0, span)]
        current = sorted((item for item in pool if item["kind"] in CURRENT),
                         key=lambda item: -self.activation(item, now))
        about = sorted((item for item in pool if item["kind"] not in CURRENT and likeness.get(item["key"], 0.0) > 0.0),
                       key=lambda item: (-likeness[item["key"]], -self.activation(item, now)))
        return (current + about)[:max(0, span)]

    def by_activation(self, now: float) -> List[dict]:
        return sorted(self.items.values(), key=lambda item: -self.activation(item, now))


def line(item: dict, now: float) -> str:
    """An item as it is before her, in words, with when it began."""
    when, text = ago(item["first"], now), item["text"]
    return {"asked": f"{text} ({when})", "thought": f'your thought {when}: "{text}"',
            "intends": f"{when} you meant {text}", "doing": f"you are doing {text} (started {when})",
            "put off": f"what you put off {when}: {text}", "named": f"{text} ({when})",
            "self": f"what you've come to know of yourself: {text}"}[item["kind"]]
