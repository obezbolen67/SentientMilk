"""Her long-term memory (docs/superpowers/specs/2026-11-17-long-term-memory-design.md).

Short-term memory is her context window: the chat she is in, after its last compaction. Long-term memory is
everything else, kept here as units found by meaning: each round of every past chat (a user message and her
replies), and the journal notes and lasting facts kept before 0.30; her episodes' vectors her mind keeps beside
them in mind.sqlite3 (mind/memory.py), filled from here. Until 0.29 all of it was found only by shared words:
"that game idea" did not find "a pixel-art platformer". From 0.30 it is her memory, always on, found only by
meaning (embeddings.py, vectors.py): what comes back is what is related (vectors.relevance). Measured on her
history, words let something back for 17 of 20 questions her past could not answer, meaning for none. Without
a key, or with the service down, nothing is found by meaning: a turn goes without, and a search says so.

The index is made from the brain's own records and can be deleted and made again. A sweep after every turn
and every 30 s takes in what is new and embeds what has no vector of the current model; deleting a chat and
returning to a message take their units out at once.

Each turn the user writes, what comes back (``note``) goes into that turn's input beside her inner note
(runs.py), so the log stays as it was sent: the prompt cache, replay and a return to a message see the same.

In her sleep what she no longer needs lets go (``forget``), as a person's memory does: what she may need a
memory for (``need``: each time it came back makes it stronger, time makes it weaker, by a power law) times
what of it no memory she needs more already holds (``Vectors.held``: the same meaning kept elsewhere, a fact
included). Only the weakest go: a memory nothing else holds lasts decades unused, one held nine tenths
elsewhere about a hundred days. What goes is kept as text, without its vector, in ``forgotten``.
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import embeddings, mentions
from .mind.memory import ago, intensity
from .vectors import Vectors

logger = logging.getLogger(__name__)

CHUNK, STEP = 1600, 1400  # characters: a unit, and where the next begins (200 overlap)
CANDIDATES = 40  # the nearest, before what is not related is left out
SHOWN, SHOWN_CHARS = 5, 400  # what comes back in a turn: the tools reach the rest
SWEEP_EVERY = 30.0
BATCH = 32
HEADER = ("FROM YOUR LONG-TERM MEMORY (what comes back for this message from past chats and what you kept; it "
          "may be out of date):")
SOURCES = ("turn", "note", "fact")  # rounds of chats; notes and facts kept before 0.30
SETTINGS = ("embeddings_base_url", "embeddings_api_key", "embeddings_model", "embeddings_dimensions",
            "base_url", "api_key")
DECAY = 0.5  # how need falls with time: a power law (Anderson & Schooler 1991; ACT-R's base-level learning)
FORGET = 0.02  # what she may need it for, times what of it nothing else holds: under this a memory goes


def need(uses: int, days: float) -> float:
    """How likely she is to need a memory, as human memory weighs it: (1 + uses) / ((1 - d) L^d), L its age
    in days plus one, d = DECAY (ACT-R's base-level learning, Anderson & Lebiere 1998). Just made: 2."""
    return (1 + uses) / ((1.0 - DECAY) * (1.0 + max(0.0, days)) ** DECAY)


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
                    session TEXT NOT NULL, at REAL NOT NULL, text TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (source, ref));
                CREATE TABLE IF NOT EXISTS forgotten (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL, app TEXT NOT NULL,
                    session TEXT NOT NULL, at REAL NOT NULL, text TEXT NOT NULL, uses INTEGER NOT NULL,
                    gone REAL NOT NULL, weight REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS units_chat ON units (app, session, at);
                CREATE TABLE IF NOT EXISTS sleep_prune (id INTEGER PRIMARY KEY CHECK (id = 1), through REAL NOT NULL);
                DROP TRIGGER IF EXISTS unit_added;  -- its index by words, until 0.30
                DROP TRIGGER IF EXISTS unit_gone;
                DROP TABLE IF EXISTS units_terms;
                DROP TABLE IF EXISTS units_fts;
                CREATE TABLE IF NOT EXISTS marks (app TEXT NOT NULL, session TEXT NOT NULL,
                                                  last_event INTEGER NOT NULL, PRIMARY KEY (app, session));
            """)
            if "uses" not in {row[1] for row in self._db.execute("PRAGMA table_info(units)")}:  # made by 0.29
                self._db.execute("ALTER TABLE units ADD COLUMN uses INTEGER NOT NULL DEFAULT 0")
        self.vectors = Vectors(self._db, "units", self._lock)
        self.embedder: embeddings.Embedder  # set by refresh, below
        self._settings: Optional[tuple] = None
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.refresh()

    # ============== Settings and life ==============

    def refresh(self) -> embeddings.Embedder:
        """Her embedder as the settings say now (remade when they change; her mind's memory uses it too)."""
        values = self.brain.config.values()
        settings = tuple(values.get(key) for key in SETTINGS)
        if settings != self._settings:
            self._settings, self.embedder = settings, embeddings.make(values)
            mind = getattr(self.brain, "mind", None)
            if mind is not None:
                mind.memory.embedder = mind.reactions.embedder = self.embedder
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
        else:
            with self._lock:
                self._db.close()

    def wake(self) -> None:
        """Something new may be there (a turn ended): take it in now."""
        self._wake.set()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self.sweep()
                except Exception:
                    logger.exception("Her long-term memory could not take in what is new")
                self._wake.wait(SWEEP_EVERY)
                self._wake.clear()
        finally:
            with self._lock:
                self._db.close()

    def status(self) -> dict:
        embedder = self.refresh()
        with self._lock:
            units = self._db.execute("SELECT COUNT(*) FROM units").fetchone()[0]
            forgotten = self._db.execute("SELECT COUNT(*) FROM forgotten WHERE ref LIKE '%#0'").fetchone()[0]
        embedded = self.vectors.count(embedder.name)
        state = embedder.problem() or ("ready" if embedded >= units else "taking in")
        return {"model": getattr(embedder, "model", None), "state": state, "units": units, "embedded": embedded, "forgotten": forgotten,
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
        with self._sweeping, self._lock:
            for table in ("units", "forgotten", "marks"):
                self._db.execute(f"DELETE FROM {table} WHERE app = ? AND session = ?", (app, session))

    def forget_from(self, app: str, session: str, event: int) -> None:
        """A return to a message undid everything from ``event`` on: its rounds go."""
        with self._sweeping, self._lock:
            for table in ("units", "forgotten"):
                self._db.execute(f"DELETE FROM {table} WHERE source = 'turn' AND app = ? AND session = ? "
                                 "AND CAST(substr(ref, 1, instr(ref, '#') - 1) AS INTEGER) >= ?", (app, session, event))
            self._db.execute("UPDATE marks SET last_event = MIN(last_event, ?) WHERE app = ? AND session = ?",
                             (event - 1, app, session))

    # ============== Finding ==============

    def search(self, query: str, count: int = SHOWN, sources: Tuple[str, ...] = SOURCES,
               held: Optional[Tuple[str, str, float]] = None, after: Optional[float] = None,
               before: Optional[float] = None, app: Optional[str] = None, strengthen: bool = True) -> List[dict]:
        """What is about ``query``, best first: dicts with the unit's ``source``, ``ref``, ``app``,
        ``session``, ``at``, ``text`` and ``relevance`` (by meaning, 0..1; only what is related). ``held``:
        (app, session, since), a chat whose units from then on she has before her (her context), left out. One
        unit a round, note or fact (its best piece). It raises what the embedder raises when it cannot embed
        now (no key, the service down)."""
        if not (query or "").strip():
            return []
        embedder = self.refresh()
        where, args = [f"source IN ({','.join('?' * len(sources))})"], list(sources)
        for clause, value in (("app = ?", app), ("at >= ?", after), ("at < ?", before)):
            if value is not None:
                where.append(clause)
                args.append(value)
        if held:
            where.append("NOT (app = ? AND session = ? AND at >= ?)")
            args += list(held)
        with self._lock:
            allowed = {row[0] for row in self._db.execute(f"SELECT id FROM units WHERE {' AND '.join(where)}", args)}
        if not allowed:
            return []
        vector = embedder.embed([query[:embeddings.MAX_CHARS]], query=True)[0]
        related = [(unit, self.vectors.relevance(cosine, embedder))
                   for unit, cosine in self.vectors.nearest(vector, embedder.name, CANDIDATES, allowed)]
        related = [(unit, relevance) for unit, relevance in related if relevance > 0.0]
        if not related:
            return []
        with self._lock:
            rows = {row["id"]: dict(row) for row in self._db.execute(
                f"SELECT * FROM units WHERE id IN ({','.join('?' * len(related))})", [unit for unit, _ in related])}
        found, seen = [], set()
        for unit, relevance in related:
            row = rows.get(unit)
            if row is None or (row["source"], _base(row["ref"])) in seen:
                continue
            seen.add((row["source"], _base(row["ref"])))
            found.append({**row, "relevance": round(relevance, 3)})
            if len(found) >= count:
                break
        self._came_of(found, embedder)
        if strengthen:
            self.attended(found)
        return found

    def _came_of(self, hits: List[dict], embedder: embeddings.Embedder) -> None:
        """What came of each (``later``): the nearest round or note after it, of another round, about the same
        matter (Vectors.matter, by the vectors already kept). Until 0.43 her note brought back "my watcher's still
        dead, want me to kick it back on?" a day after the user had said not to touch it and to forget it (the
        audit, 2026-11-18); that was in her memory too, and never came with it."""
        try:
            floor = self.vectors.matter(embedder.name)
        except Exception:  # cannot tell now: each comes back as it is
            return
        for hit in hits:
            vector = self.vectors.vector(hit["id"], embedder.name)
            if vector is None:
                continue
            with self._lock:
                after = {row["id"] for row in self._db.execute(
                    "SELECT id, ref FROM units WHERE at > ? AND source IN ('turn', 'note')", (hit["at"],))
                    if _base(row["ref"]) != _base(hit["ref"])}
            nearest = self.vectors.nearest(vector, embedder.name, 1, after) if after else []
            if nearest and nearest[0][1] >= floor:
                with self._lock:
                    row = self._db.execute("SELECT * FROM units WHERE id = ?", (nearest[0][0],)).fetchone()
                if row is not None:
                    hit["later"] = dict(row)

    def attended(self, hits):
        with self._lock:
            self._db.executemany("UPDATE units SET uses = uses + 1 WHERE id = ?", [(hit["id"],) for hit in hits])

    def note(self, run: dict, said: str) -> Optional[str]:
        """What comes back from past chats as she reads what the user wrote (None: nothing does, or not a
        turn the user wrote). Her chat comes back only from before its last compaction: the rest she has."""
        if run["kind"] != "turn" or not (said or "").strip():
            return None
        app, session = run["app"], run["session"]
        summed = self.brain.store.last_compaction(app, session)
        try:
            hits = self.search(said, held=(app, session, summed["at"] if summed else 0.0))
        except Exception as exc:  # no key, the service down: nothing comes back this time
            logger.info("Nothing comes back from her long-term memory this time: %s", exc)
            return None
        if not hits:
            return None
        return self.render(app, hits)

    def render(self, app, hits):
        now, lines, titles = time.time(), [], {}

        def told(unit):
            when = ago(unit["at"], now)
            if unit["source"] == "fact":
                return f"{when}, something you kept: {unit['text'][:SHOWN_CHARS]}"
            chat = (unit["app"], unit["session"])
            if chat not in titles:
                found = self.brain.store.find_session(*chat) or {}
                titles[chat] = (found.get("settings") or {}).get("title") or unit["session"]
            where = f'"{titles[chat]}"' + ("" if unit["app"] == app else f" ({unit['app']})")
            return (f"{when}, {'your note about' if unit['source'] == 'note' else 'in'} {where}: "
                    f"{unit['text'][:SHOWN_CHARS]}")
        for hit in hits:
            lines.append(f"- {told(hit)}" + (f"\n  what came of it: {told(hit['later'])}" if hit.get("later") else ""))
        return HEADER + "\n" + "\n".join(lines)

    # ============== Letting go ==============

    def weighed(self, now: Optional[float] = None) -> Dict[Tuple[str, str], float]:
        """Each round and note, as (source, ref) -> what she may need it for times what of it no memory she
        needs more already holds (its strongest piece). The facts kept before 0.30 are not weighed: what she
        knew of the user, few and short; they hold what is near them.

        A round whose moment moved her is needed more, by how much it moved her as far as it is still charged
        (her mind's episode of that moment, ``felt``): what was felt is bound to a memory more lastingly than its
        details (Yonelinas & Ritchey 2015). Until 0.38 a round was weighed by its use and age alone."""
        embedder, now = self.refresh(), now or time.time()
        with self._lock:
            rows = [dict(row) for row in self._db.execute(
                "SELECT id, source, ref, at, uses FROM units WHERE source IN ('turn', 'note') AND at <= ?", (now,))]
        mind = getattr(self.brain, "mind", None)
        events = {int(_base(row["ref"])) for row in rows if row["source"] == "turn" and _base(row["ref"]).isdecimal()}
        moved = {e["event_id"]: e["charge"] * min(intensity(mind.memory.felt(e)), 2.0)
                 for e in mind.memory.by_events(events)} if mind is not None and events else {}
        needs = {row["id"]: need(row["uses"], (now - row["at"]) / 86400.0)
                 * (1.0 + (moved.get(int(_base(row["ref"])), 0.0) if row["source"] == "turn"
                           and _base(row["ref"]).isdecimal() else 0.0)) for row in rows}
        held = self.vectors.held(needs, embedder.name)
        weights: Dict[Tuple[str, str], float] = {}
        for row in rows:
            key = (row["source"], _base(row["ref"]))
            weights[key] = max(weights.get(key, 0.0), needs[row["id"]] * (1.0 - held.get(row["id"], 0.0)))
        return weights

    def forget(self, now: Optional[float] = None, *, sleep_review: bool = False) -> int:
        """Rounds and notes she no longer needs go (``weighed`` under FORGET), kept as text in ``forgotten``
        and never taken in again; how many went."""
        now = now or time.time()
        with self._lock:
            self._db.execute("SAVEPOINT prune")
            try:
                if sleep_review:
                    if self._db.execute("SELECT 1 FROM sleep_prune WHERE through >= ?", (now,)).fetchone():
                        return 0
                    self._db.execute("INSERT OR REPLACE INTO sleep_prune VALUES (1, ?)", (now,))
                weak = [(source, ref, weight) for (source, ref), weight in self.weighed(now).items()
                        if weight < FORGET]
                for source, ref, weight in weak:
                    self._db.execute("INSERT INTO forgotten (source, ref, app, session, at, text, uses, gone, weight) "
                                     "SELECT source, ref, app, session, at, text, uses, ?, ? FROM units "
                                     "WHERE source = ? AND substr(ref, 1, ?) = ?",
                                     (now, weight, source, len(ref) + 1, f"{ref}#"))
                    self._remove_refs(source, [ref])
            except BaseException:
                self._db.execute("ROLLBACK TO prune")
                raise
            finally:
                self._db.execute("RELEASE prune")
        if weak:
            logger.info("Her long-term memory let go of %d rounds and notes she no longer needs", len(weak))
        return len(weak)

    # ============== Taking in ==============

    def sweep(self) -> None:
        """Take in what is new (rounds, and notes and facts kept before 0.30) and embed what has no vector of the
        current model."""
        with self._sweeping:
            embedder = self.refresh()
            self._take_in_chats()
            self._take_in_notes()
            self._take_in_facts()
            if embedder.problem() != "no embeddings API key":
                self._embed(embedder)

    def _take_in_chats(self) -> None:
        store = self.brain.store
        with self._lock:
            marks = {(row["app"], row["session"]): row["last_event"] for row in self._db.execute("SELECT * FROM marks")}
        helpers: Dict[str, set] = {}
        mine = {run["session"] for run in store.own_tasks()}  # what she did on her own is hers to find (0.42)
        for (app, session), last in store.last_events().items():
            mark = marks.get((app, session), 0)
            if last <= mark or (session.startswith(mentions.HELPERS) and session not in mine):
                continue
            if app not in helpers:
                helpers[app] = {s for _, s, _ in store.agent_sessions(app)}
            if session not in helpers[app]:
                for group in mentions.turns(self.brain, app, session):
                    ids = [entry["id"] for entry in group if "id" in entry]
                    asked = "goal" if session in mine else "they"  # her own task's goal: she set it herself
                    said = [f"{asked if e['role'] == 'user' else 'you'}: {e['text']}" for e in group
                            if e["role"] in ("user", "assistant") and (e.get("text") or "").strip()]
                    if ids and said and max(ids) > mark:
                        self.add("turn", str(ids[0]), app, session, group[0]["time"], "\n".join(said))
            with self._lock:
                self._db.execute("INSERT OR REPLACE INTO marks (app, session, last_event) VALUES (?, ?, ?)",
                                 (app, session, last))

    def _take_in_notes(self) -> None:
        """The journal's notes, kept before 0.30."""
        store = self.brain.store
        with self._lock:  # one she let go of is not taken in again
            have = {_base(row[0]) for row in self._db.execute(
                "SELECT ref FROM units WHERE source = 'note' UNION SELECT ref FROM forgotten WHERE source = 'note'")}
        for note in store.notes():
            if str(note["id"]) not in have and store.find_session(note["app"], note["session"]) is not None:
                self.add("note", str(note["id"]), note["app"], note["session"], note["at"], note["note"])

    def _take_in_facts(self) -> None:
        """The facts kept before 0.30 (and what an app imports), as they stand (a changed one again, one gone
        gone)."""
        entries = {f"{e['category']}/{e['key']}": e for e in self.brain.store.memory_entries()}
        with self._lock:
            have = {_base(row["ref"]): row["at"] for row in self._db.execute(
                "SELECT ref, at FROM units WHERE source = 'fact' AND ref LIKE '%#0'")}
            self._remove_refs("fact", [ref for ref in have if ref not in entries])
        for ref, entry in entries.items():
            if have.get(ref) != entry["updated"]:
                self.add("fact", ref, entry["app"] or "", "", entry["updated"], f"{entry['key']}: {entry['value']}")

    def _embed(self, embedder: embeddings.Embedder) -> None:
        mind = getattr(self.brain, "mind", None)
        # her long-term memory's units, her mind's moments and her learned reactions' cues (0.39)
        for vectors in [self.vectors] + ([mind.memory.vectors, mind.reactions.vectors] if mind is not None else []):
            while not self._stop.is_set():
                if embedder is not self.embedder:  # the model changed meanwhile: the next sweep embeds with it,
                    return  # and this one must not take its vectors as old ones (until 0.42 it did)
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
                with vectors.lock:
                    current = dict(vectors.texts([unit for unit, _ in found]))
                    vectors.put([(unit, row) for (unit, text), row in zip(found, rows)
                                 if current.get(unit) == text], embedder.name)
