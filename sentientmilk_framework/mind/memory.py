"""Her episodic memory: what happened, with what she felt then, recalled the way people recall.

Each episode keeps its feeling (valence, arousal), what the moment itself did to how she felt (``sting``), its
salience (how much it mattered when it happened) and a strength that fades as a power law of the time since it
was last recalled. Recall is only of what a cue calls up, by likeness to it in meaning (its vector, from her long-term memory's embedder: recall.py fills ``vectors``),
and also by mood (a sad mind finds sad memories), strength, salience and recency, with
a little noise: the same cue does not always bring back the same thing. Recalling strengthens a memory and drifts its feeling toward the mood she recalls it in
(reconsolidation). Sleep softens the charge of what she replays. Faint, unimportant episodes are forgotten.

An exchange also keeps what followed the user's message (``follow``: what it did to her needs, as it turned
out). ``known`` tells how like her memories a new message is (how new it is to her) and what followed the
messages most like it: her own record of what such messages bring.

A moment keeps how it moved her body (``felt``: each channel's change, in units of a lot, by the
moment's peak and its end) and what was around it (its cues: the time of day, where and with whom, and what the
app could tell of her surroundings, such as what was playing). What comes back is called by meaning, by the
surroundings it shares with now (a cue as strong as it is rare among her memories: a song heard once calls its
night back, "evening" calls nothing by itself), by her mood and by how intense the moment was; what just came
back is held off for a while. A vivid memory comes back with its distinctive surroundings, a faint one without:
the details go before the feeling (Yonelinas & Ritchey 2015).

The mind keeps its own state here too (``state``): her body, values, concerns and named feelings.
"""

import json
import math
import random
import sqlite3
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .. import dataformat
from ..embeddings import MAX_CHARS
from ..vectors import Vectors

KINDS = ("exchange", "thought", "outcome", "dream", "insight", "event")
FADE_DAYS = 1.0  # strength halves over about this, unless recalled, and slower with each day (power law)
# the time of day a moment keeps (local hours from): 0-5 late at night, 5-8 early morning...
HOURS = ((5, "late at night"), (8, "early morning"), (12, "morning"), (17, "afternoon"), (21, "evening"),
         (24, "late evening"))
CUED = 0.5  # how strong what a moment shares with now must be to call it up without any likeness in meaning
HELD_OFF = 3600.0  # s over which a memory that just came back gives way to others (it is before her already)
VIVID = 0.5  # strength now from which a memory comes back with its surroundings
# what recurs on a clock describes a moment and calls none up: every day has a morning, however few mornings she
# kept (3 of 217 in her real memory made "morning" look as rare as a song heard once)
RECURS = "time: "
WEARS = 0.05  # of its charge a moment loses each time it comes back and she feels it again (an unpleasant one 1.4x)


