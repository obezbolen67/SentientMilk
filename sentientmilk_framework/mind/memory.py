"""Her episodic memory: what happened, with what she felt then, recalled the way people recall.

Each episode keeps its feeling (valence, arousal), its salience (how much it mattered when it happened)
and a strength that fades as a power law of the time since it was last recalled. Recall is by likeness to
a cue (bm25 over the episode's words, SQLite FTS5), and also by mood (a sad mind finds sad memories),
strength, salience and recency, with a little noise: the same cue does not always bring back the same
thing. Recalling strengthens a memory and drifts its feeling toward the mood she recalls it in
(reconsolidation). Sleep softens the charge of what she replays. Faint, unimportant episodes are forgotten.

An exchange also keeps what followed the user's message (``follow``: what it did to her needs, as it turned
out). ``known`` tells how like her memories a new message is (how new it is to her) and what followed the
messages most like it: her own record of what such messages bring.

The mind keeps its own state here too (``state``): her body, values, story, concerns and named feelings.
"""

import json
import math
import random
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

KINDS = ("exchange", "thought", "outcome", "dream", "insight", "event")
FADE_DAYS = 1.0  # strength halves over about this, unless recalled, and slower with each day (power law)
WORDS = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _words(text: str) -> List[str]:
    return list(dict.fromkeys(word.lower() for word in WORDS.findall(text or "")))[:24]


