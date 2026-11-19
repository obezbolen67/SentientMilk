"""Her learned reactions (design: docs/superpowers/specs/2026-11-18-learned-reactions-design.md).

What a cue comes to set off in her body, learned from what followed it, as the amygdala learns (LeDoux 2000) apart
from what happened, which her memory keeps (memory.py): either can be there without the other (Bechara et al.
1995). A reaction is a cue, its words (by meaning, through her embedder) or a surrounding ("in front: outlook"), and
the change of her chemistry and soreness it has come to predict, in lots.

- **Learned from surprise**, all present cues together: the outcome minus what they predicted (Rescorla & Wagner
  1972), so a cue that adds nothing learns nothing (blocking); faster for a cue whose outcomes surprised
  (associability: Pearce & Hall 1980) and the more aroused she was (McGaugh 2004). One intense outcome is learned
  in one go.
- **Spreads by meaning**: a likeness between unrelated (what everyday questions reach) and the same thing (what
  paraphrases reach), steeper when she is calm and wider when anxious (Shepard 1987; Dunsmoor & Paz 2015).
- **Getting over it is new learning**: met without its outcome, a reaction is held back, in the surroundings it was
  met in; the hold is less elsewhere (renewal), wears off over days (spontaneous recovery, slower the more times
  it was learned) and gives under stress (reinstatement) (Bouton 2004; Maren & Holmes 2016), and goes fast when
  the outcome comes again (savings). Within hours of being called up, a mismatch changes the reaction itself
  (reconsolidation: Nader et al. 2000; Monfils et al. 2009; Schiller et al. 2010).
- **Lasts**: nothing fades it with time (Gale et al. 2004).

Calls to her embedder (``prepare``) happen outside her lock; the rest runs under it.
"""

import json
import math
import threading
from typing import Dict, Iterable, List, Optional

import numpy as np

from ..embeddings import MAX_CHARS
from ..vectors import Vectors
from .body import CHEMICALS
from .feel import USUAL

REACTS = (*CHEMICALS, "grievance")  # what a reaction moves: her chemistry and soreness, not her needs or energy
SAME_CUE = 0.9  # a likeness from which a cue is a kept one, not a new one
KEEPS = 0.7  # of a cue's associability kept at each outcome (the rest is how much that outcome surprised)
OPENS, CLOSES = 600.0, 6 * 3600.0  # s after a reaction is called up when a mismatch changes it (reconsolidation)
RECOVERS = 2 * 86400.0  # s for a getting-over to wear off (times how many times it was learned)
TEXT_CHARS = 400  # a deed and what it was for (200 held the deed alone)
TABLE = """
CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
    response TEXT NOT NULL, associability REAL NOT NULL, hold REAL NOT NULL DEFAULT 0,
    contexts TEXT NOT NULL DEFAULT '{}', extinctions INTEGER NOT NULL DEFAULT 0, extinguished REAL,
    called REAL, learned REAL NOT NULL, updated REAL NOT NULL, trials INTEGER NOT NULL DEFAULT 0, episode INTEGER,
    origins TEXT NOT NULL DEFAULT '[]', size REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS reactions_cue ON reactions(kind, text);
CREATE INDEX IF NOT EXISTS reactions_size ON reactions(size);
"""


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def anxious(levels: Dict[str, float]) -> float:
    """How anxious her body is, 0..1: her strain (cortisol) above usual, over half its range."""
    return _clip((levels["cortisol"] - USUAL["cortisol"]) / 0.5)


def _size(change: Dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in change.values()))


