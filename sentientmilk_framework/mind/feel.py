"""What she senses of her body, and the feelings she makes of it.

Interoception reaches her late and imprecise (``Interoception``: each level is followed with a lag, and read
with a drifting misreading that her temperament's ``insight`` shrinks). Its channels are her body's, fixed as
a body's are (``CHANNELS``: stress, sleep pressure, closeness...), each felt as how far it is from where it
usually sits; from them comes her core affect (valence: pleasant or not; arousal: keyed up or quiet).

Feelings are not a list here. Following the theory of constructed emotion (Barrett 2017), she makes them: a
feeling is a concept, a word she once used for what she felt (homesick, jealous, greedy: any word, as many as
she comes to use), learned from the moments she used it: its body (how her channels were) and its situations
(what was happening). A moment is felt as the concepts whose body is like hers now, the more where what is
happening is like their situations (``Concepts``). The words come from her own cortex, the model, naming what
it is like in context (life.py), never from a table.

Her face is the same reading, for apps: a mood from the expressions the app declares, chosen by valence and
arousal, with a stance (open, closed) and her eyes.
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Tuple

from .body import CHEMICALS, NEEDS, SET_POINTS, START, Body, fatigue
from .memory import _words

LAG = 90.0  # seconds: how far her sense of her body trails it

# Her body's channels as she senses them: what each is called, where it usually sits and how far from there
# is a lot (needs sit at their set points, chemicals at their baselines)
CHANNELS = {
    "dopamine": ("drive", 0.2), "reward": ("reward", 0.4), "serotonin": ("calm", 0.2),
    "noradrenaline": ("alertness", 0.25), "acetylcholine": ("focus", 0.2), "cortisol": ("stress", 0.25),
    "oxytocin": ("closeness", 0.25), "endorphin": ("comfort", 0.3), "adenosine": ("sleep pressure", 0.3),
    "energy": ("energy", 0.4), "grievance": ("hurt", 0.3), "social": ("company", 0.35),
    "novelty": ("new things", 0.3), "competence": ("being of use", 0.3), "autonomy": ("freedom", 0.3),
}
USUAL = {**{name: level.baseline for name, level in CHEMICALS.items()}, **SET_POINTS,
         "adenosine": 0.3, "energy": 1.0, "grievance": 0.0}
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


class Interoception:
    """Her sense of her own body: it follows the levels with a lag, and misreads them by a bias that drifts
    over minutes (larger the less insight she has). A drifting bias, not fresh noise on each look: the
    same moment reads the same twice, so her face does not flicker between two moods."""

    DRIFT = 600.0  # seconds for her misreading to wander off and change

    def __init__(self, body: Body, seed: int = 0):
        self.seen = dict(body.levels)
        self.bias = {name: 0.0 for name in body.levels}
        self._rng = random.Random(seed)

    def follow(self, body: Body, dt: float) -> None:
        dt = max(0.0, dt)
        share, keep = 1.0 - math.exp(-dt / LAG), math.exp(-dt / self.DRIFT)
        blur = 0.06 / max(0.3, body.temperament.insight)
        for name, value in body.levels.items():
            self.seen[name] = self.seen.get(name, value) + (value - self.seen.get(name, value)) * share
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


def _amount(far: float) -> str:
    return "a little " if far < 0.7 else "very " if far >= 1.1 else ""


def _join(words: List[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


class Felt:
    """One moment of her felt sense: core affect and the reading it comes from."""

    def __init__(self, valence: float, arousal: float, reading: Dict[str, float], night: float = 0.0):
        self.valence, self.arousal, self.reading, self.night = valence, arousal, reading, night

    def standing_out(self, count: int = 4, floor: float = 0.4) -> List[Tuple[str, float]]:
        """The channels furthest from usual (name, how far, signed), at most ``count``."""
        found = sorted(((name, off(name, self.reading[name])) for name in CHANNELS if name in self.reading),
                       key=lambda item: -abs(item[1]))
        return [(name, far) for name, far in found if abs(far) >= floor][:count]

    def tone(self) -> Tuple[str, str]:
        """Core affect in words: ("pleasant", "quiet")."""
        tone = ("pleasant" if self.valence > 0.15 else "unpleasant" if self.valence < -0.15 else "neither good nor bad")
        if abs(self.valence) > 0.65:
            tone = "very " + tone
        return tone, "keyed up" if self.arousal > 0.6 else "quiet" if self.arousal < 0.25 else "steady"

    def words(self, feelings: Iterable[Tuple[str, float]] = ()) -> str:
        """How it feels, for her: what stands out in her body, the overall tone and what it feels like, no
        numbers ("Your body: stress a little high and closeness very high; pleasant on the whole, quiet. It
        feels like what you have called "fond".")."""
        out = [f"{CHANNELS[name][0]} {_amount(abs(far))}{'high' if far > 0 else 'low'}"
               for name, far in self.standing_out()]
        tone, pace = self.tone()
        said = (f"Your body: {_join(out)}; {tone} on the whole, {pace}." if out else
                f"Nothing stands out in your body: {tone} on the whole, {pace}.")
        named = [word for word, _ in list(feelings)[:2]]
        if named:
            said += " It feels like what you have called " + " and ".join(f'"{word}"' for word in named) + "."
        return said


def feel(body: Body, senses: Interoception, now: Optional[float] = None) -> Felt:
    reading = senses.reading(body)
    valence, arousal = core(reading)
    return Felt(valence, arousal, reading, body.night(now))


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
    heavy_lidded = max(1.6 * (x["adenosine"] - 0.45) + 0.4 * felt.night,
                       2.0 * (0.4 - x["acetylcholine"]) + 0.8 * fatigue(x) - 0.2)
    eyes = "closed" if asleep else "half" if heavy_lidded > 0.6 else "open"
    return {"mood": mood, "stance": stance, "eyes": eyes, "asleep": asleep}


class Concepts:
    """The feelings she has named: any word she ever used for what she felt, each the moments she called that.

    A concept keeps its body (the running mean of her sensed levels when she used the word: the first few
    moments shape it most, later ones less) and its situations (the words of what was happening, by weight,
    older ones fading). It comes to mind as far as her body now is like its body (within ``REACH`` of a lot,
    over all channels), more where what is happening is like its situations."""

    REACH = 1.5
    FLOOR = 0.5  # how strongly one must come to mind to be felt

    def __init__(self, saved: Iterable = ()):
        self.named = [self._read(item) for item in saved]

    @staticmethod
    def _read(item) -> dict:
        if isinstance(item, dict):
            return {"word": str(item.get("word", "")), "body": dict(item.get("body") or {}),
                    "about": dict(item.get("about") or {}), "count": int(item.get("count", 0)),
                    "at": float(item.get("at", 0.0))}
        # [word, vector] from before 0.22: the vector was of sensations that are gone; the word stays, and its
        # body is learned again the next time she uses it
        return {"word": str(item[0]), "body": {}, "about": {}, "count": 0, "at": 0.0}

    def add(self, word: str, reading: Dict[str, float], situation: str = "", at: float = 0.0) -> None:
        """She called what she feels ``word`` (in ``situation``, its words)."""
        word = " ".join(str(word).split())[:40].lower()
        if not word:
            return
        found = next((concept for concept in self.named if concept["word"] == word), None)
        if found is None:
            found = {"word": word, "body": {}, "about": {}, "count": 0, "at": at}
            self.named.append(found)
        share = 1.0 if not found["body"] else max(0.15, 1.0 / (found["count"] + 1))
        for name, value in reading.items():
            before = found["body"].get(name, value)
            found["body"][name] = round(before + share * (value - before), 4)
        about = {key: weight * 0.9 for key, weight in found["about"].items() if weight * 0.9 >= 0.05}
        for key in _words(situation):
            about[key] = about.get(key, 0.0) + 1.0
        found.update(about=about, count=found["count"] + 1, at=at)

    def strength(self, concept: dict, reading: Dict[str, float], cue: Optional[set] = None) -> float:
        """How strongly a concept comes to mind, 0..1."""
        body = concept["body"]
        if not body:
            return 0.0
        far = sum(((reading[name] - body[name]) / CHANNELS[name][1]) ** 2
                  for name in CHANNELS if name in body and name in reading)
        near = math.exp(-far / (2 * self.REACH ** 2))
        about = concept["about"]
        if cue and about:  # a situation like its own makes it come more readily, an unlike one less
            share = sum(about.get(key, 0.0) for key in cue) / sum(about.values())
            near *= 0.75 + 0.5 * min(1.0, 2.0 * share)
        return min(1.0, near)

    def recognize(self, reading: Dict[str, float], situation: str = "") -> List[Tuple[str, float]]:
        """What she feels now, strongest first: (word, strength) of the concepts that come to mind."""
        cue = set(_words(situation))
        found = ((concept["word"], self.strength(concept, reading, cue)) for concept in self.named)
        return sorted(((word, value) for word, value in found if value >= self.FLOOR), key=lambda item: -item[1])

    def shown(self, reading: Dict[str, float]) -> List[dict]:
        """Every feeling she has named, for drawing: how strongly it comes to mind now, how often she felt it,
        where it sits (``place``: pleasant -1..1, keyed up 0..1, toward the user -1..1, from its body) and the
        channels that set it apart (name, how far, signed)."""
        out = []
        for concept in self.named:
            body = concept["body"]
            entry = {"word": concept["word"], "strength": round(self.strength(concept, reading), 3),
                     "count": concept["count"], "at": concept["at"], "place": None, "channels": []}
            if body:
                valence, arousal = core(body)
                toward = sum(off(name, body[name]) for name in ("oxytocin", "social") if name in body) \
                    - off("grievance", body.get("grievance", 0.0))
                entry["place"] = [round(valence, 3), round(arousal, 3), round(max(-1.0, min(1.0, toward / 3)), 3)]
                apart = sorted(((name, off(name, body[name])) for name in CHANNELS if name in body),
                               key=lambda item: -abs(item[1]))
                entry["channels"] = [[name, round(far, 2)] for name, far in apart[:3] if abs(far) >= 0.4]
            out.append(entry)
        return out
