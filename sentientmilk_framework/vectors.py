"""Vectors kept beside the rows of a SQLite table (``<table>_vectors``: id, model, vector), searched by cosine.

Brute force over a matrix kept in memory per model, reloaded when the table changes: at her size (thousands
of units) a search is a millisecond. shortcut: brute force; move to sqlite-vec past ~500k units, when a
search passes 20 ms.

What counts as related is measured on her own vectors with the model's own queries, so it means the same
whatever the model: the floor is the most that any of 20 everyday questions her past cannot answer reaches
among them (CALIBRATION), and a cosine maps to 0..1 above it; measured again when their number has doubled.
Measured on her history (spec, "Measured"): with it, every model brought the right chat back and nothing for
unrelated questions; a floor from random pairs of her own vectors (before) sat above many right hits, as a
query lands lower than a document of the same thing (models embed the two apart).

Two rows are compared with each other (``held``: how much of a memory's meaning another already holds, for
forgetting in her sleep) against how near her memories' nearest ones usually are (``usual``), not against a
query. Measured on her history (2026-11-17): against what two random ones share (95th percentile) a memory
about the same subject counted half held, and 30 of her 132 episodes would have gone a month on instead of
none; against the usual nearest only what is more alike than that counts (13, small talk said twice).
"""

import sqlite3
import threading
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

CALIBRATION = ("What is the boiling point of water at high altitude?", "How many legs does a spider have?",
               "Who painted the Mona Lisa?", "What is the chemical symbol for gold?",
               "How far is the moon from the earth?", "What language is spoken in Brazil?",
               "How do I fold a fitted sheet?", "What year did the Berlin wall fall?",
               "How many players are on a basketball team?", "What is photosynthesis?",
               "Which planet has the most moons?", "How do I remove a red wine stain?",
               "What is the speed of sound?", "Who wrote Pride and Prejudice?", "How do hurricanes form?",
               "What is the largest ocean?", "How do I grow basil indoors?", "What is a haiku?",
               "How many bones are in the human body?", "What does a sommelier do?")
# two wordings of one thing (a query, then a kept text): what "the same" reaches by a model, as CALIBRATION is what
# "unrelated" does (voyage-4-large, 2026-11-18: a median of 0.62, the lowest 0.48; unrelated pairs 0.18, at most 0.39)
SAME = (("turn off the lights", "switch the lights off"), ("deleting old files", "removing old files"),
        ("the phone on silent at night", "my phone muted overnight"), ("being late to work", "arriving late at the office"),
        ("forgetting her birthday", "not remembering her birthday"),
        ("a car crash on the highway", "a road accident on the motorway"), ("losing my keys", "misplacing my keys"),
        ("the dog barking at night", "the dog barks during the night"), ("a cold shower", "showering in cold water"),
        ("missing the train", "the train left without me"), ("shouting at a friend", "yelling at a friend"),
        ("a burnt dinner", "dinner got burned"))


