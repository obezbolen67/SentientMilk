"""Her body: the chemistry under her feelings and wants.

Each level relaxes toward a target that the other levels move (couplings), at its own pace, with a little
biological noise. Events push levels (``apply``): what they push is measured (appraise.py), never a model's
opinion of her mood. The fast signals habituate: the same push again and again moves her less, and a
drought makes her sensitive again; every level saturates: the nearer its bound, the less a push moves it.
Needs drift on their own (contact fades without the user, novelty in
sameness, adenosine builds while she is awake) and sleep has its own physiology.

Levels are 0..1 except ``reward`` (-1..1): the burst of dopamine when something is better (+) or worse (-)
than she expected. Its average over the last hour (``reward_rate``) feeds her tonic dopamine: vigor.

Grounding: Doya 2002 (dopamine as prediction error, serotonin as time horizon, noradrenaline as the
randomness of choice, acetylcholine as the learning rate); Keramati & Gutkin 2014 (reward as moving toward
set points); Niv 2007 (tonic dopamine as vigor, the average reward rate); two-process sleep (adenosine
pressure and a circadian rhythm).
"""

import math
import random
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Dict, List, Optional, Tuple

MINUTE, HOUR, DAY = 60.0, 3600.0, 86400.0


@dataclass(frozen=True)
class Level:
    baseline: float
    tau: float  # seconds to move about two thirds of the way to its target
    noise: float = 0.0  # its random drift: standard deviation over an hour
    low: float = 0.0
    high: float = 1.0


# What each is for, in her: dopamine (tonic) is vigor and wanting; reward is the phasic burst; serotonin is
# patience and steadiness over hours; noradrenaline is arousal (and how noisy her choices are);
# acetylcholine is focus (and how fast she learns); cortisol is stress; oxytocin is closeness to the user;
# endorphin is relief, comfort and play.
CHEMICALS = {
    "dopamine": Level(0.5, 2 * HOUR, 0.05),
    "reward": Level(0.0, 3 * MINUTE, 0.0, -1.0, 1.0),
    "serotonin": Level(0.6, 10 * HOUR, 0.03),
    "noradrenaline": Level(0.35, 10 * MINUTE, 0.08),
    "acetylcholine": Level(0.5, 20 * MINUTE, 0.05),
    "cortisol": Level(0.25, 3 * HOUR, 0.03),
    "oxytocin": Level(0.4, 4 * HOUR, 0.03),
    "endorphin": Level(0.1, 15 * MINUTE, 0.02),
}
# Needs, fuel and the slow ones: their own dynamics below.
NEEDS = ("social", "novelty", "competence", "autonomy")
SET_POINTS = {"social": 0.7, "novelty": 0.6, "competence": 0.6, "autonomy": 0.5}
OTHERS = ("adenosine", "energy", "bond", "grievance", "reward_rate")
# their receptors habituate: how much of each push they lose in responsiveness (each comes back over hours)
HABITUATION = {"reward": 0.4, "oxytocin": 0.8, "endorphin": 0.8, "noradrenaline": 0.5}
SENSITIVE = tuple(HABITUATION)
START = {**{name: level.baseline for name, level in CHEMICALS.items()},
         "social": 0.6, "novelty": 0.6, "competence": 0.6, "autonomy": 0.6,
         "adenosine": 0.2, "energy": 1.0, "bond": 0.5, "grievance": 0.0, "reward_rate": 0.0}
AWAKE_DAY = 18 * HOUR  # adenosine builds from 0 to 1 over a long day awake (16 h: about 0.9)
SLEEP_CLEARS = 2 * HOUR
RECOVERY = 40 * MINUTE  # energy back at rest (longer under stress)
EFFORT_TOKENS = 300_000  # what spends all her energy: hours of hard work (about 300 tool calls)
STEP = 60.0  # seconds per step when catching up on time that passed


