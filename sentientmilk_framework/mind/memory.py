"""Her episodic memory: what happened, with what she felt then, recalled the way people recall.

Each episode keeps its feeling (valence, arousal), what the moment itself did to how she felt (``sting``), its
salience (how much it mattered when it happened) and a strength that fades as a power law of the time since it
was last recalled. Recall is only of what a cue calls up, by likeness to it in meaning (its vector, from her long-term memory's embedder: recall.py fills ``vectors``; until 0.30
also by shared words), and also by mood (a sad mind finds sad memories), strength, salience and recency, with
a little noise: the same cue does not always bring back the same thing. Recalling strengthens a memory and drifts its feeling toward the mood she recalls it in
(reconsolidation). Sleep softens the charge of what she replays. Faint, unimportant episodes are forgotten.

An exchange also keeps what followed the user's message (``follow``: what it did to her needs, as it turned
out). ``known`` tells how like her memories a new message is (how new it is to her) and what followed the
messages most like it: her own record of what such messages bring.

The mind keeps its own state here too (``state``): her body, values, concerns and named feelings.
"""

import json
import random
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..embeddings import MAX_CHARS
from ..vectors import Vectors

KINDS = ("exchange", "thought", "outcome", "dream", "insight", "event")
FADE_DAYS = 1.0  # strength halves over about this, unless recalled, and slower with each day (power law)


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
                    recalled REAL, charge REAL NOT NULL, follows TEXT, sting REAL NOT NULL DEFAULT 0);
                DROP TRIGGER IF EXISTS episode_added;  -- her index by words, until 0.30
                DROP TRIGGER IF EXISTS episode_gone;
                DROP TABLE IF EXISTS recall_terms;
                DROP TABLE IF EXISTS recall;
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(episodes)")}
            if "follows" not in columns:
                self._db.execute("ALTER TABLE episodes ADD COLUMN follows TEXT")  # a mind from before 0.21
            if "sting" not in columns:  # before 0.32: what hurt was not kept, so nothing from then stings
                self._db.execute("ALTER TABLE episodes ADD COLUMN sting REAL NOT NULL DEFAULT 0")
            for name, sql_type in (("run_id", "INTEGER"), ("event_id", "INTEGER"), ("actor", "TEXT"),
                                   ("device", "TEXT"), ("superseded_by", "INTEGER"), ("encoding_valence", "REAL"),
                                   ("origin_ids", "TEXT"), ("attention", "TEXT")):
                if name not in columns:
                    self._db.execute(f"ALTER TABLE episodes ADD COLUMN {name} {sql_type}")
            self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS episode_run ON episodes(run_id) WHERE run_id IS NOT NULL")
            self._db.execute("CREATE INDEX IF NOT EXISTS episode_correction ON episodes(superseded_by) "
                             "WHERE superseded_by IS NOT NULL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS episode_sequence (id INTEGER PRIMARY KEY CHECK(id = 1), last_id INTEGER);
                INSERT OR IGNORE INTO episode_sequence SELECT 1, COALESCE(MAX(id), 0) FROM episodes;
                CREATE TRIGGER IF NOT EXISTS episode_number AFTER INSERT ON episodes BEGIN
                    UPDATE episode_sequence SET last_id = MAX(last_id, NEW.id) WHERE id = 1;
                END;
            """)
        self.vectors = Vectors(self._db, "episodes", self._lock)
        self.embedder = None  # her long-term memory's (recall.py sets it)

    def _alike(self, cue: str, where: str = "", args: Iterable = ()) -> Optional[Dict[int, float]]:
        """Episodes alike in meaning to ``cue`` (``where``: an SQL condition on ``e``), as id -> relevance
        0..1; None when she cannot tell now (no cue, no embedder, or it cannot embed now)."""
        embedder = self.embedder
        if embedder is None or not (cue or "").strip():
            return None
        try:
            vector = embedder.embed([cue[:MAX_CHARS]], query=True)[0]
        except Exception:  # the service is down, or no key: nothing by meaning this time
            return None
        with self._lock:
            allowed = {row[0] for row in self._db.execute(f"SELECT e.id FROM episodes e WHERE 1=1{where}", list(args))}
        try:
            return {episode: self.vectors.relevance(cosine, embedder)
                    for episode, cosine in self.vectors.nearest(vector, embedder.name, 40, allowed)}
        except Exception:  # its floor could not be measured now: nothing by meaning this time
            return None

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ============== Her own state ==============

    @contextmanager
    def transaction(self):
        with self._lock:
            self._db.execute("SAVEPOINT mind_write")
            try:
                yield
            except BaseException:
                self._db.execute("ROLLBACK TO mind_write")
                raise
            finally:
                self._db.execute("RELEASE mind_write")

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
            session: str = "", at: Optional[float] = None, sting: float = 0.0, run_id=None, event_id=None,
            actor=None, device=None, origins=(), attention=()) -> int:
        """``valence``: how she felt in the moment (her mood then, as it keeps it); ``sting``: what the moment
        itself did to how she felt (negative: it hurt), whatever her mood was."""
        text = " ".join(str(text).split())[:1200]
        salience = max(0.0, min(1.0, salience))
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO episodes (id, at, kind, text, app, session, valence, arousal, salience, strength, charge, "
                "sting,run_id,event_id,actor,device,encoding_valence,origin_ids,attention) "
                "VALUES ((SELECT last_id+1 FROM episode_sequence),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time() if at is None else at, kind, text, app, session, max(-1.0, min(1.0, valence)),
                 max(0.0, min(1.0, arousal)), salience, 0.5 + 0.5 * salience, 1.0, max(-2.0, min(2.0, sting)),
                 run_id, event_id, actor, device, valence, json.dumps(list(origins)), json.dumps(list(attention))))
            return cursor.lastrowid

    @staticmethod
    def strength_now(episode: dict, now: float) -> float:
        since = max(0.0, now - (episode["recalled"] or episode["at"])) / 86400.0
        return episode["strength"] * (1.0 + since / FADE_DAYS) ** -0.5

    def recall(self, cue: str, valence: float, now: float, count: int = 3, kinds: Iterable[str] = (),
               before: Optional[float] = None, strengthen: bool = True,
               held: Optional[Tuple[str, str, float]] = None, status=None) -> List[dict]:
        """What comes back for ``cue`` in a mood of ``valence``: up to ``count`` episodes the cue calls up (alike
        in meaning), best first; nothing when she cannot tell what is alike now (no service). ``before``: only
        what happened before then (not what just happened). ``held``: (app, session, since), a chat whose
        exchanges from then on she still has before her (her context holds them): they are not brought back (in
        the user's brain, 2026-11-16, what came back was mostly the chat she was in).

        Until 0.32 her strongest memories also came back unbidden, whatever the cue: replayed on her messages of
        2026-11-17, 13 of 21 brought back one of her own brooding thoughts (one of them 11 times) and two of her
        insights came back with 15 and 13, nearly all related by nothing, each recall making it stronger still.
        A memory that comes by itself is cued by something about the moment (Berntsen 2009); what a resting mind
        replays at random is ``replay``."""
        kinds = list(kinds)
        clause = (" AND e.kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        when = (" AND e.at < ?" if before is not None else "") + \
            (" AND NOT (e.app = ? AND e.session = ? AND e.at >= ?)" if held else "")
        args = list(kinds) + ([before] if before is not None else []) + list(held or ())
        alike = self._alike(cue, clause + when + " AND e.superseded_by IS NULL", args)
        if status is not None:
            status["available"] = alike is not None
        alike = alike or {}
        with self._lock:
            found = {}
            if alike:
                for row in self._db.execute(f"SELECT e.* FROM episodes e WHERE e.id IN ({','.join('?' * len(alike))})",
                                            list(alike)):
                    found[row["id"]] = {**dict(row), "relevance": alike[row["id"]]}
            scored = []
            for episode in found.values():
                strength = self.strength_now(episode, now)
                age = max(0.0, now - episode["at"]) / 86400.0
                congruence = 1.0 - abs(episode["valence"] - valence) / 2.0
                score = (1.2 * episode["relevance"] + 0.4 * strength + 0.25 * episode["salience"] * episode["charge"]
                         + 0.25 / (1.0 + age) + 0.35 * abs(valence) * congruence + self._rng.gauss(0.0, 0.05))
                if episode["relevance"]:
                    scored.append((score, episode))
            chosen = [episode for _, episode in sorted(scored, key=lambda item: -item[0])[:count]]
            if strengthen:
                self.attended(chosen, now, valence)
        return chosen

    def attended(self, chosen, now, valence):
        with self._lock:
            for episode in chosen:
                strength = self.strength_now(episode, now)
                self._db.execute("UPDATE episodes SET recalls = recalls + 1, recalled = ?, strength = ?, valence = ? "
                                 "WHERE id = ? AND superseded_by IS NULL",
                                 (now, min(1.0, strength + 0.25 * (1 - strength)),
                                  episode["valence"] + 0.1 * (valence - episode["valence"]), episode["id"]))

    def replacements(self, origins):
        """Resolve corrected memories without treating a superseded account as corroboration."""
        result = []
        for item in origins:
            seen = set()
            while item and item.get("superseded_by") and item["id"] not in seen:
                seen.add(item["id"])
                rows = self.by_ids([item["superseded_by"]])
                item = rows[0] if rows else None
            if item and not item.get("superseded_by"):
                result.append(item)
        return result

    def corrections(self) -> dict:
        with self._lock:
            return {row["event_id"]: row["superseded_by"] for row in self._db.execute(
                "SELECT event_id,superseded_by FROM episodes WHERE superseded_by IS NOT NULL") if row["event_id"]}

    def replay(self, count: int = 2) -> List[dict]:
        """What a resting mind replays: episodes drawn at random from her whole life, the strong and charged
        more often, so two that never met can come up together (what a new idea is made of)."""
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT id FROM episodes ORDER BY id")]
            sample = self._rng.sample(ids, min(60, len(ids)))
            rows = [dict(row) for row in self._db.execute(
                f"SELECT * FROM episodes WHERE id IN ({','.join('?' * len(sample))}) ORDER BY id", sample)]
        chosen = []
        while rows and len(chosen) < count:
            weights = [0.1 + row["salience"] * row["charge"] * row["strength"] for row in rows]
            chosen.append(rows.pop(self._rng.choices(range(len(rows)), weights)[0]))
        return chosen

    def recorded(self, run_id: int) -> bool:
        with self._lock:
            return bool(self._db.execute("SELECT 1 FROM episodes WHERE run_id=?", (run_id,)).fetchone())

    def supersede(self, episode: int, replacement: int) -> None:
        with self._lock:
            self._db.execute("UPDATE episodes SET superseded_by = ? WHERE id = ?", (replacement, episode))

    def by_ids(self, ids) -> list:
        if not ids:
            return []
        with self._lock:
            return [dict(row) for row in self._db.execute(
                f"SELECT * FROM episodes WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", list(ids))]

    def follow(self, episode_id: int, followed: Dict[str, float]) -> None:
        """What followed the user's message in this exchange: what it did to her needs, as it turned out."""
        with self._lock:
            self._db.execute("UPDATE episodes SET follows = ? WHERE id = ?", (json.dumps(followed), episode_id))

    def known(self, cue: str, before: float, count: int = 8) -> Tuple[Optional[float], Dict[str, float], float]:
        """How ``cue`` (a message) meets her memories from before ``before``: the likeness in meaning (0..1) of
        the memory most like it (None: she cannot tell now, without her long-term memory's embedder), what
        followed the ``count`` messages most like it (each need's change, weighted by likeness) and how much she
        has to go on (their summed likeness). A "hi" after a hundred "hello"s is not new; until 0.30 likeness
        was also the share of the cue's words a memory had, which said nothing of a message in other words."""
        alike = self._alike(cue, " AND e.at < ? AND e.kind = 'exchange' AND e.superseded_by IS NULL", [before])
        if alike is None:
            return None, {}, 0.0
        with self._lock:
            follows = dict(self._db.execute(
                f"SELECT id, follows FROM episodes WHERE id IN ({','.join('?' * len(alike))})", list(alike)).fetchall()
            ) if alike else {}
        liked = sorted(((like, follows.get(episode)) for episode, like in alike.items()), key=lambda item: -item[0])
        best, sums, weights, evidence, used = (liked[0][0] if liked else 0.0), {}, {}, 0.0, 0
        for like, followed in liked:
            if followed and used < count and like > 0.0:
                used += 1
                evidence += like
                for need, change in json.loads(followed).items():
                    weights[need] = weights.get(need, 0.0) + like
                    sums[need] = sums.get(need, 0.0) + like * change
        return best, ({need: total / weights[need] for need, total in sums.items()} if evidence else {}), evidence

    def replay_window(self, start, end, pending, limit):
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT e.* FROM episodes e WHERE at > ? AND at <= ? AND kind IN ('exchange','event','thought') "
                "ORDER BY EXISTS(SELECT 1 FROM episodes old WHERE old.superseded_by=e.id) DESC, "
                "e.id IN (SELECT value FROM json_each(?)) DESC, salience * charge DESC, e.id DESC LIMIT ?",
                (start, end, json.dumps(pending), limit))]

    def since(self, at: float, kinds: Iterable[str] = (), count: int = 0) -> List[dict]:
        """Episodes from ``at`` on, the most charged first (``count`` of them; 0: all)."""
        kinds = list(kinds)
        clause = (" AND kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM episodes WHERE at >= ?{clause} "
                                    "ORDER BY salience * charge * (0.5 + arousal) DESC" + (" LIMIT ?" if count else ""),
                                    [at] + kinds + ([count] if count else [])).fetchall()
        return [dict(row) for row in rows]

    def lived(self, app: str, session: str, start: float, end: float, kinds: Iterable[str] = ("exchange",)) -> List[dict]:
        """What she lived in a session between ``start`` and ``end``."""
        kinds = list(kinds)
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM episodes WHERE app = ? AND session = ? AND at BETWEEN ? AND ? "
                                    f"AND kind IN ({','.join('?' * len(kinds))})",
                                    [app, session, start, end] + kinds).fetchall()
        return [dict(row) for row in rows]

    def rewrite(self, episode_id: int, text: str) -> None:
        """An episode's words, set right (recall finds it by the new ones)."""
        text = " ".join(str(text).split())[:1200]
        with self._lock:
            row = self._db.execute("SELECT text FROM episodes WHERE id = ?", (episode_id,)).fetchone()
            if row is None or row["text"] == text:
                return
            self._db.execute("UPDATE episodes SET text = ? WHERE id = ?", (text, episode_id))

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

    def forget_faint(self, now: float, older_days: float = 30.0, *, protected=()) -> int:
        """Old, faint, unimportant episodes go (insights and dreams she wrote down stay longer): faint is its
        strength now times what of it no stronger episode already holds (``Vectors.held``, by meaning), so of
        two alike the weaker goes sooner (since 0.30; by strength alone before)."""
        with self._lock:
            keep = set(protected)
            for row in self._db.execute("SELECT origin_ids, superseded_by, id FROM episodes "
                                        "WHERE superseded_by IS NOT NULL OR origin_ids != '[]'"):
                keep.update(json.loads(row["origin_ids"] or "[]"))
                if row["superseded_by"] is not None:
                    keep.update((row["id"], row["superseded_by"]))
            rows = self._db.execute("SELECT * FROM episodes WHERE at < ? AND salience < 0.3 AND kind NOT IN "
                                    "('insight')", (now - older_days * 86400.0,)).fetchall()
            strengths = {row["id"]: self.strength_now(dict(row), now) for row in rows if row["id"] not in keep}
            held = self.vectors.held(strengths, self.embedder.name) if self.embedder is not None and rows else {}
            gone = [episode for episode, strength in strengths.items() if strength * (1.0 - held.get(episode, 0.0)) < 0.08]
            for episode_id in gone:
                self._db.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
        return len(gone)

    def retract(self, app, session, event=None, since=None):
        cutoff = "" if event is None else " AND (event_id >= ? OR (event_id IS NULL AND at >= ?))"
        args = [app, session] + ([] if event is None else [event, since])
        with self.transaction():
            gone = {r[0] for r in self._db.execute("SELECT id FROM episodes WHERE app=? AND session=?" + cutoff, args)}
            for row in self._db.execute("SELECT id, origin_ids FROM episodes WHERE origin_ids IS NOT NULL ORDER BY id"):
                if gone.intersection(json.loads(row["origin_ids"])):
                    gone.add(row["id"])
            for episode in gone:
                self._db.execute("DELETE FROM episodes WHERE id=?", (episode,))
                self._db.execute("UPDATE episodes SET superseded_by=NULL WHERE superseded_by=?", (episode,))
            return gone

    def forget_session(self, app: str, session: str) -> int:
        """The user deleted a conversation: what she kept of it goes too."""
        with self._lock:
            return self._db.execute("DELETE FROM episodes WHERE app = ? AND session = ?", (app, session)).rowcount

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]