class Vectors:
    def __init__(self, db: sqlite3.Connection, table: str, lock: threading.RLock):
        self.db, self.table, self.lock = db, table, lock
        self._matrices: Dict[str, Tuple[tuple, np.ndarray, np.ndarray]] = {}  # model -> (version, ids, rows)
        self._floors: Dict[str, Tuple[int, float]] = {}  # model -> (count when measured, floor)
        self._usuals: Dict[str, Tuple[int, float]] = {}  # model -> (count when measured, usual nearest)
        self._sames: Dict[str, Tuple[float, float]] = {}  # model -> (what one thing reaches, what unrelated does)
        self._matters: Dict[str, Tuple[int, float]] = {}  # model -> (count when measured, what one matter reaches)
        with lock:
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS {table}_vectors (id INTEGER PRIMARY KEY, model TEXT NOT NULL,
                                                             vector BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS {table}_vector_revision (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO {table}_vector_revision VALUES(1,0);
                CREATE TRIGGER IF NOT EXISTS {table}_vector_insert AFTER INSERT ON {table}_vectors BEGIN
                    UPDATE {table}_vector_revision SET revision=revision+1 WHERE id=1; END;
                CREATE TRIGGER IF NOT EXISTS {table}_vector_delete AFTER DELETE ON {table}_vectors BEGIN
                    UPDATE {table}_vector_revision SET revision=revision+1 WHERE id=1; END;
                CREATE INDEX IF NOT EXISTS {table}_vectors_model ON {table}_vectors (model);
                CREATE TRIGGER IF NOT EXISTS {table}_vector_gone AFTER DELETE ON {table} BEGIN
                    DELETE FROM {table}_vectors WHERE id = old.id; END;
                CREATE TRIGGER IF NOT EXISTS {table}_vector_stale AFTER UPDATE OF text ON {table} BEGIN
                    DELETE FROM {table}_vectors WHERE id = old.id; END;
            """)

    def put(self, rows: List[Tuple[int, np.ndarray]], model: str) -> None:
        with self.lock:
            self.db.executemany(f"INSERT OR REPLACE INTO {self.table}_vectors (id, model, vector) VALUES (?, ?, ?)",
                                [(int(i), model, np.asarray(v, np.float32).tobytes()) for i, v in rows])

    def drop(self, ids: Iterable[int] = (), other_than: str = "") -> None:
        """These rows' vectors; or ``other_than``: every vector not of that model."""
        with self.lock:
            if other_than:
                self.db.execute(f"DELETE FROM {self.table}_vectors WHERE model != ?", (other_than,))
            self.db.executemany(f"DELETE FROM {self.table}_vectors WHERE id = ?", [(int(i),) for i in ids])

    def pending(self, model: str, limit: int) -> List[int]:
        """Rows of the table without a vector of ``model``, the newest first."""
        with self.lock:
            return [row[0] for row in self.db.execute(
                f"SELECT t.id FROM {self.table} t LEFT JOIN {self.table}_vectors v ON v.id = t.id AND v.model = ? "
                "WHERE v.id IS NULL ORDER BY t.id DESC LIMIT ?", (model, limit))]

    def texts(self, ids: List[int]) -> List[Tuple[int, str]]:
        """The ``text`` of these rows of the table (those still there)."""
        with self.lock:
            return [(row[0], row[1]) for row in self.db.execute(
                f"SELECT id, text FROM {self.table} WHERE id IN ({','.join('?' * len(ids))})", list(ids))]

    def count(self, model: str) -> int:
        with self.lock:
            return self.db.execute(f"SELECT COUNT(*) FROM {self.table}_vectors WHERE model = ?", (model,)).fetchone()[0]

    def _matrix(self, model: str) -> Tuple[np.ndarray, np.ndarray]:
        with self.lock:
            version = self.db.execute(f"SELECT revision FROM {self.table}_vector_revision WHERE id=1").fetchone()
            kept = self._matrices.get(model)
            if kept and kept[0] == tuple(version):
                return kept[1], kept[2]
            found = self.db.execute(f"SELECT id, vector FROM {self.table}_vectors WHERE model = ?", (model,)).fetchall()
        ids = np.array([row[0] for row in found], dtype=np.int64)
        rows = np.stack([np.frombuffer(row[1], np.float32) for row in found]) if found else np.zeros((0, 1), np.float32)
        self._matrices[model] = (tuple(version), ids, rows)
        return ids, rows

    def nearest(self, query: np.ndarray, model: str, count: int,
                where: Optional[Set[int]] = None) -> List[Tuple[int, float]]:
        """The ``count`` rows nearest ``query`` (a unit vector of ``model``), best first, as (id, cosine);
        ``where``: only these rows."""
        ids, rows = self._matrix(model)
        if not len(ids) or rows.shape[1] != len(query):
            return []
        scores = rows @ np.asarray(query, np.float32)
        if where is not None:
            scores = np.where(np.isin(ids, np.fromiter(where, np.int64, len(where))), scores, -np.inf)
        top = np.argsort(-scores)[:count]
        return [(int(ids[i]), float(scores[i])) for i in top if np.isfinite(scores[i])]

    def vector(self, row: int, model: str) -> Optional[np.ndarray]:
        """The vector a row keeps for ``model`` (None: none)."""
        ids, rows = self._matrix(model)
        found = np.flatnonzero(ids == row)
        return rows[found[0]] if len(found) else None

    def matter(self, model: str) -> float:
        """What two rows about one matter reach: the closest 3 in 100 of all pairs of these rows (on her memories,
        voyage-4-large, 2026-11-18: from 0.59; the milk she buys and its correction 0.77, an essay skeleton and its
        deletion 0.63, a question about a watcher and "forget that thing" 0.64; an unrelated pair 0.38 in the
        middle). Measured again when their number has doubled; 1.0 (nothing is one matter) under ten rows: a few
        rows tell nothing of what is usual among them."""
        ids, rows = self._matrix(model)
        measured = self._matters.get(model)
        if measured and len(ids) < 2 * measured[0]:
            return measured[1]
        if len(ids) < 10:
            return 1.0
        sample = rows if len(ids) <= 1024 else rows[np.random.default_rng(0).choice(len(ids), 1024, replace=False)]
        value = float(np.quantile((sample @ sample.T)[np.triu_indices(len(sample), 1)], 0.97))
        self._matters[model] = (len(ids), value)
        return value

    def holding(self, model: str, block: int = 512) -> List[Tuple[int, int, float]]:
        """Every pair of rows where one holds some of the other's meaning, on ``held``'s scale: (a, b, how
        much) with a < b, 0 at ``usual`` (how near a row's nearest usually is), 1 the same. In blocks, so
        thousands of rows never need all their cosines at once."""
        ids, rows = self._matrix(model)
        found: List[Tuple[int, int, float]] = []
        if len(ids) < 2:
            return found
        floor = self.usual(model)
        for start in range(0, len(ids), block):
            cosines = rows[start:start + block] @ rows.T
            for i, j in zip(*np.nonzero(cosines > floor)):
                a, b = int(ids[start + i]), int(ids[j])
                if a < b:
                    found.append((a, b, float(min(1.0, (cosines[i, j] - floor) / (1.0 - floor)))))
        return found

    def floor(self, embedder) -> float:
        """The most an unrelated question reaches among these vectors of ``embedder``'s (1.0: none yet).
        It raises what the embedder raises when it cannot embed the questions now."""
        ids, rows = self._matrix(embedder.name)
        if not len(ids):
            return 1.0
        measured = self._floors.get(embedder.name)
        if measured and len(ids) < 2 * measured[0]:
            return measured[1]
        questions = embedder.embed(list(CALIBRATION), query=True)
        if questions.shape[1] != rows.shape[1]:
            return 1.0
        value = float(min(0.95, (questions @ rows.T).max()))
        self._floors[embedder.name] = (len(ids), value)
        return value

    def _reach(self, embedder) -> Tuple[float, float]:
        """What two wordings of one thing reach on ``embedder`` (the median of SAME's pairs) and what unrelated
        questions reach (CALIBRATION asked against SAME's kept wordings: 9 in 10 stay below), measured once; it
        calls the embedder: never under a lock. Both are the embedder's, whatever is kept: the most an unrelated
        question reached among her learned cues rose with every cue (a cleanup cue met "How do I remove a red wine
        stain?"), and a request 0.37 alike to what she had learned to fear that morning called up nothing by the
        afternoon (the exam, 2026-11-18)."""
        if embedder.name not in self._sames:
            kept = np.asarray(embedder.embed([text for _, text in SAME]))
            pairs = np.sum(np.asarray(embedder.embed([asked for asked, _ in SAME], query=True)) * kept, axis=1)
            unrelated = np.asarray(embedder.embed(list(CALIBRATION), query=True)) @ kept.T
            self._sames[embedder.name] = (float(np.median(pairs)), float(np.quantile(unrelated, 0.9)))
        return self._sames[embedder.name]

    def same(self, embedder) -> float:
        """What two wordings of one thing reach on ``embedder`` (voyage-4-large: 0.62), above what unrelated
        things reach. It calls the embedder: never under a lock."""
        same, unrelated = self._reach(embedder)
        return max(same, unrelated + 0.1)

    def unrelated(self, embedder) -> float:
        """What unrelated things reach on ``embedder`` (voyage-4-large: 0.19); below it, nothing alike."""
        return self._reach(embedder)[1]

    def relevance(self, cosine: float, embedder) -> float:
        """How related, 0..1: 0 at or under what an unrelated question reaches."""
        floor = self.floor(embedder)
        return max(0.0, min(1.0, (cosine - floor) / (1.0 - floor)))

    def usual(self, model: str) -> float:
        """How near these rows' nearest ones usually are: the median of each row's cosine to its nearest
        (at most 0.95; measured again when their number has doubled)."""
        ids, rows = self._matrix(model)
        measured = self._usuals.get(model)
        if measured and len(ids) < 2 * measured[0]:
            return measured[1]
        nearest = []
        for start in range(0, len(ids), 512):  # a block at a time: 512 x all of them
            cosines = rows[start:start + 512] @ rows.T
            cosines[np.arange(len(cosines)), np.arange(start, start + len(cosines))] = -np.inf
            nearest.extend(cosines.max(axis=1))
        value = float(min(0.95, np.median(nearest))) if len(ids) > 1 else 0.95
        self._usuals[model] = (len(ids), value)
        return value

    def held(self, need: Dict[int, float], model: str) -> Dict[int, float]:
        """For each row in ``need`` (id -> how much she may need it): how much of its meaning a row she needs
        more already holds, 0..1 (the nearest such row's cosine, above ``usual``); a row not in ``need`` is
        kept whatever happens and holds what is near it. A row without a vector of ``model`` holds nothing
        and is held by nothing (0)."""
        ids, rows = self._matrix(model)
        held = dict.fromkeys(need, 0.0)
        position = {int(row_id): n for n, row_id in enumerate(ids)}
        mine = [row_id for row_id in need if row_id in position]
        if len(ids) < 2 or not mine:
            return held
        floor = self.usual(model)
        needs = np.array([need.get(int(row_id), np.inf) for row_id in ids])
        for start in range(0, len(mine), 512):  # a block at a time: 512 x all of them
            block = mine[start:start + 512]
            index = np.array([position[row_id] for row_id in block])
            cosines = rows[index] @ rows.T
            own = needs[index][:, None]
            # who may hold it: one needed more, or as much and newer (so of two alike, one stays)
            more = (needs[None, :] > own) | ((needs[None, :] == own) & (ids[None, :] > ids[index][:, None]))
            best = np.where(more, cosines, -np.inf).max(axis=1)
            for row_id, cosine in zip(block, best):
                if np.isfinite(cosine):
                    held[row_id] = float(max(0.0, min(1.0, (cosine - floor) / (1.0 - floor))))
        return held