class Memory:
    def __init__(self, path: Path, seed: int = 0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        with self._lock:
            self._db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                    app TEXT, session TEXT, valence REAL NOT NULL, arousal REAL NOT NULL,
                    salience REAL NOT NULL, strength REAL NOT NULL, recalls INTEGER NOT NULL DEFAULT 0,
                    recalled REAL, charge REAL NOT NULL, follows TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS recall USING fts5(text, content='episodes', content_rowid='id');
                CREATE VIRTUAL TABLE IF NOT EXISTS recall_terms USING fts5vocab(recall, 'row');
                CREATE TRIGGER IF NOT EXISTS episode_added AFTER INSERT ON episodes BEGIN
                    INSERT INTO recall(rowid, text) VALUES (new.id, new.text); END;
                CREATE TRIGGER IF NOT EXISTS episode_gone AFTER DELETE ON episodes BEGIN
                    INSERT INTO recall(recall, rowid, text) VALUES ('delete', old.id, old.text); END;
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            if "follows" not in {row[1] for row in self._db.execute("PRAGMA table_info(episodes)")}:
                self._db.execute("ALTER TABLE episodes ADD COLUMN follows TEXT")  # a mind from before 0.21

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ============== Her own state ==============

    def get(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
                             "value = excluded.value", (key, json.dumps(value, ensure_ascii=False)))

    # ============== Episodes ==============

    def add(self, kind: str, text: str, valence: float, arousal: float, salience: float, *, app: str = "",
            session: str = "", at: Optional[float] = None) -> int:
        text = " ".join(str(text).split())[:1200]
        salience = max(0.0, min(1.0, salience))
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO episodes (at, kind, text, app, session, valence, arousal, salience, strength, charge) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time() if at is None else at, kind, text, app, session, max(-1.0, min(1.0, valence)),
                 max(0.0, min(1.0, arousal)), salience, 0.5 + 0.5 * salience, 1.0))
            return cursor.lastrowid

    @staticmethod
    def strength_now(episode: dict, now: float) -> float:
        since = max(0.0, now - (episode["recalled"] or episode["at"])) / 86400.0
        return episode["strength"] * (1.0 + since / FADE_DAYS) ** -0.5

    def recall(self, cue: str, valence: float, now: float, count: int = 3, kinds: Iterable[str] = (),
               before: Optional[float] = None, strengthen: bool = True,
               held: Optional[Tuple[str, str, float]] = None) -> List[dict]:
        """What comes back for ``cue`` in a mood of ``valence``: up to ``count`` episodes, best first.
        ``before``: only what happened before then (not what just happened). ``held``: (app, session, since),
        a chat whose exchanges from then on she still has before her (her context holds them): they are
        not brought back (in the user's brain, 2026-11-16, what came back was mostly the chat she was in)."""
        words = _words(cue)
        kinds = list(kinds)
        clause = (" AND e.kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        when = (" AND e.at < ?" if before is not None else "") + \
            (" AND NOT (e.app = ? AND e.session = ? AND e.at >= ?)" if held else "")
        args = list(kinds) + ([before] if before is not None else []) + list(held or ())
        with self._lock:
            found = {}
            if words:
                query = " OR ".join(f'"{word}"' for word in words)
                for row in self._db.execute(
                        "SELECT e.*, bm25(recall) AS rank FROM recall JOIN episodes e ON e.id = recall.rowid "
                        f"WHERE recall MATCH ?{clause}{when} ORDER BY rank LIMIT 40", [query] + args):
                    found[row["id"]] = {**dict(row), "relevance": -row["rank"] / (1.0 - row["rank"])}
            # what comes to mind unbidden: the strongest and the most recent, whatever the words
            for row in self._db.execute(f"SELECT e.* FROM episodes e WHERE 1=1{clause}{when} "
                                        "ORDER BY e.salience * e.strength DESC, e.at DESC LIMIT 20", args):
                found.setdefault(row["id"], {**dict(row), "relevance": 0.0})
            scored = []
            for episode in found.values():
                strength = self.strength_now(episode, now)
                age = max(0.0, now - episode["at"]) / 86400.0
                congruence = 1.0 - abs(episode["valence"] - valence) / 2.0
                score = (1.2 * episode["relevance"] + 0.4 * strength + 0.25 * episode["salience"] * episode["charge"]
                         + 0.25 / (1.0 + age) + 0.35 * abs(valence) * congruence + self._rng.gauss(0.0, 0.05))
                if episode["relevance"] or strength > 0.35:
                    scored.append((score, episode))
            chosen = [episode for _, episode in sorted(scored, key=lambda item: -item[0])[:count]]
            if strengthen:
                for episode in chosen:  # recalled: stronger, and its feeling drifts toward the mood it is recalled in
                    self._db.execute(
                        "UPDATE episodes SET recalls = recalls + 1, recalled = ?, strength = ?, valence = ? WHERE id = ?",
                        (now, min(1.0, self.strength_now(episode, now) + 0.25 * (1.0 - self.strength_now(episode, now))),
                         episode["valence"] + 0.1 * (valence - episode["valence"]), episode["id"]))
        return chosen

    def replay(self, count: int = 2) -> List[dict]:
        """What a resting mind replays: episodes drawn at random from her whole life, the strong and charged
        more often, so two that never met can come up together (what a new idea is made of)."""
        with self._lock:
            rows = [dict(row) for row in self._db.execute("SELECT * FROM episodes ORDER BY RANDOM() LIMIT 60")]
        chosen = []
        while rows and len(chosen) < count:
            weights = [0.1 + row["salience"] * row["charge"] * row["strength"] for row in rows]
            chosen.append(rows.pop(self._rng.choices(range(len(rows)), weights)[0]))
        return chosen

    def follow(self, episode_id: int, followed: Dict[str, float]) -> None:
        """What followed the user's message in this exchange: what it did to her needs, as it turned out."""
        with self._lock:
            self._db.execute("UPDATE episodes SET follows = ? WHERE id = ?", (json.dumps(followed), episode_id))

    def known(self, cue: str, before: float, count: int = 8) -> Tuple[Optional[float], Dict[str, float], float]:
        """How ``cue`` (a message) meets her memories from before ``before``: the likeness (0..1) of the
        memory most like it (None: no words to go by), what followed the ``count`` messages most like it
        (each need's change, weighted by likeness) and how much she has to go on (their summed likeness).
        Likeness is the share of the cue's words a memory has, each weighed by how rare it is among her
        memories, so words every memory has count for little and a word she never met makes it new. The
        weight is log(1 + (N - n + 0.5) / (n + 0.5)), which stays above 0 in a young memory (bm25's own is 0
        for any word in half of them: with two memories, every likeness was 0 live); bm25 finds candidates."""
        words = _words(cue)
        if not words:
            return None, {}, 0.0
        with self._lock:
            total = self._db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            seen = dict(self._db.execute(f"SELECT term, doc FROM recall_terms WHERE term IN ({','.join('?' * len(words))})",
                                         words).fetchall())
            rows = self._db.execute(
                "SELECT e.text, e.follows FROM recall JOIN episodes e ON e.id = recall.rowid "
                "WHERE recall MATCH ? AND e.at < ? ORDER BY bm25(recall) LIMIT 40",
                (" OR ".join(f'"{word}"' for word in words), before)).fetchall()
        rare = {w: math.log(1.0 + (total - seen.get(w, 0) + 0.5) / (seen.get(w, 0) + 0.5)) for w in words}
        whole = sum(rare.values())
        liked = []
        for row in rows:
            has = {word.lower() for word in WORDS.findall(row["text"])}
            liked.append((sum(weight for word, weight in rare.items() if word in has) / whole, row["follows"]))
        liked.sort(key=lambda item: -item[0])
        best, sums, evidence, used = (liked[0][0] if liked else 0.0), {}, 0.0, 0
        for like, follows in liked:
            if follows and used < count:
                used += 1
                evidence += like
                for need, change in json.loads(follows).items():
                    sums[need] = sums.get(need, 0.0) + like * change
        return best, ({need: total_ / evidence for need, total_ in sums.items()} if evidence else {}), evidence

    def since(self, at: float, kinds: Iterable[str] = (), count: int = 0) -> List[dict]:
        """Episodes from ``at`` on, the most charged first (``count`` of them; 0: all)."""
        kinds = list(kinds)
        clause = (" AND kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM episodes WHERE at >= ?{clause} "
                                    "ORDER BY salience * charge * (0.5 + arousal) DESC" + (" LIMIT ?" if count else ""),
                                    [at] + kinds + ([count] if count else [])).fetchall()
        return [dict(row) for row in rows]

    def recent(self, count: int = 10, kinds: Iterable[str] = ()) -> List[dict]:
        kinds = list(kinds)
        clause = (" WHERE kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM episodes{clause} ORDER BY at DESC, id DESC LIMIT ?",
                                    kinds + [count]).fetchall()
        return [dict(row) for row in rows]

    def soften(self, ids: Iterable[int], share: float = 0.35) -> None:
        """Sleep replays them: their charge softens, and replaying makes them a little stronger."""
        with self._lock:
            for episode_id in ids:
                self._db.execute("UPDATE episodes SET charge = charge * ?, strength = MIN(1.0, strength + 0.1) "
                                 "WHERE id = ?", (1.0 - share, episode_id))

    def forget_faint(self, now: float, older_days: float = 30.0) -> int:
        """Old, faint, unimportant episodes go (insights and dreams she wrote down stay longer)."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM episodes WHERE at < ? AND salience < 0.3 AND kind NOT IN "
                                    "('insight')", (now - older_days * 86400.0,)).fetchall()
            gone = [row["id"] for row in rows if self.strength_now(dict(row), now) < 0.08]
            for episode_id in gone:
                self._db.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
        return len(gone)

    def forget_session(self, app: str, session: str) -> int:
        """The user deleted a conversation: what she kept of it goes too."""
        with self._lock:
            return self._db.execute("DELETE FROM episodes WHERE app = ? AND session = ?", (app, session)).rowcount

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]


def line(episode: dict, now: float) -> str:
    """An episode as it comes back to her: how long ago, and what."""
    ago = max(0.0, now - episode["at"])
    when = ("just now" if ago < 120 else f"{int(ago // 60)} minutes ago" if ago < 3600 else
            f"{int(ago // 3600)} hours ago" if ago < 86400 else f"{int(ago // 86400)} days ago")
    return f"({when}) {episode['text']}"


def describe_salience(surprise: float, arousal: float, stakes: float) -> float:
    """How much a moment matters to memory: surprise, how stirred she was, and what was at stake for her."""
    return max(0.0, min(1.0, 0.4 * surprise + 0.4 * arousal + 0.3 * stakes - 0.05))

