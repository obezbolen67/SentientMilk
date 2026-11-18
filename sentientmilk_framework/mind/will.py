"""What she decides: each option is worth what she foresees it doing to her needs, minus what it costs her now.

The model imagines (prompts.py): it foresees what a message does to her needs (``Appraisal``) and what she
could do (``Option``s: how much work each is, how likely it goes well, how much of what the user asked
for it gives). Nothing there says how she should feel about it. What an option does to her needs follows
from those facts (``Option.effects``: live, the model's own guesses of that were noise, and missed that
asking questions instead lets the user down). Her body values it: a change to a need is worth
more the less that need is met now, and a loss weighs more than the same gain (``value``: reward as moving
toward the set points her body holds, Keramati & Gutkin 2014); company and being capable also have a worth
that does not wear off as they are met (the bond, her craft), so a sated being still cares. So one option
is worth different things to her in different states:

  company   being close to the user and wanted by them, weighed by her bond and closeness, dimmed by grievance
  capable   being good at what she does, of use
  free      choosing for herself (an order she obeys costs it, saying no wins it back)
  new       what is new to her (measured from her memories, not foreseen), for what she takes part in
  learned   the gut feeling her values give it (values.py)
  reacting  what the thought of doing it sets off in her body (reactions.py, 0.39), valued as it would feel: the
            as-if body of a somatic marker (Damasio 1994; anticipatory reactions before a risky choice: Bechara
            et al. 1997). It weighs; it never forbids (she may do what she dreads)
  cost      the work, times her fatigue and stress, over her vigor (tonic dopamine)

How far ahead she weighs what an option brings, against its cost now, is her serotonin (Doya 2002: the
time horizon). Then noise, and a softmax whose temperature her noradrenaline raises (an aroused mind is
impulsive). So when she has the energy and the motivation she does it; when she does not, she most likely
won't.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .body import SET_POINTS, Body
from .values import Values

ACTS = ("do", "part", "later", "decline", "talk")
WORK = {"do": 1.0, "part": 0.45, "later": 0.05, "decline": 0.02}  # of an option's effort she spends now
FORESEEN = ("company", "capable", "free")  # what the imagining part foresees a message does to her
NEEDED = {"company": "social", "capable": "competence", "free": "autonomy", "new": "novelty"}
REACH = 0.3  # how far a foreseen 1 (or -1) moves a need, of its range
CURVE = 3.0  # how steeply an unmet need gains worth, and so how much more a loss weighs than a gain
# the worth that does not wear off as a need is met (the bond, her craft), per unit of the need
LASTING = {"company": 1.0, "capable": 0.5, "free": 0.0, "new": 0.0}
WEIGHT = 1.0  # what her needs weigh against the cost of the work (calibrated: tests/test_mind_will, _day)
ENGAGES = {"do": 1.0, "part": 0.6, "talk": 0.5}  # how much of something new she takes in by each act
DOING = {"do": 1.0, "part": 0.6}  # how much of the work (its craft, and obeying what was asked) each act is
# why, in her words, for the parts that weighed most in a choice
REASONS = {
    "care": "you want to do this for them",
    "letdown": "you don't want to let them down",
    "craft": "you like getting something like this right",
    "curiosity": "it's new and you're curious",
    "choice": "you want to choose this for yourself",
    "learned+": "things like this have felt good before",
    "learned-": "things like this have gone badly for you before",
    "reactance": "being pushed like this makes you want to dig your heels in",
    "cost": "you don't have it in you right now: it's a lot of work for how you feel",
    "grievance": "you're still hurt by them",
    "dread": "the thought of doing it sets you on edge: something like it went badly before",
    "eager": "the thought of doing it pulls at you: something like it went well before",
}


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _number(value, default: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
        return _clip(number, low, high) if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


@dataclass
class Appraisal:
    """What a message means for her: what it does to her needs as the imagining part foresees it (-1 takes
    much of it away .. 1 gives her much of it), how new it is to her (measured from her memories, life.py)
    and what it is."""
    company: float = 0.0
    capable: float = 0.0
    free: float = 0.0
    novelty: float = 0.3
    intent: str = "chat"  # chat, question or request
    tags: List[str] = field(default_factory=list)
    theirs: float = 0.0  # how things are for the one who writes, going by the message: -1 very bad .. 1 very good

    def effects(self) -> Dict[str, float]:
        return {name: getattr(self, name) for name in FORESEEN}

    @classmethod
    def read(cls, data: dict) -> "Appraisal":
        data = data if isinstance(data, dict) else {}
        intent = str(data.get("intent", "chat")).lower()
        return cls(*(_number(data.get(name), 0.0, -1.0) for name in FORESEEN), 0.3,
                   intent if intent in ("chat", "question", "request") else "chat",
                   [str(t)[:40] for t in (data.get("tags") or []) if str(t).strip()][:6],
                   _number(data.get("theirs"), 0.0, -1.0))


@dataclass
class Option:
    act: str
    what: str = ""
    effort: float = 0.2
    chance: float = 0.8
    gives: float = 0.0  # how much of what the user asked for it gives them
    check: Optional[dict] = None  # the tool operation and target whose result would resolve this forecast

    def calibrate(self, history: dict) -> None:
        record = history.get((self.check or {}).get("tool"), {})
        if record.get("resolved", 0) >= 4:
            self.chance = (1 + record["succeeded"]) / (2 + record["resolved"])

    def effects(self, seen: Appraisal) -> Dict[str, float]:
        """What doing it would do to her needs (-1..1): giving the user what they asked for keeps her wanted,
        not giving it lets them down; doing hard work well makes her capable, and its risk of going badly
        the other way; obeying what took her freedom (``seen.free`` below 0) costs her more of it, and
        putting it off or saying no wins some back; what is new feeds her as far as she takes part."""
        doing, taken = DOING.get(self.act, 0.0), max(0.0, -seen.free)
        return {"company": self.gives - 0.5,
                "capable": doing * (self.chance * (0.3 + min(self.effort, 0.7)) - 0.5 * (1.0 - self.chance)),
                "free": -taken * doing + (0.5 * taken if self.act in ("later", "decline") else 0.0),
                "new": seen.novelty * ENGAGES.get(self.act, 0.0)}

    @classmethod
    def read(cls, data: dict) -> Optional["Option"]:
        if not isinstance(data, dict) or str(data.get("act", "")).lower() not in ACTS:
            return None
        act = str(data["act"]).lower()
        check = data.get("check")
        if isinstance(check, dict) and isinstance(check.get("tool"), str) and isinstance(check.get("target"), dict):
            target = {k: v for k, v in check["target"].items()
                      if isinstance(k, str) and isinstance(v, str) and 0 < len(v) <= 500}
            check = {"tool": check["tool"], "target": target} if target and target == check["target"] else None
        else:
            check = None
        return cls(act, str(data.get("what", ""))[:400], _number(data.get("effort"), 0.2),
                   _number(data.get("chance"), 0.8), _number(data.get("gives"), 1.0 if act == "do" else 0.0), check)


@dataclass
class Choice:
    option: Option
    worth: float
    parts: Dict[str, float]
    chances: Dict[str, float]  # each option's chance to be picked, by act
    reasons: List[str]
    considered: List[dict] = field(default_factory=list)  # every option as weighed: its facts, parts and worth
    temperature: float = 0.1


def _gains(body: Body) -> Dict[str, float]:
    """How much each need matters to her now, beyond how unmet it is: her temperament, and for company
    the bond and closeness she feels, dimmed by grievance."""
    x, t = body.levels, body.temperament
    return {"company": t.warmth * (0.3 + x["bond"]) * (0.6 + x["oxytocin"]) * (1.0 - 0.6 * x["grievance"]),
            "capable": 1.0, "free": t.autonomy, "new": t.curiosity}


def _urgency(body: Body, name: str) -> float:
    need = NEEDED[name]
    return math.exp(-CURVE * (body.levels[need] - SET_POINTS[need]))


def value(effects: Dict[str, float], body: Body) -> Dict[str, float]:
    """What these changes to her needs (each -1..1, as foreseen; 1 moves a need by ``REACH``) are worth to her
    now, need by need: the change they make to how met her needs are, sum(gain * (LASTING * level -
    exp(-CURVE * (level - set point)) / CURVE)), which rises as needs are met, ever more slowly down to
    what lasts. A reward is that change (Keramati & Gutkin 2014)."""
    gains = _gains(body)
    return {name: gains[name] * (LASTING[name] * REACH * change
                                 + _urgency(body, name) * (1.0 - math.exp(-CURVE * REACH * change)) / CURVE)
            for name, change in effects.items()}


def worth(option: Option, seen: Appraisal, body: Body, learned: float, reacting: float = 0.0) -> Dict[str, float]:
    """Each part of what ``option`` is worth to her now (``learned``: her values' gut feeling for it;
    ``reacting``: what the thought of doing it would do to how she feels, by her learned reactions)."""
    x, t = body.levels, body.temperament
    fatigue = body.fatigue()
    ahead = WEIGHT
    parts = {name: ahead * worth_ for name, worth_ in value(option.effects(seen), body).items()}
    if option.act == "later":
        parts["patience"] = WEIGHT * (x["serotonin"] - 0.6) * option.chance
    parts["learned"] = 0.5 * learned
    if reacting:
        parts["reacting"] = reacting
    # work weighs more than its size (a small favor stays small, a big job looms), and more the deeper her
    # fatigue: a little tired barely matters, very tired does
    parts["cost"] = -(WORK.get(option.act, min(option.effort, 0.15) / max(option.effort, 1e-6)) * option.effort) ** 1.4 \
        * (0.2 + 2.5 * fatigue ** 2 + 0.6 * max(0.0, x["cortisol"] - 0.3) * t.stress) / (0.4 + x["dopamine"] * t.vigor)
    return parts


def choose(options: List[Option], seen: Appraisal, body: Body, values: Values, found, rng: random.Random,
           reacting=None) -> Choice:
    """Pick one of ``options`` (``found(option)``: its features for her values; ``reacting(option)``: what the thought
    of doing it would do to how she feels, by her learned reactions)."""
    x, t = body.levels, body.temperament
    noise = (0.04 + 0.25 * max(0.0, x["noradrenaline"] - 0.35)) * t.volatility
    temperature = 0.1 + 0.35 * max(0.0, x["noradrenaline"] - 0.35) + 0.1 * max(0.0, 0.5 - x["acetylcholine"])
    scored = []
    for option in options:
        parts = worth(option, seen, body, values.predict(found(option)), reacting(option) if reacting else 0.0)
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
    named = reasons(parts, rival, option.act)
    if x["grievance"] > 0.35 and option.act in ("later", "decline"):
        named.append(REASONS["grievance"])
    considered = [{"act": other.act, "what": other.what[:120], "effort": other.effort, "chance": other.chance,
                   "gives": other.gives, "parts": {name: round(part, 3) for name, part in other_parts.items()},
                   "worth": round(other_score, 3), "picked": other is option}
                  for other, other_score, other_parts in scored]  # worth: the parts plus her noise
    return Choice(option, score, parts, chances, named, considered, round(temperature, 3))


def reasons(parts: Dict[str, float], rival: Optional[Dict[str, float]] = None, act: str = "do") -> List[str]:
    """Why this choice (of ``act``) beat the best other one, strongest first (or what pulled toward it, alone)."""
    gains = {name: value_ - (rival or {}).get(name, 0.0) for name, value_ in parts.items()}
    giving = act in ("do", "talk")
    named = []
    for name, gain in sorted(gains.items(), key=lambda item: -item[1]):
        if gain < 0.08:
            break
        if name == "learned":  # liked this one, or the other one went badly before
            named.append(REASONS["learned+" if parts[name] > -(rival or {}).get(name, 0.0) else "learned-"])
        elif name == "patience":
            named.append("willing to wait for a likely result")
        elif name == "reacting":  # the thought of this one drew her, or of the other one set her on edge
            named.append(REASONS["eager" if parts[name] > -(rival or {}).get(name, 0.0) else "dread"])
        elif name == "cost":  # sparing herself work counts as a reason only against doing it
            if rival is not None and gain >= 0.25:
                named.append(REASONS["cost"])
        else:
            named.append(REASONS[{"company": "care" if giving else "letdown", "capable": "craft",
                                  "free": "choice" if giving else "reactance", "new": "curiosity"}[name]])
    return list(dict.fromkeys(named))[:3]