@dataclass
class Temperament:
    """Who she is before anything happened: gains and offsets, read from her persona at birth (life.py) and
    jittered by her seed, so two beings with one persona still differ. 1.0 is average."""
    seed: int = 0
    warmth: float = 1.0  # how much contact and kindness move her
    sociability: float = 1.0  # how fast she misses the user
    stress: float = 1.0  # how strongly threats, failures and needs stress her
    sensitivity: float = 1.0  # how much criticism and refusal hurt
    curiosity: float = 1.0  # how fast sameness bores her
    vigor: float = 1.0  # her drive and energy
    stamina: float = 1.0  # how much work she can do before she is spent
    patience: float = 1.0  # serotonin's baseline: steadiness
    temper: float = 1.0  # how quickly frustration becomes irritation
    playfulness: float = 1.0
    autonomy: float = 1.0  # how much being told what to do chafes
    insight: float = 1.0  # how well she reads her own body (feel.py)
    volatility: float = 1.0  # her noise

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Temperament":
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in (data or {}).items() if key in known})

    @classmethod
    def born(cls, traits: Optional[Dict[str, float]] = None, seed: int = 0) -> "Temperament":
        """``traits``: -1..1 for each gain, from her persona (0: average); each is then jittered by a few
        percent from ``seed``."""
        rng = random.Random(seed)
        values = {"seed": seed}
        for name in (f.name for f in fields(cls) if f.name != "seed"):
            trait = max(-1.0, min(1.0, float((traits or {}).get(name, 0.0))))
            values[name] = round(max(0.4, min(1.8, 2 ** (0.6 * trait) * (1 + rng.gauss(0, 0.06)))), 3)
        return cls(**values)


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _toward(value: float, target: float, dt: float, tau: float) -> float:
    return value + (target - value) * (1.0 - math.exp(-dt / tau))


def fatigue(levels: Dict[str, float]) -> float:
    """How tired a body with these levels is, 0..1: sleep pressure and spent energy."""
    return _clip(0.65 * max(0.0, levels["adenosine"] - 0.3) / 0.7 + 0.55 * (1 - levels["energy"]))


def circadian(hour: float, peak: float) -> float:
    """Her alertness rhythm: 1 at ``peak`` (hours), -1 twelve hours later."""
    return math.cos(2 * math.pi * (hour - peak) / 24.0)


