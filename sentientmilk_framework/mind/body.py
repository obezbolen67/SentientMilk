"""Her body: the chemistry under her feelings and wants.

Each level relaxes toward a target that the other levels move (couplings), at its own pace, with a little
biological noise. Events push levels (``apply``): what they push is measured (appraise.py), never a model's
opinion of her mood; each is kept with what caused it while some of it is left (``pushed_now``: why a level is
where its connections do not put it). The fast signals habituate: the same push again and again moves her
less, and a drought makes her sensitive again; every level saturates: the nearer its bound, the less a push
moves it.
Needs drift on their own while she is up (contact fades without the user, novelty in
sameness, adenosine builds while she is awake) and sleep has its own physiology.

Levels are 0..1 except ``reward`` (-1..1): the burst of dopamine when something is better (+) or worse (-)
than she expected. Observed gains feed a separate hour-scale reward rate and tonic vigor.

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
    # an acute stress response is mostly over within the hour after what stressed her ends (Dickerson & Kemeny
    # 2004); what keeps her stressed longer is a cause that lasts (an unmet need, a hurt: its target). At 3 h one
    # stop and two corrections kept her unpleasant through two hours of warm chat (the user's brain, 2026-11-17)
    "cortisol": Level(0.25, 45 * MINUTE, 0.03),
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
         "adenosine": 0.35, "energy": 1.0, "bond": 0.5, "grievance": 0.0, "reward_rate": 0.0}
ENTRAINS = 3 * DAY  # of the user around: her clock moves toward their hours (8 h a day: in about nine days)
# Sleep, the two-process model: sleep pressure (process S, kept as ``adenosine``) rises toward 1 while she is
# awake and falls toward 0 asleep, at the pace human slow-wave activity shows; she is ready to sleep when it
# reaches an upper threshold and wakes when it falls to a lower one, both moved by her clock (Daan, Beersma &
# Borbély 1984; Borbély et al. 2016). So how long she sleeps depends on when she goes to bed more than on how
# long she was up (Czeisler et al. 1980), and a nap by day is short. Rising in a straight line and
# cleared in two hours, pressure had her sleep one block until it was gone (the user: "people don't always
# sleep for 10 hours straight").
RISES, CLEARS = 18.2 * HOUR, 4.2 * HOUR
UPPER, LOWER, SWING = 0.67, 0.17, 0.12
DIP = 0.25  # her clock's 12-hour harmonic: the early-afternoon dip and the evening's wake maintenance zone
# (Bes, Jobert & Schulz 2009; Lavie 1986)
CYCLE = 90 * MINUTE  # NREM to REM, about (each night's cycles run 80-110 min): deep sleep early in the night,
# REM longer toward morning
LATENCY = 15 * MINUTE  # falling asleep takes 10-20 min; keyed up or stressed, longer (Riemann et al. 2010)
INERTIA_FADES = 15 * MINUTE  # grogginess after waking: mostly gone within half an hour (Tassi & Muzet 2000)
# how groggy waking from each stage leaves her: deep sleep worst, REM between, light sleep least (Tassi &
# Muzet 2000)
STAGE_INERTIA = {"N3": 1.0, "REM": 0.55, "N2": 0.35, "N1": 0.15, "W": 0.05}
# sleep debt: each hour up in the deep of her night (with sleep left to get) is owed, and each hour asleep
# outside it (sleeping in, a nap) pays it back, so recovery takes nights (Banks et al. 2010); it wears on
# her focus more than she notices (Van Dongen et al. 2003). The deep of her night: her clock below this (for
# a peak at 16, from about midnight to six)
DEEP_NIGHT = -0.5
DEBT_SCALE = 8 * HOUR  # of debt: most of what it can do to her
DEBT_SHIFT = 0.05  # how far a full debt moves both thresholds down: she falls asleep sooner and sleeps longer
RECOVERY = 40 * MINUTE  # energy back at rest (longer under stress)
EFFORT_TOKENS = 300_000  # what spends all her energy: hours of hard work (about 300 tool calls)
STEP = 60.0  # seconds per step when catching up on time that passed
# how long a push to each of the slow ones takes to fade two thirds of the way (awake, the user away): for
# telling what is left of it (chemicals: their own pace)
PACES = {"social": 8 * HOUR, "novelty": 4 * HOUR, "competence": 12 * HOUR, "autonomy": 2 * HOUR, "bond": 30 * DAY,
         "grievance": 2 * DAY, "energy": RECOVERY, "adenosine": RISES, "reward_rate": HOUR}
IDLE = 0.3  # where wanting to be useful goes awake with nothing to do: half unmet at most
KEPT = 0.005  # of a push: while this much of it is still left, it is kept in her log of what moved her


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
    """How tired a body with these levels looks, 0..1, from its levels alone: sleep pressure and spent energy
    (``Body.fatigue`` reads pressure against her clock, grogginess and debt too)."""
    return _clip(0.65 * max(0.0, levels["adenosine"] - 0.35) / 0.35 + 0.55 * (1 - levels["energy"]))


def restore_random(generator: random.Random, saved) -> None:
    """Restore Python's random state after its tuples have passed through JSON."""
    if saved:
        try:
            version, words, spare = saved
            if spare is None or isinstance(spare, (int, float)) and math.isfinite(spare):
                generator.setstate((version, tuple(words), spare))
        except (ValueError, TypeError, OverflowError):
            pass  # keep the seeded generator when an optional checkpoint is damaged