def line(episode: dict, now: float, *, waking_evidence: bool = False) -> str:
    """An episode as it comes back to her: how long ago, and what."""
    ago = max(0.0, now - episode["at"])
    when = ("just now" if ago < 120 else f"{int(ago // 60)} minutes ago" if ago < 3600 else
            f"{int(ago // 3600)} hours ago" if ago < 86400 else f"{int(ago // 86400)} days ago")
    if waking_evidence and episode.get("kind") == "dream":
        return (f"({when}) A dream came to mind. Your records here contain no waking observation. "
                "If asked whether something was done, you can say you cannot verify it. Check before acting.")
    source = {
        "dream": "You dreamed this scene while asleep. Its events are imagined. Verify any real-world action separately.",
        "thought": "This was a private thought. Any plan mentioned here still needs an execution record.",
        "insight": "An unverified hypothesis you formed on reflection. Check it before relying on it.",
        "exchange": "Remembered exchange. A speaker's words establish what they said.",
        "event": "Recorded event. A task report establishes what was reported.",
        "outcome": "Remembered outcome. Check its original evidence before relying on a more specific claim.",
    }.get(episode.get("kind"))
    return f"({when}) " + (f"{source} " if source else "") + episode["text"]


def describe_salience(surprise: float, arousal: float, stakes: float) -> float:
    """How much a moment matters to memory: surprise, how stirred she was, and what was at stake for her."""
    return max(0.0, min(1.0, 0.4 * surprise + 0.4 * arousal + 0.3 * stakes - 0.05))