class Reactions:
    def __init__(self, db, lock: threading.RLock):
        self._db, self._lock = db, lock
        with lock:
            db.executescript(TABLE)
        self.vectors = Vectors(db, "reactions", lock)
        self.embedder = None  # her long-term memory's (recall.py sets it, as for her memory)

    # ============== calling up (outside her lock: they may call her embedder) ==============

    def prepare(self, cues: List[dict], anxious_: float = 0.0, keep: bool = False) -> List[dict]:
        """These cues ({"text", "kind": "meaning" | "around", ...}) with what each is alike to among her reactions
        (``found``: id -> likeness, None when she cannot tell by meaning now) and, to be learned (``keep``), its
        vector as a kept text (``vector``). A surrounding is found by itself, exactly (``around``). On the path of
        every message: with nothing to be alike to and nothing to keep, her embedder is not asked."""
        cues = [dict(cue, text=" ".join(str(cue["text"]).split())[:TEXT_CHARS]) for cue in cues if str(cue.get("text") or "").strip()]
        meant = [cue for cue in cues if cue["kind"] == "meaning"]
        for cue in cues:
            cue.setdefault("found", None)
            cue.setdefault("vector", None)
        embedder = self.embedder
        if not meant or embedder is None:
            return cues
        try:
            if not keep and not self.vectors.count(embedder.name):
                for cue in meant:
                    cue["found"] = {}
                return cues
            texts = [cue["text"][:MAX_CHARS] for cue in meant]
            asked = embedder.embed(texts, query=True)
            kept = embedder.embed(texts) if keep else [None] * len(texts)
            floor, same = self.vectors.unrelated(embedder), self.vectors.same(embedder)
        except Exception:  # her embedder cannot now: by meaning nothing is called up, nothing kept
            return cues
        steep = 2.0 - _clip(anxious_)  # calm, the likeness falls off steeply; anxious, it spreads wider
        for cue, query, vector in zip(meant, asked, kept):
            cue["vector"] = vector
            cue["found"] = {rid: min(1.0, (cosine - floor) / (same - floor)) ** steep
                            for rid, cosine in self.vectors.nearest(query, embedder.name, 24) if cosine > floor}
        return cues

    def around(self, texts: Iterable[str]) -> Dict[int, float]:
        """The reactions to these surroundings, as they are now (id -> 1)."""
        texts = list({" ".join(str(t).split())[:TEXT_CHARS] for t in texts if str(t).strip()})
        if not texts:
            return {}
        with self._lock:
            return {row[0]: 1.0 for row in self._db.execute(
                f"SELECT id FROM reactions WHERE kind = 'around' AND text IN ({','.join('?' * len(texts))})", texts)}

    # ============== what they set off ==============

    def _rows(self, ids: Iterable[int]) -> List[dict]:
        ids = list(ids)
        if not ids:
            return []
        with self._lock:
            rows = [dict(row) for row in self._db.execute(
                f"SELECT * FROM reactions WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)]
        for row in rows:
            row["response"] = json.loads(row["response"])
            row["contexts"] = json.loads(row["contexts"])
            row["origins"] = json.loads(row["origins"])
        return rows

    @staticmethod
    def held(row: dict, now: float, around: Iterable[str] = (), stress: float = 0.0) -> float:
        """How much of a reaction getting over it holds back now, 0..1: as far as she is where she got over it
        (what is around her now, there then), the more recently and the more times, and less under stress."""
        if not row["hold"]:
            return 0.0
        here = set(around)
        where = len(here & set(row["contexts"])) / len(here) if here else 1.0
        since = math.exp(-(now - (row["extinguished"] or now)) / (RECOVERS * max(1, row["extinctions"])))
        return row["hold"] * where * since * (1.0 - 0.5 * _clip(stress))

    def expressed(self, row: dict, now: float, around: Iterable[str] = (), stress: float = 0.0) -> Dict[str, float]:
        """What a reaction sets off now, in lots: its response, less what getting over it holds back."""
        keep = 1.0 - self.held(row, now, around, stress)
        return {name: value * keep for name, value in row["response"].items()}

    def each(self, present: Dict[int, float], now: float, around: Iterable[str] = (), stress: float = 0.0
             ) -> Dict[int, Dict[str, float]]:
        """What each reaction called up (id -> likeness) sets off now, as far as it was called up, in lots."""
        around = list(around)
        return {row["id"]: {name: present[row["id"]] * value
                            for name, value in self.expressed(row, now, around, stress).items()}
                for row in self._rows(present)}

    def predict(self, present: Dict[int, float], now: float, around: Iterable[str] = (), stress: float = 0.0
                ) -> Dict[str, float]:
        """What the reactions called up (id -> likeness) set off together, each channel in lots."""
        total = dict.fromkeys(REACTS, 0.0)
        for moved in self.each(present, now, around, stress).values():
            for name, value in moved.items():
                total[name] = total.get(name, 0.0) + value
        return total

    def called(self, ids: Iterable[int], now: float) -> None:
        """These were called up now: for a few hours a mismatch changes them (reconsolidation)."""
        ids = list(ids)
        if ids:
            with self._lock:
                self._db.execute(f"UPDATE reactions SET called = ? WHERE id IN ({','.join('?' * len(ids))})",
                                 [now, *ids])

    def texts(self, ids: Iterable[int]) -> Dict[int, str]:
        return {row["id"]: row["text"] for row in self._rows(ids)}

    # ============== learning (under her lock) ==============

    def learn(self, cues: List[dict], outcome: Dict[str, float], arousal: float, now: float,
              around: Iterable[str] = (), episode: Optional[int] = None, stress: float = 0.0) -> List[dict]:
        """An outcome came (``outcome``: how the moment moved her, each channel in lots, less what reactions did in
        it) with these cues (``prepare``d; a surrounding with its ``salience``, how rare it is). Every reaction they
        call up learns from the same surprise, as far as each is alike, salient and attended to; a cue like none
        of them is kept as a new one. Learned at a rate that her arousal raises. What changed, for drawing."""
        around = list(around)
        outcome = {name: float(outcome.get(name, 0.0)) for name in REACTS}
        present: Dict[int, float] = {}
        salience: Dict[int, float] = {}
        new = []
        for cue in cues:
            weight = _clip(cue.get("salience", 1.0))
            if not weight:
                continue
            if cue["kind"] == "around":
                found = self.around([cue["text"]])
            elif cue.get("found") is None:
                continue  # by meaning, she cannot tell now what this was alike to
            else:
                found = cue["found"]
            for rid, likeness in found.items():
                if likeness > present.get(rid, 0.0):
                    present[rid], salience[rid] = likeness, weight
            if not any(likeness >= SAME_CUE for likeness in found.values()):
                new.append({**cue, "salience": weight})
        rows = self._rows(present)
        foreseen = dict.fromkeys(REACTS, 0.0)
        expected = {}
        for row in rows:
            expected[row["id"]] = self.expressed(row, now, around, stress)
            for name, value in expected[row["id"]].items():
                foreseen[name] = foreseen.get(name, 0.0) + present[row["id"]] * value
        error = {name: outcome[name] - foreseen.get(name, 0.0) for name in REACTS}
        surprise = min(1.0, _size(error))
        aroused = 0.2 + 0.8 * _clip(arousal)
        changed = []
        with self._lock:
            for row in rows:
                rate = row["associability"] * aroused * present[row["id"]] * salience[row["id"]]
                predicted = expected[row["id"]]
                toward = sum(predicted.get(name, 0.0) * error[name] for name in REACTS)
                size = sum(value * value for value in predicted.values())
                response, hold, how = dict(row["response"]), row["hold"], "learned"
                if toward < 0 and size > 1e-9:  # it foresaw more than came: getting over it
                    failed = min(1.0, -toward / size)
                    if row["called"] and OPENS <= now - row["called"] <= CLOSES:  # opened by a reminder: changed
                        response = {name: value * (1.0 - rate * failed) for name, value in response.items()}
                        how = "changed"
                    else:
                        hold += rate * failed * (1.0 - hold)
                        contexts = dict(row["contexts"])
                        for cue in around:
                            contexts[cue] = contexts.get(cue, 0) + 1
                        self._db.execute("UPDATE reactions SET contexts = ?, extinctions = extinctions + 1, "
                                         "extinguished = ? WHERE id = ?", (json.dumps(contexts), now, row["id"]))
                        how = "getting over it"
                else:
                    for name in REACTS:
                        response[name] = response.get(name, 0.0) + rate * error[name]
                    if toward > 0 and hold:
                        hold *= 1.0 - min(1.0, 2.0 * rate)  # the outcome again: the getting-over goes fast
                response = {name: round(value, 4) for name, value in response.items() if abs(value) >= 1e-4}
                origins = row["origins"] + ([episode] if episode is not None and episode not in row["origins"] else [])
                self._db.execute("UPDATE reactions SET response = ?, hold = ?, associability = ?, trials = trials + 1, "
                                 "updated = ?, origins = ?, size = ? WHERE id = ?",
                                 (json.dumps(response), round(hold, 4),
                                  round((1 - KEEPS) * surprise + KEEPS * row["associability"], 4), now,
                                  json.dumps(origins), _size(response), row["id"]))
                changed.append({"id": row["id"], "text": row["text"], "how": how, "response": response})
            for cue in new:
                rate = aroused * cue["salience"]  # new: as attended to as can be (associability 1)
                response = {name: round(rate * error[name], 4) for name in REACTS if abs(rate * error[name]) >= 1e-4}
                if not response:
                    continue
                cursor = self._db.execute(
                    "INSERT INTO reactions (kind, text, source, response, associability, learned, updated, trials, "
                    "episode, origins, size) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (cue["kind"], cue["text"], cue.get("source") or cue["kind"], json.dumps(response),
                     round((1 - KEEPS) * surprise + KEEPS, 4), now, now, episode,
                     json.dumps([episode] if episode is not None else []), _size(response)))
                if cue.get("vector") is not None and self.embedder is not None:
                    self.vectors.put([(cursor.lastrowid, np.asarray(cue["vector"]))], self.embedder.name)
                changed.append({"id": cursor.lastrowid, "text": cue["text"], "how": "new", "response": response})
        return changed

    def withdraw(self, gone: Iterable[int]) -> List[int]:
        """The moments ``gone`` were taken back (a deleted chat, a turn gone back before): the reactions any of them
        taught or changed go with them, as her other generalizations do (Mind._revise_derived). What sleep lets
        fade is not taken back: a reaction outlives the memory of what taught it. The ids withdrawn."""
        gone = set(gone)
        if not gone:
            return []
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT id, origins FROM reactions")
                   if gone.intersection(json.loads(row[1] or "[]"))]
            for rid in ids:
                self._db.execute("DELETE FROM reactions WHERE id = ?", (rid,))
            self.vectors.drop(ids)
        return ids

    # ============== seen ==============

    def strongest(self, count: int, now: float, around: Iterable[str] = (), stress: float = 0.0) -> List[dict]:
        """Her strongest reactions, as they are now: what each sets off, how much getting over it holds back."""
        with self._lock:  # by how much each sets off (its size kept with it): the rest are not read
            ids = [row[0] for row in self._db.execute("SELECT id FROM reactions ORDER BY size DESC, id LIMIT ?", (count,))]
        around = list(around)
        rows = sorted(self._rows(ids), key=lambda row: -_size(row["response"]))
        return [{"id": row["id"], "text": row["text"], "kind": row["kind"], "source": row["source"],
                 "response": row["response"], "hold": row["hold"],
                 "held": round(self.held(row, now, around, stress), 3),
                 "now": {name: round(value, 3) for name, value in self.expressed(row, now, around, stress).items()},
                 "trials": row["trials"], "extinctions": row["extinctions"], "learned": row["learned"],
                 "episode": row["episode"]} for row in rows]