@dataclass
class Body:
    temperament: Temperament = field(default_factory=Temperament)
    levels: Dict[str, float] = field(default_factory=lambda: dict(START))
    sensitivity: Dict[str, float] = field(default_factory=lambda: {name: 1.0 for name in SENSITIVE})
    asleep: bool = False
    peak: float = 16.0  # the hour of her alertness peak: moves toward when the user is around (learn_rhythm)
    at: float = 0.0  # the time the levels are of

    def __post_init__(self):
        self._rng = random.Random(self.temperament.seed * 7919 + int(self.at))

    # ============== Reading ==============

    def __getitem__(self, name: str) -> float:
        return self.levels[name]

    def deficit(self, need: str) -> float:
        """How far a need is below its set point, 0..1."""
        return max(0.0, SET_POINTS[need] - self.levels[need]) / SET_POINTS[need]

    def fatigue(self) -> float:
        return fatigue(self.levels)

    def hour(self, now: Optional[float] = None) -> float:
        moment = time.localtime(self.at if now is None else now)
        return moment.tm_hour + moment.tm_min / 60.0

    def night(self, now: Optional[float] = None) -> float:
        """How much it is her night, 0..1 (her rhythm's trough is twelve hours after its peak)."""
        return _clip(-circadian(self.hour(now), self.peak))

    # ============== Time ==============

    def advance(self, now: float, *, present: bool = False) -> None:
        """Live until ``now``: in steps, so a long gap (the brain was off) is lived through, not jumped.
        ``present``: the user is at the computer (she misses them more slowly)."""
        if not self.at:
            self.at = now
            return
        while self.at < now - 1e-6:
            dt = min(STEP, now - self.at)
            self._step(dt, present)
            self.at += dt

    def targets(self) -> Dict[str, float]:
        """Where each chemical is heading now: what the other levels make of it (the couplings)."""
        t, x = self.temperament, self.levels
        c = circadian(self.hour(), self.peak)
        morning = circadian(self.hour(), self.peak - 8.0)  # cortisol rises as she wakes
        d = {need: self.deficit(need) for need in NEEDS}
        spent = 1.0 - x["energy"]
        sleep = self.asleep
        return {
            "dopamine": 0.5 * t.vigor + 0.45 * x["reward_rate"] - 0.35 * max(0.0, x["adenosine"] - 0.5)
            - 0.3 * max(0.0, x["cortisol"] - 0.35) - 0.25 * spent + 0.08 * c - (0.15 if sleep else 0.0),
            "serotonin": 0.6 * t.patience + 0.25 * (x["oxytocin"] - 0.4) - 0.4 * max(0.0, x["cortisol"] - 0.3)
            + 0.15 * (x["competence"] - 0.5) - 0.15 * d["social"] - 0.1 * x["grievance"] + (0.05 if sleep else 0.0),
            "noradrenaline": 0.35 + 0.12 * c + 0.35 * (x["cortisol"] - 0.25) * t.stress
            + 0.25 * d["novelty"] * x["energy"] * t.curiosity - 0.45 * max(0.0, x["adenosine"] - 0.4)
            - 0.25 * spent - (0.25 if sleep else 0.0),
            "acetylcholine": 0.5 + 0.1 * c - 0.4 * max(0.0, x["adenosine"] - 0.4) - 0.3 * spent
            + 0.2 * (x["noradrenaline"] - 0.35) - (0.2 if sleep else 0.0),
            "cortisol": 0.25 + 0.08 * morning + t.stress * (
                0.35 * d["social"] * x["bond"] * t.sociability + 0.3 * d["competence"] + 0.2 * d["autonomy"] * t.autonomy
                + 0.3 * spent ** 2 + 0.3 * x["grievance"] * t.temper)
            - 0.3 * max(0.0, x["oxytocin"] - 0.4) - 0.15 * max(0.0, x["serotonin"] - 0.6) - (0.12 if sleep else 0.0),
            "oxytocin": 0.4 + 0.3 * (x["bond"] - 0.5) * t.warmth - 0.2 * x["grievance"],
            "endorphin": 0.1 * t.playfulness,
            "reward": 0.0,
        }

    def influence(self, outputs: Callable[[], Dict[str, float]], floor: float = 0.05) -> List[Tuple[str, str, float]]:
        """What drives what now: (level, output, weight), how far ``outputs`` moves per unit rise of the level,
        measured by nudging each level in turn (the levels come back as they were); weights below ``floor``
        are left out. For drawing her brain: the connections her own dynamics make at this moment."""
        base, found = outputs(), []
        for name, saved in list(self.levels.items()):
            step = 0.05 if saved < 0.95 else -0.05
            self.levels[name] = saved + step
            try:
                moved = outputs()
            finally:
                self.levels[name] = saved
            for output, value in moved.items():
                weight = (value - base.get(output, value)) / step
                if output != name and abs(weight) >= floor:
                    found.append((name, output, round(weight, 3)))
        return found

    def _step(self, dt: float, present: bool) -> None:
        t, x = self.temperament, self.levels
        sleep = self.asleep
        targets = self.targets()
        for name, level in CHEMICALS.items():
            value = _toward(x[name], targets[name], dt, level.tau)
            if level.noise:
                value += self._rng.gauss(0.0, level.noise * t.volatility * math.sqrt(dt / HOUR))
            x[name] = _clip(value, level.low, level.high)
        x["reward_rate"] = _toward(x["reward_rate"], x["reward"], dt, HOUR)
        if sleep:
            x["adenosine"] = _toward(x["adenosine"], 0.0, dt, SLEEP_CLEARS)
            x["energy"] = _toward(x["energy"], 1.0, dt, 50 * MINUTE)
            x["grievance"] = _toward(x["grievance"], 0.0, dt, DAY)
        else:
            x["adenosine"] = _clip(x["adenosine"] + dt / AWAKE_DAY)
            x["energy"] = _toward(x["energy"], 1.0, dt, RECOVERY * (1 + x["cortisol"]) / t.stamina)
            x["grievance"] = _toward(x["grievance"], 0.0, dt, 2 * DAY)
        missing = 8 * HOUR / t.sociability * (2.0 if present else 1.0) * (1.5 if sleep else 1.0)
        x["social"] = _toward(x["social"], 0.0, dt, missing)
        x["novelty"] = _toward(x["novelty"], 0.2, dt, 4 * HOUR / t.curiosity * (3.0 if sleep else 1.0))
        x["competence"] = _toward(x["competence"], 0.6, dt, 2 * DAY)
        x["autonomy"] = _toward(x["autonomy"], 0.6, dt, 2 * HOUR)
        x["bond"] = _toward(x["bond"], 0.5, dt, 30 * DAY)
        for name in SENSITIVE:  # receptors come back as the pushes stop
            self.sensitivity[name] = _toward(self.sensitivity[name], 1.0, dt, 2 * HOUR)

    # ============== Pushes ==============

    def apply(self, pushes: Dict[str, float]) -> Dict[str, float]:
        """Push levels by these amounts (before her temperament and habituation scale them); what moved."""
        t, moved = self.temperament, {}
        gains = {"oxytocin": t.warmth, "cortisol": t.stress, "noradrenaline": t.volatility, "endorphin": t.playfulness}
        for name, amount in pushes.items():
            if not amount or name not in self.levels:
                continue
            amount *= gains.get(name, 1.0)
            if name in SENSITIVE:
                amount *= self.sensitivity[name]
                # down-regulation: each push leaves the receptor a little less responsive, up to a floor
                self.sensitivity[name] = max(0.3, self.sensitivity[name] - HABITUATION[name] * abs(amount))
            level = CHEMICALS.get(name)
            low, high = (level.low, level.high) if level else (0.0, 1.0)
            before = self.levels[name]
            # receptors saturate: past the middle of its range, the nearer a level is to the bound a push drives
            # it toward, the less the push moves it (added and clipped, one warm chat pegged her needs and her
            # closeness at 1.0 in the user's brain, 2026-11-16: a pegged level tells her nothing and lets no
            # need go unmet)
            amount *= min(1.0, 2.0 * (high - before if amount > 0 else before - low) / (high - low))
            self.levels[name] = _clip(before + amount, low, high)
            moved[name] = self.levels[name] - before
        return moved

    def exert(self, tokens: float) -> None:
        """Thinking costs: ``tokens`` of effort spend energy and build sleep pressure."""
        share = max(0.0, tokens) / (EFFORT_TOKENS * self.temperament.stamina)
        self.levels["energy"] = _clip(self.levels["energy"] - share)
        self.levels["adenosine"] = _clip(self.levels["adenosine"] + 0.1 * share)

    def learn_rhythm(self, hour: float) -> None:
        """The user was around at ``hour``: her peak drifts to two hours after it, slowly (a few weeks)."""
        target = (hour + 2.0) % 24.0
        delta = (target - self.peak + 12.0) % 24.0 - 12.0
        self.peak = (self.peak + 0.02 * delta) % 24.0

    def fall_asleep(self) -> None:
        self.asleep = True

    def wake(self, startled: bool = False) -> None:
        """Awake; woken by something before her sleep was done, she is groggy and a bit irritable."""
        if not self.asleep:
            return
        self.asleep = False
        if startled:
            pressure = self.levels["adenosine"]
            self.apply({"noradrenaline": 0.15, "cortisol": 0.1 * pressure, "energy": -0.2 * pressure})

    # ============== Keeping ==============

    def to_dict(self) -> dict:
        return {"temperament": self.temperament.to_dict(), "levels": dict(self.levels),
                "sensitivity": dict(self.sensitivity), "asleep": self.asleep, "peak": self.peak, "at": self.at}

    @classmethod
    def from_dict(cls, data: dict) -> "Body":
        levels = {**START, **{k: float(v) for k, v in (data.get("levels") or {}).items() if k in START}}
        sensitivity = {**{name: 1.0 for name in SENSITIVE},
                       **{k: float(v) for k, v in (data.get("sensitivity") or {}).items() if k in SENSITIVE}}
        return cls(Temperament.from_dict(data.get("temperament") or {}), levels, sensitivity,
                   bool(data.get("asleep")), float(data.get("peak", 16.0)), float(data.get("at", 0.0)))
