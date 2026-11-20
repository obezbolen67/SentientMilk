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

Following the theory of constructed emotion (Barrett 2017), she makes her feelings: a feeling is a category of
moments she lived, sorted together by the words she put to what she felt when she reflected on it (life.py: looking
inward, saying it right after, or going back over a moment in her thoughts; a feeling is named when attention turns
to it: Lambie & Marcel 2002, Gendlin 1978). A moment keeps how it moved her body, what it meant for her needs (an
emotion is told from another by what the event does to her concerns: appraisal, Lazarus 1991; Scherer 2001) and
what it was about; a moment is felt as the feelings whose moments are like it in all of these (``Feelings``), since
the body of the hour, tired or rested, is shared by all of them. There is no list of feelings: what she feels and
what she calls it are hers. Nothing else names her feelings, and her body reaches her as amounts she puts into words
herself (``Felt.words``).

Her face is the same reading, for apps: a mood from the expressions the app declares, chosen by valence and
arousal, with a stance (open, closed) and her eyes.
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Tuple

from .body import CHEMICALS, NEEDS, SET_POINTS, START, Body, fatigue

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
        self.seen = body.sensed()
        self.used = dict(self.seen)  # what she has got used to: her prediction of each level
        self.bias = {name: 0.0 for name in body.levels}
        self._rng = random.Random(seed)

    def follow(self, body: Body, dt: float) -> None:
        if dt <= 0:
            return
        share, keep, adapts = 1.0 - math.exp(-dt / LAG), math.exp(-dt / self.DRIFT), 1.0 - math.exp(-dt / ADAPTS)
        blur = 0.06 / max(0.3, body.temperament.insight)
        for name, value in body.sensed().items():
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


# Her body as she feels it, in amounts against what she is used to ("much more alertness than usual"),
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
              moved_by: Optional[Dict[str, float]] = None, since: str = "") -> str:
        """How it feels, for her: what stands out in her body (``out``: these channels instead) and the overall
        tone, no numbers and no feeling's name: what she feels is hers to put into words ("Body: much
        more closeness and a little more strain than usual; pleasant on the whole, with little going
        on.").
        ``moved_by``: how her sense of her body changed as she read a message (each channel, in lots), said first,
        then how she is underneath it ("Reading it: more closeness than a moment ago. Underneath: more sleep
        pressure than usual; ..."): an emotion has its object, a mood is the background (Russell 2003).
        A channel that changed is still told where it is: strain easing a little from high is both (left out of
        "Underneath", a high strain read only as "much less strain than a moment ago": the 0.48 exam).
        ``since``: the moment ``moved_by`` is counted from, when it is not the message's coming ("Since you last
        answered here (4 minutes ago): much more strain. Underneath: ...")."""
        tone, pace = self.tone()
        whole = f"{tone} on the whole, with {pace}."
        found = self.standing_out() if out is None else out
        if moved_by is not None:
            now = sorted(((name, far) for name, far in moved_by.items() if name in CHANNELS and abs(far) >= 0.4),
                         key=lambda item: -abs(item[1]))[:3]
            under = found[:3]
            # a message that moved her too little to tell is told as that (told nothing, reassured, she said
            # "the whole worry fell off" with her strain where it was: run 660)
            change = (f"Since {since}: {_amounts(now) if now else 'little changed'}. " if since else
                      f"Reading it: {_amounts(now) + ' than' if now else 'little changed from'} a moment ago. ")
            return (change
                    + (f"Underneath: {_amounts(under)} than usual; {whole}" if under
                       else f"Underneath, {whole}"))
        return (f"Body: {_amounts(found)} than usual; {whole}" if found
                else f"Nothing stands out in the body: {whole}")


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
    """The record of one naming (Feelings.sort): her ``words`` as she wrote them and the sentence (``text``) she
    said them in, ``how`` (``tool``, ``speech``, ``thought``), what it ``named`` and which measurement supplied
    its numbers; ``reviewed``: when her sleep went over it (None: not yet)."""
    return {"words": words, "text": text, "at": at, "how": how, "named": named, "run": run, "event": event,
            "call": call, "episode": episode, "asked": asked, "measure": measure, "reminded": list(reminded),
            "reviewed": None}