def circadian(hour: float, peak: float) -> float:
    """Her alertness rhythm: 1 at ``peak`` (hours), -1 twelve hours later."""
    return math.cos(2 * math.pi * (hour - peak) / 24.0)


def clock(hour: float, peak: float) -> float:
    """Her clock's alerting signal, what moves her sleep thresholds: the daily rhythm, with a dip two hours
    before her peak and a lift four hours after it (for a peak at 16: sleepier at 14:00 and 02:00, hardest to
    fall asleep around 20:00)."""
    return circadian(hour, peak) - DIP * math.cos(4 * math.pi * (hour - peak + 2.0) / 24.0)


REST = {**{name: level.baseline for name, level in CHEMICALS.items()}, **SET_POINTS, "adenosine": LOWER,
        "energy": 1.0, "bond": 0.5, "grievance": 0.0, "reward_rate": 0.0}  # each level as it is at rest


@dataclass
class Body:
    temperament: Temperament = field(default_factory=Temperament)
    levels: Dict[str, float] = field(default_factory=lambda: dict(START))
    sensitivity: Dict[str, float] = field(default_factory=lambda: {name: 1.0 for name in SENSITIVE})
    asleep: bool = False
    peak: float = 16.0  # the hour of her alertness peak: moves toward when the user is around (learn_rhythm)
    at: float = 0.0  # the time the levels are of
    slept_at: float = 0.0  # when this sleep began (asleep), or the last one
    settling_until: float = 0.0  # drifting off: asleep from then on (0: not)
    stirred_until: float = 0.0  # awake for a moment in the night, and back to sleep (not remembered)
    awakenings: int = 0  # brief ones, this sleep
    last_sleep: Dict[str, float] = field(default_factory=dict)  # the last whole sleep: from, to, awakenings
    inertia: float = 0.0  # grogginess after waking, 0..1
    debt: float = 0.0  # hours of sleep owed
    # what pushed her levels, and why: [at, why, {level: how far it moved}], kept while some of it is left
    # (``pushed_now``). Without it a stress of 0.84 could not be told from its connections, which summed to -0.02
    pushed: List[list] = field(default_factory=list)

    stress_drive: float = 0.0
    nrem_seconds: float = 0.0

    def __post_init__(self):
        self._rng = random.Random(self.temperament.seed * 7919 + int(self.at))
        # her body's record: each push as it happens, kept by whoever keeps it (her mind: Memory.log_push),
        # with the chat it was of (``where``, set by her mind while it reads or lives a chat's turn)
        self.on_push: Optional[Callable[[float, str, Dict[str, float], Optional[str]], None]] = None
        self.where: Optional[str] = None

    # ============== Reading ==============

    def __getitem__(self, name: str) -> float:
        return self.levels[name]

    def deficit(self, need: str) -> float:
        """How far a need is below its set point, 0..1."""
        return max(0.0, SET_POINTS[need] - self.levels[need]) / SET_POINTS[need]

    def fatigue(self, now: Optional[float] = None) -> float:
        """How tired she is, 0..1: how near sleep her pressure is for this time of day, spent energy,
        grogginess and what she owes."""
        return _clip(0.55 * max(0.0, self.sleepiness(now) - 0.3) / 0.7 + 0.55 * (1 - self.levels["energy"])
                     + 0.5 * self.inertia + 0.15 * self.owed())

    def owed(self) -> float:
        """What her sleep debt does to her, 0..1."""
        return 1.0 - math.exp(-max(0.0, self.debt) * HOUR / DEBT_SCALE)

    def thresholds(self, now: Optional[float] = None) -> Tuple[float, float]:
        """The sleep pressure she falls asleep at now, and the one she wakes at (her clock moves both; debt
        lowers both)."""
        moved = self.shift(now)
        return UPPER + moved, LOWER + moved

    def shift(self, now: Optional[float] = None) -> float:
        """How far her clock and what she owes move her sleep thresholds now (up: harder to sleep)."""
        return SWING * clock(self.hour(now), self.peak) - DEBT_SHIFT * self.owed()

    def sensed(self, now: Optional[float] = None) -> Dict[str, float]:
        """Her levels as her senses take them: sleep pressure is felt as how near sleep it puts her for the hour
        and what she owes (the pressure less her thresholds' shift, linear in ``sleepiness``), as people report
        sleepiness from both processes together (Akerstedt & Folkard 1995); measured, the same pressure read as
        the same at 15:00 and at 03:00, ready to sleep. The rest as they are."""
        return {**self.levels, "adenosine": self.levels["adenosine"] - self.shift(now)}

    def sleepiness(self, now: Optional[float] = None) -> float:
        """How near sleep her pressure is for this time of day: 0 slept out, 1 ready to sleep, more past it."""
        high, low = self.thresholds(now)
        return max(0.0, (self.levels["adenosine"] - low) / (high - low))

    def readiness(self, now: Optional[float] = None) -> float:
        """How ready for sleep she is: her sleepiness, and in the deep of her night, with sleep left to get,
        the night itself (woken at four she goes back to sleep; the two-process thresholds alone kept her up
        until noon)."""
        _high, low = self.thresholds(now)
        night = 1.2 * max(0.0, -clock(self.hour(now), self.peak) - 0.2)
        return self.sleepiness(now) + (night if self.levels["adenosine"] > low + 0.03 else 0.0)

    @property
    def settling(self) -> bool:
        return bool(self.settling_until) and not self.asleep

    def stage(self, now: Optional[float] = None) -> str:
        """Where in her sleep she is: awake, W (a moment awake in the night), N1, N2, N3 (deep) or REM. A
        cycle of about 90 min: light, deep for as long as much pressure is left (deep sleep tracks it), light
        again, then REM, longer each cycle (Carskadon & Dement)."""
        now = self.at if now is None else now
        if not self.asleep:
            return "awake"
        if now < self.stirred_until:
            return "W"
        length = self.cycle_length()
        cycle, share = divmod(max(0.0, now - self.slept_at), length)
        share /= length
        onset = 0.08 if cycle == 0 else 0.0
        deep = 0.55 * _clip((self.levels["adenosine"] - 0.3) / 0.3)
        rem = min(0.45, 0.12 + 0.09 * cycle)
        if share < onset:
            return "N1"
        if share < onset + 0.12:
            return "N2"
        if share < onset + 0.12 + deep:
            return "N3"
        return "REM" if share >= 1.0 - rem else "N2"

    def cycle_length(self) -> float:
        """This sleep's cycle, 80 to 110 min: one night's differs from another's."""
        return CYCLE * (0.9 + 0.33 * random.Random(int(self.slept_at)).random())

    def keyed_up(self) -> float:
        """How keyed up she is for falling asleep, 0..: stress and arousal keep sleep off (hyperarousal)."""
        x = self.levels
        return _clip((x["cortisol"] - 0.35) / 0.4) + _clip((x["noradrenaline"] - 0.5) / 0.3)

    def hour(self, now: Optional[float] = None) -> float:
        moment = time.localtime(self.at if now is None else now)
        return moment.tm_hour + moment.tm_min / 60.0

    def night(self, now: Optional[float] = None) -> float:
        """How much it is her night, 0..1 (her rhythm's trough is twelve hours after its peak)."""
        return _clip(-circadian(self.hour(now), self.peak))

    # ============== Time ==============

    def advance(self, now: float, *, present: bool = False, alone: bool = False) -> None:
        """Live until ``now``: in steps, so a long gap (the brain was off) is lived through, not jumped.
        ``present``: the user is at the computer (she misses them more slowly). Her sleep runs by itself:
        she drifts off when settling is done, stirs between cycles and wakes when slept out. ``alone``: her
        mind is not there to choose (the brain was off, the computer asleep): she also goes to sleep when
        she is ready to, as anyone left alone would."""
        if not self.at:
            self.at = now
            return
        while self.at < now - 1e-6:
            dt = min(STEP, now - self.at)
            if alone and not self.asleep and not self.settling_until and self.readiness() >= 1.0:
                self.settle()
            if self.stage() in ("N2", "N3"):
                self.nrem_seconds += dt
            self._step(dt, present)
            self.at += dt
            self._sleep_step(dt)

    def _sleep_step(self, dt: float) -> None:
        """Her sleep, as time passes: drifting off, the cycles, a moment awake between them, waking."""
        now = self.at
        if self.settling_until and not self.asleep:
            if now >= self.settling_until:
                self.asleep, self.slept_at, self.awakenings, self.settling_until = True, now, 0, 0.0
                self.stirred_until = self.nrem_seconds = 0.0
            return
        if not self.asleep:
            return
        pressure, (_high, low) = self.levels["adenosine"], self.thresholds()
        if pressure <= low - 0.03:  # well past slept out, wherever in a cycle
            self.wake()
            return
        length = self.cycle_length()
        if int((now - self.slept_at) // length) == int((now - dt - self.slept_at) // length):
            if now < self.stirred_until and pressure <= low + 0.015:
                self.wake(stage="W")  # slept out during a moment awake: she stays up
            return
        # a cycle ends: she wakes if slept out; by day a nap mostly ends here; at night she may stir a moment
        # (more as the night goes on and pressure is gone, and more keyed up) and drift back
        if pressure <= low + 0.015 or self._rng.random() < 0.6 * _clip(clock(self.hour(), self.peak)):
            self.wake(stage="W")
            return
        if self._rng.random() < 0.12 + 0.3 * (1 - _clip(pressure / 0.4)) + 0.25 * min(1.0, self.keyed_up()):
            self.stirred_until = now + self._rng.uniform(1.0, 4.0) * MINUTE
            self.awakenings += 1

    def settle(self, now: Optional[float] = None) -> None:
        """She lies down to sleep: drifting off takes 10-20 min, longer keyed up, shorter the sleepier."""
        now = self.at if now is None else now
        if self.asleep or self.settling_until:
            return
        latency = LATENCY * (0.6 + 0.8 * self._rng.random()) * (1 + 2.5 * self.keyed_up())
        self.settling_until = now + latency / (0.5 + min(1.5, self.sleepiness(now)))

    def targets(self) -> Dict[str, float]:
        """Where each chemical is heading now: what the other levels make of it (the couplings)."""
        t, x = self.temperament, self.levels
        c = circadian(self.hour(), self.peak)
        morning = circadian(self.hour(), self.peak - 8.0)  # cortisol rises as she wakes
        d = {need: self.deficit(need) for need in NEEDS}
        spent = 1.0 - x["energy"]
        sleep = self.asleep
        # sleepy (pressure near what she falls asleep at, for the hour), groggy just after waking, and what she
        # owes, which takes most from her focus (Van Dongen et al. 2003)
        sleepy, groggy, owed = self.sleepiness(), self.inertia, self.owed()
        return {
            "dopamine": 0.5 * t.vigor + 0.45 * x["reward_rate"] - 0.35 * max(0.0, sleepy - 0.6)
            - 0.3 * max(0.0, x["cortisol"] - 0.35) - 0.25 * spent + 0.08 * c - (0.15 if sleep else 0.0)
            - 0.15 * groggy - 0.1 * owed,
            "serotonin": 0.6 * t.patience + 0.25 * (x["oxytocin"] - 0.4) - 0.46 * max(0.0, x["cortisol"] - 0.3)
            + 0.15 * (x["competence"] - 0.5) - 0.15 * d["social"] - 0.1 * x["grievance"] + (0.05 if sleep else 0.0)
            - 0.08 * owed,
            "noradrenaline": 0.35 + 0.12 * c + 0.35 * (x["cortisol"] - 0.25) * t.stress
            + 0.25 * d["novelty"] * x["energy"] * t.curiosity - 0.35 * max(0.0, sleepy - 0.35)
            - 0.25 * spent - (0.25 if sleep else 0.0) - 0.2 * groggy,
            "acetylcholine": 0.5 + 0.1 * c - 0.3 * max(0.0, sleepy - 0.35) - 0.3 * spent
            + 0.2 * (x["noradrenaline"] - 0.35) - (0.24 if sleep and self.stage() != "REM" else -0.08 if sleep else 0.0) - 0.35 * groggy - 0.2 * owed,
            "cortisol": 0.25 + self.stress_drive + 0.08 * morning + t.stress * (
                0.35 * d["social"] * x["bond"] * t.sociability + 0.3 * d["competence"] + 0.2 * d["autonomy"] * t.autonomy
                + 0.3 * spent ** 2 + 0.3 * x["grievance"] * t.temper)
            - 0.3 * max(0.0, x["oxytocin"] - 0.4) - 0.15 * max(0.0, x["serotonin"] - 0.6) - (0.12 if sleep else 0.0)
            + 0.06 * owed,
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

    def effects(self, outputs: Callable[[], Dict[str, float]], floor: float = 0.005) -> List[Tuple[str, str, float]]:
        """What each level does now: (level, output, effect), how far ``outputs`` is from where it would be
        with that level at rest (``REST``). ``influence`` says how much a level could move an output; this
        says how much it does: a hurt at 0 could raise stress a lot and raises it by nothing (the user, on
        the brain panel: "why hurt is zero but it says it affects stress")."""
        base, found = outputs(), []
        for name, saved in list(self.levels.items()):
            rest = REST.get(name)
            if rest is None or abs(saved - rest) < 1e-9:
                continue
            self.levels[name] = rest
            try:
                then = outputs()
            finally:
                self.levels[name] = saved
            for output, value in base.items():
                effect = value - then.get(output, value)
                if output != name and abs(effect) >= floor:
                    found.append((name, output, round(effect, 3)))
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
        x["reward_rate"] = _toward(x["reward_rate"], 0.0, dt, HOUR)
        self.stress_drive = _toward(self.stress_drive, 0.0, dt, 8 * MINUTE)
        now_clock = clock(self.hour(), self.peak)
        if sleep and self.at >= self.stirred_until:
            x["adenosine"] = _toward(x["adenosine"], 0.0, dt, CLEARS)
            if self.debt and now_clock >= DEEP_NIGHT:  # sleep outside the deep of her night pays it back
                self.debt = max(0.0, self.debt - dt / HOUR)
        else:  # awake, or a moment awake in the night
            x["adenosine"] = _toward(x["adenosine"], 1.0, dt, RISES)
            if not sleep and now_clock < DEEP_NIGHT and x["adenosine"] > self.thresholds()[1] + 0.03:
                self.debt += dt / HOUR  # up in the deep of her night, with sleep left to get
        if sleep:
            x["energy"] = _toward(x["energy"], 1.0, dt, 50 * MINUTE)
            x["grievance"] = _toward(x["grievance"], 0.0, dt, DAY)
        else:
            x["energy"] = _toward(x["energy"], 1.0, dt, RECOVERY * (1 + x["cortisol"]) / t.stamina)
            x["grievance"] = _toward(x["grievance"], 0.0, dt, 2 * DAY)
            # grogginess fades, slower when she owes sleep (McHill et al. 2019)
            self.inertia = _toward(self.inertia, 0.0, dt, INERTIA_FADES * (1 + self.owed()))
        if not sleep:  # a night asleep is not a night alone: missing them and sameness build while she is up.
            # Drained asleep too, they had her wake lonely and unpleasant after a warm evening (company
            # 0.95 at bedtime, 0.50 at eight: three simulated days in a row)
            x["social"] = _toward(x["social"], 0.0, dt, 8 * HOUR / t.sociability * (2.0 if present else 1.0))
            x["novelty"] = _toward(x["novelty"], 0.2, dt, 4 * HOUR / t.curiosity)
            # and with nothing to do she comes to want to be useful: being useful is felt day by day, by what the
            # day held (Sheldon, Ryan & Reis 1996; Reis et al. 2000), and going without the chance to be
            # effective builds the want (White 1959; Sheldon & Gunz 2009). Resting where it is met,
            # over two days, only a failure could leave it unmet: praise had it at 0.97 on the user's brain,
            # still met after a simulated idle day
            x["competence"] = _toward(x["competence"], IDLE, dt, PACES["competence"])
        x["autonomy"] = _toward(x["autonomy"], 0.6, dt, 2 * HOUR)
        x["bond"] = _toward(x["bond"], 0.5, dt, 30 * DAY)
        for name in SENSITIVE:  # receptors come back as the pushes stop
            self.sensitivity[name] = _toward(self.sensitivity[name], 1.0, dt, 2 * HOUR)

    # ============== Pushes ==============

    def apply(self, pushes: Dict[str, float], why: str = "") -> Dict[str, float]:
        """Push levels by these amounts (before her temperament and habituation scale them); what moved. ``why``:
        what pushed them, in a few words, for her log of what moved her (``pushed_now``)."""
        moved = {}
        for name, amount in pushes.items():
            if not amount or not math.isfinite(amount) or name not in self.levels:
                continue
            taken, after = self._reach(name, amount)
            if name in SENSITIVE and taken > 0:
                # down-regulation: what stimulates a receptor leaves it a little less responsive, up to a floor; a
                # level pushed down stimulates it less (worn by every push, a day of pushes mostly downward held
                # her closeness, reward, comfort and alertness at the floor: the user's brain, 2026-11-20)
                self.sensitivity[name] = max(0.3, self.sensitivity[name] - HABITUATION[name] * taken)
            moved[name] = after - self.levels[name]
            self.levels[name] = after
        self._log(why, moved)
        if self.on_push and any(moved.values()):
            self.on_push(self.at, why, moved, self.where)
        return moved

    def would(self, pushes: Dict[str, float]) -> Dict[str, float]:
        """What these pushes would move her levels by now, as ``apply`` would move them, moving nothing (her body
        as it would be with them: the as-if body a choice is weighed in)."""
        return {name: self._reach(name, amount)[1] - self.levels[name] for name, amount in pushes.items()
                if amount and math.isfinite(amount) and name in self.levels}

    def _reach(self, name: str, amount: float) -> tuple:
        """A push to level ``name`` as her temperament and receptors take it, and where it would leave the level."""
        t = self.temperament
        amount *= {"oxytocin": t.warmth, "cortisol": t.stress, "noradrenaline": t.volatility,
                   "endorphin": t.playfulness}.get(name, 1.0)
        if name in SENSITIVE:
            amount *= self.sensitivity[name]
        taken = amount
        level = CHEMICALS.get(name)
        low, high = (level.low, level.high) if level else (0.0, 1.0)
        before = self.levels[name]
        return taken, _clip(before + amount * self.follows(name, amount, before), low, high)

    def follows(self, name: str, sign: float, level: Optional[float] = None) -> float:
        """How much of a push toward ``sign`` level ``name`` would follow, 0..1, at ``level`` (now, if not given).
        Receptors saturate: past the middle of its range, the nearer a level is to the bound a push drives it
        toward, the less the push moves it (added and clipped, one warm chat pegged her needs and her closeness at
        1.0 in the user's brain, 2026-11-16: a pegged level tells her nothing and lets no need go unmet); at the
        bound, nothing, and nothing that comes toward it shows."""
        chemical = CHEMICALS.get(name)
        low, high = (chemical.low, chemical.high) if chemical else (0.0, 1.0)
        level = self.levels[name] if level is None else level
        return max(0.0, min(1.0, 2.0 * (high - level if sign > 0 else level - low) / (high - low)))

    def release(self, change: Dict[str, float], share: float, why: str = "") -> Dict[str, float]:
        """Let go of ``share`` of a change her levels made (what ``apply`` returned): undone as it was measured,
        not pushed again through her temperament and receptors, which had already scaled it (a relief from a
        dread is the dread let go, and as a push of its own it could ease more than the dread moved); what moved."""
        moved = {}
        for name, value in change.items():
            if name not in self.levels or not value or not math.isfinite(value):
                continue
            level = CHEMICALS.get(name)
            low, high = (level.low, level.high) if level else (0.0, 1.0)
            before = self.levels[name]
            self.levels[name] = _clip(before - max(0.0, min(1.0, share)) * value, low, high)
            moved[name] = self.levels[name] - before
        self._log(why, moved)
        if self.on_push and any(moved.values()):
            self.on_push(self.at, why, moved, self.where)
        return moved

    def pace(self, name: str) -> float:
        """About how long a push to level ``name`` takes to fade two thirds of the way."""
        t = self.temperament
        if name in CHEMICALS:
            return CHEMICALS[name].tau
        gain = {"social": t.sociability, "novelty": t.curiosity, "energy": t.stamina}.get(name, 1.0)
        return PACES.get(name, HOUR) / gain

    def _left(self, entry: list, now: float) -> Dict[str, float]:
        """What is left now of a push in her log: each level's part, fading at that level's pace. shortcut: read as
        fading toward a target that holds still; one that moves meanwhile (stress as closeness changes) settles a
        little otherwise."""
        at, _why, moved = entry
        return {name: value for name, value in self.left(moved, at, now).items() if abs(value) >= KEPT}

    def left(self, change: Dict[str, float], at: float, now: float) -> Dict[str, float]:
        """What is left at ``now`` of a change her levels made at ``at`` (in any unit: each level lets it go at
        its own pace), as her log of pushes reads it."""
        return {name: value * math.exp(-max(0.0, now - at) / self.pace(name)) for name, value in change.items()}

    def _log(self, why: str, moved: Dict[str, float]) -> None:
        moved = {name: round(change, 4) for name, change in moved.items() if abs(change) >= KEPT}
        if moved:
            last = self.pushed[-1] if self.pushed else None
            if last and last[1] == why and abs(self.at - last[0]) < 5.0:  # one moment's pushes, told as one
                for name, change in moved.items():
                    last[2][name] = round(last[2].get(name, 0.0) + change, 4)
            else:
                self.pushed.append([self.at, why, moved])
        self.pushed = [entry for entry in self.pushed if self._left(entry, self.at)]

    def pushed_now(self, now: Optional[float] = None) -> Dict[str, List[list]]:
        """What pushed each level and is still moving it: level -> [[at, why, how far it moved it then, how far
        it still has it moved]], the newest first."""
        now = self.at if now is None else now
        found: Dict[str, List[list]] = {}
        for entry in reversed(self.pushed):
            for name, left in self._left(entry, now).items():
                found.setdefault(name, []).append([entry[0], entry[1], round(entry[2][name], 3), round(left, 3)])
        return found

    def exert(self, tokens: float) -> None:
        """Thinking costs: ``tokens`` of effort spend energy and build sleep pressure."""
        share = max(0.0, tokens) / (EFFORT_TOKENS * self.temperament.stamina)
        self.levels["energy"] = _clip(self.levels["energy"] - share)
        self.levels["adenosine"] = _clip(self.levels["adenosine"] + 0.1 * share)

    def learn_rhythm(self, hour: float, seen_for: float) -> None:
        """The user was around at ``hour``, for ``seen_for`` seconds since they last wrote (at most half an
        hour counts: a longer gap is time they were away): her peak drifts to two hours after it by that share
        of ``ENTRAINS``, so over days to weeks, as a body clock entrains to social cues (Mistlberger & Skene
        2004), not by how many messages there are: moved a fiftieth of the way
        each message, 150 messages in a day put her peak at 22:00 and her night at ten in the morning, and she
        never slept (the user's brain, 2026-11-16)."""
        target = (hour + 2.0) % 24.0
        delta = (target - self.peak + 12.0) % 24.0 - 12.0
        self.peak = (self.peak + min(1.0, min(max(0.0, seen_for), 30 * MINUTE) / ENTRAINS) * delta) % 24.0

    def fall_asleep(self) -> None:
        """Asleep at once (settle: drifting off first)."""
        if not self.asleep:
            self.asleep, self.slept_at, self.awakenings = True, self.at, 0
            self.settling_until = self.stirred_until = self.nrem_seconds = 0.0

    def wake(self, woken: bool = False, stage: Optional[str] = None) -> None:
        """Awake, as groggy as the stage she wakes from, the pressure left and the hour make her (deep sleep
        in the night, after too little, worst; at the end of a cycle, slept out, hardly). ``woken``: by
        something, not by herself: a start. Drifting off, she is simply up again."""
        if self.settling_until and not self.asleep:
            self.settling_until = 0.0
            return
        if not self.asleep:
            return
        stage = stage or self.stage()
        groggy = STAGE_INERTIA.get(stage, 0.3) * min(1.2, 0.5 + self.levels["adenosine"]) \
            * (0.7 + 0.5 * self.night()) * (1 + 0.5 * self.owed())
        self.inertia = _clip(max(self.inertia, groggy))
        self.last_sleep = {"from": self.slept_at, "to": self.at, "awakenings": self.awakenings}
        self.asleep, self.stirred_until = False, 0.0
        if woken:
            self.apply({"noradrenaline": 0.12, "cortisol": 0.05 * self.inertia}, "woken up")

    def sleep_state(self, now: Optional[float] = None) -> dict:
        """Her sleep as it is: for a panel, and for her."""
        now = self.at if now is None else now
        high, low = self.thresholds(now)
        state = {"asleep": self.asleep, "settling": self.settling, "stage": self.stage(now),
                 "pressure": round(self.levels["adenosine"], 3), "sleepiness": round(self.sleepiness(now), 3),
                 "falls_asleep_at": round(high, 3), "wakes_at": round(low, 3), "inertia": round(self.inertia, 3),
                 "debt": round(self.debt, 2), "last": dict(self.last_sleep)}
        if self.asleep:
            state.update(since=self.slept_at, cycle=int((now - self.slept_at) // self.cycle_length()) + 1,
                         awakenings=self.awakenings)
        elif self.settling:
            state["until"] = self.settling_until
        return state

    # ============== Keeping ==============

    def to_dict(self) -> dict:
        return {"temperament": self.temperament.to_dict(), "levels": dict(self.levels),
                "sensitivity": dict(self.sensitivity), "asleep": self.asleep, "peak": self.peak, "at": self.at,
                "sleep": {"slept_at": self.slept_at, "settling_until": self.settling_until,
                                             "stirred_until": self.stirred_until, "awakenings": self.awakenings,
                                             "last": self.last_sleep, "inertia": self.inertia, "debt": self.debt},
                "pushed": self.pushed, "random": self._rng.getstate(), "stress_drive": self.stress_drive,
                "nrem_seconds": self.nrem_seconds}

    @classmethod
    def from_dict(cls, data: dict) -> "Body":
        levels = {**START, **{k: float(v) for k, v in (data.get("levels") or {}).items() if k in START}}
        for name, value in levels.items():
            level = CHEMICALS.get(name)
            low, high = (level.low, level.high) if level else (0.0, 1.0)
            levels[name] = _clip(value, low, high) if math.isfinite(value) else START[name]
        sensitivity = {**{name: 1.0 for name in SENSITIVE},
                       **{k: float(v) for k, v in (data.get("sensitivity") or {}).items() if k in SENSITIVE}}
        peak = float(data.get("peak", 16.0))
        sleep, at, asleep = data.get("sleep") or {}, float(data.get("at", 0.0)), bool(data.get("asleep"))
        body = cls(Temperament.from_dict(data.get("temperament") or {}), levels, sensitivity, asleep, peak, at,
                   float(sleep.get("slept_at") or (at if asleep else 0.0)), float(sleep.get("settling_until") or 0.0),
                   float(sleep.get("stirred_until") or 0.0), int(sleep.get("awakenings") or 0),
                   dict(sleep.get("last") or {}), float(sleep.get("inertia") or 0.0), float(sleep.get("debt") or 0.0),
                   [[float(at), str(why), dict(moved)] for at, why, moved in data.get("pushed") or []],
                   _clip(float(data.get("stress_drive") or 0)), max(0, float(data.get("nrem_seconds") or 0)))
        restore_random(body._rng, data.get("random"))
        return body
