"""Her long-term memory (docs/superpowers/specs/2026-11-17-long-term-memory-design.md).

Short-term memory is her context window: the chat she is in, after its last compaction. Long-term memory is
everything else, kept here as units found by meaning and by words: each round of every past chat (a user
message and her replies), journal notes and lasting facts; her episodes' vectors her mind keeps beside them
in mind.sqlite3 (mind/memory.py), filled from here. Before this (0.29) all of it was found only by shared
words: "that game idea" did not find "a pixel-art platformer".

A search fuses the nearest by meaning (embeddings.py, vectors.py) with the best by words (FTS5): reciprocal
rank fusion, 1 / (60 + rank) from each list (Cormack et al. 2009), so exact names, paths and numbers rank
higher. What comes back is what is related by meaning (vectors.relevance); words decide it only when
meaning cannot (no embedder, the service down): measured on her history, words let something back for 17 of
20 questions her past could not answer, meaning for none.

The index is made from the brain's own records and can be deleted and made again; journal notes are the
exception, they stay here after the journal keeps only its newest. A sweep after every turn and every 30 s
takes in what is new and embeds what has no vector of the current model; deleting a chat and returning to a
message take their units out at once.

Each turn the user writes, what comes back (``note``) goes into that turn's input beside her inner note
(runs.py), so the log stays as it was sent: the prompt cache, replay and a return to a message see the same.
"""

import logging
import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import embeddings, mentions
from .mind.memory import line
from .vectors import Vectors

logger = logging.getLogger(__name__)

CHUNK, STEP = 1600, 1400  # characters: a unit, and where the next begins (200 overlap)
CANDIDATES = 40  # from each list, before fusing
RRF_K = 60
LEXICAL_ADMIT = 0.5  # the share of a query's words a unit has (rarer ones weigh more): from here words count
# words that say nothing of what a message is about (bm25 on a young index made "was" a strong match)
STOP = frozenset("""the and was were what that this these those you your yours they them their she her hers his him
its our ours for are with have has had not but can could did does doing done from who why how when where which
will would there here about been just like into than then also some any all get got one out yes now well very
really too more most much many let lets okay sure please thanks thank want wanted know think said say""".split())
SHOWN, SHOWN_CHARS = 5, 400  # what comes back in a turn: the tools reach the rest
SWEEP_EVERY = 30.0
BATCH = 32
HELPERS = ("task-", "agent-", "summary-")  # sessions that are not conversations of hers
HEADER = "FROM YOUR LONG-TERM MEMORY (past chats that come back for this message; they may be out of date):"
WORDS = re.compile(r"[^\W_]{3,}", re.UNICODE)
SETTINGS = ("embeddings", "embeddings_base_url", "embeddings_api_key", "embeddings_model", "embeddings_dimensions",
            "base_url", "api_key")


def chunks(text: str) -> List[str]:
    """``text`` in pieces of CHUNK characters, each beginning STEP after the last: all of it, however long."""
    pieces, start = [], 0
    while True:
        pieces.append(text[start:start + CHUNK])
        if start + CHUNK >= len(text):
            return pieces
        start += STEP


def _base(ref: str) -> str:
    return ref.rsplit("#", 1)[0]


