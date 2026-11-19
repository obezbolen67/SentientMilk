"""What she senses of her body, and the feelings she makes of it.

Interoception reaches her late and imprecise (``Interoception``: each level is followed with a lag, and read
with a drifting misreading that her temperament's ``insight`` shrinks). Its channels are her body's, fixed as
a body's are (``CHANNELS``: strain, sleep pressure, closeness...); from them comes her core affect (valence:
pleasant or not; arousal: how much is going on in her).

What she notices of her body is what it does not predict: she gets used to how a channel is (``used``, over
``ADAPTS``), and it stands out by how far it is from what she is used to, so a change is felt at once and a
state that lasts fades into how things are, and coming down from a high is felt as a low (a brain passes on
the error of its prediction of the body, not the body: Barrett & Simmons 2015; Solomon 1980, the opponent
process). She never gets used to all of it (``USED_TO``): what her body needs keeps calling for her. Read as
levels against a fixed usual, the same lines came with every message of a warm chat, and she said of them "I
don't know if that's me feeling something or me reading a dial" (the user's brain, 2026-11-16).

Following the theory of constructed emotion (Barrett 2017), she makes her feelings: a feeling is a concept,
whatever words she put to what she felt when she reflected on it (life.py: looking inward, or going back over a
moment in her thoughts; a feeling is named when attention turns to it: Lambie & Marcel 2002, Gendlin 1978),
learned from the moments she named: how her body was moved in them, and their situations (what was happening).
A moment is felt as the concepts that were moved the way she is moved now, the more where what is happening is
like their situations and the more familiar the words (``Concepts``): an emotion is told from another by what
the event does to her concerns (appraisal: Lazarus 1991; Scherer 2001), and the body of the hour, tired or
rested, is shared by all of them. There is no list of feelings: what she feels and what she calls it are hers.
Nothing else names her feelings, and her body reaches her as amounts she puts into words herself (``Felt.words``).

Her face is the same reading, for apps: a mood from the expressions the app declares, chosen by valence and
arousal, with a stance (open, closed) and her eyes.
"""

import math
import random
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .body import CHEMICALS, NEEDS, SET_POINTS, START, Body, fatigue

WORDS = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _words(text: str) -> List[str]:
    """What a situation is about, as a feeling keeps it: its words of three letters or more, once each."""
    return list(dict.fromkeys(word.lower() for word in WORDS.findall(text or "")))[:24]

LAG = 90.0  # seconds: how far her sense of her body trails it
ADAPTS = 20 * 60.0  # seconds for her to get used to how a channel is

# Her body's channels as she senses them: what each is called, where it usually sits and how far from there
# is a lot (needs sit at their set points, chemicals at their baselines)
CHANNELS = {
    "dopamine": ("drive", 0.2), "reward": ("reward", 0.4), "serotonin": ("steadiness", 0.2),
    "noradrenaline": ("alertness", 0.25), "acetylcholine": ("focus", 0.2), "cortisol": ("strain", 0.25),
    "oxytocin": ("closeness", 0.25), "endorphin": ("comfort", 0.3), "adenosine": ("sleep pressure", 0.17),
    "energy": ("energy", 0.4), "grievance": ("soreness", 0.3), "social": ("company", 0.35),
    "novelty": ("novelty", 0.3), "competence": ("usefulness", 0.3), "autonomy": ("freedom", 0.3),
}
USUAL = {**{name: level.baseline for name, level in CHEMICALS.items()}, **SET_POINTS,
         "adenosine": 0.4, "energy": 1.0, "grievance": 0.0}  # sleep pressure: mid-day (body.py)
