"""What she senses of her body: a lagged, blurred reading, never the levels themselves.

Interoception reaches her late and imprecise (``Interoception``: each level is followed with a lag, and
read with noise that her temperament's ``insight`` shrinks). From that reading come her core affect
(valence: pleasant or not; arousal: keyed up or quiet) and body sensations in words: tense, warm,
drained, restless... Emotions are not here. Following the theory of constructed emotion, she makes them
herself from these sensations in context: "annoyed", "homesick", whatever she would call it. The words
she once gave a state come back when a state is like it again (``Concepts``).

Her face is the same reading, for apps: a mood from the expressions the app declares, chosen by
valence and arousal, with a stance (open, closed) and her eyes.
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Tuple

from .body import NEEDS, Body

LAG = 90.0  # seconds: how far her sense of her body trails it

# Body sensations, not emotions: what is felt, from which levels (perceived), each 0..1.
SENSATIONS = ("tense", "jittery", "restless", "flat", "heavy", "drained", "sleepy", "warm", "hollow",
              "light", "sinking", "clear", "foggy", "prickly", "itchy to do something", "hemmed in", "settled")
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


def affect(levels: Dict[str, float], fatigue: float, deficits: Dict[str, float]) -> Tuple[float, float]:
    """Core affect: (valence -1..1, arousal 0..1)."""
    x = levels
    pull = 0.35 * (deficits["social"] * x["bond"] + 0.6 * deficits["novelty"] + 0.8 * deficits["competence"]
                   + 0.5 * deficits["autonomy"])
    valence = math.tanh(1.3 * (0.9 * x["reward"] + 0.6 * (x["dopamine"] - 0.5) + 0.7 * (x["serotonin"] - 0.6)
                               + 0.6 * (x["oxytocin"] - 0.4) + 0.8 * (x["endorphin"] - 0.1)
                               - 1.0 * (x["cortisol"] - 0.25) - pull - 0.4 * fatigue - 0.5 * x["grievance"]))
    arousal = _clip(0.3 + 0.9 * (x["noradrenaline"] - 0.35) + 0.35 * abs(x["reward"])
                    + 0.4 * (x["cortisol"] - 0.25) + 0.2 * (x["acetylcholine"] - 0.5) - 0.45 * fatigue)
    return valence, arousal


def sensations(levels: Dict[str, float], fatigue: float, deficits: Dict[str, float], night: float = 0.0
               ) -> Dict[str, float]:
    """Each body sensation, 0..1."""
    x = levels
    energy = x["energy"]
    return {
        "tense": _clip(2.0 * (x["cortisol"] - 0.3) + 1.2 * (x["noradrenaline"] - 0.45)),
        "jittery": _clip(2.5 * (x["noradrenaline"] - 0.55) * energy),
        "restless": _clip(1.5 * deficits["novelty"] * x["noradrenaline"] * 2 * energy),
        "flat": _clip(2.0 * (0.45 - x["dopamine"]) + 1.5 * (0.3 - x["noradrenaline"]) + 0.5 * deficits["novelty"]),
        "heavy": _clip(2.5 * (0.5 - x["serotonin"]) + 1.5 * (0.4 - x["dopamine"])),
        "drained": _clip(1.4 * (1.0 - energy) - 0.1),
        "sleepy": _clip(1.6 * (x["adenosine"] - 0.45) + 0.4 * night),
        "warm": _clip(2.5 * (x["oxytocin"] - 0.45) + 1.5 * x["endorphin"] - 0.2),
        "hollow": _clip(1.3 * deficits["social"] * (0.4 + x["bond"])),
        "light": _clip(1.5 * x["reward"] + 1.5 * (x["endorphin"] - 0.15)),
        "sinking": _clip(-1.6 * x["reward"]),
        "clear": _clip(2.0 * (x["acetylcholine"] - 0.5) + 0.5 * energy - 0.6 * fatigue),
        "foggy": _clip(2.0 * (0.4 - x["acetylcholine"]) + 0.8 * fatigue - 0.2),
        "prickly": _clip(1.6 * (x["cortisol"] - 0.3) + 1.2 * x["grievance"] + 1.0 * (0.5 - x["serotonin"])
                         + 0.6 * fatigue - 0.1),
        "itchy to do something": _clip(1.5 * deficits["competence"] + 1.2 * (x["dopamine"] - 0.55) * energy),
        "hemmed in": _clip(1.6 * deficits["autonomy"]),
        "settled": _clip(2.0 * (x["serotonin"] - 0.55) + 1.5 * (0.3 - x["cortisol"]) + 0.8 * (0.45 - x["noradrenaline"])),
    }


def _amount(intensity: float) -> str:
    return "a little " if intensity < 0.4 else "very " if intensity >= 0.75 else ""


def _join(words: List[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


class Felt:
    """One moment of her felt sense."""

    def __init__(self, valence: float, arousal: float, sensed: Dict[str, float], reading: Dict[str, float]):
        self.valence, self.arousal, self.sensed, self.reading = valence, arousal, sensed, reading

    def strongest(self, count: int = 3, floor: float = 0.25) -> List[Tuple[str, float]]:
        found = sorted(((word, value) for word, value in self.sensed.items() if value >= floor),
                       key=lambda item: -item[1])
        return found[:count]

    def words(self, like: Optional[str] = None) -> str:
        """How it feels, for her: sensations and the overall tone, no numbers ("You feel warm and a little
        drained: pleasant on the whole, quiet.")."""
        top = [f"{_amount(value)}{word}" for word, value in self.strongest()]
        tone = ("pleasant" if self.valence > 0.15 else "unpleasant" if self.valence < -0.15 else "neither good nor bad")
        if abs(self.valence) > 0.65:
            tone = "very " + tone
        pace = "keyed up" if self.arousal > 0.6 else "quiet" if self.arousal < 0.25 else "steady"
        said = f"You feel {_join(top)}: {tone} on the whole, {pace}." if top else \
            f"Nothing stands out in your body: {tone} on the whole, {pace}."
        if like:
            said += f" It feels like what you once called \"{like}\"."
        return said

    def vector(self) -> List[float]:
        """For likeness between moments (Concepts): tone, pace and each sensation."""
        return [self.valence, self.arousal] + [self.sensed[word] for word in SENSATIONS]


def feel(body: Body, senses: Interoception, now: Optional[float] = None) -> Felt:
    reading = senses.reading(body)
    deficits = {need: max(0.0, body.deficit(need)) for need in NEEDS}
    fatigue = body.fatigue()
    valence, arousal = affect(reading, fatigue, deficits)
    return Felt(valence, arousal, sensations(reading, fatigue, deficits, body.night(now)), reading)


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
    guarded = felt.sensed["prickly"] + felt.sensed["tense"] - felt.sensed["warm"]
    stance = "closed" if guarded > 0.6 and felt.valence < -0.1 else "open" if felt.valence > 0.25 and \
        felt.sensed["warm"] > 0.3 else "neutral"
    eyes = "closed" if asleep else "half" if max(felt.sensed["sleepy"], felt.sensed["foggy"]) > 0.6 else "open"
    return {"mood": mood, "stance": stance, "eyes": eyes, "asleep": asleep}


class Concepts:
    """The words she gave her states: a state like one she named comes with its name (nearest within reach)."""

    REACH = 0.9

    def __init__(self, named: Iterable[Tuple[str, List[float]]] = ()):
        self.named = [(word, list(vector)) for word, vector in named]

    def add(self, word: str, vector: List[float]) -> None:
        """A state she named: a word she used before moves toward this state (a concept is what its moments
        share), a new one starts here."""
        word = " ".join(str(word).split())[:40].lower()
        if not word:
            return
        for index, (known, other) in enumerate(self.named):
            if known == word and len(other) == len(vector):
                self.named[index] = (word, [a + 0.2 * (b - a) for a, b in zip(other, vector)])
                return
        self.named.append((word, list(vector)))

    def like(self, vector: List[float]) -> Optional[str]:
        best, distance = None, self.REACH
        for word, other in self.named:
            if len(other) != len(vector):
                continue
            gap = math.dist(vector, other)
            if gap < distance:
                best, distance = word, gap
        return best