class Recall:
    def __init__(self, brain, path: Path):
        self.brain = brain
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._sweeping = threading.Lock()
        with self._lock:
            self._db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS units (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL, app TEXT NOT NULL,
                    session TEXT NOT NULL, at REAL NOT NULL, text TEXT NOT NULL, UNIQUE (source, ref));
                CREATE INDEX IF NOT EXISTS units_chat ON units (app, session, at);
                CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(text, content='units', content_rowid='id');
                CREATE VIRTUAL TABLE IF NOT EXISTS units_terms USING fts5vocab(units_fts, 'row');
                CREATE TRIGGER IF NOT EXISTS unit_added AFTER INSERT ON units BEGIN
                    INSERT INTO units_fts(rowid, text) VALUES (new.id, new.text); END;
                CREATE TRIGGER IF NOT EXISTS unit_gone AFTER DELETE ON units BEGIN
                    INSERT INTO units_fts(units_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
                CREATE TABLE IF NOT EXISTS marks (app TEXT NOT NULL, session TEXT NOT NULL,
                                                  last_event INTEGER NOT NULL, PRIMARY KEY (app, session));
            """)
        self.vectors = Vectors(self._db, "units", self._lock)
        self.embedder: Optional[embeddings.Embedder] = None
        self._settings: Optional[tuple] = None
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.refresh()

    # ============== Settings and life ==============

    def refresh(self) -> Optional[embeddings.Embedder]:
        """Her embedder as the settings say now (remade when they change; her mind's memory uses it too)."""
        values = self.brain.config.values()
        settings = tuple(values.get(key) for key in SETTINGS)
        if settings != self._settings:
            self._settings, self.embedder = settings, embeddings.make(values)
            mind = getattr(self.brain, "mind", None)
            if mind is not None:
                mind.memory.embedder = self.embedder
            self._wake.set()
        return self.embedder

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="recall", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def wake(self) -> None:
        """Something new may be there (a turn ended): take it in now."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception:
                logger.exception("Her long-term memory could not take in what is new")
            self._wake.wait(SWEEP_EVERY)
            self._wake.clear()

    def status(self) -> dict:
        embedder = self.refresh()
        with self._lock:
            units = self._db.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        embedded = self.vectors.count(embedder.name) if embedder else 0
        state = "off" if embedder is None else embedder.problem() or ("ready" if embedded >= units else "taking in")
        return {"embeddings": self.brain.config.values()["embeddings"], "model": getattr(embedder, "model", None),
                "state": state, "units": units, "embedded": embedded,
                "spent": round(getattr(embedder, "spent", 0.0), 4)}

    # ============== Units ==============

    def add(self, source: str, ref: str, app: str, session: str, at: float, text: str) -> List[int]:
        """``text`` as the units of ``(source, ref)``, in place of what was there."""
        text = " ".join(str(text).split())
        with self._lock:
            self._remove_refs(source, [ref])
            return [self._db.execute("INSERT INTO units (source, ref, app, session, at, text) VALUES (?, ?, ?, ?, ?, ?)",
                                     (source, f"{ref}#{n}", app, session, at, piece)).lastrowid
                    for n, piece in enumerate(chunks(text))]

    def _remove_refs(self, source: str, refs: Iterable[str]) -> None:
        for ref in refs:
            self._db.execute("DELETE FROM units WHERE source = ? AND substr(ref, 1, ?) = ?",
                             (source, len(ref) + 1, f"{ref}#"))

    def remove(self, source: str, refs: Iterable[str] = (), app: str = "", session: str = "",
               since: float = 0.0) -> None:
        """Units of ``source``: those of ``refs``, or of a chat from ``since`` on."""
        with self._lock:
            self._remove_refs(source, refs)
            if app:
                self._db.execute("DELETE FROM units WHERE source = ? AND app = ? AND session = ? AND at >= ?",
                                 (source, app, session, since))

    def forget_session(self, app: str, session: str) -> None:
        """The user deleted a chat: nothing of it comes back."""
        with self._lock:
            self._db.execute("DELETE FROM units WHERE app = ? AND session = ?", (app, session))
            self._db.execute("DELETE FROM marks WHERE app = ? AND session = ?", (app, session))

    def forget_from(self, app: str, session: str, event: int) -> None:
        """A return to a message undid everything from ``event`` on: its rounds go."""
        with self._lock:
            self._db.execute("DELETE FROM units WHERE source = 'turn' AND app = ? AND session = ? "
                             "AND CAST(substr(ref, 1, instr(ref, '#') - 1) AS INTEGER) >= ?", (app, session, event))
            self._db.execute("UPDATE marks SET last_event = MIN(last_event, ?) WHERE app = ? AND session = ?",
                             (event - 1, app, session))

    # ============== Finding ==============

    def search(self, query: str, count: int = SHOWN, sources: Tuple[str, ...] = ("turn", "note"),
               held: Optional[Tuple[str, str, float]] = None, after: Optional[float] = None,
               before: Optional[float] = None, app: Optional[str] = None) -> List[dict]:
        """What is about ``query``, best first: dicts with the unit's ``source``, ``ref``, ``app``,
        ``session``, ``at``, ``text`` and ``relevance`` (by meaning, 0..1), ``lexical`` (by words, 0..1),
        ``score`` (fused). ``held``: (app, session, since), a chat whose units from then on she has before
        her (her context), left out. One unit a round or note (its best chunk)."""
        embedder = self.refresh()
        where, args = [f"source IN ({','.join('?' * len(sources))})"], list(sources)
        for clause, value in (("app = ?", app), ("at >= ?", after), ("at < ?", before)):
            if value is not None:
                where.append(clause)
                args.append(value)
        if held:
            where.append("NOT (app = ? AND session = ? AND at >= ?)")
            args += list(held)
        clause = " AND ".join(where)
        words = [w for w in dict.fromkeys(word.lower() for word in WORDS.findall(query or "")) if w not in STOP][:24]
        with self._lock:
            allowed = {row[0] for row in self._db.execute(f"SELECT id FROM units WHERE {clause}", args)}
            candidates = self._db.execute(
                "SELECT u.id, u.text FROM units_fts JOIN units u ON u.id = units_fts.rowid "
                f"WHERE units_fts MATCH ? AND {clause} ORDER BY bm25(units_fts) LIMIT ?",
                [" OR ".join(f'"{word}"' for word in words)] + args + [CANDIDATES]).fetchall() if words and allowed else []
            total = self._db.execute("SELECT COUNT(*) FROM units").fetchone()[0]
            held_by = dict(self._db.execute(f"SELECT term, doc FROM units_terms WHERE term IN ({','.join('?' * len(words))})",
                                            words).fetchall()) if candidates else {}
        # how much of the query a unit has, each word weighed by how rare it is among her units (a weight that
        # stays above 0 in a young index: bm25's own is 0 for a word in half of them; a word none has weighs most)
        rare = {w: math.log(1.0 + (total - held_by.get(w, 0) + 0.5) / (held_by.get(w, 0) + 0.5)) for w in words}
        whole = sum(rare.values()) or 1.0
        lexical = sorted(((row["id"], sum(weight for word, weight in rare.items()
                                          if word in {t.lower() for t in WORDS.findall(row["text"])}) / whole)
                          for row in candidates), key=lambda item: -item[1])
        meaning: Optional[Dict[int, float]] = None  # None: meaning cannot say this time
        fused: Dict[int, float] = {}
        if embedder and allowed and (query or "").strip():
            try:
                vector = embedder.embed([query[:embeddings.MAX_CHARS]], query=True)[0]
                nearest = self.vectors.nearest(vector, embedder.name, CANDIDATES, allowed)
                meaning = {unit: self.vectors.relevance(cosine, embedder) for unit, cosine in nearest}
                for rank, (unit, _) in enumerate(nearest):
                    fused[unit] = 1.0 / (RRF_K + rank + 1)
            except Exception as exc:  # the service is down, or no key: by words this time
                logger.info("Her long-term memory goes by words this time: %s", exc)
                meaning, fused = None, {}
        matched = {unit: share for unit, share in lexical if share >= LEXICAL_ADMIT}
        for rank, unit in enumerate(matched):
            fused[unit] = fused.get(unit, 0.0) + 1.0 / (RRF_K + rank + 1)
        kept = sorted((u for u in fused if (meaning.get(u, 0.0) > 0.0 if meaning is not None else u in matched)),
                      key=lambda u: -fused[u])
        if not kept:
            return []
        with self._lock:
            rows = {row["id"]: dict(row) for row in self._db.execute(
                f"SELECT * FROM units WHERE id IN ({','.join('?' * len(kept))})", kept)}
        found, seen = [], set()
        for unit in kept:
            row = rows.get(unit)
            if row is None or (row["source"], _base(row["ref"])) in seen:
                continue
            seen.add((row["source"], _base(row["ref"])))
            found.append({**row, "relevance": round((meaning or {}).get(unit, 0.0), 3),
                          "lexical": round(matched.get(unit, 0.0), 3), "score": fused[unit]})
            if len(found) >= count:
                break
        return found

    def note(self, run: dict, said: str) -> Optional[str]:
        """What comes back from past chats as she reads what the user wrote (None: nothing does, or not a
        turn the user wrote). Her chat comes back only from before its last compaction: the rest she has."""
        if run["kind"] != "turn" or not (said or "").strip():
            return None
        app, session = run["app"], run["session"]
        summed = self.brain.store.last_compaction(app, session)
        hits = self.search(said, sources=("turn",), held=(app, session, summed["at"] if summed else 0.0))
        if not hits:
            return None
        now, lines, titles = time.time(), [], {}
        for hit in hits:
            chat = (hit["app"], hit["session"])
            if chat not in titles:
                found = self.brain.store.find_session(*chat) or {}
                titles[chat] = (found.get("settings") or {}).get("title") or hit["session"]
            when = line({"at": hit["at"], "text": ""}, now).strip()[1:-1]
            where = f'"{titles[chat]}"' + ("" if hit["app"] == app else f" ({hit['app']})")
            lines.append(f"- {when}, in {where}: {hit['text'][:SHOWN_CHARS]}")
        return HEADER + "\n" + "\n".join(lines)

    # ============== Taking in ==============

    def sweep(self) -> None:
        """Take in what is new (rounds, notes, facts) and embed what has no vector of the current model."""
        with self._sweeping:
            embedder = self.refresh()
            self._take_in_chats()
            self._take_in_notes()
            self._take_in_facts()
            if embedder is not None and embedder.problem() != "no embeddings API key":
                self._embed(embedder)

    def _take_in_chats(self) -> None:
        store = self.brain.store
        with self._lock:
            marks = {(row["app"], row["session"]): row["last_event"] for row in self._db.execute("SELECT * FROM marks")}
        helpers: Dict[str, set] = {}
        for (app, session), last in store.last_events().items():
            mark = marks.get((app, session), 0)
            if last <= mark or session.startswith(HELPERS):
                continue
            if app not in helpers:
                helpers[app] = {s for _, s, _ in store.agent_sessions(app)}
            if session not in helpers[app]:
                for group in mentions.turns(self.brain, app, session):
                    ids = [entry["id"] for entry in group if "id" in entry]
                    said = [f"{'they' if e['role'] == 'user' else 'you'}: {e['text']}" for e in group
                            if e["role"] in ("user", "assistant") and (e.get("text") or "").strip()]
                    if ids and said and max(ids) > mark:
                        self.add("turn", str(ids[0]), app, session, group[0]["time"], "\n".join(said))
            with self._lock:
                self._db.execute("INSERT OR REPLACE INTO marks (app, session, last_event) VALUES (?, ?, ?)",
                                 (app, session, last))

    def _take_in_notes(self) -> None:
        """Journal notes, kept here after the journal lets them go (the newest 20 are in her prompt)."""
        store = self.brain.store
        with self._lock:
            have = {_base(row[0]) for row in self._db.execute("SELECT ref FROM units WHERE source = 'note'")}
        for note in store.notes(limit=-1):
            if str(note["id"]) not in have and store.find_session(note["app"], note["session"]) is not None:
                self.add("note", str(note["id"]), note["app"], note["session"], note["at"], note["note"])

    def _take_in_facts(self) -> None:
        """Lasting facts, as they stand now (a changed one again, a forgotten one gone)."""
        entries = {f"{e['category']}/{e['key']}": e for e in self.brain.store.memory_entries()}
        with self._lock:
            have = {_base(row["ref"]): row["at"] for row in self._db.execute(
                "SELECT ref, at FROM units WHERE source = 'fact' AND ref LIKE '%#0'")}
            self._remove_refs("fact", [ref for ref in have if ref not in entries])
        for ref, entry in entries.items():
            if have.get(ref) != entry["updated"]:
                self.add("fact", ref, entry["app"] or "", "", entry["updated"], f"{entry['key']}: {entry['value']}")

    def _embed(self, embedder: embeddings.Embedder) -> None:
        memory = getattr(getattr(self.brain, "mind", None), "memory", None)
        for vectors in [self.vectors] + ([memory.vectors] if memory is not None else []):
            while not self._stop.is_set():
                found = vectors.texts(vectors.pending(embedder.name, BATCH))
                if not found:
                    vectors.drop(other_than=embedder.name)  # all there in this model: the old ones go
                    try:
                        vectors.floor(embedder)  # measured here, so a turn does not wait for it
                    except Exception as exc:
                        logger.info("Her long-term memory measures what is related later: %s", exc)
                    break
                try:
                    rows = embedder.embed([text for _, text in found])
                except Exception as exc:
                    logger.warning("Her long-term memory could not embed now: %s", exc)
                    return
                vectors.put([(unit, row) for (unit, _), row in zip(found, rows)], embedder.name)