# How much of a lasting state she stops noticing: what her body needs (sleep, energy, her needs, a hurt) keeps
# calling for her; the rest fades into how things are, down to what is still far from usual
USED_TO = {name: 0.3 if name in (*NEEDS, "adenosine", "energy", "grievance") else 0.6 for name in CHANNELS}
# Where moods sit in valence and arousal: an app's expression names, as far as they are known.
MOOD_PLACES = {
    "neutral": (0.0, 0.3), "smile": (0.5, 0.45), "happy": (0.6, 0.5), "playful": (0.65, 0.75),
    "excited": (0.6, 0.85), "calm": (0.3, 0.15), "sad": (-0.55, 0.2), "mad": (-0.6, 0.8),
    "angry": (-0.65, 0.8), "annoyed": (-0.4, 0.6), "nervous": (-0.35, 0.7), "scared": (-0.6, 0.85),
    "confused": (-0.1, 0.55), "surprised": (0.1, 0.9), "zoned_out": (0.0, 0.05), "sleepy": (-0.05, 0.05),
    "tired": (-0.15, 0.1), "bored": (-0.2, 0.15), "shy": (0.15, 0.5), "smug": (0.4, 0.4),
}


def _clip(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def off(name: str, value: float) -> float:
    """How far a channel is from where it usually sits, in units of a lot (signed)."""
    return (value - USUAL[name]) / CHANNELS[name][1]


def noticed(reading: Dict[str, float], used: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """What she notices of each channel, in units of a lot (signed): how far it is from what she is used to
    (``used``; without it, from where it usually sits)."""
    return {name: off(name, reading[name]) - (USED_TO[name] * off(name, used.get(name, USUAL[name])) if used else 0.0)
            for name in CHANNELS if name in reading}


def moved(before: Dict[str, float], after: Dict[str, float]) -> Dict[str, float]:
    """What a moment did to her body: the change of each channel, in units of a lot (signed)."""
    return {name: (after[name] - before[name]) / CHANNELS[name][1] for name in CHANNELS if name in before and name in after}


def _alike(one: Dict[str, float], other: Dict[str, float]) -> float:
    """How alike two ways of being moved are, 0..1: whether they point the same way (their cosine), whatever
    their size. Nothing moved is like nothing."""
    size = math.sqrt(sum(v * v for v in one.values()) * sum(v * v for v in other.values()))
    return max(0.0, sum(value * other.get(name, 0.0) for name, value in one.items()) / size) if size else 0.0


class Interoception:
    """Her sense of her own body: it follows the levels with a lag, and misreads them by a bias that drifts
    over minutes (larger the less insight she has). A drifting bias, not fresh noise on each look: the
    same moment reads the same twice, so her face does not flicker between two moods."""

    DRIFT = 600.0  # seconds for her misreading to wander off and change

    def __init__(self, body: Body, seed: int = 0):
        self.seen = dict(body.levels)
        self.used = dict(body.levels)  # what she has got used to: her prediction of each level
        self.bias = {name: 0.0 for name in body.levels}
        self._rng = random.Random(seed)

    def follow(self, body: Body, dt: float) -> None:
        if dt <= 0:
            return
        share, keep, adapts = 1.0 - math.exp(-dt / LAG), math.exp(-dt / self.DRIFT), 1.0 - math.exp(-dt / ADAPTS)
        blur = 0.06 / max(0.3, body.temperament.insight)
        for name, value in body.levels.items():
            self.seen[name] = self.seen.get(name, value) + (value - self.seen.get(name, value)) * share
            self.used[name] = self.used.get(name, value) + (self.seen[name] - self.used.get(name, value)) * adapts
            self.bias[name] = self.bias.get(name, 0.0) * keep + self._rng.gauss(0.0, blur * math.sqrt(1 - keep * keep))

    def reading(self, body: Body) -> Dict[str, float]:
        """The levels as she senses them now: lagged and misread."""
        return {name: value + self.bias.get(name, 0.0) for name, value in self.seen.items()}


def core(levels: Dict[str, float]) -> Tuple[float, float]:
    """Core affect of these levels: (valence -1..1, arousal 0..1)."""
    x = {**START, **levels}
    d = {need: max(0.0, SET_POINTS[need] - x[need]) / SET_POINTS[need] for need in NEEDS}
    tired = fatigue(x)
    pull = 0.35 * (d["social"] * x["bond"] + 0.6 * d["novelty"] + 0.8 * d["competence"] + 0.5 * d["autonomy"])
    valence = math.tanh(1.3 * (0.9 * x["reward"] + 0.6 * (x["dopamine"] - 0.5) + 0.7 * (x["serotonin"] - 0.6)
                               + 0.6 * (x["oxytocin"] - 0.4) + 0.8 * (x["endorphin"] - 0.1)
                               - 1.0 * (x["cortisol"] - 0.25) - pull - 0.4 * tired - 0.5 * x["grievance"]))
    arousal = _clip(0.3 + 0.9 * (x["noradrenaline"] - 0.35) + 0.35 * abs(x["reward"])
                    + 0.4 * (x["cortisol"] - 0.25) + 0.2 * (x["acetylcholine"] - 0.5) - 0.45 * tired)
    return valence, arousal


# Her body as she feels it, in amounts against what she is used to ("much more alertness than you're used to"),
# its parts named as a body's are, never as a feeling (not stress, calm or hurt): what it is like and what to
# call it are hers to find (a felt sense has no words yet: Gendlin; she constructs the feeling from it:
# Barrett 2017). Ready-made sensations ("buzzing", "braced", "heavy-eyed") came back word for word in 18 of
# 44 live replies (amounts: 3 of 45), she said "handed over, and I just picked it up and repeated it", and a
# blind judge heard her less from inside (amounts preferred in 27 of 39 pairs)
def _amount(far: float) -> str:
    return "a little " if far < 0.7 else "much " if far >= 1.1 else ""


def _amounts(found: List[Tuple[str, float]]) -> str:
    return _join([f"{_amount(abs(far))}{'more' if far > 0 else 'less'} {CHANNELS[name][0]}" for name, far in found])


def _join(words: List[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


class Felt:
    """One moment of her felt sense: core affect, the reading it comes from and what she is used to."""

    def __init__(self, valence: float, arousal: float, reading: Dict[str, float], night: float = 0.0,
                 used: Optional[Dict[str, float]] = None):
        self.valence, self.arousal, self.reading, self.night, self.used = valence, arousal, reading, night, used

    def standing_out(self, count: int = 4, floor: float = 0.4, usual: bool = False) -> List[Tuple[str, float]]:
        """The channels she notices most (name, how far, signed), at most ``count``: how far each is from what
        she is used to, in units of a lot. ``usual``: from where it usually sits instead, whatever she has got
        used to (her body as it is, for drawing)."""
        found = sorted(noticed(self.reading, None if usual else self.used).items(), key=lambda item: -abs(item[1]))
        return [(name, far) for name, far in found if abs(far) >= floor][:count]

    def noticed(self) -> Dict[str, float]:
        """The way her body is moved with nothing new having come: what she notices of every channel (see
        ``noticed``). Nothing ({}) while nothing stands out: a body at rest is moved no way, and no feeling is
        read into the little there is."""
        return noticed(self.reading, self.used) if self.standing_out(1) else {}

    def tone(self) -> Tuple[str, str]:
        """Core affect in words: ("pleasant", "little going on"), an amount for how stirred up she is, as for her
        body: "keyed up", a ready-made phrase, she traced in the exam ("That line isn't mine")."""
        tone = ("pleasant" if self.valence > 0.15 else "unpleasant" if self.valence < -0.15 else "neither good nor bad")
        if abs(self.valence) > 0.65:
            tone = "very " + tone
        return tone, ("much going on" if self.arousal > 0.6 else "little going on" if self.arousal < 0.25
                      else "some going on")

    def words(self, out: Optional[List[Tuple[str, float]]] = None,
              moved_by: Optional[Dict[str, float]] = None) -> str:
        """How it feels, for her: what stands out in her body (``out``: these channels instead) and the overall
        tone, no numbers and no feeling's name: what she feels is hers to put into words ("Your body: much
        more closeness and a little more strain than you're used to; pleasant on the whole, with little going
        on.").
        ``moved_by``: what a message did to her (the change of each channel, in lots), said first, then how she
        is underneath it ("Reading it: more closeness than a moment ago. Underneath: more sleep pressure than
        you're used to; ..."): an emotion has its object, a mood is the background (Russell 2003)."""
        tone, pace = self.tone()
        whole = f"{tone} on the whole, with {pace}."
        found = self.standing_out() if out is None else out
        if moved_by is not None:
            now = sorted(((name, far) for name, far in moved_by.items() if name in CHANNELS and abs(far) >= 0.4),
                         key=lambda item: -abs(item[1]))[:3]
            under = [(name, far) for name, far in found if name not in dict(now)][:3]
            # a message that moved her too little to tell is told as that (told nothing, reassured, she said
            # "the whole worry fell off" with her strain where it was: run 660)
            return (f"Reading it: {_amounts(now) + ' than' if now else 'little changed from'} a moment ago. "
                    + (f"Underneath: {_amounts(under)} than you're used to; {whole}" if under
                       else f"Underneath, {whole}"))
        return (f"Your body: {_amounts(found)} than you're used to; {whole}" if found
                else f"Nothing stands out in your body: {whole}")


def feel(body: Body, senses: Interoception, now: Optional[float] = None) -> Felt:
    reading = senses.reading(body)
    valence, arousal = core(reading)
    return Felt(valence, arousal, reading, body.night(now), senses.used)


def face(felt: Felt, options: Dict[str, List[str]], asleep: bool) -> Optional[dict]:
    """How she looks now, for an app: ``mood`` (one of its declared moods, nearest by valence and arousal),
    ``stance`` (open, closed or neutral, for the app to pick a pose), ``eyes`` (open, half, closed) and
    ``asleep``. None when the app declares no moods she knows a place for."""
    moods = {mood for pose_moods in (options or {}).values() for mood in pose_moods if mood in MOOD_PLACES}
    if not moods:
        return None
    if asleep:
        calm = [m for m in ("sleepy", "zoned_out", "calm", "neutral") if m in moods]
        mood = calm[0] if calm else min(moods, key=lambda m: MOOD_PLACES[m][1])
    else:
        mood = min(moods, key=lambda m: (MOOD_PLACES[m][0] - felt.valence) ** 2
                   + 0.6 * (MOOD_PLACES[m][1] - felt.arousal) ** 2)
    x = felt.reading
    guarded = off("cortisol", x["cortisol"]) + off("grievance", x["grievance"]) - off("oxytocin", x["oxytocin"])
    stance = "closed" if guarded > 1.5 and felt.valence < -0.1 else "open" if felt.valence > 0.25 and \
        off("oxytocin", x["oxytocin"]) > 0.5 else "neutral"
    heavy_lidded = max(3.0 * (x["adenosine"] - 0.45) + 0.4 * felt.night,
                       2.0 * (0.4 - x["acetylcholine"]) + 0.8 * fatigue(x) - 0.2)
    eyes = "closed" if asleep else "half" if heavy_lidded > 0.6 else "open"
    return {"mood": mood, "stance": stance, "eyes": eyes, "asleep": asleep}


def naming(words: str, text: str, at: float, how: str, named: str, *, run: Optional[int] = None,
           event: Optional[int] = None, call: Optional[str] = None, episode: Optional[int] = None,
           asked: Optional[str] = None, measure: Optional[dict] = None, reminded: Iterable[int] = ()) -> dict:
    """The record of one naming (Concepts.add): her ``words`` as she wrote them and the sentence (``text``) she
    said them in, ``how`` (``tool``, ``speech``, ``thought``), what it ``named`` and which measurement supplied
    its numbers."""
    return {"words": words, "text": text, "at": at, "how": how, "named": named, "run": run, "event": event,
            "call": call, "episode": episode, "asked": asked, "measure": measure, "reminded": list(reminded)}


class Concepts:
    """The feelings she has named: whatever words she put to what she felt, reflecting (life.py: looking inward or
    going back over a moment in her thoughts), each the moments she called that.

    A concept keeps the way her body was moved in those moments (``moved``: the running mean, in units of a
    lot a channel; the first few moments shape it most, later ones less) and its situations (the words of
    what was happening, by weight, older ones fading). It comes to mind as far as she is moved the same way
    now, more where what is happening is like its situations.

    Not by how near her whole body is to its body: measured on moments of six kinds
    (2026-11-16): the nearest earlier moment was of the same kind 23% of the time at twenty minutes apart and
    3% at two (chance: 17%), since the body of the hour is common to all that happens in it, so what came back
    was whatever she had felt last; by the way she was moved, 82% and 80%, and 76% at four hours apart."""

    FLOOR = 0.6  # how strongly one must come to mind to be felt
    NAMED = ("now", "past", "unresolved", "legacy")  # what a naming names (see ``add``)
    MEASURED = ("message", "reading", "moment", "legacy")  # what supplied a naming's numbers

    def __init__(self, saved: Iterable = ()):
        self.named: List[dict] = []
        for item in saved:
            self.named.append(self._read(item))

    @staticmethod
    def key(words: str) -> str:
        """Her words for a feeling as they are known again: one spacing, any case, no end punctuation. Her
        wording itself is kept as she wrote it, on each naming (``words``)."""
        return " ".join(str(words).split()).strip(" .,!?\"'").casefold()

    @staticmethod
    def _read(item: dict) -> dict:
        return {"word": str(item["word"]), "moved": dict(item["moved"]), "about": dict(item["about"]),
                "count": int(item["count"]), "measured": int(item["measured"]), "back": int(item["back"]),
                "back_at": item["back_at"],
                "back_run": item["back_run"], "at": float(item["at"]),
                "said": [Concepts._naming(one) for one in item["said"]]}

    @staticmethod
    def _naming(one: dict) -> dict:
        if one["named"] not in Concepts.NAMED or (one["measure"] and one["measure"]["of"] not in Concepts.MEASURED):
            raise ValueError(f"not a naming: {one}")
        return {key: one[key] for key in ("words", "text", "at", "how", "named", "run", "event", "call", "episode",
                                          "asked", "measure", "reminded")}

    def naming(self, run: Optional[int], call: Optional[str]) -> Optional[dict]:
        """The feeling a tool call already named (a call made again names nothing twice); None: none."""
        if call is None:
            return None
        return next((concept for concept in self.named for one in concept["said"]
                     if one["call"] == call and one["run"] == run), None)

    def add(self, naming: dict, situation: str = "") -> Optional[dict]:
        """She put what she feels into words: ``naming`` is the record of it (``_naming``: her ``words`` as she
        wrote them, the sentence she said them in, ``how``, what it ``named``: ``now`` (the experience she is
        in: ``run``, ``event``, its ``episode`` once kept), ``past`` (the ``episode`` she pointed to),
        ``unresolved`` (a past moment she ``asked`` for that is not there); ``measure``: what supplied the
        numbers, ``{"of", "way", ...}`` or None; ``reminded``: what came back as she looked, which is not what
        she named). The words become a feeling of hers, or one she had; its ``moved`` is the running mean of
        the measured namings only (``measured`` of them: an unmeasured one moves nothing), and ``situation``
        adds to what it is about. The feeling."""
        naming = self._naming(naming)
        word = self.key(naming["words"])
        if not word:
            return None
        found = next((concept for concept in self.named if concept["word"] == word), None)
        if found is None:
            found = {"word": word, "moved": {}, "about": {}, "count": 0, "measured": 0, "back": 0, "back_at": None,
                     "back_run": None, "at": naming["at"], "said": []}
            self.named.append(found)
        if naming["measure"]:
            kept = found["moved"]
            share = 1.0 if not kept else max(0.15, 1.0 / (found["measured"] + 1))
            found["measured"] += 1
            for name, value in naming["measure"]["way"].items():
                kept[name] = round(kept.get(name, value) + share * (value - kept.get(name, value)), 4)
        about = {key: weight * 0.9 for key, weight in found["about"].items() if weight * 0.9 >= 0.05}
        for key in _words(situation):
            about[key] = about.get(key, 0.0) + 1.0
        found["said"].append(naming)
        found.update(about=about, count=found["count"] + 1, at=naming["at"])
        return found

    def link(self, run: int, episode: int) -> bool:
        """The moment of ``run`` was kept: her namings of it, made while she was in it, name it. Whether any did."""
        linked = False
        for concept in self.named:
            for one in concept["said"]:
                if one["named"] == "now" and one["run"] == run and one["episode"] is None:
                    one["episode"], linked = episode, True
        return linked

    def came_back(self, word: str, at: float = 0.0, run: Optional[int] = None) -> None:
        """A feeling of hers was recognized again by likeness, in a moment she did not call by it: counted
        apart from her namings (``back``, when and in which run) and no more: made a little more like each
        moment it came back at, one drifted until it came back at everything (measured: one of 108 felt 37
        times, at kindness and blame alike)."""
        for concept in self.named:
            if concept["word"] == word:
                concept.update(back=concept["back"] + 1, back_at=at, back_run=run)

    def strength(self, concept: dict, way: Dict[str, float], cue: Optional[set] = None) -> float:
        """How strongly a concept comes to mind, 0..1, with her body moved this ``way``: how alike, times how
        familiar the word is to her (a word used often comes to mind sooner than one used once, as frequency
        makes a concept accessible: a word used once does not come as readily as one used fifty times)."""
        near = _alike(concept["moved"], way) * (0.5 + 0.5 * concept["count"] / (concept["count"] + 1))
        about = concept["about"]
        if cue and about:  # in a situation unlike its own it comes less readily
            share = sum(about.get(key, 0.0) for key in cue) / sum(about.values())
            near *= 0.75 + 0.25 * min(1.0, 2.0 * share)
        return near

    def recognize(self, way: Dict[str, float], situation: str = "") -> List[Tuple[str, float]]:
        """What she feels, moved this ``way``, strongest first: (word, strength) of the concepts that come to
        mind."""
        cue = set(_words(situation))
        found = ((concept["word"], self.strength(concept, way, cue)) for concept in self.named)
        return sorted(((word, value) for word, value in found if value >= self.FLOOR), key=lambda item: -item[1])

    def shown(self, way: Dict[str, float]) -> List[dict]:
        """Every feeling she has named, for drawing: how strongly it comes to mind now, how often she called a
        moment by it (``count``) and how often it came back at one she did not (``back``), where it sits (``place``: pleasant -1..1, keyed up 0..1, toward the user -1..1: a usual body moved a
        lot and a half its way) and the channels it moves most (name, its share of the way, signed)."""
        out = []
        for concept in self.named:
            entry = {"word": concept["word"], "strength": round(self.strength(concept, way), 3),
                     "count": concept["count"], "back": concept["back"], "back_at": concept["back_at"],
                     "back_run": concept["back_run"], "at": concept["at"], "place": None,
                     "said": [dict(one) for one in concept["said"]],
                     "measured": concept["measured"], "channels": []}
            size = math.sqrt(sum(value * value for value in concept["moved"].values()))
            if size:
                part = {name: value / size for name, value in concept["moved"].items() if name in CHANNELS}
                valence, arousal = core({name: USUAL[name] + 1.5 * share * CHANNELS[name][1]
                                         for name, share in part.items()})
                toward = part.get("oxytocin", 0.0) + part.get("social", 0.0) - part.get("grievance", 0.0)
                entry["place"] = [round(valence, 3), round(arousal, 3), round(max(-1.0, min(1.0, toward)), 3)]
                most = sorted(part.items(), key=lambda item: -abs(item[1]))
                entry["channels"] = [[name, round(share, 2)] for name, share in most[:3] if abs(share) >= 0.25]
            out.append(entry)
        return out
