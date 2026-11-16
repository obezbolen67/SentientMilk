"""What she decides: options compete on what they are worth to her now, minus what they cost her now.

The model imagines (prompts.py): it reads a message and returns how it strikes her (``Appraisal``) and
what she could do (``Option``s, each with how much work it is, how likely it goes well, how much fun, how
much of what the user wants it gives). Her body chooses: each option's worth is

  care      the bond and closeness she feels, times how much it matters to the user, times what it gives
  craft     the pleasure of doing something well (more when she needs to feel capable)
  fun       what she expects to enjoy, lifted by her dopamine
  curiosity what is new, when she is bored
  learned   the gut feeling her values give it (values.py)
  reactance being pushed when her autonomy is low makes yes cost and no feel like relief
  letdown   saying no or later disappoints someone she cares for (weighed by her serotonin: patience)
  cost      the work, times her fatigue and stress, over her vigor (tonic dopamine)

with noise, and a softmax whose temperature her noradrenaline raises (an aroused mind is impulsive).
So when she has the energy and the motivation she does it; when she does not, she most likely won't.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .body import Body
from .values import Values

ACTS = ("do", "part", "later", "decline", "talk")
WORK = {"do": 1.0, "part": 0.45, "later": 0.05, "decline": 0.02}  # of an option's effort she spends now
# why, in her words, for the parts that weighed most in a choice
REASONS = {
    "care": "you want to do this for them",
    "craft": "you like getting something like this right",
    "fun": "it sounds fun to you",
    "curiosity": "it's new and you're curious",
    "learned+": "things like this have felt good before",
    "learned-": "things like this have gone badly for you before",
    "reactance": "being pushed like this makes you want to dig your heels in",
    "letdown": "you don't want to let them down",
    "cost": "you don't have it in you right now: it's a lot of work for how you feel",
    "grievance": "you're still hurt by them",
}


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _number(value, default: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return _clip(float(value), low, high)
    except (TypeError, ValueError):
        return default


@dataclass
class Appraisal:
    """How a message strikes her, as the imagining part read it."""
    warmth: float = 0.0  # -1 hostile .. 1 loving
    pressure: float = 0.0  # 0 an offer .. 1 an order, insisted on
    novelty: float = 0.3
    importance: float = 0.5  # to the user
    intent: str = "chat"  # chat, question or request
    tags: List[str] = field(default_factory=list)

    @classmethod
    def read(cls, data: dict) -> "Appraisal":
        data = data if isinstance(data, dict) else {}
        intent = str(data.get("intent", "chat")).lower()
        return cls(_number(data.get("warmth"), 0.0, -1.0), _number(data.get("pressure"), 0.0),
                   _number(data.get("novelty"), 0.3), _number(data.get("importance"), 0.5),
                   intent if intent in ("chat", "question", "request") else "chat",
                   [str(t)[:40] for t in (data.get("tags") or []) if str(t).strip()][:6])


@dataclass
class Option:
    act: str
    what: str = ""
    effort: float = 0.2
    chance: float = 0.8
    fun: float = 0.0  # -1..1
    gives: float = 0.0  # how much of what the user wants
    why: str = ""  # the imagining part's own reason

    @classmethod
    def read(cls, data: dict) -> Optional["Option"]:
        if not isinstance(data, dict) or str(data.get("act", "")).lower() not in ACTS:
            return None
        act = str(data["act"]).lower()
        return cls(act, str(data.get("what", ""))[:400], _number(data.get("effort"), 0.2),
                   _number(data.get("chance"), 0.8), _number(data.get("fun"), 0.0, -1.0),
                   _number(data.get("gives"), 1.0 if act == "do" else 0.0), str(data.get("why", ""))[:300])


@dataclass
class Choice:
    option: Option
    worth: float
    parts: Dict[str, float]
    chances: Dict[str, float]  # each option's chance to be picked, by act
    reasons: List[str]


def worth(option: Option, seen: Appraisal, body: Body, learned: float) -> Dict[str, float]:
    """Each part of what ``option`` is worth to her now (``learned``: her values' gut feeling for it)."""
    x, t = body.levels, body.temperament
    fatigue = body.fatigue()
    grudge = 1.0 - 0.6 * x["grievance"]
    closeness = x["bond"] * (0.6 + x["oxytocin"]) * t.warmth * grudge
    act = option.act
    parts = {
        "care": 1.2 * closeness * seen.importance * option.gives ** 1.5,
        "craft": 0.6 * (0.3 + 0.7 * body.deficit("competence")) * option.chance * min(option.effort, 0.7)
        * {"do": 1.0, "part": 0.6}.get(act, 0.0),  # half a job satisfies less
        "fun": 0.6 * option.fun * (0.4 + x["dopamine"]) * (act in ("do", "part", "talk")),
        "curiosity": 0.5 * (0.2 + body.deficit("novelty")) * seen.novelty * t.curiosity * (act in ("do", "part", "talk")),
        "learned": 0.5 * learned,
        "reactance": 0.0, "letdown": 0.0,
        # work weighs more than its size (a small favor stays small, a big job looms), and more the deeper
        # her fatigue: a little tired barely matters, very tired does
        "cost": -(WORK.get(act, min(option.effort, 0.15) / max(option.effort, 1e-6)) * option.effort) ** 1.4
        * (0.2 + 2.5 * fatigue ** 2 + 0.6 * max(0.0, x["cortisol"] - 0.3) * t.stress) / (0.4 + x["dopamine"] * t.vigor),
    }
    push = seen.pressure * (0.3 + body.deficit("autonomy")) * t.autonomy
    if act in ("do", "part"):
        parts["reactance"] = -0.5 * push * (1.0 if act == "do" else 0.5)
    elif act in ("later", "decline"):
        parts["reactance"] = 0.3 * push
    if act in ("part", "later", "decline"):  # not giving them all of it disappoints someone she cares for
        missing = seen.importance * (1.0 - option.gives)
        parts["letdown"] = -0.5 * closeness * missing * (0.4 + x["serotonin"]) * (1.0 if act == "decline" else 0.5)
    return parts


def choose(options: List[Option], seen: Appraisal, body: Body, values: Values, found, rng: random.Random
           ) -> Choice:
    """Pick one of ``options`` (``found(option)``: its features for her values)."""
    x, t = body.levels, body.temperament
    noise = (0.04 + 0.25 * max(0.0, x["noradrenaline"] - 0.35)) * t.volatility
    temperature = 0.1 + 0.35 * max(0.0, x["noradrenaline"] - 0.35) + 0.1 * max(0.0, 0.5 - x["acetylcholine"])
    scored = []
    for option in options:
        parts = worth(option, seen, body, values.predict(found(option)))
        scored.append((option, sum(parts.values()) + rng.gauss(0.0, noise), parts))
    top = max(score for _, score, _ in scored)
    weights = [math.exp((score - top) / temperature) for _, score, _ in scored]
    total = sum(weights)
    pick = rng.random() * total
    for (option, score, parts), weight in zip(scored, weights):
        pick -= weight
        if pick <= 0:
            break
    chances = {}
    for (other, _, _), weight in zip(scored, weights):
        chances[other.act] = chances.get(other.act, 0.0) + weight / total
    rivals = [item for item in scored if item[0] is not option]
    doing = [item for item in rivals if item[0].act == "do"]  # not doing it is explained against doing it
    rival = (doing or sorted(rivals, key=lambda item: -item[1]) or [(None, 0, None)])[0][2]
    named = reasons(parts, rival)
    if x["grievance"] > 0.35 and option.act in ("later", "decline"):
        named.append(REASONS["grievance"])
    return Choice(option, score, parts, chances, named)


def reasons(parts: Dict[str, float], rival: Optional[Dict[str, float]] = None) -> List[str]:
    """Why this choice beat the best other one, strongest first (or what pulled toward it, alone)."""
    gains = {name: value - (rival or {}).get(name, 0.0) for name, value in parts.items()}
    named = []
    for name, gain in sorted(gains.items(), key=lambda item: -item[1]):
        if gain < 0.08:
            break
        if name == "learned":  # liked this one, or the other one went badly before
            named.append(REASONS["learned+" if parts[name] > -(rival or {}).get(name, 0.0) else "learned-"])
        elif name == "cost":  # sparing herself work counts as a reason only against doing it
            if rival is not None and gain >= 0.25:
                named.append(REASONS["cost"])
        elif name in REASONS:
            named.append(REASONS[name])
    return list(dict.fromkeys(named))[:3]