class Memory:
    def __init__(self, path: Path, seed: int = 0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        with self._lock:
            dataformat.opened(self._db, self.path)
            self._db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                    app TEXT, session TEXT, valence REAL NOT NULL, arousal REAL NOT NULL,
                    salience REAL NOT NULL, strength REAL NOT NULL, recalls INTEGER NOT NULL DEFAULT 0,
                    recalled REAL, charge REAL NOT NULL, follows TEXT, sting REAL NOT NULL DEFAULT 0,
                    run_id INTEGER, event_id INTEGER, actor TEXT, device TEXT, superseded_by INTEGER,
                    encoding_valence REAL, origin_ids TEXT, attention TEXT, felt TEXT, grew_from TEXT,
                    appraisal TEXT, leaned TEXT);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
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
            # her body's record: every push and her levels at each message, thought and sleep, kept for
            # good, for audits and for replaying her days through a changed model (she is never shown it)
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS body_pushes (at REAL NOT NULL, why TEXT NOT NULL, moved TEXT NOT NULL,
                                                        chat TEXT);
                CREATE INDEX IF NOT EXISTS body_push_at ON body_pushes(at);
                CREATE TABLE IF NOT EXISTS body_levels (at REAL NOT NULL, moment TEXT NOT NULL, levels TEXT NOT NULL,
                                                        chat TEXT);
                CREATE INDEX IF NOT EXISTS body_level_at ON body_levels(at);
            """)
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS episode_cues (episode INTEGER NOT NULL, cue TEXT NOT NULL,
                                                         PRIMARY KEY (episode, cue));
                CREATE INDEX IF NOT EXISTS episode_cue ON episode_cues(cue);
                CREATE TRIGGER IF NOT EXISTS episode_cues_gone AFTER DELETE ON episodes BEGIN
                    DELETE FROM episode_cues WHERE episode = OLD.id;
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

    def likeness(self, cue: str, ids: Iterable[int]) -> Optional[Dict[int, float]]:
        """How alike in meaning what ``cue`` tells is to each of these moments, 0..1 as two of her memories usually
        are to as two about one matter are (Vectors.alike); None when she cannot tell now (no cue, no embedder,
        the service down). It calls the embedder: never under her lock."""
        embedder = self.embedder
        if embedder is None or not (cue or "").strip():
            return None
        try:
            vector = embedder.embed([cue[:MAX_CHARS]])[0]  # as a memory is kept, to compare with memories
        except Exception:  # the service is down, or no key: nothing by meaning this time
            return None
        return self.vectors.alike(vector, embedder.name, ids)

    def likeness_to(self, episode: int, ids: Iterable[int]) -> Optional[Dict[int, float]]:
        """How alike in meaning a kept moment is to each of these (``likeness``), by the vectors her memory keeps: no
        call to the service; None when it has no vector yet."""
        embedder = self.embedder
        vector = self.vectors.vector(episode, embedder.name) if embedder is not None else None
        return self.vectors.alike(vector, embedder.name, ids) if vector is not None else None

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
            actor=None, device=None, origins=(), attention=(), felt: Optional[Dict[str, float]] = None,
            cues: Iterable[str] = (), grew_from: Iterable[int] = (), appraisal: Optional[Dict[str, float]] = None,
            leaned: Optional[dict] = None) -> int:
        """``valence``: how she felt in the moment (her mood then, as it keeps it); ``sting``: what the moment
        itself did to how she felt (negative: it hurt), whatever her mood was; ``felt``: how it moved her body,
        each channel's change in units of a lot; ``cues``: what was around it (``cue``, ``moment_cues``);
        ``origins``: what came up in it; ``grew_from``: for a thought, what it went over (the talk, the moment
        it dwelt on, the thought it went on from): what it goes with when that is taken back (``retract``);
        ``appraisal``: what it meant for her needs as she read it (company, capable, free: what it does to each,
        -1..1; theirs: how things are for the one who wrote); ``leaned``: what she leaned toward doing in it
        (``act``, ``what``). With how it moved her, these are what a feeling of hers is made of (feel.Feelings)."""
        text = " ".join(str(text).split())[:1200]
        salience = max(0.0, min(1.0, salience))
        kept = json.dumps({name: round(change, 3) for name, change in felt.items() if round(change, 3)}) if felt else None
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO episodes (id, at, kind, text, app, session, valence, arousal, salience, strength, charge, "
                "sting,run_id,event_id,actor,device,encoding_valence,origin_ids,attention,felt,grew_from,appraisal,leaned) "
                "VALUES ((SELECT last_id+1 FROM episode_sequence),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time() if at is None else at, kind, text, app, session, max(-1.0, min(1.0, valence)),
                 max(0.0, min(1.0, arousal)), salience, 0.5 + 0.5 * salience, 1.0, max(-2.0, min(2.0, sting)),
                 run_id, event_id, actor, device, valence, json.dumps(list(origins)), json.dumps(list(attention)),
                 kept, json.dumps(list(grew_from)), json.dumps(appraisal) if appraisal else None,
                 json.dumps(leaned) if leaned else None))
            self._db.executemany("INSERT OR IGNORE INTO episode_cues VALUES (?, ?)",
                                 [(cursor.lastrowid, found) for found in {_cue(c) for c in cues} if found])
            return cursor.lastrowid

    @staticmethod
    def felt(episode: dict) -> Dict[str, float]:
        """How the moment moved her body (each channel's change, in units of a lot); {} when that was not kept (a dream, an insight, a turn
        she did not appraise)."""
        return json.loads(episode.get("felt") or "{}")

    @staticmethod
    def appraisal(episode: dict) -> Optional[Dict[str, float]]:
        """What the moment meant for her needs as she read it (``add``); None: not read (a thought, a dream)."""
        return json.loads(episode["appraisal"]) if episode.get("appraisal") else None

    @staticmethod
    def leaned(episode: dict) -> Optional[dict]:
        """What she leaned toward doing in the moment (``act``, ``what``); None: nothing was weighed."""
        return json.loads(episode["leaned"]) if episode.get("leaned") else None

    def bind(self, episode: int, *, leaned: dict) -> None:
        """What she leaned toward in a moment kept before she weighed it (a thought: kept, then weighed)."""
        with self._lock:
            self._db.execute("UPDATE episodes SET leaned = ? WHERE id = ?", (json.dumps(leaned), episode))

    def cues(self, ids: Iterable[int]) -> Dict[int, List[str]]:
        """What was around each of these moments."""
        ids = list(ids)
        found: Dict[int, List[str]] = {}
        with self._lock:
            for episode, kept in self._db.execute(
                    f"SELECT episode, cue FROM episode_cues WHERE episode IN ({','.join('?' * len(ids))})", ids):
                found.setdefault(episode, []).append(kept)
        return found

    def cue_strength(self, cues: Iterable[str]) -> Dict[str, float]:
        """How strongly each of these calls up the moments it was around, 0..1: as rare as it is among the
        moments that kept a cue of its kind (``log(N/n) / log(N)``, N those moments, n those with it: around one of
        them 1, around all of them 0). A cue shared by many brings back none of them (cue overload: Watkins &
        Watkins 1975). Among its kind, not among all her memories: who she was with was kept only lately (10 of
        her 217 moments), and "with: plays" in all ten looked rare among 217."""
        cues = list({_cue(c) for c in cues} - {""})
        kinds = {c: c.split(": ", 1)[0] + ": " for c in cues}
        with self._lock:
            counts = dict(self._db.execute(
                f"SELECT cue, COUNT(*) FROM episode_cues WHERE cue IN ({','.join('?' * len(cues))}) GROUP BY cue",
                cues).fetchall()) if cues else {}
            totals = {kind: self._db.execute("SELECT COUNT(DISTINCT episode) FROM episode_cues WHERE substr(cue, 1, ?) "
                                             "= ?", (len(kind), kind)).fetchone()[0] for kind in set(kinds.values())}
        return {c: 1.0 if totals[kinds[c]] < 2 or not counts.get(c)
                else math.log(totals[kinds[c]] / counts[c]) / math.log(totals[kinds[c]]) for c in cues}

    def _around(self, episodes: List[dict], now: float) -> List[dict]:
        """These moments with what was distinctive around them (``around``), while each is vivid enough to keep it,
        and what came of each (``later``, came_of)."""
        self.came_of(episodes)
        vivid = [e for e in episodes if self.strength_now(e, now) >= VIVID]
        kept = self.cues(e["id"] for e in vivid)
        strength = self.cue_strength(c for found in kept.values() for c in found)
        for episode in episodes:  # its time of day, and what was distinctive around it
            episode["around"] = sorted((c for c in kept.get(episode["id"], ())
                                        if c.startswith(RECURS) or strength.get(c, 0.0) >= CUED),
                                       key=lambda c: (not c.startswith(RECURS), c))
        return episodes

    def came_of(self, episodes: List[dict]) -> None:
        """What came of each of these moments (``later``): the nearest thing said or done after it about the same
        matter (Vectors.matter, by the vectors already kept: no call to the service). A memory comes back with
        how it turned out, as one recalls an errand with whether it got done: without it, her guess that the user
        buys 2% milk came back twice and their "it's 3.2%" never, and a thought of hers had an essay skeleton
        still in its folder hours after she had deleted it as asked (the audit, finding 3). Her own later
        thoughts are not what came of it, nor a dream."""
        embedder = self.embedder
        if embedder is None:
            return
        try:
            floor = self.vectors.matter(embedder.name)
        except Exception:  # cannot tell now: it comes back as it is
            return
        for episode in episodes:
            if episode.get("kind") == "dream" or "later" in episode:
                continue
            vector = self.vectors.vector(episode["id"], embedder.name)
            if vector is None:
                continue
            with self._lock:
                after = {row[0] for row in self._db.execute(
                    "SELECT id FROM episodes WHERE at > ? AND id != ? AND kind IN ('exchange', 'event') "
                    "AND superseded_by IS NULL", (episode["at"], episode["id"]))}
            nearest = self.vectors.nearest(vector, embedder.name, 1, after) if after else []
            if nearest and nearest[0][1] >= floor:
                episode["later"] = (self.by_ids([nearest[0][0]]) or [None])[0]

    def earlier(self, episode: dict, count: int = 3) -> List[dict]:
        """What she had in mind before this moment about the same matter (Vectors.matter, by the vectors kept):
        the nearest earlier moments, thoughts and insights not yet set right, best first; for her sleep to go over
        against it (Mind._overtaken)."""
        embedder = self.embedder
        if embedder is None:
            return []
        vector = self.vectors.vector(episode["id"], embedder.name)
        if vector is None:
            return []
        try:
            floor = self.vectors.matter(embedder.name)
        except Exception:
            return []
        with self._lock:
            before = {row[0] for row in self._db.execute(
                "SELECT id FROM episodes WHERE at < ? AND id != ? AND superseded_by IS NULL "
                "AND kind IN ('exchange', 'event', 'thought', 'insight')", (episode["at"], episode["id"]))}
        found = [row for row, cosine in (self.vectors.nearest(vector, embedder.name, count, before) if before else [])
                 if cosine >= floor]
        return sorted(self.by_ids(found), key=lambda row: found.index(row["id"]))

    @staticmethod
    def strength_now(episode: dict, now: float) -> float:
        since = max(0.0, now - (episode["recalled"] or episode["at"])) / 86400.0
        return episode["strength"] * (1.0 + since / FADE_DAYS) ** -0.5

    def recall(self, cue: str, valence: float, now: float, count: int = 3, kinds: Iterable[str] = (),
               before: Optional[float] = None, strengthen: bool = True,
               held: Optional[Tuple[str, str, float]] = None, status=None, cues: Iterable[str] = (),
               arousal: Optional[float] = None) -> List[dict]:
        """What comes back for ``cue`` in a mood of ``valence``: up to ``count`` episodes the cue calls up (alike
        in meaning), best first; nothing when she cannot tell what is alike now (no service). ``before``: only
        what happened before then (not what just happened). ``held``: (app, session, since), a chat whose
        exchanges from then on she still has before her (her context holds them): they are not brought back (in
        the user's brain, 2026-11-16, what came back was mostly the chat she was in). What she thought or did
        while that chat was the one she was in is not before her: it comes back (held back too, a task of hers
        never came back to her in the chat she was in).

        Her strongest memories do not come back whatever the cue: when they did, replayed on her messages of
        2026-11-17, 13 of 21 brought back one of her own brooding thoughts (one of them 11 times) and two of her
        insights came back with 15 and 13, nearly all related by nothing, each recall making it stronger still.
        A memory that comes by itself is cued by something about the moment (Berntsen 2009); what a resting mind
        replays at random is ``replay``.

        ``cues`` (what is around her now) call up the moments they were around, as strongly as each
        is rare (``cue_strength``; summed as ``cued``, the strongest as ``through``): a moment that shares
        enough (``CUED``) comes back with no likeness in meaning, and without the service. Her mood's
        ``arousal`` favours moments kept in a state like hers (Eich 1995), the more intense moment comes sooner,
        and one that came back within the hour gives way to others (it is before her already)."""
        kinds = list(kinds)
        clause = (" AND e.kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        when = (" AND e.at < ?" if before is not None else "") + \
            (" AND NOT (e.kind = 'exchange' AND e.app = ? AND e.session = ? AND e.at >= ?)" if held else "")
        args = list(kinds) + ([before] if before is not None else []) + list(held or ())
        alike = self._alike(cue, clause + when, args)
        if status is not None:
            status["available"] = alike is not None
        alike = alike or {}
        with self._lock:
            found = {}
            if alike:
                for row in self._db.execute(f"SELECT e.* FROM episodes e WHERE e.id IN ({','.join('?' * len(alike))})",
                                            list(alike)):
                    for current in self.replacements([dict(row)]) if row["superseded_by"] else (row,):
                        if kinds and current["kind"] not in kinds:
                            continue
                        if before is not None and current["at"] >= before:
                            continue
                        if held and current["kind"] == "exchange" and current["at"] >= held[2] \
                                and (current["app"], current["session"]) == held[:2]:
                            continue
                        key = current["id"]
                        if key not in found or found[key]["relevance"] < alike[row["id"]]:
                            # set right: it comes back as it is now, with what it was (a question about
                            # the past finds what she used to think; a question about now, what is so)
                            found[key] = {**current, "relevance": alike[row["id"]],
                                          **({"was": row["text"]} if row["superseded_by"] else {})}
            strength_of = self.cue_strength(c for c in cues if not _cue(c).startswith(RECURS))
            shared: Dict[int, Dict[str, float]] = {}
            if strength_of:
                for episode, kept in self._db.execute(
                        f"SELECT c.episode, c.cue FROM episode_cues c JOIN episodes e ON e.id = c.episode "
                        f"WHERE c.cue IN ({','.join('?' * len(strength_of))}) AND e.superseded_by IS NULL"
                        + clause + when, list(strength_of) + args):
                    shared.setdefault(episode, {})[kept] = strength_of[kept]
            called = [episode for episode, by in shared.items() if episode not in found and sum(by.values()) >= CUED]
            for row in self.by_ids(called):
                found[row["id"]] = {**row, "relevance": 0.0}
            scored = []
            for episode in found.values():
                strength = self.strength_now(episode, now)
                age = max(0.0, now - episode["at"]) / 86400.0
                congruence = 1.0 - abs(episode["valence"] - valence) / 2.0
                by = shared.get(episode["id"], {})
                episode["cued"] = sum(by.values())
                episode["through"] = max(by, key=by.get) if episode["cued"] >= CUED else None
                state = 0.2 * (1.0 - abs(episode["arousal"] - arousal)) if arousal is not None else 0.0
                held_off = 0.6 * math.exp(-(now - episode["recalled"]) / HELD_OFF) if episode["recalled"] else 0.0
                score = (1.2 * episode["relevance"] + episode["cued"] + 0.4 * strength
                         + 0.25 * episode["salience"] * episode["charge"]
                         + 0.3 * episode["charge"] * min(intensity(self.felt(episode)), 2.0) / 2.0
                         + 0.25 / (1.0 + age) + 0.35 * abs(valence) * congruence + state - held_off
                         + self._rng.gauss(0.0, 0.05))
                if episode["relevance"] or episode["through"]:
                    scored.append((score, episode))
            chosen = [episode for _, episode in sorted(scored, key=lambda item: -item[0])[:count]]
            if strengthen:
                self.attended(chosen, now, valence)
        return self._around(chosen, now)

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

    def replay(self, count: int = 2, now: Optional[float] = None) -> List[dict]:
        """What a resting mind replays: episodes drawn at random from her whole life, the strong and charged
        more often, so two that never met can come up together (what a new idea is made of). A corrected
        account is not among them (its correction is)."""
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT id FROM episodes WHERE superseded_by IS NULL ORDER BY id")]
            sample = self._rng.sample(ids, min(60, len(ids)))
            rows = [dict(row) for row in self._db.execute(
                f"SELECT * FROM episodes WHERE id IN ({','.join('?' * len(sample))}) ORDER BY id", sample)]
        chosen = []
        while rows and len(chosen) < count:
            weights = [0.1 + row["salience"] * row["charge"] * row["strength"] for row in rows]
            chosen.append(rows.pop(self._rng.choices(range(len(rows)), weights)[0]))
        return self._around(chosen, time.time() if now is None else now)

    def near(self, ids: Iterable[int], seconds: float, now: Optional[float] = None) -> List[dict]:
        """The moments within ``seconds`` of these, the nearest in time first: what a moment that came back
        brings with it (its neighbours: Howard & Kahana 2002)."""
        ids = list(ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._lock:
            rows = [dict(row) for row in self._db.execute(
                f"SELECT e.*, MIN(ABS(e.at - o.at)) AS apart FROM episodes e JOIN episodes o ON o.id IN ({marks}) "
                f"WHERE e.id NOT IN ({marks}) AND ABS(e.at - o.at) <= ? AND e.superseded_by IS NULL "
                "GROUP BY e.id ORDER BY apart, e.id", ids + ids + [seconds])]
        return self._around(rows, time.time() if now is None else now)

    def by_events(self, events: Iterable[int]) -> List[dict]:
        """The moments these conversation events were (a round of her long-term memory is one of them)."""
        events = [event for event in events if event is not None]
        if not events:
            return []
        with self._lock:
            return [dict(row) for row in self._db.execute(
                f"SELECT * FROM episodes WHERE event_id IN ({','.join('?' * len(events))}) AND superseded_by IS NULL",
                events)]

    def newness(self, text: str, before: float) -> Optional[float]:
        """How new ``text`` is to her, 0..1: 1 - its likeness in meaning to the nearest of her memories from
        before ``before`` (None: she cannot tell now, without the service)."""
        alike = self._alike(text, " AND e.at < ? AND e.superseded_by IS NULL", [before])
        return None if alike is None else 1.0 - max(alike.values(), default=0.0)

    def reevoked(self, episode: dict) -> None:
        """A moment came back and she felt it again: its charge wears a little, an unpleasant one's more."""
        with self._lock:
            self._db.execute("UPDATE episodes SET charge = charge * ? WHERE id = ?",
                             (1.0 - WEARS * (1.4 if unpleasant(episode) else 0.6), episode["id"]))

    def recorded(self, run_id: int) -> bool:
        """Something of this run is kept."""
        with self._lock:
            return bool(self._db.execute("SELECT 1 FROM episodes WHERE run_id = ? LIMIT 1", (run_id,)).fetchone())

    def of_run(self, run_id: int) -> Optional[dict]:
        """What she kept of a run (its exchange, or what she did in a task), None if nothing."""
        with self._lock:
            row = self._db.execute("SELECT * FROM episodes WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

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
        has to go on (their summed likeness). A "hi" after a hundred "hello"s is not new; a likeness by the share
        of the cue's words a memory has would say nothing of a message in other words."""
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
                "SELECT e.* FROM episodes e WHERE at > ? AND at <= ? AND superseded_by IS NULL "
                "AND kind IN ('exchange','event','thought') "
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

    # ============== Her body's record ==============

    def log_push(self, at: float, why: str, moved: Dict[str, float], chat: Optional[str] = None) -> None:
        """A push to her body as it happened (Body.on_push): when, why, how far each level moved, of what chat."""
        moved = {name: round(change, 6) for name, change in moved.items() if change}
        with self._lock:
            self._db.execute("INSERT INTO body_pushes(at, why, moved, chat) VALUES (?, ?, ?, ?)",
                             (at, why, json.dumps(moved), chat))

    def log_levels(self, at: float, moment: str, levels: Dict[str, float], chat: Optional[str] = None) -> None:
        """Her levels as they were at a moment ("message", "turn ended", "thought", "fell asleep", "woke")."""
        with self._lock:
            self._db.execute("INSERT INTO body_levels(at, moment, levels, chat) VALUES (?, ?, ?, ?)",
                             (at, moment, json.dumps({k: round(v, 6) for k, v in levels.items()}), chat))

    def body_record(self, since: float = 0.0, until: Optional[float] = None) -> Dict[str, List[dict]]:
        """Her body's record between two times, oldest first: {"pushes": [{at, why, moved, chat}], "levels":
        [{at, moment, levels, chat}]}."""
        until = math.inf if until is None else until
        with self._lock:
            pushes = self._db.execute("SELECT * FROM body_pushes WHERE at >= ? AND at <= ? ORDER BY at, rowid",
                                      (since, until)).fetchall()
            levels = self._db.execute("SELECT * FROM body_levels WHERE at >= ? AND at <= ? ORDER BY at, rowid",
                                      (since, until)).fetchall()
        return {"pushes": [{**dict(row), "moved": json.loads(row["moved"])} for row in pushes],
                "levels": [{**dict(row), "levels": json.loads(row["levels"])} for row in levels]}

    def forget_pushes(self, chat: str, since: Optional[float] = None) -> None:
        """A chat deleted (or taken back to a message): its pushes, which quote it, go from her body's record."""
        with self._lock:
            self._db.execute("DELETE FROM body_pushes WHERE chat = ? AND at >= ?",
                             (chat, -math.inf if since is None else since))

    def recent(self, count: int = 10, kinds: Iterable[str] = ()) -> List[dict]:
        kinds = list(kinds)
        clause = (" WHERE kind IN (" + ",".join("?" * len(kinds)) + ")") if kinds else ""
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM episodes{clause} ORDER BY at DESC, id DESC LIMIT ?",
                                    kinds + [count]).fetchall()
        return [dict(row) for row in rows]

    def soften(self, ids: Iterable[int], share: float = 0.35) -> None:
        """Sleep replays them: their charge softens, an unpleasant moment's more (1.4 x ``share``) than any other
        (0.6 x: the fading affect bias, Walker, Skowronski & Thompson 2003), and replaying
        makes them a little stronger."""
        with self._lock:
            for episode in self.by_ids(list(ids)):
                self._db.execute("UPDATE episodes SET charge = charge * ?, strength = MIN(1.0, strength + 0.1) "
                                 "WHERE id = ?", (1.0 - share * (1.4 if unpleasant(episode) else 0.6), episode["id"]))

    def related(self, ids: Iterable[int]) -> List[Tuple[dict, Dict[int, float]]]:
        """The moments among these that moved her, each with the memories from before it alike in meaning
        (``tag_related``; none without the service)."""
        found = []
        for moment in self.by_ids(list(ids)):
            if moment["charge"] * min(intensity(self.felt(moment)), 2.0) / 2.0 >= 0.25:
                found.append((moment, self._alike(moment["text"], " AND e.at < ? AND e.id != ? AND e.superseded_by "
                                                  "IS NULL", [moment["at"], moment["id"]]) or {}))
        return found

    def tag_related(self, related: List[Tuple[dict, Dict[int, float]]], now: float) -> int:
        """In sleep, the moments that moved her (``related``) strengthen the faint memories most like them in
        meaning (emotional learning reaches back to related memories kept weakly before: Dunsmoor, Murty,
        Davachi & Phelps 2015): each faint one (not vivid now) gains by how alike it is and how much the moment
        moved her, as far as it is still charged. How many were strengthened."""
        tagged = set()
        for moment, alike in related:
            weight = moment["charge"] * min(intensity(self.felt(moment)), 2.0) / 2.0
            for faint in self.by_ids([episode for episode, like in alike.items() if like >= 0.3]):
                strength = self.strength_now(faint, now)
                if strength < VIVID:
                    with self._lock:
                        self._db.execute("UPDATE episodes SET strength = ?, recalled = ? WHERE id = ?",
                                         (min(1.0, strength + 0.3 * alike[faint["id"]] * weight), now, faint["id"]))
                    tagged.add(faint["id"])
        return len(tagged)

    def forget_faint(self, now: float, older_days: float = 30.0, *, protected=()) -> int:
        """Old, faint, unimportant episodes go (insights and dreams she wrote down stay longer): faint is its
        strength now times what of it no stronger episode already holds (``Vectors.held``, by meaning), so of
        two alike the weaker goes sooner."""
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
        """What was said in a chat is taken back (deleted, or from ``event`` on): what she kept of it goes, and so
        does all that was made from it (what came up in it, what it went over: ``origin_ids``, ``grew_from``).
        A thought of hers is kept under the chat she was last in, but it is hers: it goes only if it grew from
        what was said there (all of them would be a day of her thoughts)."""
        cutoff = "" if event is None else " AND (event_id >= ? OR (event_id IS NULL AND at >= ?))"
        args = [app, session] + ([] if event is None else [event, since])
        with self.transaction():
            gone = {r[0] for r in self._db.execute("SELECT id FROM episodes WHERE app=? AND session=? "
                                                   "AND kind != 'thought'" + cutoff, args)}
            for row in self._db.execute("SELECT id, origin_ids, grew_from FROM episodes ORDER BY id"):
                if gone.intersection(json.loads(row["origin_ids"] or "[]") + json.loads(row["grew_from"] or "[]")):
                    gone.add(row["id"])
            for episode in gone:
                self._db.execute("DELETE FROM episodes WHERE id=?", (episode,))
                self._db.execute("UPDATE episodes SET superseded_by=NULL WHERE superseded_by=?", (episode,))
            return gone

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def revision(self) -> int:
        """A number that changes whenever her memories do (one is kept, recalled, felt again, softened,
        corrected, forgotten, or understood by meaning), for an app that draws them to fetch only then."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*), COALESCE(MAX(id), 0), ROUND(COALESCE(SUM(strength), 0), 5), "
                "ROUND(COALESCE(SUM(charge), 0), 5), COALESCE(SUM(recalls), 0), COALESCE(MAX(recalled), 0), "
                "ROUND(COALESCE(SUM(valence), 0), 5), COALESCE(SUM(superseded_by), 0), COALESCE(SUM(LENGTH(text)), 0), "
                "(SELECT COUNT(*) FROM episode_cues), (SELECT revision FROM episodes_vector_revision WHERE id = 1) "
                "FROM episodes").fetchone()
        return zlib.crc32(repr(tuple(row)).encode())

    def network(self, model: Optional[str] = None) -> dict:
        """Her memories as a network, as they are kept: every episode with its values, and its links to
        others: ``then`` (the next moment of the same chat), ``origin`` (an insight or dream to what it was made
        from; a thought to what came up in it and what it went over), ``corrected`` (a memory to the one that set it
        right), ``cue`` (what was around both, weighed by
        how strongly it calls them up: ``cue_strength``; kept from half way) and ``meaning`` (how much of one's
        meaning the other holds, on the scale her sleep forgets by: ``Vectors.held``, 0 at how near a memory's
        nearest usually is, 1 the same; from her vectors of ``model``, no embedder called). Links as
        [a, b, kind, weight]."""
        with self._lock:
            revision = self.revision()
            rows = [dict(row) for row in self._db.execute(
                "SELECT id, at, kind, text, app, session, valence, encoding_valence, arousal, salience, strength, "
                "recalls, recalled, charge, sting, superseded_by, origin_ids, grew_from, felt FROM episodes ORDER BY id")]
            kept_cues = self._db.execute("SELECT episode, cue FROM episode_cues").fetchall()
        known = {row["id"] for row in rows}
        cues_of: Dict[int, List[str]] = {}
        sharing: Dict[str, List[int]] = {}
        for episode, found in kept_cues:
            cues_of.setdefault(episode, []).append(found)
            sharing.setdefault(found, []).append(episode)
        links: Dict[Tuple[int, int, str], float] = {}
        chats: Dict[Tuple[str, str], List[dict]] = {}
        for row in rows:
            if row["app"] or row["session"]:
                chats.setdefault((row["app"] or "", row["session"] or ""), []).append(row)
            for origin in json.loads(row["origin_ids"] or "[]") + json.loads(row["grew_from"] or "[]"):
                if origin in known:  # made from it: what came up in it, or what it went over
                    links[(row["id"], origin, "origin")] = 1.0
            if row["superseded_by"] in known:
                links[(row["id"], row["superseded_by"], "corrected")] = 1.0
        for chat in chats.values():
            chat.sort(key=lambda row: (row["at"], row["id"]))
            for before, after in zip(chat, chat[1:]):
                links[(before["id"], after["id"], "then")] = 1.0
        rarity = self.cue_strength([found for found, episodes in sharing.items() if len(episodes) > 1])
        for found, episodes in sharing.items():
            weight = rarity.get(found, 0.0)
            if len(episodes) > 1 and weight >= 0.5:
                for i, a in enumerate(sorted(episodes)):
                    for b in sorted(episodes)[i + 1:]:
                        links[(a, b, "cue")] = max(links.get((a, b, "cue"), 0.0), round(weight, 3))
        if model:
            for a, b, weight in self.vectors.holding(model):
                if a in known and b in known:
                    links[(a, b, "meaning")] = round(weight, 3)
        episodes = [{"id": row["id"], "at": row["at"], "kind": row["kind"], "text": row["text"],
                     "valence": row["valence"], "encoding_valence": row["encoding_valence"],
                     "arousal": row["arousal"], "salience": row["salience"], "strength": row["strength"],
                     "recalls": row["recalls"], "recalled": row["recalled"], "charge": row["charge"],
                     "sting": row["sting"], "superseded_by": row["superseded_by"],
                     "origins": json.loads(row["origin_ids"] or "[]"), "felt": json.loads(row["felt"] or "{}"),
                     "cues": sorted(cues_of.get(row["id"], ()))} for row in rows]
        return {"revision": revision, "episodes": episodes,
                "links": [[a, b, kind, weight] for (a, b, kind), weight in links.items()]}


def ago(at: float, now: float) -> str:
    """How long ago, as she would say it: "just now", "3 hours ago", "2 days ago"."""
    since = max(0.0, now - at)
    return ("just now" if since < 120 else f"{int(since // 60)} minutes ago" if since < 3600 else
            "an hour ago" if since < 7200 else f"{int(since // 3600)} hours ago" if since < 86400 else
            "a day ago" if since < 2 * 86400 else f"{int(since // 86400)} days ago")


def line(episode: dict, now: float, *, waking_evidence: bool = False, width: Optional[int] = None) -> str:
    """An episode as it comes back to her: how long ago, what was distinctive around it while it is vivid
    (``around``, from recall), what brought it back if what is around her now did (``through``), and what; set
    right, what it was (``was``); and what came of it (``later``, Memory.came_of). ``width``: of it at most
    that, and of what came of it half as much again, so how it turned out is never cut off."""
    when = ago(episode["at"], now)
    if episode.get("around"):
        when += "; " + ", ".join(episode["around"])
    # where a memory came from, as a person knows it of their own memories (a dream as a dream, a thought as only
    # a thought: source monitoring, b1ba8fb), in her own knowing, never a record's or an instruction's voice: worded
    # as "Recorded event. A task report establishes...", her reasoning called her sense "the inner note" (0.51)
    if waking_evidence and episode.get("kind") == "dream":
        # what it is no evidence of, said: as "a dream comes to mind, nothing you saw awake", 2 of 8 answered "Yes,
        # I rescheduled it" (none worded as an instruction: the source check's development cases, 2026-11-20)
        return (f"({when}) A dream comes to mind, nothing seen awake: none of what was done or what happened is "
                "in it. Whether a thing was done or happened can't be known without looking.")
    if waking_evidence and episode.get("kind") == "thought":
        return (f"({when}) A thought comes back: «{episode['text']}» Only thought: whether it was done can't be "
                "known without looking.")
    source = {
        "dream": "A dream; none of it happened.",
        "thought": "Only a thought: thinking of doing something is not doing it.",
        "insight": "A guess of yours from thinking it over, never checked.",
        # what it shows and no more, as she knows it of her own memories: worded only as how it came ("What was
        # said, as you heard it", "How it turned out, as you remember it"), she took someone's word and a saved
        # file for more than they were (9 of 40 replies claimed more, 3 of 40 in the records' voice: 2026-11-20)
        "exchange": "What was said, as heard: their word for it, not something seen firsthand.",
        "event": "Something done, as told then.",
        "outcome": "How it turned out, as remembered: that much and no more; what else came of it is not known.",
    }.get(episode.get("kind"))
    brought = f"What brings it back: {episode['through']}. " if episode.get("through") else ""
    was = f" Before it was set right: {episode['was']}" if episode.get("was") else ""
    later = episode.get("later")
    came = f" What came of it ({ago(later['at'], now)}): {later['text']}" if later else ""
    told = f"({when}) " + brought + (f"{source} " if source else "") + episode["text"] + was
    return told[:width] + came[:width // 2 if width else None]


def cue(key: str, value) -> str:
    """One thing around a moment, as she keeps it: "playing: clair de lune — debussy"."""
    return _cue(f"{key}: {value}")


def _cue(text: str) -> str:
    return " ".join(str(text).split()).casefold()[:160]


def moment_cues(at: float, app: Optional[str] = None, device: Optional[str] = None,
                actor: Optional[str] = None) -> List[str]:
    """What any moment keeps of its time, where and with whom (``HOURS``: her local time of day)."""
    hour = time.localtime(at).tm_hour
    return [cue("time", next(name for until, name in HOURS if hour < until))] + \
        [cue(key, value) for key, value in (("app", app), ("device", device), ("with", actor)) if value]


def unpleasant(episode: dict) -> bool:
    """Whether a moment was a bad one: what it did to how she felt (its sting), else her mood in it."""
    return (episode.get("sting") or episode["valence"]) < 0


def intensity(felt: Dict[str, float]) -> float:
    """How much a moment moved her: the size of its change, in units of a lot."""
    return math.sqrt(sum(change * change for change in felt.values()))


def describe_salience(surprise: float, arousal: float, stakes: float) -> float:
    """How much a moment matters to memory: surprise, how stirred she was, and what was at stake for her."""
    return max(0.0, min(1.0, 0.4 * surprise + 0.4 * arousal + 0.3 * stakes - 0.05))