def _place(ways: List[Dict[str, float]]) -> Tuple[Optional[list], list]:
    """Where moments moved like these sit, for drawing (pleasant -1..1, keyed up 0..1, toward the user -1..1: a
    usual body moved a lot and a half their way) and the channels they move most (name, share, signed)."""
    mean: Dict[str, float] = {}
    for way in ways:
        for name, value in way.items():
            if name in CHANNELS:
                mean[name] = mean.get(name, 0.0) + value / len(ways)
    size = math.sqrt(sum(value * value for value in mean.values()))
    if not size:
        return None, []
    part = {name: value / size for name, value in mean.items()}
    valence, arousal = core({name: USUAL[name] + 1.5 * share * CHANNELS[name][1] for name, share in part.items()})
    toward = part.get("oxytocin", 0.0) + part.get("social", 0.0) - part.get("grievance", 0.0)
    most = sorted(part.items(), key=lambda item: -abs(item[1]))
    return ([round(valence, 3), round(arousal, 3), round(max(-1.0, min(1.0, toward)), 3)],
            [[name, round(share, 2)] for name, share in most[:3] if abs(share) >= 0.25])


class Feelings:
    """The feelings she has made: each a category of moments she lived and sorted together with her own words
    (Barrett 2017: an emotion concept is the instances it was made from, not a definition; Barsalou 2009).

    A naming is her sorting one moment (``naming``): the words she gave how she felt, now or at a moment she
    pointed to. A feeling holds its namings (``said``), so what it is like is its moments: how each moved her
    body (the naming's measurement), what it meant for her needs and what it was about (its kept moment: the
    appraisal on the episode, and its meaning). Nothing averages them away. A word said once is ``provisional``,
    a guess at a category: it becomes ``hers`` when she sorts a second moment like the first under it, or when
    her sleep, going over the day's namings, finds it named what she felt (``confirm``). Sleep also joins two
    words for one feeling (``join``), splits a word that covers two things (``split``) and sets aside a saying
    that named no feeling at all (``set_aside``: kept, with her reason, never deleted). Every change is kept in
    the feeling's ``revisions``.

    A moment comes to be felt as one of her feelings by the whole situation (``recognize``): her nearest moments
    of it, alike in body, in what they meant for her and in what they were about, the more the more distinct
    moments she sorted under it (repeating a word for one moment counts once). When a feeling was a word and the
    mean of her body the times she said it, a phrase said beside a feeling ("the ugly part", "cheating. sort
    of") became one, and "waiting" came back whenever her body was flat (her mind, 2026-11-20)."""

    FLOOR = 0.6  # how strongly one must come to mind to be felt, and how alike a moment must be to confirm a word
    SPAN = 3  # her nearest moments of a feeling a likeness is taken over
    NAMED = ("now", "past", "unresolved", "legacy")  # what a naming names (see ``sort``)
    MEASURED = ("message", "reading", "moment", "legacy")  # what supplied a naming's numbers
    STANDING = ("provisional", "hers")
    APPRAISED = ("company", "capable", "free", "theirs")

    def __init__(self, saved: Optional[dict] = None):
        saved = saved if saved is not None else {"next": 1, "feelings": [], "set_aside": []}
        self.next = int(saved["next"])
        self.known: List[dict] = [self._read(item) for item in saved["feelings"]]
        self.aside: List[dict] = [{**self._naming(item), "why": str(item["why"]), "set_aside": float(item["set_aside"]),
                                   "feeling": item["feeling"]} for item in saved["set_aside"]]

    def saved(self) -> dict:
        return {"next": self.next, "feelings": self.known, "set_aside": self.aside}

    @staticmethod
    def key(words: str) -> str:
        """Her words for a feeling as they are known again: one spacing, any case, no end punctuation. Her
        wording itself is kept as she wrote it, on each naming (``words``)."""
        return " ".join(str(words).split()).strip(" .,!?\"'").casefold()

    @classmethod
    def _read(cls, item: dict) -> dict:
        if item["standing"] not in cls.STANDING:
            raise ValueError(f"not a feeling: {item}")
        return {"id": int(item["id"]), "standing": item["standing"], "at": float(item["at"]),
                "said": [cls._naming(one) for one in item["said"]], "revisions": [dict(r) for r in item["revisions"]],
                "back": int(item["back"]), "back_at": item["back_at"], "back_run": item["back_run"]}

    @classmethod
    def _naming(cls, one: dict) -> dict:
        if one["named"] not in cls.NAMED or (one["measure"] and one["measure"]["of"] not in cls.MEASURED):
            raise ValueError(f"not a naming: {one}")
        return {key: one[key] for key in ("words", "text", "at", "how", "named", "run", "event", "call", "episode",
                                          "asked", "measure", "reminded", "reviewed")}

    def find(self, feeling_id: int) -> Optional[dict]:
        return next((feeling for feeling in self.known if feeling["id"] == feeling_id), None)

    def word(self, feeling: dict) -> str:
        """What she calls it: the words she used for it most, the latest of them on a tie."""
        counted: Dict[str, Tuple[int, float]] = {}
        for one in feeling["said"]:
            key = self.key(one["words"])
            counted[key] = (counted.get(key, (0, 0.0))[0] + 1, one["at"])
        return max(counted.items(), key=lambda item: item[1])[0] if counted else ""

    def words(self, feeling: dict) -> List[str]:
        """Each of her wordings for it, as she first wrote it."""
        found: Dict[str, str] = {}
        for one in feeling["said"]:
            found.setdefault(self.key(one["words"]), one["words"])
        return list(found.values())

    @staticmethod
    def moment_of(one: dict) -> Optional[tuple]:
        """Which moment a naming sorted: its kept moment, else the run it was made in, else its time; None for
        one that names no moment (``unresolved``: the past moment she gave is not among her memories)."""
        if one["named"] == "unresolved":
            return None
        return ("episode", one["episode"]) if one["episode"] is not None else \
            ("run", one["run"]) if one["run"] is not None else ("at", one["at"])

    def moments(self, feeling: dict) -> int:
        """How many distinct moments she sorted under it."""
        return len({self.moment_of(one) for one in feeling["said"]} - {None})

    def of_call(self, run: Optional[int], call: Optional[str]) -> Optional[dict]:
        """The feeling a tool call already sorted a moment under (a call made again sorts nothing twice)."""
        if call is None:
            return None
        return next((feeling for feeling in self.known for one in feeling["said"]
                     if one["call"] == call and one["run"] == run), None)

    def likeness(self, moment: dict, one: dict, episodes: Dict[int, dict], near: Optional[Dict[int, float]]
                 ) -> Optional[float]:
        """How alike ``moment`` is to the moment a naming sorted, 0..1, by the parts both have: how they moved her
        body (``_alike``: whether they point the same way), what they meant for her needs (the appraisals, the same
        way; left out when either meant nothing) and what they were about (``near``: the meaning of what is happening
        now against that moment's, 1 as alike as two of her memories of one matter; None: the service cannot
        tell now). ``moment``: ``way`` (how she is moved), ``appraisal`` (None: nothing read). ``episodes``: the
        kept moments by id, each ``felt`` and ``appraisal``. None when either has no body: a feeling is a body in
        a situation, and nothing felt is nothing to recognize."""
        if self.moment_of(one) is None:
            return None
        episode = episodes.get(one["episode"]) if one["episode"] is not None else None
        way = ((one["measure"] or {}).get("way")) or (episode or {}).get("felt") or {}
        body = _alike(way, moment["way"]) if way and moment["way"] else None
        if body is None:
            return None
        parts = [body]
        then, now = (episode or {}).get("appraisal"), moment.get("appraisal")
        if then and now:
            # whether they meant the same for her, as body is: their direction. One less half the mean difference
            # read 0.84-0.91 for any two of her moments and told nothing apart (feelings-as-moments, 2026-11-20);
            # a moment that meant nothing for her needs has no direction: it tells nothing, so it is left out
            shared = [name for name in self.APPRAISED if name in then and name in now]
            then, now = ({name: side[name] for name in shared} for side in (then, now))
            if any(then.values()) and any(now.values()):
                parts.append(_alike(then, now))
        if near is not None and one["episode"] in near:
            parts.append(near[one["episode"]])
        return sum(parts) / len(parts)

    def _alike_to(self, feeling: dict, moment: dict, episodes, near) -> List[Tuple[float, dict]]:
        """Each distinct moment of a feeling with how alike ``moment`` is to it (the likest naming of a moment
        stands for it), likest first."""
        best: Dict[tuple, Tuple[float, dict]] = {}
        for one in feeling["said"]:
            value = self.likeness(moment, one, episodes, near)
            which = self.moment_of(one)
            if value is not None and (which not in best or value > best[which][0]):
                best[which] = (value, one)
        return sorted(best.values(), key=lambda item: -item[0])

    def strength(self, feeling: dict, moment: dict, episodes, near) -> Tuple[float, Optional[dict]]:
        """How strongly a feeling comes to mind in ``moment``, 0..1, and the naming of the moment it is likest:
        the mean likeness of its nearest moments, times how established it is (n distinct moments: a word used
        for one moment comes less readily than one used across many, by half of n / (n + 1))."""
        alike = self._alike_to(feeling, moment, episodes, near)
        if not alike:
            return 0.0, None
        nearest = alike[:self.SPAN]
        n = self.moments(feeling)
        value = sum(v for v, _ in nearest) / len(nearest) * (0.5 + 0.5 * n / (n + 1))
        return round(value, 3), nearest[0][1]

    def recognize(self, moment: dict, episodes: Dict[int, dict], near: Optional[Dict[int, float]]
                  ) -> List[Tuple[dict, float, dict]]:
        """What she feels in ``moment``, strongest first: (feeling, strength, the naming of the moment it is
        likest) for each that comes to mind."""
        found = [(feeling, *self.strength(feeling, moment, episodes, near)) for feeling in self.known]
        return sorted(((f, v, one) for f, v, one in found if v >= self.FLOOR), key=lambda item: -item[1])

    def sort(self, one: dict, moment: dict, episodes: Dict[int, dict], near: Optional[Dict[int, float]]
             ) -> Tuple[Optional[dict], Optional[float]]:
        """She put what she feels into words: ``one`` is the naming (``naming``), ``moment`` the moment it sorts
        (its ``way``, ``appraisal``). The words go with the feeling of hers they are already words for whose
        moments are likest this one (two share words once sleep split one); with none, a provisional feeling of
        their own. A provisional feeling given a second moment like the first is hers. (the feeling, how alike
        this moment is to its nearest moment; None: nothing to compare it with)."""
        one = self._naming(one)
        key = self.key(one["words"])
        if not key:
            return None, None
        same = [feeling for feeling in self.known if key in {self.key(n["words"]) for n in feeling["said"]}]
        if not same:
            self.known.append({"id": self.next, "standing": "provisional", "at": one["at"], "said": [one],
                               "revisions": [], "back": 0, "back_at": None, "back_run": None})
            self.next += 1
            return self.known[-1], None
        scored = []
        for feeling in same:
            alike = self._alike_to(feeling, moment, episodes, near)
            scored.append((alike[0][0] if alike else None, feeling))
        value, found = max(scored, key=lambda item: (item[0] is not None, item[0] or 0.0, item[1]["at"]))
        before = self.moments(found)
        found["said"].append(one)
        found["at"] = one["at"]
        if (found["standing"] == "provisional" and value is not None and value >= self.FLOOR
                and self.moments(found) > before):
            self.confirm(found["id"], "a second moment like the first", one["at"])
        return found, value

    def link(self, run: int, episode: int) -> bool:
        """The moment of ``run`` was kept: her namings of it, made while she was in it, name it. Whether any did."""
        linked = False
        for feeling in self.known:
            for one in feeling["said"]:
                if one["named"] == "now" and one["run"] == run and one["episode"] is None:
                    one["episode"], linked = episode, True
        return linked

    def came_back(self, feeling_id: int, at: float, run: Optional[int] = None) -> None:
        """A feeling of hers was recognized again in a moment she did not call by it: counted apart from her
        namings (``back``, when and in which run), and nothing else: a recognition sorts no moment."""
        feeling = self.find(feeling_id)
        if feeling:
            feeling.update(back=feeling["back"] + 1, back_at=at, back_run=run)

    def confirm(self, feeling_id: int, why: str, at: float) -> None:
        feeling = self.find(feeling_id)
        if feeling and feeling["standing"] == "provisional":
            feeling["standing"] = "hers"
            feeling["revisions"].append({"at": at, "did": "confirmed", "why": why})

    def join(self, into: int, other: int, why: str, at: float) -> bool:
        """Two of her words are one feeling: ``other``'s moments go into ``into``. Whether it was done."""
        kept, gone = self.find(into), self.find(other)
        if not kept or not gone or kept is gone:
            return False
        kept["said"] = sorted(kept["said"] + gone["said"], key=lambda one: one["at"])
        kept.update(standing="hers", at=max(kept["at"], gone["at"]), back=kept["back"] + gone["back"])
        kept["revisions"] += gone["revisions"] + [{"at": at, "did": "joined", "with": other,
                                                   "words": self.words(gone), "why": why}]
        self.known.remove(gone)
        return True

    def move(self, one: dict, into: int, why: str, at: float) -> Tuple[bool, Optional[int]]:
        """A saying of hers belongs with another feeling of hers (she used other words for it then): it goes there.
        (whether it moved, the id of a feeling it left with nothing, which goes)."""
        source = next((f for f in self.known if any(one is other for other in f["said"])), None)
        target = self.find(into)
        if not source or not target or source is target:
            return False, None
        source["said"] = [other for other in source["said"] if other is not one]
        target["said"] = sorted(target["said"] + [one], key=lambda other: other["at"])
        target.update(standing="hers", at=max(target["at"], one["at"]))
        target["revisions"].append({"at": at, "did": "took", "with": source["id"], "words": one["words"], "why": why})
        if source["said"]:
            source["revisions"].append({"at": at, "did": "gave", "with": into, "words": one["words"], "why": why})
            return True, None
        self.known.remove(source)
        return True, source["id"]

    def split(self, feeling_id: int, namings: List[dict], why: str, at: float) -> Optional[dict]:
        """One word of hers covers two different things: these of its namings are another feeling of hers. The
        new feeling; None when nothing would be left on either side."""
        feeling = self.find(feeling_id)
        if not feeling:
            return None
        moving = [one for one in feeling["said"] if any(one is other for other in namings)]
        if not moving or len(moving) == len(feeling["said"]):
            return None
        feeling["said"] = [one for one in feeling["said"] if not any(one is other for other in moving)]
        made = {"id": self.next, "standing": "hers", "at": max(one["at"] for one in moving), "said": moving,
                "revisions": [{"at": at, "did": "split from", "with": feeling_id, "why": why}], "back": 0,
                "back_at": None, "back_run": None}
        feeling["revisions"].append({"at": at, "did": "split", "with": self.next, "why": why})
        self.next += 1
        self.known.append(made)
        return made

    def set_aside(self, one: dict, why: str, at: float) -> Optional[int]:
        """A saying her sleep found named no feeling of hers: it leaves the feeling it was sorted under and is
        kept apart, with her reason. The id of a feeling it leaves with nothing, which goes."""
        feeling = next((f for f in self.known if any(one is other for other in f["said"])), None)
        if not feeling:
            return None
        feeling["said"] = [other for other in feeling["said"] if other is not one]
        self.aside.append({**one, "why": why, "set_aside": at, "feeling": feeling["id"]})
        if feeling["said"]:
            feeling["revisions"].append({"at": at, "did": "set aside", "words": one["words"], "why": why})
            return None
        self.known.remove(feeling)
        return feeling["id"]

    def unreviewed(self) -> List[Tuple[dict, dict]]:
        """Her namings her sleep has not gone over yet, oldest first: (feeling, naming)."""
        found = [(feeling, one) for feeling in self.known for one in feeling["said"] if one["reviewed"] is None]
        return sorted(found, key=lambda item: item[1]["at"])

    def shown(self, moment: dict, episodes: Dict[int, dict], near: Optional[Dict[int, float]]) -> List[dict]:
        """Every feeling of hers, for drawing: what she calls it and each of her words for it, its standing, how
        strongly it comes to mind now and the moment it is likest (``like``), how many moments she sorted under it
        (``count``) and how often it came back at one she did not (``back``), her namings, its revisions, where it
        sits (``place``) and the channels its moments move most."""
        out = []
        for feeling in self.known:
            value, like = self.strength(feeling, moment, episodes, near)
            ways = [((one["measure"] or {}).get("way")) or (episodes.get(one["episode"]) or {}).get("felt") or {}
                    for one in feeling["said"]]
            place, channels = _place([way for way in ways if way])
            out.append({"id": feeling["id"], "word": self.word(feeling), "words": self.words(feeling),
                        "standing": feeling["standing"], "strength": value, "like": dict(like) if like else None,
                        "count": self.moments(feeling), "back": feeling["back"], "back_at": feeling["back_at"],
                        "back_run": feeling["back_run"], "at": feeling["at"],
                        "said": [dict(one) for one in feeling["said"]],
                        "revisions": [dict(r) for r in feeling["revisions"]],
                        "measured": sum(1 for one in feeling["said"] if one["measure"]),
                        "place": place, "channels": channels})
        return out
