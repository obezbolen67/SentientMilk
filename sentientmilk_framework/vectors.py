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


class Vectors:
    def __init__(self, db: sqlite3.Connection, table: str, lock: threading.RLock):
        self.db, self.table, self.lock = db, table, lock
        self._matrices: Dict[str, Tuple[tuple, np.ndarray, np.ndarray]] = {}  # model -> (version, ids, rows)
        self._floors: Dict[str, Tuple[int, float]] = {}  # model -> (count when measured, floor)
        with lock:
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS {table}_vectors (id INTEGER PRIMARY KEY, model TEXT NOT NULL,
                                                             vector BLOB NOT NULL);
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
            version = self.db.execute(f"SELECT COUNT(*), TOTAL(id), MAX(rowid) FROM {self.table}_vectors "
                                      "WHERE model = ?", (model,)).fetchone()
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

    def relevance(self, cosine: float, embedder) -> float:
        """How related, 0..1: 0 at or under what an unrelated question reaches."""
        floor = self.floor(embedder)
        return max(0.0, min(1.0, (cosine - floor) / (1.0 - floor)))
