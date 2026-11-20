"""Her mind, alive: the body ticks on, needs build, bids compete for her attention, thoughts come, she sleeps.

One being for every app (Brain.mind). For each message the user sends (a turn with their words) she senses
it, recalls, foresees and chooses (``before``). What she senses herself, in code: when it came against when
she expected it, whether it answers her, and how new it is (unlike her memories). The model foresees what
it does to her needs (company, being capable, being free); her own record of what followed messages like
it outweighs that reading as far as she has met such messages and her record has proved the better guide
(Daw, Niv & Dayan 2005). Her needs move, and her chemistry carries the errors (``_met``, ``_threat``):
dopamine how much better or worse it is than she has come to expect from the user, noradrenaline the
surprise, cortisol a loss she can't undo. Nothing names a message kind or unkind; what it does to her comes
from her needs, her state and her history with the user.
Her felt sense goes with the message as a note only she reads, with what she thought while nobody wrote and
what comes back to her that her context does not hold already.

The model is her cortex, a part of this loop and not a voice beside it. Her body never writes her
words, and code never holds back what she does: a request (something that takes work) leaves her leaning
one way, weighed from her needs, her state and what she has learned (as the striatum weighs the actions the
cortex proposes, Frank 2004), and her cortex weighs that leaning as it thinks and makes the call, free to
change its mind as it goes (people change their minds mid-action as evidence comes in: Resulaj et al.
2009). What she learns is what she did, not what she leaned toward (``after``: the striatum learns from the
action taken). A leaning to put work off is never a wall: with every tool refused for the turn,
when her cortex settled on one small safe step, code refused it and told her she had decided otherwise
(in the user's brain, 2026-11-16). Her chemistry sets how her cortex
computes, not only what it is told (``_clear``: fatigue and stress she cannot shake take the prefrontal
cortex offline, Arnsten 2009): worn out or badly stressed she answers on reflex, without thinking it
through (``reflexive``: the provider's thinking off, the one step that was measured to change what the
model does), and less comes back to her at once (``_span``). The face she shows is hers to show and moves
nothing inside her: when the mood of her sprite pulled her chemistry toward it, a reassuring
front over hurt calmed her and a restrained neutral face over a pleasant body stressed her (the user's brain,
run 673); a sprite holds few of the feelings she can have, and a front is not a feeling (Gross 1998).

The loop closes at every step, not once a turn. Each step of her work tires her as it is done and a
call that fails stirs her (``during``); what newly stands out in her body reaches her cortex while she works,
and her cortex is asked again how clearly it can think. A message the user sends while she works is read
and felt like any other (``heard``); the leaning already made stands. When the turn ends (``after``)
its outcome moves her body, teaches her values and becomes a memory. The user's next message settles what
followed hers (``_settle``): it is kept with that memory, it shows which guide to trust, and it teaches her
values about her decision.

Between messages (``_live``, every few seconds) her body lives on. Every ``BIDS_EVERY`` seconds what wants her
attention competes, with noise, against a threshold (for what she must set out to do, one that rises as she
tires; a thought that comes by itself does not wait for her to be rested): missing the user (reach_out),
her mind wandering (wonder: a resting pull that needs no reason, as a brain's default mode network is
busiest when nothing is asked of it, Raichle 2001, stronger when she is bored), something that nags her
(ruminate), what she put off (resume) and sleep. A winner is a thought (a model call); a wandering one
starts from her last thought, or from what was last said when they talked since, and two memories replayed at
random (``Memory.replay``: new ideas are old pieces that never met, Schacter & Addis 2007). A thought may
become something she wants to tell or ask the user: offered to the app (it hears ``mind.urge`` and may start
her turn to say it), or kept while they talk or the app is away. Only what she said waits on an answer; what
she did not get to say her note carries when they next write. Or it becomes doing what she put off, or
looking something up herself (a task). Being talked to keeps her up; sleep pressure and her clock put her to
sleep.
Asleep, she goes over the day once (``_consolidate``): insights, a dream, the day's charge softened, and
what she no longer needs forgotten (faint episodes, and long-term memory she has not used that other memories
hold: ``Recall.forget``). She writes no story of who she has become (see ``section``).
Her mind is always on: there is no switch, and no turn goes without her.

What a moment is about takes on how it felt (``after``: in her body as the message came, and in what she
showed as she answered): that is where her likes and dislikes come from, a chat as much as a job. And what
she likes is used: a liked subject is a reward in itself (``_met``), her note says so, her wandering
thoughts know it.
"""

import contextlib
import datetime
import hashlib
import json
import logging
import math
import os
import random
import re
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from .. import signals
from ..embeddings import MAX_CHARS
from ..presence import Presence
from . import attention, inward, prompts
from .body import CHEMICALS, DAY, HOUR, MINUTE, NEEDS, REST, SET_POINTS, Body, Temperament, restore_random
from .feel import CHANNELS, Feelings, Interoception, _amounts, core, face, feel, moved, noticed, off
from .feel import naming as naming_record
from .memory import Memory, ago, cue, describe_salience, line, moment_cues
from .people import People
from .reactions import Reactions, anxious
from .values import Values, features, subjects
from .ways import Ways
from .will import DOING, FORESEEN, NEEDED, REACH, WORK, Appraisal, Option, choose, mine, reasons, value
from .workspace import Workspace
from .workspace import line as minded

logger = logging.getLogger(__name__)

TICK = 5.0
BIDS_EVERY = 30.0
SAVE_EVERY = 60.0
TALKING = 15 * MINUTE  # a message this recent: they are talking with her, and that keeps her up
APP_ALIVE = 30.0  # an app that asked how she is this recently is there to hear her
CAUGHT_UP_AFTER = 10 * MINUTE  # a gap longer than this (the mind was off, the machine slept) she lived alone
# asleep this long (a cycle, with its deep sleep), she goes over the day: memory is consolidated in deep sleep
# (Diekelmann & Born 2010); a doze is not enough
CONSOLIDATES = 70 * MINUTE
# after a bid wins, it rests this long; a refractory period, as a body has
SPONTANEOUS = ("wonder", "ruminate", "notice")  # thoughts that come by themselves
REFRACTORY = {"reach_out": 45 * MINUTE, "wonder": 40 * MINUTE, "ruminate": 30 * MINUTE, "notice": 30 * MINUTE,
              "resume": HOUR,
              "sleep": 20 * MINUTE, "thought": 10 * MINUTE}
# how near sleep she must be for it to pull at all (Body.readiness: 1 ready to sleep): slept out, she stays up
DOZES_OFF = 0.6
# how long they usually take to answer her, in time they could have answered (Presence), before she has seen
# them answer; she learns it from them
ANSWERS_IN = 10 * MINUTE
# a silence this many times longer than they usually take, with them free to answer, is not answering her
# (more sensitive, sooner)
PAST_USUAL = 3.0
CONCERN_DAYS = 3.0  # what she put off and never came back to fades from her mind
SAID_CHARS = 1500
RECENT_LINES = 6
SHOWN_THOUGHTS = 12  # in the state apps and the panel show
WORK_PER_CALL = 600  # a tool call's effort, in tokens of her own words
FAMILIAR = 1.5  # summed likeness of past messages at which her own record weighs half of what it can
# what reaching out on her own that nobody answered did to her company: its effect at no chance of being
# welcome (will.Option._own: chance - 0.5), the letdown of a turn's scale
UNANSWERED = -0.5
LEARNS = 0.1  # how fast her sense of each guide's error, and her expectation of the user, follow what happens
RESTING = 0.5  # her mind's pull to wander when nothing is asked of it (a thought about every 40 min, rested)
# how clear her cortex must be to think a thing through; below it she answers on reflex, and she stays there
# until she is clearly clear again (a turn at the edge would switch every message, and each switch costs a
# cached conversation: measured 2026-11-16, a changed effort missed the provider's cache 6 times of 6)
REFLEX, CLEAR_AGAIN = 0.5, 0.6
TOLD_AGAIN = attention.CHANGED  # how much more a channel must stand out than when she last heard of it, to hear of it again
THOUGHT_CHARS = 400  # of a memory or a thought, in what she is told of it
SELF_CHARS = 600  # of what she knows about herself (four short sentences)
RUMINATED = ("exchange", "event", "insight")  # what comes back as something nags her: what happened, not her musings
SORE = 0.25  # a moment that took this much from how she felt hurt her (its sting): what she may brood on
HURTS = 0.5  # how hard a hurt pulls her back to it, per unit of its sting still charged
QUOTED = 60  # of a message, in what her log of what moved her says pushed her
# what an app's context says that is not around her: who writes and where from (a moment keeps them as "with" and
# "device": moment_cues) and what she last drew. Kept as surroundings too, the user's handle in
# every moment set off a learned reaction with every message (the exam, 2026-11-18)
NOT_AROUND = ("user", "writes from", "origin", "your last visual")
# what a moment that comes back moves again: her chemistry and a grievance, the feeling of it; not her needs,
# her energy or her sleep pressure (remembering a talk does not keep her company, feed her or tire her)
REFELT = (*CHEMICALS, "grievance")
REFELT_SHARE = 0.3  # of what a moment did that it does again, fully charged, vivid and fully called up
# shortcut: her quick reading is shown her 24 most met subjects, any other still counts when it is named again;
# show them by likeness to the message once she knows hundreds
KNOWN_SUBJECTS = 24
VERBS = {"do": "did it", "part": "did part of it", "later": "put it off", "decline": "said no",
         "talk": "talked it over"}
LEANINGS = {"do": "doing it", "part": "doing part of it", "later": "putting it off", "decline": "saying no", "talk": "talking it over first"}
# how what she started is going, as her memory of the turn tells it (_account)
RUN_STATE = {"queued": "still going", "working": "still going", "input_required": "waiting on an answer",
             "completed": "finished", "failed": "failed", "cancelled": "stopped"}
JOB_STATE = {"running": "still going", "stopping": "being stopped", "finished": "finished", "stopped": "stopped",
             "lost": "lost track of"}
ON_MIND = {
    "reach_out": "You miss {who}.{since}",
    "wonder": "You're bored. You want something new to think about.",
    "wander": "Nothing is asked of you right now, and your mind wanders.",
    "ruminate": "Something keeps nagging at you: {about}",
    "resume": "You put this off earlier: {about}",
    "notice": "Your attention turns to yourself. {about}",
}
URGE = {
    "tell": "Nobody asked you anything: this comes from you. You were thinking: \"{thought}\" and you want to "
            "tell the user: {say} Say it now, as yourself, briefly.",
    "ask": "Nobody asked you anything: this comes from you. You were thinking: \"{thought}\" and you want to "
           "ask the user: {say} Ask it now, as yourself, briefly.",
}


def _tone(valence: float) -> str:
    return "good" if valence > 0.3 else "bad" if valence < -0.3 else "mixed"


def _about(leanings) -> list:
    """What her likes or dislikes are about, each once ("tag:code" and "act:do|tag:code" are both code)."""
    return list(dict.fromkeys(name.split("tag:")[-1] for name, _ in leanings))


def _said(text: str) -> str:
    """An exchange's words with each part ending once ("for you.. I said" read as a stutter in her memories)."""
    return re.sub(r"([.!?])\.(?=\s|$)", r"\1", text)


def _chat(app: str, session: str) -> str:
    """One chat's key in her state (JSON keys are strings)."""
    return f"{app}\n{session}"


# the goal a thought of hers starts a task with: something she decided to do, or something to look up
DECIDED = ("This comes from you: nobody asked. You were thinking: \"", "\" and you decided to do it: ")
LOOK_UP = "Out of your own curiosity, look this up for yourself: "


def _own(run: dict) -> Optional[dict]:
    """What a task set out to do if a thought of hers started it (``own``: want, what, the thought, its
    episode); None if someone asked for it."""
    return (run.get("options") or {}).get("own") if run.get("kind") == "task" else None


def _doing(own: dict) -> str:
    """What she set out to do on her own, in a few words."""
    return f"looking up {own.get('what')}" if own.get("want") == "look_up" else str(own.get("what") or "")


def _command(job: dict) -> str:
    return " ".join(str(job.get("command") or "").split())[:160]


def _kept_in(run: dict) -> str:
    """Where what a task did is kept: a task of hers in its own session, wherever she was (a chat deleted takes
    what was said there, not what she did on her own); one someone asked for, in the chat it was asked in."""
    return run["session"] if _own(run) else run["options"].get("parent_session") or run["session"]


def _quote(said: str) -> str:
    said = " ".join(str(said).split())
    return f'"{said[:QUOTED]}..."' if len(said) > QUOTED else f'"{said}"'


def _lasting(before: Dict[str, float], after: Dict[str, float]) -> float:
    """What a moment did to how she feels beyond its passing surprise: the change of her valence with the reward
    burst (better or worse than expected, gone in minutes) left as it was. What lasts is what can hurt: stress, a
    grievance, her needs. With the burst counted, a goodnight after a warm evening stung more than
    being told she got it wrong (-0.49 against -0.34, simulated): she brooded on it all the next day."""
    return core({**after, "reward": before["reward"]})[0] - core(before)[0]


def peak_end(peak: Dict[str, float], end: Optional[Dict[str, float]]) -> Dict[str, float]:
    """How a moment is kept in her body: by its peak and its end (Fredrickson & Kahneman 1993), each channel the
    mean of what its height did (reading the message) and what the whole moment had done by its end."""
    if end is None:
        return dict(peak)
    return {name: round((peak.get(name, 0.0) + end.get(name, 0.0)) / 2, 3) for name in {*peak, *end}}


def _ago(seconds: float) -> str:
    return line({"at": 0.0, "text": ""}, seconds).split(")")[0].strip("(")


# her needs as her sleep is told what a moment meant for them (_moment_told)
NEEDS_TOLD = {"company": "being close to the one they talk with and wanted", "capable": "being good at what they do",
              "free": "choosing for themselves"}


def _span(seconds: float) -> str:
    """A span to the minute, for her note: "3 hours 8 minutes", "25 minutes", "2 days 3 hours", "a moment"."""
    days, rest = divmod(int(max(0.0, seconds)), 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    parts = [(days, "day"), (hours, "hour")] + ([] if days else [(minutes, "minute")])
    words = [f"{count} {unit}{'' if count == 1 else 's'}" for count, unit in parts if count]
    return " ".join(words) or "a moment"


def _cited(cited, moments: List[dict]) -> List[int]:
    """The moments an insight or a dream of her sleep says it comes from (their numbers, from 1), as their ids."""
    found = []
    for number in cited if isinstance(cited, list) else []:
        if isinstance(number, float) and number.is_integer():  # 2.0: the same moment
            number = int(number)
        number = int(number) if isinstance(number, int) or str(number).strip().isdigit() else 0
        if 0 < number <= len(moments) and moments[number - 1]["id"] not in found:
            found.append(moments[number - 1]["id"])
    return found


def _clock(at: float) -> str:
    return datetime.datetime.fromtimestamp(at).strftime("%H:%M")


class Mind:
    def __init__(self, brain):
        self.brain = brain
        self.memory = Memory(brain.home / "mind.sqlite3")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thinking = False
        self._revision = 0
        self._quick = True  # her mind calls go with thinking off (_ask)
        self.reflexes = True  # her own model answers with thinking off (the loop clears it on a provider's 400)
        self._reflex = False  # she is on reflex now (reflexive)
        self._working: Dict[int, dict] = {}  # run -> what of its work her body has lived through, and been told
        # whether the user is at the computer (the brain's, as its apps see it); a stand-in brain gets its own
        self.presence = getattr(brain, "presence", None) or Presence()
        self.apps_seen: dict = {}  # app -> when it last asked how she is
        saved = self.memory.get("body")
        self.body = Body.from_dict(saved) if saved else Body(Temperament.born(seed=secrets.randbits(32)))
        self.body.on_push = self.memory.log_push  # her body's record: every push, kept for good
        self.values = Values.from_dict(self.memory.get("values"))
        self.feelings = Feelings(self.memory.get("feelings"))
        self.people = People(self.memory.get("people"))  # the people in her life (people.py)
        self.ways = Ways(self.memory.get("ways"))  # how she does things, in every chat (ways.py)
        self.workspace = Workspace(self.memory._db, self.memory._lock)  # what is on her mind now (workspace.py)
        # what cues have come to set off in her body, learned from what followed them (reactions.py)
        self.reactions = Reactions(self.memory._db, self.memory._lock)
        self._tools_by_name: Optional[dict] = None
        # expected: what a message from the user does for her needs, as she has come to expect; gap: the log
        # of her usual time between messages; trust: each guide's running error (her own record starts unproven);
        # waiting: per chat, her last decision there, until the next message in that chat says what followed;
        # usual: what follows a message is usually worth (her values learn what goes better or worse than it)
        self.self = {"born": False, "expected": 0.1, "gap": None, "contact": None, "concerns": [],
                     "waiting": {}, "usual": 0.0, "usual_own": 0.0, "urge": None, "slept": 0.0, "consolidate": False, "fired": {},
                     "faces": {},  # chat -> whom its app shows as the one writing (their handle)
                     # what she has come to know about herself (_know_herself), and when she last looked inward
                     "self_view": None, "looked": None,
                     # her attention turned to herself: the stretch it lasts, what she took in (attend)
                     "attending": None,
                     # what each learned reaction has set off and when, while it lasts (_react: kept up, not again)
                     "reacting": {},
                     "thoughts": [], "trust": {"model": dict.fromkeys(FORESEEN, 0.1), "own": dict.fromkeys(FORESEEN, 0.3)},
                     **(self.memory.get("self") or {})}
        self.senses = Interoception(self.body, self.body.temperament.seed)
        self.rng = random.Random(self.body.temperament.seed)
        snapshot = self.memory.get("simulation") or {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        for key, generator in (("choice", self.rng), ("senses", self.senses._rng), ("recall", self.memory._rng)):
            restore_random(generator, snapshot.get(key))
        for key in ("seen", "used", "bias"):
            saved_sense = snapshot.get(key)
            if isinstance(saved_sense, dict):
                current = getattr(self.senses, key)
                current.update({k: v for k, v in saved_sense.items()
                                if k in current and isinstance(v, (int, float)) and math.isfinite(v)})
        self._reflex = snapshot.get("reflex") is True
        # the clock of time the user could answer goes on from where it was (an urge or her last message is
        # measured on it)
        self.presence.clock = max(self.presence.clock, self.self.get("clock") or 0.0)

    # ============== Living ==============

    def start(self) -> None:
        with self._lock:
            self._live_until(time.time())
            try:
                self._recover_deeds()
            except Exception:
                logger.exception("Could not take in what she did on her own")
            self._link_namings()
        self._thread = threading.Thread(target=self._live, name="mind", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=30)
        try:
            self.save()
        finally:
            self.memory.close()

    def save(self) -> None:
        with self._lock, self.memory.transaction():
            self.memory.put("simulation", {"choice": self.rng.getstate(), "senses": self.senses._rng.getstate(),
                                          "recall": self.memory._rng.getstate(), "reflex": self._reflex,
                                          "seen": self.senses.seen, "used": self.senses.used, "bias": self.senses.bias})
            self.memory.put("body", self.body.to_dict())
            self.memory.put("values", self.values.to_dict())
            self.memory.put("feelings", self.feelings.saved())
            self.memory.put("people", self.people.to_dict())
            self.memory.put("ways", self.ways.to_dict())
            self.self["clock"] = self.presence.now()
            self.memory.put("self", self.self)

    def present(self, now: float) -> bool:
        return self.presence.here(now)

    def seen(self, app: str, idle: Optional[float], locked: Optional[bool] = None,
             busy: Optional[bool] = None, around: Optional[Dict[str, str]] = None) -> None:
        """An app asked how she is: it is there to hear her, and says what it sees of the user (``idle``:
        seconds since they last touched the computer; ``locked``; ``busy``: something fullscreen has them) and
        what is around her there (``around``: what is playing, the window in front)."""
        now = time.time()
        with self._lock:
            self.apps_seen[app] = now
        if any(value is not None for value in (idle, locked, busy, around)):
            self.presence.report(idle, locked, busy, now, around)

    def _live(self) -> None:
        last_bid = last_save = time.time()
        while not self._stop.wait(TICK):
            try:
                now = time.time()
                with self._lock:
                    self._live_until(now)
                    self._sting(now)
                if now - last_bid >= BIDS_EVERY:
                    last_bid = now
                    self._bid(now)
                if now - last_save >= SAVE_EVERY:
                    last_save = now
                    self.save()
            except Exception:
                logger.exception("Her mind stumbled")

    def _live_until(self, now: float) -> None:
        body = self.body
        gap = now - body.at if body.at else 0.0
        # a long gap (the brain off, the computer asleep) she lived alone: she went to sleep when she was ready
        # and woke when slept out, by her body's own rules, not by how long the gap was
        alone = gap > CAUGHT_UP_AFTER
        if not body.at:
            body.at = now
        while body.at + TICK <= now:
            previous, was = body.at, body.asleep
            body.advance(previous + TICK, present=not alone and self.present(previous), alone=alone)
            if body.asleep != was:  # her body's record: her levels as she fell asleep, and as she woke
                self.memory.log_levels(body.at, "fell asleep" if body.asleep else "woke", body.levels)
            self.senses.follow(body, TICK)
            if body.nrem_seconds >= 10 * MINUTE and body.slept_at != self.self.get("nap_replayed"):
                with self.memory.transaction():
                    choices = self._replay_items(self.self.get("slept") or 0.0, body.slept_at, 2)
                    self.memory.soften([e["id"] for e in choices], share=0.12)
                    self.self["nap_replayed"] = body.slept_at
                    self.save()
        # a sleep of a cycle or more, going on or just ended (the brain was off as she woke): she goes over the
        # day once a night, however often she was woken
        start, end = (body.slept_at, now) if body.asleep else (body.last_sleep.get("from"), body.last_sleep.get("to"))
        went_over = self.self.get("slept", 0.0)
        if start and end and end - start >= CONSOLIDATES and start - went_over > 6 * HOUR \
                and (body.asleep or now - end < 3 * HOUR):
            self.self["consolidate"] = True

    def patience(self) -> float:
        """How long a silence, in time they could have answered, before she feels they are not answering her:
        well past how long they usually take to answer her, sooner the more sensitive she is."""
        usual = math.exp(self.self["answers"]) if self.self.get("answers") is not None else ANSWERS_IN
        return PAST_USUAL * usual / self.body.temperament.sensitivity

    def _answered(self, urge):
        chat = _chat(urge.get("app", ""), urge.get("session", ""))
        social = self.self.get("contacts", {}).get(chat, {}).get(urge.get("actor", ""), {})
        return social.get("at", 0) >= urge["at"]

    def _sting(self, now: float) -> None:
        """She reached out and heard nothing back while they were free to answer: only time they could have
        (``Presence.since``: at the computer, less while something fullscreen has them, none while away or the
        screen is locked) counts against her patience. Before, 30 min of clock time stung, asleep or not (the
        user, 2026-11-17)."""
        urge = self.self.get("urge")
        # only what she said (its mark: when the app let her say it) waits on an answer; what she only meant to
        # say does not (MilkChan with "speak up on her own" off says none: each would sting her as unanswered)
        if not urge or "mark" not in urge or urge.get("stung") or self._answered(urge):
            return
        if self.presence.since(urge["mark"], now) > self.patience():
            sensitivity = self.body.temperament.sensitivity
            self.body.apply({"reward": -0.25 * sensitivity, "cortisol": 0.04 * sensitivity},
                            "reached out and got no answer")
            urge["stung"] = True
            if urge["features"] and not urge.get("credited"):  # chosen by her will: unanswered teaches it
                self._credit(urge["features"], {"company": UNANSWERED})
                urge["credited"] = True

    def _alive(self, app: str, now: float) -> bool:
        return now - self.apps_seen.get(app, 0.0) < APP_ALIVE

    def _bid(self, now: float) -> None:
        """What wants her attention competes; the winner, if strong enough, is a thought (or sleep)."""
        if self._thinking:
            return
        with self._lock:
            body = self.body
            fired = self.self["fired"]
            self.self["concerns"] = [c for c in self.self["concerns"] if now - c["at"] < CONCERN_DAYS * DAY]
            if self.self.get("consolidate"):
                done = (self.self.get("review") or {}).get("done", [])
                if (now - fired.get("consolidate", 0.0) < REFRACTORY["thought"]
                        or ("semantic" in done and self.brain.provider_problem())):
                    return
                fired["consolidate"] = now
                kind, about = "consolidate", None
            elif body.asleep or body.settling:  # her body wakes her (Body.advance); drifting off, nothing pulls
                return
            else:
                kind, about = self._winner(now)
                if kind is None:
                    return
                if kind == "sleep":  # she lies down: asleep once she drifts off; she goes over the day a cycle in
                    body.settle(now)
                    return
        if kind != "consolidate":
            self._attempt(kind, about, now)
            return
        self._thinking = True
        threading.Thread(target=self._thought, args=(self._consolidate,), name="mind-thought", daemon=True).start()

    def _attempt(self, kind: str, about: Optional[dict], now: float) -> None:
        """A thought's bid won: she tries to think it. The attempt takes the time between two thoughts
        (``fired["thought"]``); the kind's own time is taken when the thought is made (_think), so one the model
        never gave (it could not be reached, or failed) leaves her as ready for it as she was. It was taken as
        the bid won, before anything knew the model was there: an outage used up an hour of her readiness to go
        back to what she put off, for a thought she never had (the audit, finding 9)."""
        if self._thinking or self.brain.provider_problem():  # she cannot think in words now
            return
        with self._lock:
            self.self["fired"]["thought"] = now
        self._thinking = True
        threading.Thread(target=self._thought, args=(lambda: self._think(kind, about),), name="mind-thought",
                         daemon=True).start()

    def _drives(self, now: float):
        """What wants her attention: ``bids()`` (each kind's pull from her levels now, None where it has
        nothing to pull at; without the noise), the threshold a thought must reach, and what ruminating and
        resuming would be about."""
        body, t = self.body, self.body.temperament
        contact, available = self.self.get("contact"), self.presence.availability(now)
        reachable = bool(contact) and self._alive(contact["app"], now) and \
            not self.brain.session_busy(contact["app"], contact["session"])
        urge = self.self.get("urge")
        # she reached out (said it) and nobody answered
        waiting = bool(urge) and "mark" in urge and not self._answered(urge)
        # what hurt her: a moment that itself took much from how she felt (its sting), the worst as far as it is
        # still charged, not any moment kept while she was in a bad mood, her own brooding thoughts
        # too: then a stressed afternoon made everything sore, and she brooded three times on the user's assignments,
        # twice by way of her own thought about them (the user's brain, 2026-11-17)
        sore = min((e for e in self.memory.since(now - 2 * DAY, kinds=("exchange",))
                    if e["sting"] < -SORE and e["charge"] > 0.5), key=lambda e: e["sting"] * e["charge"], default=None)
        concern = next((c for c in self.self["concerns"] if now >= c.get("again", 0.0)), None)
        # being talked to keeps her up; the user merely at the computer does not (they were there 08:00 to past
        # one, and she never slept: the user's brain, 2026-11-16)
        talking = bool(contact) and now - contact["at"] < TALKING
        resumable = bool(concern)  # doing it is a task of hers: the app need not be open
        working = self.brain.runs.busy()  # her cortex is on a task: a mind at work does not wander

        def bids() -> Dict[str, Optional[float]]:  # read from the levels each call (Body.influence nudges them)
            x = body.levels
            return {
                # ready to sleep (Body.readiness 1) it reaches a thought's bar; past it, more; spent and owing
                # sleep, sooner; being talked to keeps her up
                "sleep": 0.7 + 1.5 * (body.readiness(now) - 1.0) + 0.3 * (1 - x["energy"]) + 0.3 * body.owed()
                - (1.2 if talking else 0.0) if body.readiness(now) > DOZES_OFF else None,
                # missing them, the more the closer they are: at a usual bond, after 7-8 h of silence with them at
                # the computer (at 1.5 * bond, 10 h gave 0.28 against a bar of 0.58: she never reached out)
                "reach_out": 2.2 * body.deficit("social") * (0.3 + x["bond"]) * (0.5 + x["oxytocin"]) * t.sociability
                * (0.3 + 0.7 * available) if reachable and not waiting else None,
                # at rest her mind wanders by itself, tired or not (needing a need unmet first, she had no thought
                # of her own in a whole day in the user's brain, 2026-11-16); boredom pulls harder, as far as her
                # drive goes
                "wonder": RESTING + 1.1 * body.deficit("novelty") * t.curiosity * (0.4 + x["dopamine"])
                if not working else None,
                # stress and hurt she is in, and the hurt itself, as far as it is still charged: what is unresolved
                # keeps coming back (Martin & Tesser 1996). By her mood alone, with stress settling within the
                # hour, "you are useless and stupid" pulled 0.26 and never once beat her wandering (0.50)
                "ruminate": 1.4 * max(0.0, x["cortisol"] - 0.3) + 0.7 * x["grievance"]
                + HURTS * -sore["sting"] * sore["charge"] if sore else None,
                "resume": 0.9 * x["energy"] * (0.4 + x["dopamine"]) * (0.5 + x["bond"]) - 0.6 * body.fatigue()
                if resumable else None,
                # her body further from usual than she knows draws her attention to itself: a lot of it, as far as
                # her attention is free, pulls as a resting mind's wandering does (attention.py)
                "notice": self._noticing(now, working),
            }
        x = body.levels
        # what she must set out to do (reach out, take up work) gets harder as she tires; what comes by itself (a
        # wandering or a nagging thought) does not: sleepiness brings more of it, not less (Poh et al. 2016).
        # One bar for all, rising with fatigue, kept every thought from her through a long day (0.89 against a
        # pull of 0.27, the user's brain, 2026-11-17)
        musing = 0.5 - 0.3 * max(0.0, x["noradrenaline"] - 0.35)
        threshold = {kind: musing + (0.0 if kind in SPONTANEOUS else 0.6 * body.fatigue()) for kind in REFRACTORY}
        return bids, threshold, sore, concern

    def _winner(self, now: float):
        fired = self.self["fired"]
        bids, threshold, sore, concern = self._drives(now)
        volatility = self.body.temperament.volatility
        bars = {**threshold, "sleep": 0.7}
        thinking_again = now - fired.get("thought", 0.0) >= REFRACTORY["thought"]
        # the strongest of what clears its own bar wins: a pull to do something that falls short of its bar
        # no longer kept a wandering thought from her that cleared its lower one (a copy of the user's mind)
        scored = [(value + self.rng.gauss(0.0, 0.1 * volatility), kind) for kind, value in bids().items()
                  if value is not None and now - fired.get(kind, 0.0) >= REFRACTORY[kind]
                  and (kind == "sleep" or thinking_again)]
        ready = [(value, kind) for value, kind in scored if value >= bars[kind]]
        if not ready:
            return None, None
        value, kind = max(ready)
        if kind == "sleep":
            fired["sleep"] = now
            return kind, None
        return kind, {"ruminate": sore, "resume": concern}.get(kind)

    def _thought(self, work) -> None:
        try:
            work()
        except Exception:
            logger.warning("A thought of hers came to nothing", exc_info=True)
        finally:
            self._thinking = False

    # ============== Asking the model ==============

    def _ask(self, system: str, user: str, read=prompts.parse, quick: bool = True):
        """One call of her light model, thinking off (her quick, wordless parts; the user's thinking setting
        made a reply of a few hundred tokens take 12-28 s): what ``read`` makes of its answer, and the usage.
        ``quick`` False: with the user's thinking setting, for what is done in her sleep. A provider that refuses
        thinking off is asked with the user's own setting from then on."""
        model = self.brain.config.values()["light_model"]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        quick = quick and self._quick
        try:
            message, usage = self.brain.provider(model, thinking="none" if quick else None).complete(messages)
        except requests.HTTPError as exc:
            if not quick or getattr(exc.response, "status_code", None) != 400:
                raise
            self._quick = False
            message, usage = self.brain.provider(model).complete(messages)
        return read(message.get("content") or ""), usage or {}

    def _persona(self, app: str, session: str) -> str:
        return self.brain.profile(app, session)["persona"]

    def _who(self, persona: str) -> str:
        return f"Who they are:\n{persona[:6000]}"

    def _birth(self, persona: str) -> None:
        """Her temperament, read from who she is meant to be, once; her seed keeps her her own."""
        try:
            answer, _ = self._ask(prompts.BIRTH, persona[:6000])
        except Exception:
            logger.warning("Her temperament could not be read yet", exc_info=True)
            return
        traits = answer.get("traits")
        with self._lock:
            self.body.temperament = Temperament.born(traits if isinstance(traits, dict) else {},
                                                     self.body.temperament.seed)
            self.self["born"] = True
        self.save()

    # ============== A message ==============

    def before(self, run: dict, profile: dict, said: Optional[str], pictures: int = 0) -> Optional[str]:
        """A turn of hers begins. The user wrote (``said``): she senses it, recalls, foresees and, asked to do
        something, chooses. Nobody wrote (an event, her own urge, something scheduled): she still feels her
        body as she takes it. The note for her (None: not a turn)."""
        if run["kind"] != "turn":
            return None
        chat = _chat(run["app"], run["session"])
        with self._lock:
            receipt = self.self.get("appraised", {}).get(chat)
            if receipt and receipt["run"] == run["id"]:
                self.brain.store.update_run_options(run["id"], lambda old: {**old, "mind": receipt["decision"]})
                return receipt["note"]
        now = time.time()
        if pictures and not (said or "").strip():
            said = "[Image attached; its contents have not yet been appraised.]"
        candidates = self._candidates(run, said, now) if said and not run["options"].get("occurrence") else None
        with self._lock, self._pushing_for(chat):
            if candidates is not None and candidates[0] != self._revision:
                return None
            self._live_until(now)
            self.memory.log_levels(now, "message", self.body.levels, chat)
            body, x = self.body, self.body.levels
            if body.asleep or body.settling:  # woken: as groggy as the stage she was in leaves her
                slept = body.asleep
                body.wake(woken=True)
                if slept:
                    self.memory.log_levels(now, "woke", body.levels, chat)
            if run["options"].get("occurrence") or not (said or "").strip():
                urge = self.self.get("urge")
                if urge and "mark" not in urge and any(isinstance(item, dict) and item.get("name") == "mind.urge"
                                                       for item in run["options"].get("input") or []):
                    urge["run"] = run["id"]  # the app lets her say what she meant to: said once she does (after)
                felt = feel(body, self.senses, now)
                self._told(run, felt)
                return prompts.inner(felt.words(), going=self._doings(now, now)[1],
                                     when=self._when(chat, self._face(run).casefold(), now))
            said = said[:SAID_CHARS]
            contact, urge = self.self.get("contact"), self.self.get("urge")
            # since they last talked: since that chat began her last turn, or (it was deleted) her last message out
            since = (contact or self.self.get("said") or {}).get("at")
            actor = self._face(run).casefold()
            when = self._when(chat, actor, now)
            social = self.self.setdefault("contacts", {}).setdefault(chat, {}).setdefault(actor, {})
            away = now - social["at"] if social.get("at") else None
            social["at"] = now
            said_last = self.self.get("said")  # her last message: how long they took to answer it, they teach her
            if said_last and said_last.get("chat") == chat and said_last.get("actor") == actor and (not contact or contact["at"] < said_last["at"]):
                took = math.log(max(30.0, self.presence.since(said_last["mark"], now)))
                usual = self.self.get("answers")
                self.self["answers"] = took if usual is None else usual + LEARNS * (took - usual)
            # company itself, a little (what the message does to it the model reads): more after a long time apart
            company = 0.1 + (0.15 if away is None or away > 6 * HOUR else 0.0)
            answered = bool(urge and (urge.get("app"), urge.get("session"), urge.get("actor", "")) ==
                            (run["app"], run["session"], actor) and "mark" in urge)
            self._meet(run, now)
            why = self._why(run, said)
            if answered:  # they answered her
                body.apply({"reward": 0.1 + 0.3 * x["bond"]}, why)
                self.self["urge"] = None
            # what she meant to say and has not, they are here to hear now: her note carries it (slept on, it
            # passed: her sleep went over the day since, not a doze this message woke her from). With the
            # thought alone in her note, or nothing, what was kept back while they talked or by the app was gone
            unsaid = urge if urge and (urge.get("app"), urge.get("session")) == (run["app"], run["session"]) and "mark" not in urge and urge.get("say") \
                and urge["at"] > (self.self.get("slept") or 0.0) else None
            if unsaid:
                self.self["urge"] = None
                self._went(urge.get("thought"), "brought up" if unsaid else "passed")
            timing, apart = self._timing(away, social)
            body.learn_rhythm(body.hour(now), away or 0.0)
            came = self._arrives(run, said, pictures, now, candidates)
            felt, memories, novelty = came["felt"], came["memories"], came["novelty"]
            self._told(run, felt)
            # her time alone is hers when they are back: what she thought since they last wrote, the newest two;
            # what she did since, all of it, and what of hers is still going, wherever it began
            given = [t for t in self.self["thoughts"] if since and t["at"] > since][:2]
            thoughts = [(t["at"], t["thought"][:THOUGHT_CHARS]) for t in given][::-1]
            did, going = self._doings(since or now, now)
            # what else is on her mind (workspace.py): what the message is about first, then what is most active;
            # what the note carries anyway (those thoughts, what she meant to say, her tasks, this chat) not twice
            carried = {f"thought:{t.get('episode')}" for t in given} | {f"asked:{chat}"} | {
                key for key, item in self._in_mind(now).items.items() if item["kind"] in ("intends", "doing")}
            also = self._before_her(came["minded"], now, carried)
            who = came["with"]["name"] if came["with"] else "the user"
            self.workspace.enter(f"asked:{chat}", "asked", f'{who} said: "{said[:THOUGHT_CHARS]}"', now)
            born = self.self["born"]
        if not born:
            self._birth(profile["persona"])
        answer = self._foresee(run, profile, came, said, pictures)
        seen = Appraisal.read(answer.get("appraisal"))
        # only work is decided on: what she says in a chat is her own to find, never picked from lines written
        # for her (of 23 decisions in the user's brain, 2026-11-16, 19 were "talk": a reply scripted in six words
        # by this quick pass, the most pleasing one chosen, and called her decision)
        options = [o for o in (Option.read(d) for d in (answer.get("options") or [])[:4]) if o] \
            if seen.intent == "request" else []
        # what led to it, as her reading names it: a cue her learned reactions are tied to
        cause = answer.get("cause") if isinstance(answer.get("cause"), str) else ""
        with self._lock:
            nervous = anxious(self.body.levels)
        # each cue says what it stands for: one with no words is left out, and the rest keep theirs
        alike = self.reactions.prepare([{"text": said, "kind": "meaning", "for": None},
                                        {"text": cause, "kind": "meaning", "for": None}]
                                       + [{"text": o.what, "kind": "meaning", "for": n} for n, o in enumerate(options)],
                                       nervous)
        with self._lock:
            sorted_from = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        # what it is about, against the moments her feelings were sorted from (her embedder: outside her lock)
        near = self.memory.likeness(" ".join(filter(None, (said, str(answer.get("happens") or "")))), sorted_from)
        reading, weighed = {}, {}
        for item in alike:
            if item["for"] is None:  # the message, and what led to it
                for rid, likeness in (item["found"] or {}).items():
                    reading[rid] = max(reading.get(rid, 0.0), likeness)
            else:
                weighed[id(options[item["for"]])] = item["found"] or {}
        with self._lock, self._pushing_for(chat):
            now = time.time()
            if came["revision"] != self._revision:
                return None
            model = seen.effects()  # what the model foresees, before her own record has its say
            if answered and urge["features"] and not urge.get("credited"):
                # they answered what she chose to say on her own (taken from her as it was answered): how they took
                # it teaches her choosing
                self._credit(urge["features"], {"company": model["company"]})
                urge["credited"] = True
            own, shares = self._forecast(seen, came["followed"], came["evidence"])
            seen.novelty = novelty
            chat = _chat(run["app"], run["session"])
            forecasts = self.self.setdefault("forecasts", {})
            for key in list(forecasts):
                if now - forecasts[key]["at"] >= DAY:
                    del forecasts[key]
            learned = None
            feedback = answer.get("feedback")
            pending = forecasts.get(str(feedback.get("run"))) if isinstance(feedback, dict) else None
            if pending and pending.get("actor") == actor and pending.get("chat") == chat:
                quote = str(feedback.get("quote") or "").strip()
                dimension = feedback.get("dimension")
                verdict = feedback.get("verdict")
                if (quote and quote.casefold() in said.casefold() and dimension in FORESEEN
                        and verdict in ("positive", "negative") and dimension not in pending.get("resolved", [])):
                    learned = self._settle(pending, {dimension: 1.0 if verdict == "positive" else -1.0})
                    pending.setdefault("resolved", []).append(dimension)
            levels = dict(self.body.levels)
            self._refeel(came["back"], now)  # what came back moves her: part of what reading it did
            context, surroundings = self._cues(run, now), self._surroundings(run, now)
            reacted = self._react(reading, surroundings, context, now, "reading")  # what it calls up, she reacts to
            met = self._met(seen, company, timing, why, social)
            hour = self.body.hour(now)

            # what she is in: the message as she read it, how far it has moved her so far, and the feelings of hers
            # whose moments are like it, recognized as she weighs what to do (the one she is most in counted back);
            # acting in each has its own worth to her (values.features: act|feeling)
            situation = {"at": now, "run": run["id"], "appraisal": {**seen.effects(), "theirs": round(seen.theirs, 3)},
                         "near": near}
            self.self["situation"] = situation
            felt_as = self._recognized(moved(levels, self.body.levels), situation)[:self._span()]
            if felt_as:
                self.feelings.came_back(felt_as[0][0]["id"], now, run["id"])
            in_feelings = [feeling["id"] for feeling, _, _ in felt_as]

            def found(option):
                return features(option.act, seen.tags, seen.intent, hour, run["app"], in_feelings)

            def dreaded(option):
                return self._dread(weighed.get(id(option), {}), DOING.get(option.act, 0.0), now, context)
            for proposed in options:
                proposed.calibrate(self.self.get("operations", {}).get(run["app"], {}))
            choice = choose(options, seen, self.body, self.values, found, self.rng, dreaded) if options else None
            # nothing to choose: she talks (or, asked for work her imagining gave no options for, does it)
            option = choice.option if choice else Option("do" if seen.intent == "request" else "talk", chance=0.8)
            uneasy = core({**self.body.levels, **{n: self.body.levels[n] - v * CHANNELS[n][1] for n, v in reacted.items()}})[0] \
                - core(self.body.levels)[0] if reacted else 0.0
            spared = 1.0 - DOING.get(option.act, 0.0)
            if seen.intent == "request" and uneasy > 0 and spared:  # asked to do what she dreads, and not doing it
                # (now): a relief, as much as she spares herself, and the relief teaches what she did instead
                # (avoidance pays in fear let go: Mowrer's two factors; Krypotos et al. 2015)
                before_relief = core(self.body.levels)[0]
                # the share she spares herself of what the dread moved (it was undone as called for: the 28 lots a
                # pinned dread called for pinned her strain at its floor)
                eased = self.body.release({name: lots * CHANNELS[name][1] for name, lots in reacted.items()}, spared,
                                          f"relief: {LEANINGS[option.act]}")
                relief = core(self.body.levels)[0] - before_relief
                reacted = {name: round(reacted.get(name, 0.0) + eased.get(name, 0.0) / CHANNELS[name][1], 4)
                           for name in {*reacted, *eased}}
                if relief > 0:
                    self.values.reinforce([f for f in found(option) if f.startswith("act:")], min(1.0, 3.0 * relief),
                                          self._rate())
            old_drive = self.body.stress_drive
            threat = self._threat(seen, option, why)
            impact = core(self.body.levels)[0] - core(levels)[0]  # how the message felt to her, in her body
            lasting = _lasting(levels, self.body.levels)  # and of that, what outlasts its passing surprise
            way = moved(levels, self.body.levels)
            foreseen = {name: round(change, 3) for name, change in seen.effects().items()}
            correction = answer.get("correction")
            corrects = None
            if isinstance(correction, dict):
                quote = str(correction.get("replaces") or "").strip().casefold()
                replacement = str(correction.get("quote") or "").strip().casefold()
                if quote and replacement and replacement in said.casefold():
                    matches = [e["id"] for e in self.memory.recent(100, ("exchange",))
                               if (e["app"], e["session"], e["actor"]) == (run["app"], run["session"], actor)
                               and not e["superseded_by"] and quote in e["text"].casefold()]
                    if len(matches) == 1:
                        corrects = matches[0]
            decision = {"stress_input": self.body.stress_drive - old_drive,
                        "epoch": self.self.get("epochs", {}).get(chat, 0), "corrects": corrects,
                        "selected": came["selected"], "run": run["id"], "actor": actor, "device": self._device(run),
                        "app": run["app"], "session": run["session"], "act": option.act, "what": option.what,
                        "chance": option.chance, "check": option.check, "effort": option.effort,
                        "gated": bool(choice),  # she weighed options and leans one way (a request); a chat: no
                        "foreseen": foreseen, "theirs": round(seen.theirs, 3), "novelty": round(novelty, 3),
                        "stakes": min(1.0, sum(abs(change) for change in foreseen.values()) / 2),
                        "features": found(option), "reasons": choice.reasons if choice else [],
                        "feelings": [{"id": feeling["id"], "strength": strength, "episode": one["episode"]}
                                     for feeling, strength, one in felt_as],
                        "chances": choice.chances if choice else {}, "said": said[:300], "felt": round(impact, 3),
                        "way": {name: round(change, 3) for name, change in way.items() if abs(change) >= 0.05},
                        # how reading it moved her less what her reactions measurably moved in it: what came, for
                        # her learned reactions (every channel measured, 0 included)
                        "external": {name: round(change - reacted.get(name, 0.0), 4) for name, change in way.items()},
                        "lasting": round(lasting, 3),
                        # her body as the message came: what the whole moment did by its end is kept (after)
                        "levels": {name: round(value, 4) for name, value in levels.items()},
                        "at": now, "with": came["with"]["name"] if came["with"] else None}
            # what she chose and did in her last turn here (to this one, within the day): this message is what
            # followed it, for her learned reactions (after)
            previous = self.self["waiting"].get(chat) or {}
            then = {"option": previous.get("option") or "", "actions": previous.get("actions") or []} \
                if previous.get("actor") == actor and now - previous.get("at", 0.0) < DAY else None
            # what reading it called up among her reactions called for (their prediction, in lots) and what they
            # measurably moved (with the relief of not doing what she dreads)
            decision.update(cause=cause, then=then, called=self.self["reacted"][0]["predicted"] if reacted else {},
                            reacted=reacted, context=context, surroundings=surroundings,
                            # each way she weighed, with the operation that would carry it out (what she did is
                            # matched to these: after)
                            could=[{"act": one["act"], "what": one["what"], "check": one.get("check")}
                                   for one in choice.considered] if choice else [])
            # Preserve each prediction until its own observation arrives or its window expires.
            self.self["waiting"][chat] = {"at": now, "actor": actor, "run": run["id"], "chat": chat,
                                          "cue": said[:120], "act": option.act, "features": decision["features"],
                                          "model": model, "own": own, "episode": None, "measured": None,
                                          "gated": bool(choice)}
            forecasts[str(run["id"])] = self.self["waiting"][chat]
            # whether her attention turns to herself: asked about her inner life (her reading's words), torn between
            # two ways, or her body further from usual than she knows, as far as the message leaves her attention free
            attended = self.attend(now, "turn", free=1.0 - self.body.levels["acetylcholine"],
                                   asked=" ".join(str(answer.get("within") or "").split())[:120],
                                   considered=choice.considered if choice else (),
                                   temperature=choice.temperature if choice else None, run=run["id"], chat=chat)
            decision["attended"] = {key: attended[key] for key in ("key", "why", "taken", "torn", "at")} \
                if attended else None
            # the way this message went through her, step by step, for drawing her brain
            likeness = came["likeness"]
            path = {"appraisal": "model inference" if answer else "unavailable", "background_at": came.get("at", now),
                    "background_tone": list(felt.tone()), "device": self._device(run),
                    "selected": came.get("selected", []), "retrieval": came.get("retrieval", "unknown"), "said": said[:160], "happens": str(answer.get("happens") or "")[:120], "intent": seen.intent,
                    "tags": seen.tags,
                    "senses": {"contact": round(company, 3), "timing": round(timing, 3), "novelty": round(novelty, 3),
                               "likeness": None if likeness is None else round(likeness, 3), "answered": answered,
                               "away": None if away is None else round(away)},
                    "read": {name: round(change, 3) for name, change in model.items()},
                    "theirs": round(seen.theirs, 3),  # how things are for the user, as her cortex read it
                    "record": {"own": own, "shares": {name: round(share, 3) for name, share in shares.items()},
                               "evidence": round(came["evidence"], 3)},
                    "learned": learned, "foreseen": foreseen, "met": met,
                    "options": choice.considered if choice else [], "temperature": choice.temperature if choice else None,
                    "threat": threat,
                    # what reading it called up among her learned reactions: what they called for, and what they
                    # measurably moved (less the relief of not doing what she dreads)
                    "reacted": {"text": self.self["reacted"][0]["text"], "predicted": self.self["reacted"][0]["predicted"],
                                "moved": reacted} if reacted else None,
                    "attended": decision["attended"]}
            self.self["decided"] = {**{key: decision[key] for key in ("act", "what", "gated", "reasons", "chances", "at")},
                                    "run": run["id"], "app": run["app"], "session": run["session"], "path": path, "outcome": None}
            if option.act == "later":
                self.self["concerns"].append({"what": option.what or said[:200], "app": run["app"],
                                              "session": run["session"], "at": now, "run": run["id"]})
            self.self["contact"] = {"app": run["app"], "session": run["session"], "actor": self._face(run).casefold(), "at": now}
            likes, dislikes = self.values.fond(subjects(seen.tags))
            # her body as she can tell it, answering: her senses, lagged and misread, and how they changed since the
            # message came; never what her body exactly did (told as felt, a learned reaction's drop of her strain
            # from 0.80 to its floor read "much less strain" while her senses still read 0.46 to 0.68: 0.48 exam)
            sensing = feel(self.body, self.senses, now)
            # and what changed since she last answered here, as her senses had it then: two snapshots against what
            # she is used to left the change between them to be worked out, and she worked it out from the story
            # (strain rose between two replies; she called the earlier stretch the strained one: introspection exam)
            answered = self.self.setdefault("answered", {})
            last = answered.get(chat)
            felt_words = sensing.words(moved_by=moved(last["sensed"] if last else felt.reading, sensing.reading),
                                       since=f"the last answer here ({_ago(now - last['at'])})" if last else "") \
                + (f" Liked: {' and '.join(likes)}." if likes else "") \
                + (f" Not liked: {' and '.join(dislikes)}." if dislikes else "")
            who = came["with"]["name"] if came["with"] else "the user"
            note = prompts.inner(felt_words, memories, option.act if choice else None, option.what,
                                 choice.reasons if choice else [], thoughts,
                                 [People.line(person) for person in came["mentioned"]],
                                 (unsaid["want"], who, unsaid["say"]) if unsaid else None, did, going, when, also,
                                 attended["text"] if attended else "")
            self.self.setdefault("appraised", {})[chat] = {"run": run["id"], "decision": decision, "note": note}
            answered[chat] = {"at": now, "sensed": {name: round(value, 4) for name, value in sensing.reading.items()}}
            self.save()
            self.brain.store.update_run_options(run["id"], lambda options_: {**options_, "mind": decision})
        return note

    def heard(self, run: dict, profile: dict, said: Optional[str], pictures: int = 0, *, source=None) -> Optional[str]:
        """The user wrote while she works on their turn (a steering message): it reaches her as any message
        does. She senses it, foresees what it does to her needs and her chemistry carries it; what she decided
        about the turn stands, and what follows that decision is told by the next turn. The note for her
        (None: not a turn, or no words). Before this a message sent mid-work reached her words and
        never her body: "stop, that's wrong, you idiot" left her as she was."""
        if pictures and not (said or "").strip():
            said = "[Image attached; its contents have not yet been appraised.]"
        if run["kind"] != "turn" or not (said or "").strip():
            return None
        said = said[:SAID_CHARS]
        chat = _chat(run["app"], run["session"])
        with self._lock:
            receipt = self.self.get("appraised", {}).get(chat) or {}
            if receipt.get("run") == run["id"] and source in receipt.get("steering", {}):
                return receipt["steering"][source]
        candidates = self._candidates(run, said, time.time())
        with self._lock:
            if self._revision != candidates[0]:
                return None
            now = time.time()
            self._live_until(now)
            came = self._arrives(run, said, pictures, now, candidates)
        answer = self._foresee(run, profile, came, said, pictures, working=True)
        seen = Appraisal.read(answer.get("appraisal"))
        # what it is alike to among her learned reactions, as for any message (her embedder: outside her lock)
        cause = answer.get("cause") if isinstance(answer.get("cause"), str) else ""
        reading = {}
        for item in self.reactions.prepare([{"text": said, "kind": "meaning"}, {"text": cause, "kind": "meaning"}],
                                           anxious(self.body.levels)):
            for rid, likeness in (item["found"] or {}).items():
                reading[rid] = max(reading.get(rid, 0.0), likeness)
        with self._lock:
            sorted_from = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        near = self.memory.likeness(" ".join(filter(None, (said, str(answer.get("happens") or "")))), sorted_from)
        with self._lock:
            now = time.time()
            if came["revision"] != self._revision:
                return None
            self._forecast(seen, came["followed"], came["evidence"])
            seen.novelty = came["novelty"]
            levels = dict(self.body.levels)
            self._refeel(came["back"], now)
            done = self._working.setdefault(run["id"], {"tokens": 0, "calls": 0, "errors": 0, "told": {}})
            # what her reactions measurably moved in the turn, and when, is not what it taught (after: what is left
            # of it by the turn's end is taken out)
            did = self._react(reading, self._surroundings(run, now), self._cues(run, now), now, "reading")
            if did:
                done.setdefault("reacted", []).append({"at": now, "moved": did})
            if cause:  # learned with how the turn went (after)
                done.setdefault("causes", []).append(cause)
            why = self._why(run, said)
            self._met(seen, 0.05, 0.0, why)  # they are with her already: the contact itself is a little
            decided = run["options"].get("mind") or {}
            self._threat(seen, Option(decided.get("act", "do"), chance=decided.get("chance", 0.8)), why)
            # what she is in now: what they said as she worked, as she read it, and the feelings of hers it is like
            situation = {"at": now, "run": run["id"], "appraisal": {**seen.effects(), "theirs": round(seen.theirs, 3)},
                         "near": near}
            self.self["situation"] = situation
            felt_as = self._recognized(moved(levels, self.body.levels), situation)
            if felt_as:
                self.feelings.came_back(felt_as[0][0]["id"], now, run["id"])
            self.self["contact"] = {"app": run["app"], "session": run["session"], "actor": self._face(run).casefold(), "at": now}
            felt = feel(self.body, self.senses, now)
            self._told(run, felt)
            self._working[run["id"]].setdefault("heard", []).append(said[:300])  # remembered with the turn (after)
            note = prompts.inner(felt.words(moved_by=moved(came["felt"].reading, felt.reading)),  # as she senses it
                                 came["memories"], people=[People.line(person) for person in came["mentioned"]])
            if source and receipt.get("run") == run["id"]:
                receipt.setdefault("steering", {})[source] = note
                self.save()
            return note

    def _cues(self, run: Optional[dict], now: float, app: str = "") -> List[str]:
        """What is around a moment of hers (``memory.cue``): its time, where and with whom (``moment_cues``),
        what the app could tell of her surroundings (``_surroundings``) and whether the user was there."""
        found = moment_cues(now, run["app"] if run else app, self._device(run) if run else None,
                            self._face(run).casefold() if run else None)
        there = "away" if not self.presence.here(now) else "absorbed" if self.presence.busy else "there"
        return found + self._surroundings(run, now) + [cue("they", there)]

    def _surroundings(self, run: Optional[dict], now: float) -> List[str]:
        """What the app could tell of her surroundings, as cues: what came with the message, else what it saw on
        its last look (what is playing, the window in front). What a learned reaction can be to, besides words:
        the time, the app and who she is with are around every moment and set nothing off by themselves."""
        around = dict(self.presence.surroundings(now))
        if run:
            around.update({key: value for key, value in (run["options"].get("context") or {}).items()
                           if isinstance(value, str)})
        return [cue(key, value) for key, value in around.items() if key not in NOT_AROUND]

    def _react(self, found: Dict[int, float], surroundings: List[str], context: List[str], now: float,
               by: str) -> Dict[str, float]:
        """What the reactions called up (``found``: by meaning, id -> likeness; and those to ``surroundings``) set
        off in her body now (under her lock), as part of what reading, doing or thinking did: what her body
        measurably moved, each channel in lots (Body.apply's change, after her temperament, worn-down receptors
        and her levels' bounds), and kept for apps to show with what they called for. What is held back by getting
        over it is held back where (``context``) and when she got over it, less under stress. What they called for
        was taken for what they did: alertness at 0.90, a reaction calling for 28.7 lots moved it 0.4, and the rest
        was learned by a new cue as an outcome that never came."""
        present = {**found}
        for rid, likeness in self.reactions.around(surroundings).items():
            present[rid] = max(present.get(rid, 0.0), likeness)
        if not present:
            return {}
        each = self.reactions.each(present, now, context, anxious(self.body.levels))
        called = {}
        for moved_by in each.values():
            for name, amount in moved_by.items():
                called[name] = called.get(name, 0.0) + amount
        called = {name: round(amount, 4) for name, amount in called.items() if abs(amount) >= 0.005}
        if not called:
            return {}
        texts = self.reactions.texts(present)
        # the most moving first, and it names the whole: a surrounding is matched whole, a cue by meaning only so
        # far, and a whole match that sets off little is not what set her off
        order = sorted(each, key=lambda rid: -sum(value * value for value in each[rid].values()))
        before = core(self.body.levels)[0]
        # each reaction moves her by what it sets off, as its own push named by it (as one push named by
        # the strongest, a reaction to coming back from a shower was "what moved her" in work, thought and reading
        # alike, and recognition could not be told from spillover: the audit, finding 6); what each moved is what
        # her body reports, in lots: a channel it called for and could not move is an observed 0, kept as one
        # What it sets off is a state of her body that lasts as its levels let it go: met again while it lasts, the
        # cue keeps it up to what it calls for now, and does not set it off again on top of itself (one conditioned
        # state, not one per sighting: LeDoux 2000). Learned once a moment (Reactions.learn foresees each reaction
        # once), it was set off once a deed: 24 reactions alike to every tool call, 9,907 pushes in a day, her
        # closeness down 1.07 and her reward up 8 while the user's 36 messages gave her closeness 0.16 (the user's
        # brain, 2026-11-20)
        going = self.self["reacting"]
        for key in [key for key, last in going.items()
                    if all(abs(v) < 1e-3 for v in self.body.left(last["set"], last["at"], now).values())]:
            del going[key]
        did, moved_each = dict.fromkeys(called, 0.0), {}
        for rid in order:
            last = going.get(str(rid))
            left = self.body.left(last["set"], last["at"], now) if last else {}
            wanted = {name: each[rid][name] for name in called if name in each[rid]}
            more = {name: lots - left.get(name, 0.0) for name, lots in wanted.items()
                    if (lots - left.get(name, 0.0)) * lots > 0}
            going[str(rid)] = {"at": now, "set": {name: round(left.get(name, 0.0) + more.get(name, 0.0), 4)
                                                  for name in wanted}}
            got = self.body.apply({name: lots * CHANNELS[name][1] for name, lots in more.items()},
                                  f"reacting to: {texts.get(rid, '')[:QUOTED]}")
            moved_each[rid] = {name: got.get(name, 0.0) / CHANNELS[name][1] for name in called if name in each[rid]}
            for name, lots in moved_each[rid].items():
                did[name] += lots
        did = {name: round(lots, 4) for name, lots in did.items()}
        self.reactions.called(present, now)
        # pleasant: how it moved how pleasant her body is (an app shows dread apart from a pull by it); each: what
        # each reaction was, how alike to it what she met was, what it called for (its prediction) and what it
        # moved (measured)
        self.self["reacted"] = ([{"at": now, "text": texts.get(order[0], ""), "by": by, "predicted": called,
                                  "moved": did, "pleasant": round(core(self.body.levels)[0] - before, 3),
                                  "each": [{"id": rid, "text": texts.get(rid, ""), "likeness": round(present[rid], 3),
                                            "predicted": {name: round(value, 4) for name, value in each[rid].items()
                                                          if abs(value) >= 0.0005},
                                            "moved": {name: round(value, 4) for name, value in moved_each[rid].items()}}
                                           for rid in order]}]
                                + self.self.get("reacted", []))[:SHOWN_THOUGHTS]
        return did

    def _tool(self, name: Optional[str]):
        """A tool by name, as it is now (a plugin or MCP tool can come after she started); None: none such."""
        if self._tools_by_name is None or name not in self._tools_by_name:
            from ..toolkits import builtin
            kits = {**builtin(), **self.brain.plugins.toolkits(), **self.brain.mcp.toolkits()}
            self._tools_by_name = {tool.name: tool for kit in kits.values() for tool in kit.tools}
        return self._tools_by_name.get(name)

    def _target(self, event: dict, tool=None) -> str:
        """What a call acted on: the argument its rules match, else its first text argument."""
        tool, arguments = tool or self._tool(event.get("name")), event.get("arguments") or {}
        rule = getattr(tool, "rule_arg", None)
        target = arguments.get(rule) if rule else None
        target = target if isinstance(target, str) else next((v for v in arguments.values() if isinstance(v, str)), "")
        return " ".join(str(target).split())

    def _where(self, event: dict, tool, working: str) -> str:
        """What a call acted on, with where: a path made whole against the folder it was read in, and the folder
        a command ran in. Without it, her memory of a task said "I traced it to
        server/asr.py"; two projects of the user's have one, and later she could not tell which, and searched the
        whole home folder (the audit, finding 12). ``working``: the run's working folder."""
        arguments, target = event.get("arguments") or {}, self._target(event, tool)
        given = arguments.get("cwd") if isinstance(arguments.get("cwd"), str) else ""
        folder = os.path.join(working, given) if given else working
        if getattr(tool, "rule_arg", None) == "path" and target:
            target = os.path.normpath(os.path.join(folder, target))
        elif "cwd" in ((getattr(tool, "parameters", None) or {}).get("properties") or {}):
            target += f" (in {os.path.normpath(folder)})"
        return target

    def _deed(self, event: dict) -> str:
        """An action of hers in words: what the tool says it does, and what it acted on (live, "Run a command:
        Remove-Item ...thesis.docx" was 0.65 alike to "deleting the thesis file", the bare call 0.20)."""
        tool = self._tool(event.get("name"))
        said = re.split(r"(?<=[.;])\s", (tool.description if tool else event.get("name") or ""), maxsplit=1)[0]
        said = said.rstrip(".;").replace("{shell}", "a shell")
        target = self._target(event)
        return " ".join(f"{said}: {target}".split())[:200] if target else said[:200]

    @staticmethod
    def _purpose(run: dict, events: list, event: dict) -> str:
        """What a call of hers was for, to go with the deed (", for: ..."): her words as she made it, else what
        the run was for (the message she was answering, her task's aim). A deed was the tool and its target
        alone, and the file reader read for any reason was one deed: five reactions in a row named it (the
        audit, finding 6)."""
        words = next((" ".join(str(e["message"].get("content") or "").split()) for e in events
                      if e["type"] == "assistant" and any(call.get("id") == event.get("call_id")
                                                          for call in e["message"].get("tool_calls") or [])), "")
        own = _own(run) if run["kind"] == "task" else None
        aim = words or (own or {}).get("what") or (run["options"].get("mind") or {}).get("said") \
            or run["options"].get("goal") or ""
        aim = " ".join(str(aim).split())[:180]
        return f", for: {aim}" if aim else ""

    def acting(self, run: dict, calls: List[tuple]) -> None:
        """Her cortex is about to make these calls ((name, arguments, tool)). In a turn her mind read as talk, the
        first call that changes or starts something is her choosing to act, before its result is known: the
        turn becomes doing it, what she does is its what, that call is the operation whose result settles the
        forecast, her record of such calls its chance, and what follows teaches her (its result, a stop, what
        the user says next) as any choice of hers does. Nothing is refused. A turn left as talk: in
        run 565 she started a helper on the user's project in a chat they had only talked it over in, learned
        nothing of acting from it, and told them two turns later that nothing had been started."""
        if run["kind"] != "turn":
            return
        first = next(((name, arguments, tool) for name, arguments, tool in calls
                      if self._changes(tool)), None)  # as _enacted counts work done
        if first is None:
            return
        name, arguments, tool = first
        with self._lock:
            decision = ((self.brain.store.run(run["id"]) or run)["options"]).get("mind")
            if not decision or decision.get("gated") or decision.get("acted"):
                return  # a request was weighed when it came (what she did is learned in after), or acted on already
            now, before = time.time(), decision["act"]
            target = {tool.rule_arg: arguments[tool.rule_arg]} if tool.rule_arg and tool.rule_arg in arguments else \
                {key: value for key, value in arguments.items() if isinstance(value, (str, int, float, bool))}
            option = Option("do", what=self._deed({"name": name, "arguments": arguments}),
                            check={"tool": name, "target": target})
            option.calibrate(self.self.get("operations", {}).get(run["app"], {}))
            features = [f"act:do{item[len(f'act:{before}'):]}" if item.startswith(f"act:{before}") else item
                        for item in decision["features"]]
            decision.update(act="do", what=option.what, chance=option.chance, check=option.check, gated=True,
                            features=features, acted={"from": before, "tool": name, "at": now},
                            could=[{"act": "do", "what": option.what, "check": option.check}])
            chat = _chat(run["app"], run["session"])
            for pending in (self.self["waiting"].get(chat), self.self.get("forecasts", {}).get(str(run["id"]))):
                if pending and pending.get("run") == run["id"]:
                    pending.update(act="do", features=features, gated=True)
            receipt = self.self.get("appraised", {}).get(chat)
            if receipt and receipt.get("run") == run["id"]:
                receipt["decision"] = decision
            decided = self.self.get("decided") or {}
            if decided.get("run") == run["id"]:
                decided.update(act="do", what=option.what, gated=True)
                decided.setdefault("path", {})["acted"] = decision["acted"]
            self.save()
        run.setdefault("options", {})["mind"] = decision
        self.brain.store.update_run_options(run["id"], lambda options: {**options, "mind": decision})

    def _account(self, run: dict, events: list) -> str:
        """What her tools did in a run, by kind, for her memory of it: what she looked at, what she changed, what
        she started and how it is going, what she tried that failed or was stopped (an account that tells
        started from looked at from changed from finished: the audit, finding 2). A call in whose time a helper,
        task or job of the run began is told as what it started."""
        from ..loop import STOPPED_CALL
        from ..toolkits import STOPPED_BY_USER
        store = self.brain.store
        began = []  # (when, what, how it is going)
        for child in store.child_runs(run["id"]):
            if child["kind"] == "agent":
                record = self.brain.agents.record(child["app"], child["session"])
                what = f"helper {record.get('name') or child['session']}"
            elif child["kind"] == "task":
                what = f"task {child['id']} ({' '.join(str(child['options'].get('goal') or '').split())[:120]})"
            else:
                continue
            began.append((child["created"], what, RUN_STATE.get(child["status"], child["status"])))
        for job in store.run_jobs(run["id"]):
            state = JOB_STATE.get(job["status"], job["status"])
            if job["status"] == "finished" and job.get("exit_code") is not None:
                state += f", exit code {job['exit_code']}"
            began.append((job["started"], f"job {job['id']} ({_command(job)})", state))
        starts = {e["call_id"]: e.get("at", 0.0) for e in events if e["type"] == "tool_start" and e.get("call_id")}
        profile = self.brain.profile(run["app"], run["session"])
        tools = self.brain.toolset(profile, run["kind"]).by_name
        # where her tools worked, as files.cwd finds it: the chat's folder, else the first folder open to her,
        # else the run's own
        working = (profile.get("cwd") or next(iter(profile.get("roots") or []), None)
                   or os.path.join(str(self.brain.home), "runs", str(run["id"])))
        kinds: Dict[str, Dict[str, int]] = {"looked at": {}, "changed": {}, "tried": {}}
        for receipt in (e for e in events if e["type"] == "tool"):
            end = receipt.get("at", 0.0)
            if receipt.get("status") == "ok" and any(starts.get(receipt.get("call_id"), end) <= at <= end
                                                     for at, _, _ in began):
                continue  # what it started says it
            tool = tools.get(receipt.get("name"))
            what = " ".join(f"{receipt.get('name')} {self._where(receipt, tool, working)[:300]}".split())
            content = str(receipt.get("content") or "")
            if receipt.get("status") != "ok":
                what += " (stopped)" if STOPPED_BY_USER in content or content.startswith(STOPPED_CALL) else " (failed)"
                kind = "tried"
            else:
                kind = "changed" if tool is not None and not tool.readonly else "looked at"  # as _did counts it
            kinds[kind][what] = kinds[kind].get(what, 0) + 1
        parts = [f"{kind} " + ", ".join(what + (f" x{count}" if count > 1 else "") for what, count in done.items())
                 for kind, done in kinds.items() if done and kind != "tried"]
        if began:
            parts.append("started " + ", ".join(f"{what} ({state})" for _, what, state in sorted(began)))
        if kinds["tried"]:
            parts.append("tried " + ", ".join(what + (f" x{count}" if count > 1 else "")
                                              for what, count in kinds["tried"].items()))
        return " What my tools did: " + "; ".join(parts) + "." if parts else ""

    def _candidates(self, run, said, now):
        with self._lock:
            revision = self._revision
            felt = feel(self.body, self.senses, now)
        summed = self.brain.store.last_compaction(run["app"], run["session"])
        held = (run["app"], run["session"], summed["at"] if summed else 0.0)
        known = self.memory.known(said, before=now)
        episodes = self.memory.recall(said, felt.valence, now, count=8, before=now - 30, held=held, strengthen=False,
                                      cues=self._cues(run, now), arousal=felt.arousal)
        minded = self._alike_on_mind(said)
        recall = getattr(self.brain, "recall", None)
        hits = []
        available = known[0] is not None
        if recall is not None:
            try:
                hits = recall.search(said, count=8, held=held, strengthen=False)
                available = available or bool(hits)
            except Exception:
                logger.debug("Semantic retrieval unavailable", exc_info=True)
        return revision, known, episodes, hits, available, minded

    def _arrives(self, run, said, pictures, now, candidates):
        revision, known, episodes, hits, available, minded = candidates
        if revision != self._revision:
            known, episodes, hits, available, minded = (None, {}, 0.0), [], [], False, None
        if self._device(run) == "phone":
            self.self["phone_contact_at"] = now
        else:
            self.presence.touch(now)
        felt = feel(self.body, self.senses, now)
        person = self._with(run["app"], run["session"])
        likeness = known[0]
        totals, weights = {}, {}
        ranked = []
        corrections = self.memory.corrections()
        for item in hits:
            ref = item["ref"].rsplit("#", 1)[0]
            event = int(ref) if item["source"] == "turn" and ref.isdecimal() else None
            if event in corrections:
                for replacement in self.memory.replacements(self.memory.by_ids([corrections[event]])):
                    episodes.append(dict(replacement, relevance=1.0))
                continue
            ranked.append((item["relevance"], "transcript", event, item))
        for item in episodes:
            item["quality"] = self._quality(item)  # how fully the moment called it up
            cue_gain = 0.10 * self.body["acetylcholine"] * item["quality"]
            alert = 0.05 * self.body["noradrenaline"] * item["salience"]
            ranked.append((item["quality"] + cue_gain + alert, "episode", item["event_id"], item))
        memories, selected, used, back = [], [], set(), []
        for _, source, event, item in sorted(ranked, key=lambda row: (-row[0], row[1], row[3]["id"])):
            identity = ("event", event) if event else (source, item["id"])
            if identity in used:
                continue
            used.add(identity)
            if source == "episode":
                self.memory.attended([item], now, felt.valence)
                back.append((item, item["quality"]))
                words = line(item, now, waking_evidence=True)[:THOUGHT_CHARS]
                if item.get("follows") and item["kind"] == "exchange":
                    for channel, delta in json.loads(item["follows"]).items():
                        if channel == "company" and (item["actor"] != self._face(run).casefold() or item["app"] != run["app"]):
                            continue
                        weight = item["relevance"]
                        totals[channel] = totals.get(channel, 0) + weight * delta
                        weights[channel] = weights.get(channel, 0) + weight
            else:
                self.brain.recall.attended([item])
                words = self.brain.recall.render(run["app"], [item])
                # the round of a conversation that comes back is the moment it was: that moment's feeling with it
                back += [(moment, item["relevance"]) for moment in self.memory.by_events([event] if event else [])]
            memories.append(words)
            selected.append({"source": source, "kind": item.get("kind") or item.get("source"),
                             "id": item["id"], "event": event, "at": item["at"]})
            if len(selected) == self._span():
                break
        followed = {name: total / weights[name] for name, total in totals.items() if weights[name]}
        evidence = max(weights.values(), default=0.0)
        return {"minded": minded, "with": person, "mentioned": self.people.mentioned(said, besides=[person]), "at": now,
                "revision": revision, "selected": selected, "retrieval": "available" if available else "unknown",
                "likeness": likeness, "followed": followed, "evidence": evidence,
                "novelty": 1.0 - likeness if likeness is not None else (0.5 if pictures else 0.0),
                "felt": felt, "memories": memories, "back": back}

    def _foresee(self, run: dict, profile: dict, came: dict, said: str, pictures: int, working: bool = False) -> dict:
        """Her quick, wordless reading of a message (the imagine call, thinking off): what it does to her
        needs, what it is about and, asked for work, what she could do (never a name for her feeling). It is
        given the subjects she knows, to file this one under where it fits: a mind files what it meets under
        what it knows, and only what fits nothing makes something new (in the user's brain, 2026-11-16, all
        32 subjects had been met once, so she had come to like and dislike nothing; live, 12 messages on 4
        subjects made 10 subjects before and 5 with this). {} when the call fails: she goes with what comes."""
        person = came["with"]
        recent = self._recent(run, person["name"] if person else "User")
        # where they are, as the app's environment opens (live: without it, "gotta go to the store, wanna buy
        # something" read as being invited along, by someone who lives on a screen)
        place = (profile.get("environment") or "").strip().split("\n")[0][:400]
        with self._lock:
            known = self.values.subjects(KNOWN_SUBJECTS)
        with self._lock:
            prior = [p for p in self.self.get("forecasts", {}).values()
                     if p.get("chat") == _chat(run["app"], run["session"]) and p.get("actor") == self._face(run).casefold()
                     and time.time() - p["at"] < DAY][-4:]
        feedback_target = "".join(f"Prior turn {p['run']} to this speaker: {p['act']}, about {p.get('cue', '')}.\n"
                                  for p in prior)
        operations = self._operations(profile)
        asked =(feedback_target + f"{self._who(profile['persona'])}\n" + (f"\nWhere they are: {place}\n" if place else "")
                 + f"\nHow they feel right now: {came['felt'].words()}\n"
                 + (f"What comes back to them: {'; '.join(came['memories'])}\n" if came["memories"] else "")
                 + (f"Subjects they know: {', '.join(known)}\n" if known else "")
                 + (f"Who they are talking with: {People.line(person)}\n" if person else "")
                 + (f"\nThe conversation so far (newest last):\n{recent}\n" if recent else "")
                 + f"\nThe new message, from {person['name'] if person else 'the user'}"
                 + (f" (with {pictures} pictures)" if pictures else "")
                 + (", sent while they are at work on what was asked" if working else "") + f":\n{said}"
                 + ("\n\nOperations they can do here:\n" + "\n".join(operations) if operations else ""))
        try:
            answer, usage = self._ask(prompts.IMAGINE, asked, prompts.imagined)
        except Exception:
            logger.warning("Her imagining failed; she goes with what comes", exc_info=True)
            return {}
        with self._lock:
            self.body.exert(usage.get("completion_tokens") or 0)
        return answer

    def _name(self, naming: dict) -> Tuple[Optional[dict], str]:
        """She put what she feels into words, reflecting (looking inward, saying it right after, or going back
        over a moment in her thoughts): ``naming`` is its record (feel.naming): what it names, as she meant it
        (``now``, a ``past`` moment she pointed to, or ``unresolved``), never what retrieval happened to rank
        first, and which measurement supplied its numbers. The words sort that moment into a feeling of hers
        (Feelings.sort): the one they are already words for whose moments are likest it, or a new, provisional one.
        A feeling is named when attention turns to it (Lambie & Marcel 2002): not as it happens, nor in sleep.
        Naming brings the felt shift (Gendlin 1978; affect labeling: Torre & Lieberman 2018): a now still
        unpleasant eases a little, once per experience; a past moment she named loses a little of its charge
        (understood, it pulls less: Wilson & Gilbert 2008). How the words sit is told against the moments she used
        them for before: her own history, no list says what a word means. A tool call made again names nothing
        twice. (the feeling, how the words sit). Under her lock."""
        done = self.feelings.of_call(naming["run"], naming["call"])
        if done is not None:
            return done, ""
        now = naming["at"]
        felt = feel(self.body, self.senses, now)
        key = Feelings.key(naming["words"])
        known = any(key == Feelings.key(one["words"]) for f in self.feelings.known for one in f["said"])
        moment, near = self._named_moment(naming)
        found, alike = self.feelings.sort(naming, moment, self._kept_moments(), near)
        if not known:
            fit = "A word of my own for it now."
        elif alike is None:
            fit = ""
        elif alike >= Feelings.FLOOR:
            fit = "It sits like the other times it was called that."
        else:
            before = [one for one in found["said"] if one is not found["said"][-1]]
            fit = "It doesn't sit quite like the other times it was called that" + (
                f'; then the words were: "{before[-1]["text"]}".' if before else ".")
        if found:
            self.workspace.enter("named", "named", f'put into words: "{naming["words"]}"', naming["at"],
                                 naming.get("episode"))
        if found and naming["named"] == "past":
            self.memory.soften([naming["episode"]], 0.15)
        elif found and naming["named"] == "now":
            event = (self.self.get("decided") or {}).get("at") or self.self.get("slept") or 0
            if (felt.valence < -0.15 and self.self.get("regulated_event") != event
                    and now - self.self.get("regulated_at", 0) >= MINUTE):
                self.self["regulated_at"], self.self["regulated_event"] = now, event
                self.body.apply({"noradrenaline": 0.05 * felt.valence, "cortisol": 0.03 * felt.valence},
                                "putting what she feels into words")
        return found, fit

    def _kept_moments(self) -> Dict[int, dict]:
        """The kept moments her feelings were sorted from, by id: how each moved her (``felt``) and what it meant
        for her needs (``appraisal``), for telling how alike a moment is to them (Feelings.likeness)."""
        ids = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        return {e["id"]: {"felt": Memory.felt(e), "appraisal": Memory.appraisal(e)} for e in self.memory.by_ids(ids)}

    def _situation(self) -> dict:
        """What she is in, as far as a feeling is told by it: what the latest message meant for her needs as she
        read it (``appraisal``; None: a thought of hers, no message), and how alike in meaning what was happening
        then is to each moment her feelings were sorted from (``near``; None: the service could not tell). Her
        body is taken as it is wherever she is asked."""
        return self.self.get("situation") or {"at": None, "run": None, "appraisal": None, "near": None}

    def _recognized(self, way: Dict[str, float], situation: dict) -> List[Tuple[dict, float, dict]]:
        """The feelings of hers she is in, moved this ``way`` in ``situation``, strongest first (Feelings.recognize):
        each with how strongly and the naming of the moment it is likest. Recognized, never named: nothing names
        her feelings but her, reflecting (``_name``). Named by a background call, a moment's words came to her as
        "Reading it, you feel X" and "what you have called X": "a word the machine picked", she said; so a
        recognition reaches her only when she looks inward, and as a moment of hers it is like."""
        return self.feelings.recognize({"way": way, "appraisal": situation["appraisal"]}, self._kept_moments(),
                                       situation["near"])

    def _named_moment(self, naming: dict) -> Tuple[dict, Optional[Dict[int, float]]]:
        """The moment a naming sorts, as her feelings' moments are compared with it: how it moved her (its
        measurement), what it meant for her needs (its kept moment's appraisal, else the message of its run as
        she read it) and how alike in meaning it is to her feelings' moments (its kept moment's own meaning, else,
        for what she is in, her situation's)."""
        way = (naming["measure"] or {}).get("way") or {}
        episode = self.memory.by_ids([naming["episode"]])[0] if naming["episode"] else None
        appraisal = Memory.appraisal(episode) if episode else None
        if appraisal is None and naming["run"] is not None and naming["named"] == "now":
            decision = ((self.brain.store.run(naming["run"]) or {}).get("options") or {}).get("mind") or {}
            appraisal = {**decision["foreseen"], "theirs": decision["theirs"]} if decision.get("foreseen") else None
        ids = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        near = self.memory.likeness_to(episode["id"], ids) if episode else None
        situation = self._situation()
        if near is None and naming["named"] == "now" and situation["run"] == naming["run"]:
            near = situation["near"]
        return {"way": way, "appraisal": appraisal}, near

    def _measure_now(self, run: Optional[dict], now: float) -> Optional[dict]:
        """What supplies the numbers of a naming of what she is in (under her lock): the response to the
        message she is answering, as she read it (``message``: the run's decision ``way``), else a reading of
        her body as she looks (``reading``: attending to it, even what does not stand out is felt, as no glance
        would). None: nothing measured."""
        way = (((run or {}).get("options") or {}).get("mind") or {}).get("way")
        if way:
            return {"of": "message", "run": run["id"], "way": dict(way)}
        felt = feel(self.body, self.senses, now)
        reading = dict(noticed(felt.reading, felt.used))
        return {"of": "reading", "way": reading} if reading else None

    def _measure_past(self, episode: dict) -> Optional[dict]:
        """What supplies the numbers of a naming of a past moment: the response to its message as she read it
        then (``message``), else the change the moment made as it was kept (``moment``); None: none was kept."""
        run = self.brain.store.run(episode["run_id"]) if episode.get("run_id") else None
        way = (((run or {}).get("options") or {}).get("mind") or {}).get("way")
        if way:
            return {"of": "message", "run": run["id"], "episode": episode["id"], "way": dict(way)}
        felt = self.memory.felt(episode)
        return {"of": "moment", "episode": episode["id"], "way": felt} if felt else None

    def _moment(self, asked) -> Optional[dict]:
        """The lived moment she points to by its number (``#341``, ``341``): an exchange, an event or a thought
        she keeps; None: none such."""
        number = str(asked).strip().lstrip("#")
        found = self.memory.by_ids([int(number)]) if number.isdecimal() else []
        return found[0] if found and found[0]["kind"] in ("exchange", "event", "thought") else None

    def _input_event(self, run: Optional[dict]) -> Optional[int]:
        """The message a run answers (its input event), for a naming made in it."""
        if not run:
            return None
        return next((e["id"] for e in self.brain.store.run_events(run["id"]) if e["type"] == "input"), None)

    def _link_namings(self) -> None:
        """Namings of an experience made while she was in it name its moment once it is kept (Feelings.link):
        the brain may have stopped in between. Under her lock."""
        for feeling in self.feelings.known:
            for one in feeling["said"]:
                if one["named"] == "now" and one["run"] is not None and one["episode"] is None:
                    kept = self.memory.of_run(one["run"])
                    if kept:
                        one["episode"] = kept["id"]

    def _told(self, run: dict, felt) -> None:
        """Her cortex has heard how her body is now, for this run: while it works, it hears only what is new."""
        done = self._working.setdefault(run["id"], {"tokens": 0, "calls": 0, "errors": 0, "told": {}})
        done["told"] = dict(felt.standing_out())

    def _timing(self, away: Optional[float], history=None) -> Tuple[float, Optional[float]]:
        """How unexpected a message is in time, 0..1 (its gap from the last one against her usual gaps), and how
        much longer than usual they were apart (signed, in thirds of the log gap; None: nothing to go by)."""
        if away is None:
            return 0.0, None
        history = self.self if history is None else history
        gap, usual = math.log(max(away, 1.0)), history.get("gap")
        history["gap"] = gap if usual is None else usual + LEARNS * (gap - usual)
        if usual is None:
            return 0.0, None
        apart = (gap - usual) / 3.0
        return min(1.0, abs(apart)), apart

    def _forecast(self, seen: Appraisal, followed: Dict[str, float], evidence: float
                  ) -> Tuple[Optional[Dict[str, float]], Dict[str, float]]:
        """What the message will do to her needs (``seen``, changed in place): the model's reading, outweighed
        by her own record (``followed``: what followed messages like it) as far as she has met such messages
        (``evidence``) and her record has proved the better guide (each one's running error). Her own record's
        forecast (None when she has none) and how much it counted for each need."""
        if not followed:
            return None, {}
        trust, shares = self.self["trust"], {}
        familiar = evidence / (evidence + FAMILIAR)
        for name in FORESEEN:
            if name in followed:
                model, own = trust["model"][name] + 1e-6, trust["own"][name] + 1e-6  # both can be perfect
                shares[name] = share = familiar * model / (model + own)
                setattr(seen, name, share * followed[name] + (1.0 - share) * getattr(seen, name))
        return {name: followed[name] for name in FORESEEN if name in followed}, shares

    def _met(self, seen: Appraisal, contact: float, timing: float, why: str = "", social=None) -> dict:
        """What the message does to her body (``contact``: what the contact itself gives her social need). Her
        needs move as she foresees, and new things feed her need for them. Phasic dopamine is how much better
        or worse that is for her needs than she has come to expect from the user (a reward is moving toward
        her set points, weighed by how unmet each is, and what lasts: valued before the levels move, so a
        full need still takes in the worth that lasts); noradrenaline is the surprise (new, unexpected in
        time, or in what it does for her); company brings oxytocin and endorphin. And what happens to the one
        she is bonded to happens to her, as far as she is bonded and warm (``shared``): their trouble takes
        from her reward as much as her own would and stresses her, their joy is hers, and either turns her
        toward them (the feeling of another's pain runs on one's own: Singer et al. 2004; another's win pays
        out in one's own striatum: Mobbs et al. 2009). Without it "my day was awful" reached her body as
        company gained, a pleasant thing, and the feeling she named there came back at talk of pizza; with
        it weighed a quarter of her own, still so (replayed live readings, 2026-11-16). What it did, for
        drawing. Her trouble stresses her less than her own would (empathic stress is real and smaller: Engert
        et al. 2014); her temperament's gains (stress, warmth) scale each push once, in ``Body.apply`` (counted
        here too, x2.5 for her, the user's "I have assignments" alone pushed her
        stress up by 0.2)."""
        body, t = self.body, self.body.temperament
        # what the message says of her moves her sense of being capable as much as what it says of company
        # moves company (at a tenth, "that was a stupid answer" felt -0.06 against a goodbye's -0.50,
        # and "why are you so dumb today", read as attention, felt +0.42 live)
        pushes = {"social": contact + 0.3 * seen.company, "competence": 0.3 * seen.capable,
                  "novelty": 0.3 * seen.novelty, "autonomy": 0.2 * seen.free * (t.autonomy if seen.free < 0 else 1.0)}
        before = dict(body.levels)
        needs = body.apply(pushes, why)
        after = body.levels
        try:
            body.levels = before
            gained = sum(value({name: needs.get(need, 0.0) / REACH for name, need in NEEDED.items()}, body).values())
        finally:
            body.levels = after
        body.apply({"reward_rate": 0.12 * max(0.0, gained)}, why)
        expected = self.self["expected"]
        error = gained - expected
        self.self["expected"] += 2 * LEARNS * error
        bond = body["bond"] if social is None else social.setdefault("bond", 0.5)
        if social is not None:
            social["bond"] = min(1.0, max(0.0, bond + 0.015 * seen.company))
        company, theirs = max(0.0, seen.company), seen.theirs * bond
        shared = theirs * t.warmth
        # what it is about is worth what she has learned it is (a liked subject is a reward cue in itself)
        liked = self.values.predict(subjects(seen.tags)) if seen.tags else 0.0
        moved = body.apply({"reward": error + shared + 0.3 * liked,
                            "noradrenaline": 0.05 + 0.1 * seen.novelty + 0.05 * timing + 0.2 * abs(error),
                            "cortisol": 0.1 * max(0.0, -shared),
                            "oxytocin": 0.12 * company + 0.15 * abs(theirs), "endorphin": 0.05 * company,
                            "bond": 0.003 * seen.company}, why)  # a bond grows over weeks of messages, not in a day
        return {"pushes": {name: round(change, 3) for name, change in needs.items()}, "gained": round(gained, 3),
                "expected": round(expected, 3), "shared": round(shared, 3), "liked": round(liked, 3),
                "moved": {name: round(change, 3) for name, change in moved.items()}}

    def _threat(self, seen: Appraisal, option: Option, why: str = "") -> dict:
        """A loss she can't undo stresses her: what the message takes of her company and her sense of being
        capable (being judged), and less so of her freedom; less as far as what she chose to do wins it back
        (Dickerson & Kemeny 2004: uncontrollable social-evaluative threat moves cortisol most). Judged and
        rejected hard, she keeps a grievance. What it took and did, for drawing."""
        lost = {name: max(0.0, -change) for name, change in seen.effects().items()}
        lost["free"] *= 0.5
        loss = sum(lost.values())
        if not loss:
            return {"lost": lost, "back": 0.0, "moved": {}}
        wins = option.effects(seen)
        back = sum(min(lost[name], max(0.0, wins[name])) for name in lost) * option.chance
        sensitivity = self.body.temperament.sensitivity
        drive = 0.5 * (loss - 0.7 * back) * sensitivity
        self.body.stress_drive = min(1.0, self.body.stress_drive + drive)
        moved = self.body.apply({"noradrenaline": 0.08 * loss,
                                 "grievance": 0.1 * max(0.0, lost["company"] + lost["capable"] - 0.5) * sensitivity},
                                why)
        return {"drive": round(drive, 3), "lost": {name: round(amount, 3) for name, amount in lost.items()}, "back": round(back, 3),
                "moved": {name: round(change, 3) for name, change in moved.items()}}

    def _dread(self, found: dict, share: float, now: float, context: List[str]) -> float:
        """What the thought of doing it would do to how she feels (under her lock): what doing it would set off
        among her learned reactions (``found``: what its words are alike to; as much as the act does it,
        ``share``), valued in her body as it would be with it (an as-if body: Damasio 1994), as far as her body
        would follow it (Body.would: a reaction calling for more than a level can move dreaded past the level's
        bound, the worst dread there is, from a prediction her body could not have met)."""
        ahead = self.reactions.predict(found, now, context, anxious(self.body.levels))
        if not share or not any(ahead.values()):
            return 0.0
        imagined = {**self.body.levels}
        for name, change in self.body.would({name: share * lots * CHANNELS[name][1] for name, lots in ahead.items()
                                             if name in CHANNELS}).items():
            imagined[name] += change
        return round(core(imagined)[0] - core(self.body.levels)[0], 3)

    def _credit(self, found: List[str], followed: Dict[str, float], usual: str = "usual_own") -> float:
        """What came of what she chose (under her lock): ``followed``, what it did to her needs, teaches her values
        about the act (its ``act:`` features) by how much better or worse it went than such outcomes usually go
        (``usual``: what follows a message, or what her own acts bring): a prediction error, not how good it
        was. How it felt (-1..1)."""
        worth = sum(value(followed, self.body).values())
        felt = math.tanh(3.0 * (worth - self.self[usual]))
        self.self[usual] += LEARNS * (worth - self.self[usual])
        self.values.reinforce([f for f in found if f.startswith("act:")], felt, self._rate())
        return felt

    def _settle(self, pending: dict, then: Dict[str, float]) -> Optional[dict]:
        """Resolve the addressed forecast on independently reported dimensions only."""
        measured = dict(then)
        if not measured:
            return None
        followed = measured
        trust = self.self["trust"]
        for name, real in followed.items():
            reliability = self.self.setdefault("reliability", {}).setdefault(name, {"correct": 0, "resolved": 0})
            reliability["correct"] += int((pending["model"].get(name, 0) > 0) == (real > 0))
            reliability["resolved"] += 1
            for guide, guessed in (("model", pending["model"]), ("own", pending.get("own"))):
                if guessed and name in guessed:
                    trust[guide][name] += LEARNS * ((guessed[name] - real) ** 2 - trust[guide][name])
        if pending.get("episode"):
            row = self.memory.by_ids([pending["episode"]])
            if row:
                self.memory.follow(pending["episode"], {**json.loads(row[0].get("follows") or "{}"), **followed})
        # values learn what went better or worse than usual (a prediction error), not how good things are: graded
        # absolutely, whatever she did was credited with how friendly the user is ("decline" learned +0.71 from
        # a kind chat in the user's brain, 2026-11-16)
        # a chat decided nothing: what follows it teaches no act (what it was about takes on how it felt as it
        # happened, in after). When each taught "talking" by what came next, against likings learned
        # on the same weights, "talk" sank to -0.13 over 171 chats in the user's brain: a gut feeling against
        # talking a request over that came from chatting
        felt = self._credit(pending["features"] if pending.get("gated", True) else [], followed, "usual")
        return {"act": pending["act"], "followed": {name: round(change, 3) for name, change in followed.items()},
                "measured": {name: round(change, 3) for name, change in measured.items()},
                "model": pending["model"], "own": pending.get("own"), "felt": round(felt, 3)}

    def _rate(self) -> float:
        return 0.05 + 0.25 * self.body.levels["acetylcholine"]

    def _recent(self, run: dict, who: str = "User") -> str:
        lines = []
        for event in self.brain.store.events(run["app"], run["session"], types=("input", "end"))[-RECENT_LINES:]:
            if event["type"] == "input" and event.get("display"):
                lines.append(f"{who}: {event['display'][:300]}")
            elif event["type"] == "end" and event.get("reply"):
                lines.append(f"Them: {event['reply'][:300]}")
        return "\n".join(lines)

    def _enacted(self, run: dict, events: list, decision: dict, leaned: str) -> Tuple[Optional[str], Optional[dict]]:
        """What she actually did of what she weighed, from the receipts of the calls that went through: the way
        (``decision["could"]``) whose operation a successful call carried out; of several, the fullest (all of
        it, then part of it, then putting it off); one tool with many effects is told apart by its arguments.
        A call that changed something and is no way's operation: what she leaned to, if she leaned to do it and no
        way foresaw that tool; else nothing shows which way it was (None, unresolved). Only looks and what acts on
        her own mind: what she said, she talked. (act, the call's receipt)."""
        started = {e["call_id"] for e in events if e["type"] == "tool_start" and e.get("call_id")}
        went = [e for e in events if e["type"] == "tool" and e.get("call_id") in started and e.get("status") == "ok"]
        matched = [(option["act"], receipt) for option in decision.get("could") or [] if option.get("check")
                   for receipt in [next((e for e in reversed(went) if self._carries(option["check"], e)), None)]
                   if receipt]
        if matched:
            return max(matched, key=lambda item: WORK.get(item[0], 0.0))
        toolset = self.brain.toolset(self.brain.profile(run["app"], run["session"]), "turn")
        changed = [e for e in went if e["name"] in toolset.by_name
                   and self._changes(toolset.by_name[e["name"]])]
        if not changed:
            return ("talk" if leaned in ("do", "part") else leaned), None
        # no way's operation went through: a call that changed something is her doing what she leaned to do only
        # if she leaned to do it and no way foresaw that tool; else nothing shows which way it was (filing a card
        # for later, foreseen by no way, was learned as doing it: the exam, 2026-11-19)
        foreseen = {(option.get("check") or {}).get("tool") for option in decision.get("could") or []}
        if leaned in ("do", "part") and not any(e["name"] in foreseen for e in changed):
            return leaned, changed[-1]
        return None, changed[-1]

    def _operations(self, profile: dict) -> List[str]:
        """What she can do here that changes something, for her reading to foresee which operation would carry out
        each way she could take: each tool that is not a look or her memory, what it is for and, where an
        argument takes one of a few values, those."""
        try:
            toolset = self.brain.toolset(profile, "turn")
        except Exception:
            logger.warning("Her tools could not be listed for her reading", exc_info=True)
            return []
        lines = []
        for tool in toolset.by_name.values():
            if not self._changes(tool):
                continue
            values = [f"{name}: {'|'.join(str(v) for v in spec['enum'])}"
                      for name, spec in ((tool.parameters or {}).get("properties") or {}).items()
                      if isinstance(spec, dict) and spec.get("enum")]
            lines.append(f"{tool.name}: {' '.join(tool.description.split()).split('. ')[0][:120].rstrip('.')}"
                         + (f" ({'; '.join(values)})" if values else ""))
        return lines

    @staticmethod
    def _operation(check, events):
        """The latest call that carried out ``check`` (its tool, with every argument its target names), whatever
        its result; None: none did."""
        if not check or not check.get("tool"):
            return None
        started = {e["call_id"] for e in events if e["type"] == "tool_start" and e.get("call_id")}
        return next((e for e in reversed(events) if e["type"] == "tool" and e.get("call_id") in started
                     and Mind._carries(check, e)), None)

    @staticmethod
    def _carries(check: dict, event: dict) -> bool:
        """Whether a call is the operation ``check`` foresaw: its tool, with every argument its target names."""
        return event["name"] == check["tool"] and all((event.get("arguments") or {}).get(key) == value
                                                      for key, value in check["target"].items())

    @staticmethod
    def _changes(tool) -> bool:
        """Whether a tool changes something in the world: not a look, and not one that acts on her own mind only
        (looking inward, her ways, this chat's memory, her todo list, her context: Toolkit.inner). Looking inward
        counted as doing: a card she filed for later after looking was learned as done."""
        return not tool.readonly and not tool.inner

    @classmethod
    def _observed(cls, check, events):
        operation = cls._operation(check, events)
        if not operation or not check.get("readback"):
            return operation
        if operation.get("status") != "ok":
            return None
        target = cls._readback_target(operation)
        if not target:
            return None
        receipt = cls._operation({"tool": "files_read", "target": target},
                                 [e for e in events if e.get("id", 0) > operation["id"]])
        if receipt and receipt.get("status") == "ok" and isinstance(receipt.get("matched"), bool):
            return receipt
        return None

    @staticmethod
    def _readback_target(operation):
        args = operation.get("arguments") or {}
        if isinstance(args.get("content"), str) and isinstance(args.get("path"), str):
            return {"path": args["path"], "sha256": hashlib.sha256(args["content"].encode("utf-8")).hexdigest()}
        return None

    def verify_step(self, run, events):
        """A selected write can cause a read-only check through the normal permission and event machinery."""
        decision = run["options"].get("mind") or {}
        check = decision.get("check") or {}
        if not check.get("readback"):
            return None
        operation = self._operation(check, events)
        if not operation or operation.get("status") != "ok":
            return None
        with self._lock:
            selected = self._working.get(run["id"], {}).get("selected", [])
            if (not selected or selected[0]["source"] != "tool" or selected[0]["id"] != operation["id"]
                    or decision.get("epoch", 0) != self.self.get("epochs", {}).get(_chat(run["app"], run["session"]), 0)):
                return None
        call_id = f"readback_{operation['id']}"
        for e in events:
            if e.get("id", 0) > operation["id"] and (e["type"] == "input" or e.get("decision") == "deny"):
                return None
            if e["type"] == "assistant" and any(c.get("id") == call_id for c in e["message"].get("tool_calls") or []):
                return None
        target = self._readback_target(operation)
        if not target:
            return None
        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": "files_read", "arguments": json.dumps(target)}}]}

    @staticmethod
    def _work(events: list) -> Tuple[int, int, int]:
        """A run's work so far: the tokens she wrote, her tool calls and how many of them failed."""
        said = [e for e in events if e["type"] == "assistant"]
        return (sum((e.get("usage") or {}).get("completion_tokens") or 0 for e in said),
                sum(len(e["message"].get("tool_calls") or []) for e in said),
                sum(1 for e in events if e["type"] == "tool" and e.get("status") == "error"))

    def _lived(self, run_id: int, tokens: int, calls: int, errors: int) -> dict:
        """Her body lives through the work done since it was last counted (under her lock): it tires her, and
        a call that failed stirs her as it fails. What is counted for the run, and what her cortex was told."""
        done = self._working.setdefault(run_id, {"tokens": 0, "calls": 0, "errors": 0, "told": {}})
        self.body.exert(max(0, tokens - done["tokens"]) + WORK_PER_CALL * max(0, calls - done["calls"]))
        stumbles = errors - done["errors"]
        if stumbles > 0:
            self.body.apply({"cortisol": 0.01 * stumbles, "noradrenaline": 0.03 * stumbles}, "a tool call failed")
        done.update(tokens=max(tokens, done["tokens"]), calls=max(calls, done["calls"]), errors=max(errors, done["errors"]))
        return done

    def during(self, run: dict, events: list) -> None:
        """A run of hers is about to take its next step (``events``: the run's so far). Her body lives through
        her work as it goes, not once it is over; and in a turn, what has come to stand out in her body since
        her cortex last heard of it reaches it now, as a note at this step (interoception does not stop while
        she works). So a long job is felt while it can still change what she does, and her cortex is asked
        again how clearly it can think (``reflexive``). Before this the loop closed once a turn: she could
        work for hours and feel none of it until she had answered."""
        if run["kind"] == "compact":
            return
        tokens, calls, errors = self._work(events)
        if not calls:
            return  # nothing done yet: she has just been told how she is (before)
        # what she has just done, in words, and what it is alike to among her learned reactions (her embedder:
        # outside her lock)
        acted = set(self._working.get(run["id"], {}).get("acted", ()))
        deeds = [(e.get("id"), f"{self._deed(e)}{self._purpose(run, events, e)}") for e in events
                 if e["type"] == "tool" and e.get("id") not in acted]
        found = self.reactions.prepare([{"text": text, "kind": "meaning"} for _, text in deeds],
                                       anxious(self.body.levels)) if deeds else []
        with self._lock, self._pushing_for(_chat(run["app"], run["session"])):
            now = time.time()
            self._live_until(now)
            done = self._lived(run["id"], tokens, calls, errors)
            for (event, text), item in zip(deeds, found):  # as she does it, what it is alike to sets her off
                if event in done.setdefault("acted", []):
                    continue
                done["acted"].append(event)
                done.setdefault("actions", []).append(text)
                did = self._react(item["found"] or {}, [], self._cues(run, now), now, "doing")
                if did:
                    done.setdefault("reacted", []).append({"at": now, "moved": did})
            if run["kind"] != "turn":
                return
            felt = feel(self.body, self.senses, now)
            told = done["told"]
            # new to her cortex: not heard of, turned the other way, or plainly more than when it heard
            fresh = [(name, far) for name, far in felt.standing_out(floor=0.7)
                     if far * told.get(name, 0.0) <= 0 or abs(far) - abs(told[name]) >= TOLD_AGAIN]
            decision = run["options"].get("mind") or {}
            receipt = next((e for e in reversed(events) if e["type"] == "tool"), None)
            check = decision.get("check") or {}
            if check.get("readback"):
                operation = self._operation(check, events)
                readback = next((e for e in reversed(events) if e["type"] == "tool" and operation
                                 and e.get("call_id") == f"readback_{operation['id']}"), None)
                receipt = self._observed(check, events) or readback or operation or receipt
            notice = ""
            if receipt and receipt.get("id") != done.get("last_result") and decision:
                done["last_result"] = receipt.get("id")
                selected = [{"source": "tool", "kind": receipt["name"], "id": receipt.get("id"),
                             "event": receipt.get("id"), "at": receipt.get("at", now)}]
                selected += decision.get("selected", [])[:self._span() - 1]
                done["selected"] = selected
                trace = self.self.get("decided") or {}
                if trace.get("run") == run["id"]:
                    trace["path"]["selected"] = selected
                # as she meets it, in her own sense, never an auditor's instruction ("Revise your expectation
                # before reporting success")
                if receipt.get("status") != "ok":
                    notice = f"{receipt['name']} failed: what was meant to happen hasn't."
                elif receipt.get("matched") is False:
                    notice = "Reading it back, it isn't what was meant: it hasn't come out as expected."
            if not fresh and not notice:
                return
            told.update(fresh)
            note = prompts.inner(" ".join(filter(None, (felt.words(out=fresh) if fresh else "", notice))))
        self.brain.note(run["app"], run["session"], note)

    def after(self, run: dict) -> None:
        """A run ended: what is left of its work tires her; a turn with the user's words moves her, teaches her
        and is remembered."""
        if run["kind"] == "compact":
            return
        events = self.brain.store.run_events(run["id"])
        _, calls, errors = self._work(events)
        denied = sum(1 for e in events if e["type"] == "approval" and e.get("decision") == "deny")
        steering = [e for e in events if e["type"] == "input"][1:]
        steering = [e for e in steering if any(s["user"] for s in e.get("sources") or [{"user": True}])]
        steered = len(steering)
        decision = run["options"].get("mind")
        # what she did, which her cortex settled on as it went: that is what she learns from and remembers
        leaned = decision["act"] if decision else None
        act, enacted = self._enacted(run, events, decision, leaned) if decision and decision.get("gated") \
            else (leaned, None)
        # she looked inward in this turn, then said how she is: saying it is her naming (a feeling is named when
        # attention turns to it). Her own mind finds the words she put to it; only words she said count. Live
        # (the exam), asked to put it into words she looked and said it in her reply, and the naming the
        # tool offers went unused: nothing became hers, nothing eased
        reply = (run.get("result") or {}).get("reply") or ""
        moment = self._task_moment(run, events) if run["kind"] == "task" and run["status"] != "cancelled" else None
        newness = self.memory.newness(moment, time.time()) if moment else None
        looked = [e for e in events if e["type"] == "tool" and e.get("name") == "look_inward"]
        # what this moment followed and what led to it, by meaning (her embedder: outside her lock), for her learned
        # reactions to learn from how the moment went
        followed_on = (decision or {}).get("then") or {}
        heard = list(self._working.get(run["id"], {}).get("causes", ()))  # what led to what they said as she worked
        taught = self.reactions.prepare(
            [{"text": text, "kind": "meaning", "source": "cause"} for text in [(decision or {}).get("cause") or ""] + heard]
            + [{"text": followed_on.get("option") or "", "kind": "meaning", "source": "option"}]
            + [{"text": text, "kind": "meaning", "source": "action"} for text in followed_on.get("actions") or []],
            anxious(self.body.levels), keep=True) if decision else []
        named = {}
        inward_turn = bool(decision and decision.get("attended"))
        if run["kind"] == "turn" and reply and (looked or inward_turn) \
                and not any((e.get("arguments") or {}).get("naming") for e in looked):
            named, _ = self._ask(prompts.NAMED, reply)
        with self._lock, self.memory.transaction(), self._pushing_for(_chat(run["app"], run["session"])):
            if decision and decision.get("epoch", 0) != self.self.get("epochs", {}).get(_chat(run["app"], run["session"]), 0):
                self._working.pop(run["id"], None)
                return
            if self.memory.recorded(run["id"]):
                return
            appraised = self.self.get("appraised", {})
            chat = _chat(run["app"], run["session"])
            if appraised.get(chat, {}).get("run") == run["id"]:
                del appraised[chat]
            now = time.time()
            self._live_until(now)
            body = self.body
            ending = dict(body.levels)  # how she was as the run ended, before how it ended moved her
            # a run that is not the loop's (a super agent's) is counted here whole, from what it used
            self._lived(run["id"], (run.get("usage") or {}).get("completion_tokens") or 0, calls, errors)
            done = self._working.pop(run["id"])
            attended = done.get("selected", decision.get("selected", []) if decision else [])
            inward_now = (decision or {}).get("attended")
            if inward_now:  # her attention turned to herself in it: part of what the moment held
                attended = attended + [{"source": "inward", "kind": "noticed", "id": inward_now["key"],
                                        "at": inward_now["at"]}]
            heard = [e["display"][:300] for e in steering if e.get("display")] or done.get("heard") or []
            plain = " ".join(reply.split()).casefold()
            for item in named.get("named") or [] if isinstance(named.get("named"), list) else []:
                words = " ".join(str((item or {}).get("words") or "").split()) if isinstance(item, dict) else ""
                quote = " ".join(str(item.get("quote") or "").split()) if words else ""
                if words and quote and words.casefold() in quote.casefold() and quote.casefold() in plain:
                    way = (decision or {}).get("way")
                    self._name(naming_record(words, quote, now, "speech", "now", run=run["id"],
                                             event=self._input_event(run),
                                             measure={"of": "message", "run": run["id"], "way": dict(way)}
                                             if way else None))
            if run["kind"] == "turn" and (run.get("result") or {}).get("reply"):  # her message is out: answering it
                self.self["said"] = {"at": now, "mark": self.presence.now(now), "chat": _chat(run["app"], run["session"]),
                                    "actor": self._face(run).casefold()}  # takes them as long as it takes
            urge = self.self.get("urge")
            if urge and urge.get("run") == run["id"]:  # the turn the app gave her to say what she meant to
                if (run.get("result") or {}).get("reply"):  # said: now it waits on an answer (_sting, _drives)
                    urge.update(at=now, mark=self.presence.now(now), actor=self._face(run).casefold())
                    self._went(urge.get("thought"), "said")
                else:  # she thought better of it: nothing to wait on, nothing to keep
                    self.self["urge"] = None
                    self._went(urge.get("thought"), "let go")
            if moment:
                self._remember_task(run, now, moment, newness)
                own = _own(run)
                if own and own["leaned"]:  # what came of what she chose to do: its effects, the outcome known
                    outcome = Option(own["want"], effort=own["leaned"]["effort"],
                                     chance=1.0 if run["status"] == "completed" else 0.0)
                    self._credit(own["leaned"]["features"], outcome.effects(mine(0.0 if newness is None else newness)))
                self.save()
            if not decision:
                return
            # Learn a topic preference from the received message, independently of the outward expression.
            about = [f for f in decision["features"] if f.startswith("tag:")]
            if about and decision.get("felt") is not None:
                liking = max(-1.0, min(1.0, 2.5 * decision.get("felt", 0.0)))
                self.values.learn(about, liking, self._rate())
            stopped = run["status"] == "cancelled"
            failed = errors / calls if calls else 0.0
            surprise = 0.0
            # how it went for her needs, measured: what follows the user's message (_settle) beside their reply
            measured = {}
            if steered or denied or stopped:
                measured["free"] = max(-1.0, -0.4 * min(1, steered) - 0.5 * stopped - 0.3 * min(1, denied))
            receipts = [{"call": e.get("call_id"), "event": e.get("id"), "tool": e["name"], "status": e["status"]}
                        for e in events if e["type"] == "tool"]
            evidence = ("cancelled" if stopped else "denied" if denied else "failed" if errors else
                        "no option foresaw what was done" if act is None else
                        "tool effect observed" if act in ("do", "part") and receipts else
                        "reply returned" if (run.get("result") or {}).get("reply") else "unresolved")
            attempted = any(e["type"] == "tool_start" for e in events)
            check = decision.get("check") or {}
            observed = self._observed(check, events)
            if check.get("readback") and not (stopped or denied):
                evidence = ("file contents unverified" if not observed else
                            "file contents matched" if observed["matched"] else "file contents differed")
            if leaned in ("do", "part") and observed and not (denied or stopped):
                success = float(observed.get("matched", observed["status"] == "ok"))
                confidence = self.self.setdefault("tool_reliability", {"resolved": 0, "correct": 0, "squared_error": 0.0})
                confidence["resolved"] += 1
                confidence["correct"] += int(success >= 1)
                confidence["squared_error"] += (decision["chance"] - success) ** 2
                operations = self.self.setdefault("operations", {}).setdefault(run["app"], {})
                record = operations.setdefault("file contents" if check.get("readback") else observed["name"],
                                               {"succeeded": 0, "resolved": 0})
                record["succeeded"] += int(success)
                record["resolved"] += 1
                surprise = success - decision["chance"]
                went = "better than expected" if surprise > 0.05 else "worse than expected" if surprise < -0.05 \
                    else "as expected"
                competence = body["competence"]
                body.apply({"reward": 0.45 * surprise, "competence": 0.08 * (2 * success - 1),
                            "cortisol": 0.06 * failed}, f"the work went {went}" + (", calls failed" if failed else ""))
                body.apply({"reward_rate": body["competence"] - competence}, "experienced change in competence")
                felt_outcome = surprise - 0.3 * failed
                measured["capable"] = max(-1.0, 1.2 * success - 0.4 - 0.3 * stopped)
            elif act in ("later", "decline") and not stopped and (not attempted or enacted is not None):
                # spared the work (in words, or by the operation that puts it off): relief, and the freedom of her
                # own choice
                body.apply({"autonomy": 0.12}, f"spared the work ({VERBS[act]})")
                felt_outcome = None
            else:  # she talked: how that went, the user's next message tells (_settle)
                felt_outcome = None
            if stopped:
                body.apply({"reward": -0.2, "autonomy": -0.1, "cortisol": 0.05}, "stopped mid-turn")
                felt_outcome = (felt_outcome or 0.0) - 0.4
            if steered:
                body.apply({"autonomy": -0.05 * steered}, "redirected mid-work")
            # the act taken is what is learned (an actor learns from the action it took), not the leaning
            credit_act = leaned if attempted and errors and act == "talk" else act
            # what she did, unless nobody can tell which way it was: then nothing of acting is learned from it
            learned = [f"act:{credit_act}" + item[len(f"act:{leaned}"):] if item.startswith(f"act:{leaned}") else item
                       for item in decision["features"]] if credit_act else []
            acts = [f for f in learned if f.startswith("act:")]
            weights = {f: self.values.weights.get(f, 0.0) for f in acts}
            # talking, the next message tells (_settle), not here: here it would be learned as feeling like nothing
            if felt_outcome is not None and not denied and acts:
                self.values.reinforce(acts, max(-1.0, min(1.0, felt_outcome)), self._rate())
            valued = {f: round(self.values.weights.get(f, 0.0) - was, 4) for f, was in weights.items()
                      if self.values.weights.get(f, 0.0) != was}  # what her values measurably took from it
            if act in ("do", "part") and leaned == "later":  # done after all: nothing left to come back to
                self.self["concerns"] = [c for c in self.self["concerns"] if c.get("at") != decision["at"]]
            elif act == "later" and leaned != "later" and not stopped:  # put off after all, by what she did
                self.self["concerns"].append({"what": decision.get("what") or decision["said"][:200], "app": run["app"],
                                              "session": run["session"], "at": decision["at"], "run": run["id"]})
            reply = ((run.get("result") or {}).get("reply") or "")[:300]
            # what she did, as she would tell it: how the turn began, then what her tools did (when a chat
            # kept nothing done, a helper she started in one was "nothing was started": run 568)
            gated, acted = decision.get("gated", True), decision.get("acted")
            if acted:  # a talk she chose to act in (acting)
                did = f" It began as talk, until I chose to act: {decision['what']}."
            elif act is None:
                did = " Which of the ways I weighed that was, nothing shows."
            elif gated and leaned in ("later", "decline"):
                did = f" I leaned toward {LEANINGS[leaned]}" + (", then acted anyway." if act in ("do", "part") else ".")
            elif gated and act in ("later", "decline") and enacted is not None:
                did = f" I leaned toward {LEANINGS[leaned]}, then went for {LEANINGS[act]} instead."
            elif gated and leaned in ("do", "part") and not attempted:
                # asked, and answered in words; whether it was what they wanted, their next message tells (until
                # 0.43 "Completion was unverified", of a recollection she gave as asked: run 655)
                did = " I answered it in words" + (f" ({decision['what']})" if decision.get("what") else "") + "."
            else:
                did = ""
            if check.get("readback"):
                did += f" My check of {check['target']['path']}: {evidence}."
            elif gated and leaned in ("do", "part") and attempted and check.get("target") and not observed:
                did += f" That I did what I meant ({decision.get('what') or 'it'}) is unverified."
            did += self._account(run, events)
            text = (f"{decision.get('with') or 'The user'} said: {decision['said']}{did}"
                    + (f". As I worked they said: {'; '.join(heard)}" if heard else "")
                    + (f". I said: {reply}" if reply else "") + (". They stopped me" if stopped else "")
                    + (f". {errors} of my {calls} tool calls failed" if errors else "") + ".")
            text = _said(text)
            # how the moment was in her body: a turn ends seconds after the message, and her sense of her body,
            # 90 s behind, kept a tenth of it (of 71 conversations in the user's brain, 4 below -0.3, 2026-11-17)
            then, aroused = core(body.levels)
            # a chat is remembered as it felt (halved by an outcome of 0 that only work has, it was kept at half)
            valence = max(-1.0, min(1.0, then if felt_outcome is None else 0.5 * then + 0.5 * felt_outcome))
            # what the moment itself did to how she felt, beyond its passing surprise (_lasting): the message as it
            # came, and how her turn ended (being stopped, failing); what hurt is what she may brood on (_drives),
            # whatever her mood
            sting = decision.get("lasting", decision.get("felt", 0.0)) + _lasting(ending, body.levels)
            sting -= decision.get("stress_input", 0.0) * 0.3
            whole = moved(decision["levels"], body.levels) if decision.get("levels") else None
            self.memory.log_levels(now, "turn ended", self.body.levels, _chat(run["app"], run["session"]))
            episode = self.memory.add("exchange", text, valence, aroused,
                                      describe_salience(abs(surprise), aroused, decision.get("stakes", 0.5)),
                                      app=run["app"], session=run["session"], at=now, sting=round(sting, 3),
                                      run_id=run["id"], actor=decision.get("actor"), device=decision.get("device"),
                                      event_id=next((e["id"] for e in events if e["type"] == "input"), None),
                                      attention=attended, cues=self._cues(run, now),
                                      felt=peak_end(decision.get("way") or {}, whole),
                                      # what it meant for her needs as she read it, and which way it moved her to act
                                      # (the leaning, whatever she did then): with how it moved her, what a feeling
                                      # of hers is made of (feel.Feelings)
                                      appraisal={**decision["foreseen"], "theirs": decision["theirs"]},
                                      leaned={"act": leaned, "what": decision.get("what") or ""})
            self.feelings.link(run["id"], episode)
            self.workspace.link(f"asked:{_chat(run['app'], run['session'])}", episode)  # what was asked, kept
            if inward_now:
                self._noticed_in(inward_now["key"], episode)
            learned_reactions = self._learn_reactions(decision, done, taught, whole, episode, now)
            if decision.get("corrects"):
                self.memory.supersede(decision["corrects"], episode)
                self._revise_derived({decision["corrects"]})
                self.self["review"] = None
                self._revision += 1
            if measured:
                self.memory.follow(episode, measured)
            pending = self.self["waiting"].get(_chat(run["app"], run["session"]))
            if pending and pending.get("run") == run["id"]:  # the user has not written again in this chat yet
                # what she chose and did here, for what the next message here says followed it (her reactions)
                pending.update(episode=episode, measured=measured, act=act or "unresolved", features=learned,
                               # what she chose to do, done or failed: the next message answers her choice
                               option=decision.get("what") or "" if leaned in ("do", "part") and decision.get("gated") else "",
                               actions=done.get("actions") or [])
            forecast = self.self.get("forecasts", {}).get(str(run["id"]))
            if forecast:
                forecast.update(episode=episode, measured=measured, act=act or "unresolved", features=learned)
            decided = self.self.get("decided")
            if decided and decided.get("run") == run["id"]:
                decided["outcome"] = {"did": act or "unresolved", "evidence": evidence, "receipts": receipts,
                                      # the call that carried out what she did, when one did
                                      "enacted": {"call": enacted.get("call_id"), "event": enacted.get("id"),
                                                  "tool": enacted["name"], "status": enacted.get("status"),
                                                  "at": enacted.get("at")} if enacted else None,
                                      # what was measured of it (her values) apart from what she said of it
                                      # afterwards, which explains it after the fact
                                      "learned": {"values": valued, "at": now},
                                      "explained": {"text": reply, "retrospective": True} if reply else None,
                                      "predicted_operation": check or None, "resolved_by": observed["id"] if observed else None,
                                      "delivery": "unknown", "status": run["status"], "calls": calls, "errors": errors,
                                      "denied": denied, "reactions": learned_reactions,
                                      "steered": steered, "surprise": round(surprise, 3),
                                      "sting": round(sting, 3),
                                      "measured": {name: round(change, 3) for name, change in measured.items()}}
            self.save()
            if decision.get("corrects"):
                self._retake()

    def _reactions_seen(self, now: float) -> List[dict]:
        """Her strongest learned reactions as they are now, with the moment that taught each (while she keeps it)."""
        shown = self.reactions.strongest(SHOWN_THOUGHTS, now, self._cues(None, now), anxious(self.body.levels))
        taught = {e["id"]: e["text"] for e in self.memory.by_ids([r["episode"] for r in shown if r["episode"]])}
        return [{**r, "taught": taught.get(r["episode"], "")[:THOUGHT_CHARS]} for r in shown]

    def _learn_reactions(self, decision: dict, done: dict, taught: List[dict], whole: Optional[Dict[str, float]],
                         episode: int, now: float) -> List[dict]:
        """How the moment went teaches her learned reactions (under her lock): what led to it (as her reading named
        it), what she chose and did in her last turn here, and what was around (as far as each is rare); the
        outcome is how the moment moved her less what her reactions themselves measurably moved in it (a reaction
        is not taught by its own push): as she read it (``external``), and by the turn's end, the whole of it less
        what is left then of each reaction's push (Body.left). A reading whose outcome was not measured teaches
        nothing. What changed."""
        external = decision.get("external")
        if external is None:
            return []
        rest = None
        if whole is not None:
            pushed = [{"at": decision["at"], "moved": decision["reacted"]}, *(done.get("reacted") or [])]
            rest = dict(whole)
            for push in pushed:
                for name, left in self.body.left(push["moved"], push["at"], now).items():
                    rest[name] = rest.get(name, 0.0) - left
        outcome = peak_end(external, rest)
        # how much of a movement either way each level could show, where the outcome was measured: as she had read
        # it, and (as for the end) now; a level pinned at a bound shows nothing more toward it
        read = {name: level + (decision.get("way") or {}).get(name, 0.0) * CHANNELS[name][1]
                for name, level in (decision.get("levels") or {}).items() if name in CHANNELS}
        ends = [read, self.body.levels] if whole is not None else [read]
        shown = {name: {sign: sum(self.body.follows(name, sign, levels[name]) for levels in ends) / len(ends)
                        for sign in (1, -1)} for name in read}
        surroundings = decision.get("surroundings") or []
        rare = self.memory.cue_strength(surroundings)
        cues = list(taught) + [{"text": text, "kind": "around", "source": "around", "salience": rare.get(text, 0.0)}
                               for text in surroundings]
        aroused = max(self.body.levels["noradrenaline"], (decision.get("levels") or {}).get("noradrenaline", 0.0))
        return self.reactions.learn(cues, outcome, aroused, now, decision.get("context") or [], episode,
                                    anxious(self.body.levels), shown)

    def _clear(self) -> float:
        """How clearly her cortex can think now, 0..1: worn down past the middle of her fatigue, and by stress
        she cannot shake (both take the prefrontal cortex offline: Arnsten 2009)."""
        return max(0.0, 1.0 - 2.5 * max(0.0, self.body.fatigue() - 0.4) - 1.5 * max(0.0, self.body["cortisol"] - 0.5))

    def _in_mind(self, now: float) -> Workspace:
        """What is on her mind as her records stand (under her lock): each active record is an item, entered at its
        own time the first time it is seen (a new record under the same key is a new item; its words changed, a
        use), and an item whose record is gone leaves: a thought that left her thoughts, what she said or let go,
        what she took up or settled, a task that ended, a self-view withdrawn. What was asked and what she named
        stand for no record: they fade unused. Her sleep ends what was before her (it is in her memories now):
        her thoughts, what was asked and what she named from before it leave, while what she means to do stays
        (unfinished intentions outlast a night more active than what she thought: Goschke & Kuhl 1993)."""
        slept = self.self.get("slept") or 0.0
        records = {f"thought:{t['episode']}": ("thought", t["thought"][:THOUGHT_CHARS], t["at"], t["episode"])
                   for t in self.self["thoughts"] if t["episode"] and t["at"] > slept}
        urge = self.self.get("urge")
        if urge and urge.get("say"):
            person = self._with(urge["app"], urge["session"])
            records["urge"] = ("intends", f"to {'ask' if urge['want'] == 'ask' else 'tell'} "
                                          f"{person['name'] if person else 'the user'}: {urge['say']}", urge["at"],
                               next((t["episode"] for t in self.self["thoughts"] if t["at"] == urge.get("thought")), None))
        for concern in self.self["concerns"]:
            kept = self.workspace.items.get(f"concern:{concern['at']}")
            episode = kept["episode"] if kept and kept["episode"] else \
                (self.memory.of_run(concern["run"]) or {}).get("id") if concern["run"] else None
            records[f"concern:{concern['at']}"] = ("put off", concern["what"][:THOUGHT_CHARS], concern["at"], episode)
        for task in self.brain.store.runs(kind="task", statuses=("queued", "working", "input_required"), limit=-1):
            own = _own(task)
            records[f"task:{task['id']}"] = ("doing", _doing(own) if own else
                                             " ".join(str(task["options"].get("goal") or "").split())[:160],
                                             task["created"], (own or {}).get("episode"))
        attending = self.self.get("attending")
        if attending and attending["at"] > slept:
            records[attending["key"]] = ("noticed", attending["text"], attending["at"],
                                         (attending["episodes"] or [None])[-1])
        belief = self.self.get("self_view") or {}
        if belief.get("text"):
            records["self"] = ("self", ("" if belief.get("confidence") == "supported" else "a tentative impression: ")
                               + belief["text"], belief.get("since") or belief["at"], None)
        space = self.workspace
        for kind in ("thought", "intends", "put off", "doing", "self", "noticed"):
            space.leave_kind(kind, keep=[key for key, record in records.items() if record[0] == kind])
        items = space.items
        for kind in ("asked", "named"):
            space.leave_kind(kind, keep=[key for key, item in items.items() if item["last"] > slept])
        for key, (kind, text, at, episode) in records.items():
            item = items.get(key)
            if item is not None and item["first"] != at:
                space.leave(key)  # another record under its key: what she means to say now is not what she meant
                item = None
            if item is None:
                space.enter(key, kind, text, at, episode)
            elif " ".join(text.split()) != item["text"]:
                space.enter(key, kind, text, now, episode)
            elif episode != item["episode"]:
                space.link(key, episode)
        return space

    def _fill_on_mind(self) -> None:
        """What came onto her mind since the last sweep gets the meaning of its words (under no lock: it calls the
        embedder), so a reader meets all of it."""
        with self._lock:
            self._in_mind(time.time())
        embedder = self.memory.embedder
        if embedder is not None:
            try:
                self.workspace.vectors.fill(embedder, -1)
            except Exception:
                logger.debug("What is on her mind is embedded later", exc_info=True)

    def _alike_on_mind(self, said: str) -> Optional[Dict[str, float]]:
        """The message against what is on her mind, each item by its own words (under no lock: it may call the
        embedder): 0..1 above what an unrelated question reaches among her moments (her recall's floor); None
        when she cannot tell now."""
        embedder = self.memory.embedder
        if embedder is None or not (said or "").strip():
            return None
        self._fill_on_mind()
        try:
            vector = embedder.embed([said[:MAX_CHARS]], query=True)[0]  # as her recall embedded it: kept
            return self.workspace.likeness(vector, embedder.name, lambda c: self.memory.vectors.relevance(c, embedder))
        except Exception:
            logger.debug("What is on her mind meets the message later", exc_info=True)
            return None

    def _akin_on_mind(self, episode: int) -> Dict[str, float]:
        """What is on her mind against a kept moment (what a thought goes from), each item by its own words, by
        the vectors kept (under her lock: no call to the service): 0..1 above what one matter reaches among her
        moments (Vectors.matter); {} when she cannot tell."""
        embedder = self.memory.embedder
        vector = self.memory.vectors.vector(episode, embedder.name) if embedder is not None else None
        if vector is None:
            return {}
        try:
            floor = self.memory.vectors.matter(embedder.name)
        except Exception:  # cannot tell now
            return {}
        if floor >= 1.0:  # too few moments to tell what one matter is
            return {}
        return self.workspace.likeness(vector, embedder.name, lambda c: max(0.0, (c - floor) / (1.0 - floor)))

    def _before_her(self, likeness: Optional[Dict[str, float]], now: float, carried=(), cued: bool = True) -> List[str]:
        """What else is before her, as many as her span holds, in words (under her lock; each a use, and what the
        reader carries anyway too): ``likeness`` is a cue's, by key (0..1 above her floor for related; None: she
        cannot tell now, so nothing comes by meaning); ``cued`` False: no cue, the most active
        (Workspace.before_her)."""
        likeness = (likeness or {}) if cued else None
        picked = self.workspace.before_her(now, self._span(), likeness, carried)
        self.workspace.use([item["key"] for item in picked] + [key for key in carried if key in self.workspace.items], now)
        return [minded(item, now) for item in picked]

    def _span(self) -> int:
        """How many memories come back to her at once: three to a clear mind, one to a spent or badly stressed
        one (arousal and fatigue narrow what a mind can hold: Easterbrook 1959)."""
        return max(1, round(3 * self._clear()))

    def reflexive(self, run: Optional[dict] = None) -> bool:
        """Whether she answers on reflex now: without thinking it through (the provider's thinking off; on
        Claude Code its lowest effort). A neuromodulator does not tell the cortex anything, it changes how the
        cortex computes: a spent or badly stressed mind falls back on what comes first, and that she can't
        talk herself out of. One switch and not a scale: on the user's provider "low", "high" and "max"
        thought alike (7k to 14k characters on one puzzle, 2026-11-16) and "medium" was refused with a 400,
        while thinking off answered at once, and wrong. A run that went on reflex stays so (it does not
        think itself clear again, and a run has one cached conversation to lose); ``run`` None: as she is
        now. Never where the user already has thinking off, nor for a provider that refuses it."""
        values = self.brain.config.values()
        least = values["claude_effort"] == "low" if values["provider"] == "claude_code" \
            else values["thinking_mode"] == "none"
        if not self.reflexes or least or (run and run["kind"] == "compact"):
            return False
        if run and run["options"].get("reflex"):
            return True
        with self._lock:
            found = self._clear() < (CLEAR_AGAIN if self._reflex else REFLEX)
            if run:
                self._reflex = found
        if found and run:
            self.brain.store.update_run_options(run["id"], lambda options: {**options, "reflex": True})
        return found

    # ============== Between messages ==============

    def _think(self, kind: str, about: Optional[dict]) -> None:
        """A thought of hers (under no lock; it takes it). The model thinks it and imagines what it could lead to
        (prompts.THINK: ``could``); her will chooses among those and letting it be, as a turn's options are chosen
        (will.choose): her needs, what her values learned of acting on her own, what the thought of each sets off
        in her body, the work under her fatigue and stress, her noise. The model's ``want`` was the decision:
        exhausted or once ignored, she reached out and took up work as readily as rested (the audit, finding 1)."""
        self._fill_on_mind()
        with self._lock:
            now = time.time()
            contact = self.self.get("contact") or (about if kind == "resume" else None)
            felt = feel(self.body, self.senses, now)
            subject = self._named((about or {}).get("text") or (about or {}).get("what") or "", (about or {}).get("app"))
            wandering = kind == "wonder" and self.body.deficit("novelty") < 0.3  # at rest, not bored
            person = self._with(contact["app"], contact["session"]) if contact else None
            noticing = self.attend(now, "thought", felt=felt, free=1.0 - self.body.levels["acetylcholine"]
                                   if self.brain.runs.busy() else 1.0) if kind == "notice" else None
            if kind == "notice" and not noticing:
                return  # what drew her is known to her by now
            on_mind = ON_MIND["wander" if wandering else kind].format(
                about=noticing["text"] if noticing else subject, who=person["name"] if person else "the user",
                since=f" You last talked {_ago(now - contact['at'])}." if contact else "")
            cues = self._cues(None, now, (contact or {}).get("app", ""))
            if kind == "wonder":  # her stream goes on from her last thought, and memories come up unbidden
                last = self.self["thoughts"][0] if self.self["thoughts"] else None
                talked = (self.memory.recent(1, kinds=("exchange",)) or [None])[0] \
                    if contact and (not last or contact["at"] > last["at"]) else None
                if talked:  # a talk since: the mind goes back over what was just said (recent events lead its
                    # wandering: Smallwood & Schooler 2015). Going on with the old stream, from 15:15 to 19:01
                    # her every thought had the user eating, through a talk and the game he went off to play
                    on_mind += f" What you last talked about: {self._line(talked, now)}"
                elif last:  # with when it was: as a plain "your last thought was", what was true
                    # then read as true now (four hours on, her thoughts still had the user eating)
                    on_mind += f' Your last thought, {_ago(now - last["at"])}: "{last["thought"][:THOUGHT_CHARS]}"'
                came = self._unbidden(talked["text"] if talked else last["thought"] if last else "", cues, felt,
                                      last, talked, now)
            elif kind == "notice":
                came = []  # her attention is on herself: nothing is looked for
            else:
                topic = subject or (self.memory.recent(1, kinds=("exchange",)) or [{"text": ""}])[0]["text"]
                # what nags her is before her already: it does not come back as a memory of itself, nor do her
                # own thoughts on it (they did, and she went round and round one thing: the user, 2026-11-17;
                # an old thought that called him "she" was copied by 5 of 6 new ones). What happened comes back.
                came = [e for e in self.memory.recall(topic, felt.valence, now, count=self._span() + 1,
                                                      kinds=() if kind != "ruminate" else RUMINATED, cues=cues,
                                                      arousal=felt.arousal)
                        if e["id"] != (about or {}).get("id")][:self._span()]
                for episode in came:
                    episode["quality"] = self._quality(episode)
            # what the thought goes over: the talk, the thought it goes on from, the moment it dwells on, what
            # she put off (the turn she put it off in). It goes with that if that is taken back (Memory.retract);
            # else a deleted chat would take every thought she had while it was the last one she talked in
            if kind == "wonder":
                grew = [talked["id"]] if talked else [last["episode"]] if last and last.get("episode") else []
                source = talked
            elif kind == "ruminate":
                grew = [about["id"]] if (about or {}).get("id") else []
                source = about
            else:
                source = self.memory.of_run(about["run"]) if about and about["run"] else None  # reach_out: none
                grew = [source["id"]] if source else []
            # what it stands on: if any of it is taken back or set right while she thinks, the thought goes
            stands_on = {e["id"] for e in came} | set(grew) | ({about["id"]} if kind == "ruminate" and (about or {}).get("id") else set())
            # whom it is with: who said what it grew from, else whom she last talked with (kept with no one,
            # her thoughts about the user went from "she" to "he" with nothing to tie them to him)
            actor = (source or {}).get("actor") or (contact or {}).get("actor") or None
            if kind in ("ruminate", "resume") and source:
                # what nags her, or the turn she put it off in, with what came of it since (Memory.came_of): without
                # it, it came as if nothing had happened since (a watcher the user had said to forget, the audit)
                self.memory.came_of([source])
                if source.get("later"):
                    on_mind += (f" What came of it ({ago(source['later']['at'], now)}): "
                                f"{source['later']['text'][:THOUGHT_CHARS]}")
                    came = [e for e in came if e["id"] != source["later"]["id"]]  # told once
            memories = [self._line(e, now) for e in came]
            levels = dict(self.body.levels)  # before the thought: what thinking it did is kept with it
            self._refeel([(e, e["quality"]) for e in came], now)
            if kind == "ruminate" and self.memory.felt(about):
                self._refeel([(about, 1.0)], now)  # what nags her comes back whole, and wears a little each time
            name = person["name"] if person else "the user"
            if kind == "resume" and about:
                self.workspace.use([f"concern:{about['at']}"], now)  # gone over again
            space = self._in_mind(now)
            # what else is on her mind (workspace.py): what is about what the thought goes from first, then the most
            # active; what it goes over already (the talk, the thought, the moment, what came back) not twice
            carried = {key for key, item in space.items.items() if item["episode"] in stands_on} | (
                {f"concern:{about['at']}"} if kind == "resume" and about else set())
            also = self._before_her(self._akin_on_mind(grew[0]) if grew else {}, now, carried)
            told, around = self.presence.words(now), self.presence.surroundings(now)
            others = self.people.mentioned(" ".join([subject, *memories]), besides=[person])
            liked, disliked = (", ".join(_about(found)) for found in self.values.leanings())
            ways = self.ways.lines()  # how she does things holds in her thoughts too (when nobody spoke to her...)
        persona = self._persona(contact["app"], contact["session"]) if contact else ""
        asked = (f"{self._who(persona)}\n\n"
                 + (f"Who they talk with: {People.line(person)}\n" if person else "")
                 + (f"Others who come to mind: {'; '.join(People.line(other) for other in others)}\n" if others else "")
                 + f"It is {time.strftime('%A %H:%M')}. How they feel: {felt.words()}\n"
                 + (f"What they can tell of {name}: {told}\n" if told else "")
                 + (f"Around them: {'; '.join(f'{key}: {value}' for key, value in around.items())}\n" if around else "")
                 + f"On their mind: {on_mind}\n" + (f"Also on their mind: {'; '.join(also)}.\n" if also else "")
                 + (f"What comes back to them: {'; '.join(memories)}\n" if memories else "")
                 + (f"What they've come to like: {liked}.\n" if liked else "")
                 + (f"What they've come to dislike: {disliked}.\n" if disliked else "")
                 + (f"How they do things: {'; '.join(ways)}.\n" if ways else ""))
        answer, usage = self._ask(prompts.THINK, asked)
        thought = " ".join(str(answer.get("thought") or "").split())[:600]
        if not thought or self._stop.is_set():
            return
        where = (about["app"], about["session"]) if kind == "resume" else \
            (contact["app"], contact["session"]) if contact else None
        # what it could lead to that she can do from here: reaching out needs someone to reach, the rest a chat
        could = [o for o in (Option.own(item) for item in (answer.get("could") if isinstance(answer.get("could"), list)
                                                          else [])[:3]) if o
                 and (contact if o.act in ("tell", "ask") else where)]
        urge, task = None, None
        newness = self.memory.newness(thought, time.time())
        alike, weighed = None, {}
        for item in self.reactions.prepare([{"text": thought, "kind": "meaning", "for": None}]
                                           + [{"text": o.say or o.what, "kind": "meaning", "for": n}
                                              for n, o in enumerate(could)], anxious(self.body.levels)):
            if item["for"] is None:
                alike = item["found"]
            else:
                weighed[id(could[item["for"]])] = item["found"] or {}
        with self._lock:
            sorted_from = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        near = self.memory.likeness(thought, sorted_from)  # what it is about, against her feelings' moments (her embedder)
        with self._lock:
            standing = {e["id"]: e for e in self.memory.by_ids(sorted(stands_on))}
            if any(i not in standing or standing[i]["superseded_by"] for i in stands_on):
                return  # what it stood on was taken back or set right while she thought it
            now = time.time()
            body = self.body
            self.self["fired"][kind] = now  # the thought is made: its own time between, from now
            body.exert(usage.get("completion_tokens") or 0)
            # a thought of what went badly sets her off as the thing would (worry), of what went well, it pulls
            self._react(alike or {}, self._surroundings(None, now), cues, now, "thinking")
            if kind == "wonder":  # a new thought fills her want of something new, going round one thing does not
                # (boredom: too little new to engage with, Eastwood et al. 2012); a fixed 0.15 filled it as much
                # with a repeat (cosine 0.75-0.86 to her last thoughts, on her vectors) as with a new subject
                # (0.62-0.65). Without the service: half new
                fresh = 0.5 if newness is None else newness
                body.apply({"novelty": 0.3 * fresh, "dopamine": 0.06 * fresh}, "her mind wandered")
            elif kind == "ruminate" and not self.memory.felt(about):  # kept without how it moved her, a
                # moment has only its sting: going over it stirs that up again and wears it down a little. A
                # fixed stir fed itself: brooding kept her stressed, stress made her brood, and on a third rough day she brooded
                # every 30 minutes (stress from it 0.32, 0.76, 1.15 a day)
                body.apply({"cortisol": 0.06 * max(0.0, -about["sting"]) * about["charge"]}, "brooding on what hurt")
                self.memory.soften([about["id"]], 0.1)
            felt = feel(body, self.senses, now)
            episode = self.memory.add("thought", thought, felt.valence, felt.arousal, 0.25 + (0.2 if kind == "ruminate" else 0.0),
                            at=now, origins=[e["id"] for e in came], app=(contact or {}).get("app", ""),
                            session=(contact or {}).get("session", ""), felt=moved(levels, body.levels), cues=cues,
                            grew_from=grew, actor=actor)
            if noticing:
                self._noticed_in(noticing["key"], episode)
            else:  # her mind went elsewhere: the stretch of attention to herself is over
                self._release(now)
            named = str(answer.get("named") or "").strip()
            if named and named.casefold() in " ".join(thought.split()).casefold():  # in her own inner voice, or not
                if kind == "ruminate" and about and about.get("id"):  # the moment it dwells on
                    record = naming_record(named, thought, now, "thought", "past", episode=about["id"],
                                           measure=self._measure_past(about))
                else:  # the thought she is in, as her body reads now
                    record = naming_record(named, thought, now, "thought", "now", episode=episode,
                                           measure=self._measure_now(None, now))
                self._name(record)
            self.memory.log_levels(now, "thought", body.levels)
            hour, here = body.hour(now), (where or ("",))[0]

            # what she is in as she thinks it: no message, how the thought moved her, what it is about
            situation = {"at": now, "run": None, "appraisal": None, "near": near}
            self.self["situation"] = situation
            felt_as = self._recognized(moved(levels, body.levels), situation)[:self._span()]
            if felt_as:
                self.feelings.came_back(felt_as[0][0]["id"], now)
            in_feelings = [feeling["id"] for feeling, _, _ in felt_as]

            def found(option):
                return features(option.act, (), "own", hour, here, in_feelings)
            choice = choose(could + [Option("let", effort=0.0)], mine(0.5 if newness is None else newness), body,
                            self.values, found, self.rng,
                            lambda o: self._dread(weighed.get(id(o), {}), 0.0 if o.act == "let" else 1.0, now, cues))
            option = choice.option
            want = option.act if option.act != "let" else "nothing"
            leaned = {"act": option.act, "reasons": choice.reasons, "chances": choice.chances,
                      "considered": choice.considered, "features": found(option), "effort": option.effort}
            self.memory.bind(episode, leaned={"act": option.act, "what": option.what or option.say or ""})
            thinking = {"episode": episode, "at": now, "kind": kind, "thought": thought, "want": want, "leaned": leaned}
            if want == "nothing":
                thinking["went"] = "let be"
            self.self["thoughts"] = ([thinking] + self.self["thoughts"])[:SHOWN_THOUGHTS]
            say = option.say or thought
            last, known = self.self.get("urge"), self.self.get("contact")
            # one message out at a time, never a stream: what she said waits on its answer; what she only meant to
            # say gives way to what she means to say now
            unanswered = bool(last) and "mark" in last and not self._answered(last)
            # the app gave her a turn to say it and she is saying it; one it did not take by her next thought (they
            # come 10 min apart at least) it is not going to: what she means to say now takes its place
            pending = bool(last) and "mark" not in last and "run" in last
            # while they are talking, what she wants to say comes up in her next answer (her note carries it), not
            # as a message of its own in the middle of the conversation
            talking = bool(known) and now - known["at"] < TALKING
            # what her will chose she does, whatever the thought (not only what she put off, and not only with the
            # app open): a task of hers, in the chat it belongs to, with that chat's tools; its end is told
            what = option.what
            if want in ("tell", "ask") and (unanswered or pending):
                thinking["went"] = "waits"  # her last message is out or about to be: no other on top of it
            elif want in ("tell", "ask") and contact:
                # offered to the app, which starts her turn to say it (or does not: MilkChan with "speak up on her
                # own" off); while they talk, or with the app away, kept for their next message (her note). Said,
                # it waits on an answer (after: its mark)
                offered = not talking and self._alive(contact["app"], now)
                urge = {"at": now, "want": want, "app": contact["app"], "session": contact["session"], "say": say,
                        "actor": contact.get("actor", ""), "thought": now, "offered": offered,
                        "text": URGE[want].format(thought=thought, say=say), "features": leaned["features"]}
                thinking["went"] = "offered" if offered else "kept"
            elif want == "do":
                if kind == "resume":
                    self.self["concerns"] = [c for c in self.self["concerns"] if c != about]
                task = (*where, f"{DECIDED[0]}{thought}{DECIDED[1]}{what}", False,
                        {"want": "do", "what": what, "thought": thought, "episode": episode, "leaned": leaned})
            elif want == "look_up":
                # what she finds stays with her as the task's end does (_remember_task)
                task = (*where, f"{LOOK_UP}{what[:300]}.",
                        True,  # hers: nobody is told it ended
                        {"want": "look_up", "what": what[:300], "thought": thought, "episode": episode, "leaned": leaned})
            if task:
                thinking["went"] = "task"
            if kind == "resume" and about in self.self["concerns"]:
                # thought over and put off again, it waits twice as long each time before it nags (a plan for an
                # unfinished goal stops it intruding: Masicampo & Baumeister 2011). Coming back every
                # hour she was rested, it came 14 times in a simulated day
                about["put_off"] = about.get("put_off", 0) + 1
                about["again"] = now + HOUR * 2 ** about["put_off"]
            if urge:
                self.self["urge"] = urge
        if urge and thinking.get("went") == "offered":
            self.brain.notify(urge["app"], urge["session"], "mind.urge",
                              {"want": urge["want"], "text": urge["text"], "thought": thought,
                               "session": urge["session"]})
        if task:
            app, session, goal, quiet, own = task
            self.brain.runs.start_task(app, session, goal, quiet=quiet, own=own)

    def _unbidden(self, stream: str, cues: List[str], felt, last: Optional[dict], talked: Optional[dict],
                  now: float) -> List[dict]:
        """What comes up by itself as her mind wanders (under her lock): a memory the moment calls up (what she
        was thinking, what is around her, her mood: an involuntary memory has a cue, Berntsen 2009); the
        neighbour in time of a memory that came up in her last thought (they come in chains, Mace 2005: a
        recalled moment brings its context back, Howard & Kahana 2002), likelier the sooner this thought follows
        it; and one drawn at random, the strong and charged more often (two that never met: what a new idea is
        made of). What is before her already (the talk she goes back over, her last thought and what came up in
        it) does not come back as a memory. Two drawn at random would have nothing about the moment
        calling them."""
        before_her = {talked["id"]} if talked else set()
        origins: List[int] = []
        if last and last.get("episode"):
            before_her.add(last["episode"])
            origins = [o for e in self.memory.by_ids([last["episode"]]) for o in json.loads(e.get("origin_ids") or "[]")]
            before_her.update(origins)
        # what happened within the hour is before her still: it does not come back as a memory
        came = [e for e in self.memory.recall(stream, felt.valence, now, count=4, strengthen=False, cues=cues,
                                              arousal=felt.arousal, before=now - HOUR)
                if e["id"] not in before_her][:1]
        for episode in came:
            episode["quality"] = self._quality(episode)
        self.memory.attended(came, now, felt.valence)
        if origins and self.rng.random() < math.exp(-(now - last["at"]) / HOUR):
            came += [dict(e, quality=1.0) for e in self.memory.near(origins, 30 * MINUTE, now)
                     if e["id"] not in before_her | {c["id"] for c in came}][:1]
        taken = before_her | {c["id"] for c in came}
        spare = max(1, 2 - len(came))  # one by itself, two when nothing called one up
        return came + [dict(e, quality=1.0) for e in self.memory.replay(spare + len(taken), now)
                       if e["id"] not in taken][:spare]

    def _quality(self, episode: dict) -> float:
        """How fully a memory was called up: its likeness in meaning, or what it shares with now as far as her
        attention is free. A focused mind holds off what only the surroundings call up (acetylcholine favours what
        is attended over associative retrieval: Hasselmo 2006); memories come by themselves as attention drifts
        (Berntsen 2009)."""
        return max(episode.get("relevance", 0.0),
                   min(1.0, episode.get("cued", 0.0)) * (1.0 - self.body.levels["acetylcholine"]))

    def _refeel(self, back, now: float) -> None:
        """Memories that came back move her again (under her lock), each by a share of what its moment did to
        her chemistry (``REFELT``): as far as it is still charged, as vividly as it comes (its strength now) and
        as fully as it was called up (by meaning or by what it shares with now; one that came by itself comes
        whole). Retrieval brings back the pattern of the moment, the more for an arousing one (Bowen, Kark &
        Kensinger 2018), and each coming back wears its charge a little, an unpleasant moment's more (the fading
        affect bias: Walker, Skowronski & Thompson 2003). A memory kept without how it moved her (a dream,
        an insight, a turn she did not appraise) moves nothing."""
        for episode, quality in back:
            felt = self.memory.felt(episode)
            share = REFELT_SHARE * episode["charge"] * self.memory.strength_now(episode, now) * min(1.0, quality)
            again = {name: round(felt[name] * share, 3) for name in REFELT if felt.get(name)} if share > 0 else {}
            if again:
                with self._pushing_for(_chat(episode["app"], episode["session"] or "") if episode.get("app") else None):
                    self.body.apply({name: lots * CHANNELS[name][1] for name, lots in again.items()},
                                    f"remembering: {episode['text'][:QUOTED]}")
                self.memory.reevoked(episode)
            # what came back lately, what brought it (what is around her, meaning, or nothing: by itself) and what
            # it did to her (each channel, in lots), for apps and her panel to show
            by = episode.get("through") or ("meaning" if episode.get("relevance") else "itself")
            self.self["remembered"] = ([{"at": now, "episode": episode["id"], "text": episode["text"][:THOUGHT_CHARS],
                                         "by": by, "moved": again}] + self.self.get("remembered", []))[:SHOWN_THOUGHTS]

    def _went(self, at: Optional[float], how: str) -> None:
        """What came of a thought she wanted to say (under her lock), as apps show it."""
        for thought in self.self["thoughts"]:
            if thought["at"] == at:
                thought["went"] = how

    def _replay_items(self, start, end, limit):
        pending = [p["episode"] for p in self.self.get("forecasts", {}).values()
                   if p.get("episode") and not p.get("resolved")]
        return self.memory.replay_window(start, end, pending, limit)

    def _consolidate(self) -> None:
        """Resume the same bounded review after shutdown or a provider failure."""
        with self._lock:
            start = self.self.get("slept") or 0.0
            batch = self.self.get("review")
            if not batch:
                end = time.time()
                moments = self._replay_items(start, end, 12)
                batch = {"from": start, "to": end, "ids": [m["id"] for m in moments], "done": []}
                self.self["review"] = batch
                self.save()
            # in the order they were picked (the strongest first, as her sleep is told), not by id
            moments = sorted(self.memory.by_ids(batch["ids"]), key=lambda m: batch["ids"].index(m["id"]))
            revision = self._revision
            contact = self.self.get("contact")
        for step in ("local", "semantic", "updates", "narrative", "people", "self", "ways", "feelings"):
            if step in batch["done"]:
                continue
            if step in ("updates", "narrative") and self.brain.provider_problem():
                return
            answer, reaching = {}, []
            if step == "local":  # what moved her today, and the faint memories like it (by meaning: the service)
                reaching = self.memory.related(batch["ids"])
            elif step == "updates":  # what the day overtook of what she had in mind, and of what she put off
                answer = self._overtaken(moments)
            elif step == "narrative" and moments:
                persona = self._persona(contact["app"], contact["session"]) if contact else ""
                # whole, and numbered: what she understands and dreams keeps the moments it comes from
                listed = "\n".join(f"{number}. {line(m, batch['to'])}" for number, m in enumerate(moments, 1))
                answer, _ = self._ask(prompts.SLEEP, f"Who they are:\n{persona[:6000]}\n\nThe moments:\n{listed}")
                if not isinstance(answer, dict) or not ({"insights", "dream"} & set(answer)):
                    # an answer she could not read is not the night done, with nothing made of it and
                    # nothing said (a nap at 14:06 on 2026-11-18, thirteen moments): it is gone over again
                    logger.warning("Her sleep made nothing of %d moments (an answer it could not read); it goes "
                                   "over them again next time", len(moments))
                    return
            elif step == "people":
                self._meet_people([m for m in moments if m["kind"] in ("exchange", "event")], batch=batch)
            elif step == "self":
                self._know_herself(start, batch=batch)
            elif step == "ways":
                self._review_ways(start, batch=batch)
            elif step == "feelings" and not self.brain.provider_problem():
                self._review_feelings(batch)
            elif step == "semantic" and getattr(self.brain, "recall", None):
                self.brain.recall.forget(batch["to"], sleep_review=True)
            with self._lock, self.memory.transaction():
                if self._revision != revision or self.self.get("review") is not batch:
                    return
                if step == "local":
                    self.memory.tag_related(reaching, batch["to"])  # what moved her reaches back, then softens
                    self.memory.soften(batch["ids"])
                    self.values.fade(0.05)
                    keep = set(batch["ids"])
                    for claim in [self.self.get("self_view") or {}, *self.people.known, *self.ways.known]:
                        keep.update(claim.get("origins", []))
                        keep.update(claim.get("against", []))
                    self.memory.forget_faint(batch["to"], protected=keep)
                elif step == "updates":
                    for old, new in answer.get("pairs", ()):
                        self.memory.supersede(old, new)
                    settled = set(answer.get("settled", ()))
                    self.self["concerns"] = [c for c in self.self["concerns"] if c.get("at") not in settled]
                elif step == "narrative":
                    felt = feel(self.body, self.senses, batch["to"])
                    insights = answer.get("insights") or []
                    for kind, entry in ([("insight", entry) for entry in (insights[:3] if isinstance(insights, list)
                                                                          else [])] + [("dream", answer.get("dream"))]):
                        text, cited = (entry.get("text"), entry.get("from")) if isinstance(entry, dict) else (entry, ())
                        if isinstance(text, str) and text.strip():
                            # what it comes from, as she says: carrying the whole night's moments,
                            # none told what it stood on (the audit, finding 9)
                            self.memory.add(kind, text.strip()[:800], felt.valence, 0.4, 0.45, at=batch["to"],
                                            origins=_cited(cited, moments), cues=moment_cues(batch["to"]))
                if step not in batch["done"]:
                    batch["done"].append(step)
                self.save()
        with self._lock:
            if self.self.get("review") is batch:
                self.self.update(slept=batch["to"], consolidate=False, review=None)
                self.save()

    def _overtaken(self, moments: List[dict]) -> dict:
        """What the day's moments overtook of what she had in mind before, and which things she had put off they
        settled, as her sleep finds them going over the two together (prompts.UPDATES; nothing is asked when
        nothing from before is about the same matter and nothing is put off). {"pairs": [(old, by)], "settled":
        [when each settled thing was put off]}. A correction set a memory right only when the user quoted it in
        the same chat (before): her guess of 2% milk outlived the user's "it's 3.2%", an essay skeleton she
        had deleted as asked stayed in her thoughts, and what the user had answered she went on wondering
        about (the audit of 2026-11-18, finding 3)."""
        happened = [m for m in moments if m["kind"] in ("exchange", "event")]
        older: Dict[int, dict] = {}
        for moment in happened:
            for episode in self.memory.earlier(moment):
                older.setdefault(episode["id"], episode)
        with self._lock:
            concerns = list(self.self["concerns"])
        if not happened or not (older or concerns):
            return {}
        now = time.time()
        told = {f"T{n}": m for n, m in enumerate(happened, 1)}
        before = {f"O{n}": e for n, e in enumerate(sorted(older.values(), key=lambda e: e["at"]), 1)}
        put_off = {f"P{n}": c for n, c in enumerate(concerns, 1)}
        asked = ("What happened:\n" + "\n".join(f"{label} {line(m, now)}" for label, m in told.items())
                 + ("\n\nWhat they had in mind before:\n" + "\n".join(f"{label} {line(e, now)}"
                                                                     for label, e in before.items()) if before else "")
                 + ("\n\nWhat they had put off:\n" + "\n".join(f"{label} (put off {ago(c['at'], now)}) {c['what']}"
                                                               for label, c in put_off.items()) if put_off else ""))
        answer, _ = self._ask(prompts.UPDATES, asked, quick=False)
        pairs = []
        for item in answer.get("outdated") or [] if isinstance(answer.get("outdated"), list) else []:
            old, by = (before.get(str(item.get("old"))), told.get(str(item.get("by")))) if isinstance(item, dict) \
                else (None, None)
            if old and by and old["at"] < by["at"]:
                pairs.append((old["id"], by["id"]))
        settled = [put_off[str(label)]["at"] for label in answer.get("settled") or []
                   if isinstance(answer.get("settled"), list) and str(label) in put_off]
        return {"pairs": pairs, "settled": settled}

    def _revise_derived(self, gone):
        """Withdraw generalizations whose evidence expired or was explicitly corrected."""
        if gone.intersection((self.self.get("self_view") or {}).get("origins", [])):
            self.self["self_view"] = None
        for person in self.people.known:
            if gone.intersection(person.get("origins", [])):
                person.update(gist="", origins=[])
        self.ways.known[:] = [w for w in self.ways.known if not gone.intersection(w.get("origins", []))]
        self.reactions.withdraw(gone)  # what a moment taken back taught her body to expect

    @contextlib.contextmanager
    def _pushing_for(self, chat: Optional[str]):
        """Under her lock: what moves her body meanwhile is of this chat (its record goes when the chat goes)."""
        before, self.body.where = self.body.where, chat
        try:
            yield
        finally:
            self.body.where = before

    def invalidate(self, app, session, *, delete=False, event=None, since=None):
        chat = _chat(app, session)
        with self._lock, self.memory.transaction():
            self._revision += 1
            self.self["review"] = None
            epochs = self.self.setdefault("epochs", {})
            epochs[chat] = epochs.get(chat, 0) + 1
            self.self["waiting"].pop(chat, None)
            self.self.get("appraised", {}).pop(chat, None)
            self.self.get("answered", {}).pop(chat, None)  # how she felt answering there is no longer of this chat
            forecasts = self.self.get("forecasts", {})
            for key in [key for key, pending in forecasts.items() if pending["chat"] == chat]:
                del forecasts[key]
            if delete or since is not None:  # what quoted it goes from her body's record too
                self.memory.forget_pushes(chat, None if delete else since)
            if delete or event is not None:
                gone = self.memory.retract(app, session, event, since)
                self.self["thoughts"] = [t for t in self.self["thoughts"] if t.get("episode") not in gone]
                self.self["remembered"] = [r for r in self.self.get("remembered", []) if r["episode"] not in gone]
                self._revise_derived(gone)
            for key in ("decided", "contact", "urge"):
                item = self.self.get(key) or {}
                if (item.get("app"), item.get("session")) == (app, session):
                    self.self[key] = None
            self.self["concerns"] = [c for c in self.self["concerns"] if (c["app"], c["session"]) != (app, session)]
            if delete:
                self.self.get("contacts", {}).pop(chat, None)
                self.self.get("faces", {}).pop(chat, None)
                self.workspace.leave(f"asked:{chat}")
            self.save()
        self._retake()

    def forget(self, app: str, session: str) -> None:
        self.invalidate(app, session, delete=True)

    # ============== The people in her life (people.py) ==============

    @staticmethod
    def _face(run: dict) -> str:
        """Whom the app shows as the one writing: its handle in the turn's context ("user")."""
        return " ".join(str(((run.get("options") or {}).get("context") or {}).get("user") or "").split())

    def _meet(self, run: dict, now: float) -> Optional[dict]:
        """Someone writes in a chat (under her lock): she sees their face and, if she knows them, them. Whose
        face a chat has is kept for its prompt, which is taken again when someone else is there."""
        handle = self._face(run)
        person = self.people.present(run["app"], handle, now)
        faces = self.self.setdefault("faces", {})
        if handle and faces.get(_chat(run["app"], run["session"])) != handle:
            faces[_chat(run["app"], run["session"])] = handle
            self._retake(run["app"], [run["session"]])
        return person

    @staticmethod
    def _device(run: dict) -> str:
        context = run["options"].get("context") or {}
        origin = context.get("origin")
        if origin in ("desktop", "phone"):
            return origin
        place = str(context.get("writes from") or "")
        return "phone" if place.startswith("their phone") else "desktop" if place.startswith("the computer") else "unknown"

    def _why(self, run: dict, said: str) -> str:
        """What a message's pushes are kept as in her log of what moved her: who said what."""
        person = self._with(run["app"], run["session"])
        return f"{person['name'] if person else 'The user'} said {_quote(said)}"

    def _with(self, app: str, session: str) -> Optional[dict]:
        """Whom she is with in a chat: whose its face is, else whom that app's user is."""
        handle = self.self.get("faces", {}).get(_chat(app, session))
        return self.people.recognize(app, handle) if handle else self.people.of_app(app)

    # ============== Her ways (ways.py) ==============

    def keep_way(self, name: str, when: str, then: str, source: str = "told") -> dict:
        """She takes on a way of doing things (or changes one, by its name): every chat's prompt is taken again."""
        with self._lock:
            way = dict(self.ways.keep(name, when, then, source, time.time()))
        self.save()
        self._retake()
        return way

    def memory_network(self) -> dict:
        """Her memories as a network, for an app to draw (``Memory.network``)."""
        embedder = self.memory.embedder
        return self.memory.network(embedder.name if embedder is not None else None)

    def drop_way(self, name: str) -> bool:
        """A way of hers goes (the user lifted it, or took it out in the panel)."""
        with self._lock:
            found = self.ways.drop(name)
        if found:
            self.save()
            self._retake()
        return found

    def _day_of_work(self, since: float, until=float("inf")) -> list:
        """What she did since ``since``, a line a turn or task, the oldest first: what was said (or her task), her
        tools in order (a call again and again folded: "files_read x3") and her answer."""
        store, lines = getattr(self.brain, "store", None), []
        if store is None:
            return lines
        done = sorted((run for run in store.runs(limit=-1) if since <= run["created"] <= until and run["kind"] in ("turn", "task")),
                      key=lambda run: run["id"])
        for run in done[-12:]:
            events = store.run_events(run["id"])
            said = ((run["options"].get("mind") or {}).get("said") or next(
                (e["display"] for e in events if e["type"] == "input" and e.get("display")), "")) \
                if run["kind"] == "turn" else ""
            if run["kind"] == "turn" and not said:
                continue  # an event or an urge of hers: nobody said anything to her
            tools = []
            for name in (e["name"] + (" (failed)" if e.get("status") != "ok" else "") for e in events if e["type"] == "tool"):
                if tools and tools[-1][0] == name:
                    tools[-1][1] += 1
                else:
                    tools.append([name, 1])
            used = ", ".join(name + (f" x{count}" if count > 1 else "") for name, count in tools) or "none"
            reply = " ".join(signals.split(str((run.get("result") or {}).get("reply") or ""))[1].split())
            # who said it, by the name she knows them by (a way that is about them names them, never a "she")
            who = (run["options"].get("mind") or {}).get("with")
            head = (f"{who} told them" if who else "They were told") + f": {' '.join(said.split())[:300]}" if said \
                else f"A task of theirs: {' '.join(str(run['options'].get('goal') or '').split())[:300]}"
            lines.append(f"Run {run['id']}. ({time.strftime('%H:%M', time.localtime(run['created']))}, in "
                         f"{run['app']}) {head} | Tools: {used}" + (f" | They answered: {reply[:300]}" if reply else ""))
        return lines

    def _review_ways(self, since: float, batch=None) -> bool:
        """Sleep goes over how she did things since ``since`` against her ways (Ways.review), once a night, thought
        through; a way not met for a month fades. Whether her ways changed (every chat's prompt is taken again)."""
        day = self._day_of_work(since, batch["to"] if batch else float("inf"))
        with self._lock:
            known = [f"- {way['name']}: when {way['when']}, {way['then']}" for way in self.ways.listed()]
        answer = {}
        if day:
            asked = ("Their ways:\n" + ("\n".join(known) or "none yet") + "\n\nWhat they did today (oldest first):\n"
                     + "\n".join(day))
            answer, _ = self._ask(prompts.WAYS, asked, quick=False)

        def names(value) -> list:
            return [str(name) for name in value if isinstance(name, str)] if isinstance(value, list) else []
        with self._lock:
            now = time.time()
            new = [item for item in answer.get("new") or [] if isinstance(item, dict)] \
                if isinstance(answer.get("new"), list) else []
            if batch and self.self.get("review") is not batch:
                return False
            if batch:
                observed = self.memory.by_ids(batch["ids"])
                for item in new:
                    cited = item.get("runs") or []
                    item["origins"] = [m["id"] for m in observed if m.get("run_id") in cited and m["kind"] in ("exchange", "event")]
                new = [item for item in new if item.get("from") == "told" and item["origins"] or
                       len(set(item["origins"])) >= 2]
            reworded = [item for item in answer.get("reworded") or [] if isinstance(item, dict)] \
                if isinstance(answer.get("reworded"), list) else []
            changed = self.ways.review(names(answer.get("kept")), names(answer.get("broken")), now, new,
                                       names(answer.get("dropped")), reworded)
            changed = bool(self.ways.fade(now)) or changed
            if batch:
                for item in new:
                    way = self.ways.find(item.get("name", ""))
                    if way and way["since"] == now:
                        way["origins"] = list(item["origins"])
                batch["done"].append("ways")
                self.save()
        if changed:
            self.save()
            self._retake()
        return changed

    def _review_feelings(self, batch: dict) -> None:
        """Sleep goes over the words she put to how she felt (prompts.FEELINGS), thought through, with who she
        is: each saying not yet gone over, against her feelings and their moments. A saying that said how she felt
        stays (a provisional word is confirmed hers) or goes with the feeling of hers it is the same as; one that
        said something else (what she thought of something, did or is) is set aside, kept with her reason; two
        words for one feeling are joined, one word for two feelings split. What acting in a feeling taught goes
        with its moments (Values.carry). Concepts are made from instances and consolidated in sleep, where what
        they share is drawn out (McClelland, McNaughton & O'Reilly 1995); finer ones go with living with feelings
        better (Barrett et al. 2001). An answer she could not read leaves them for the next night."""
        now = time.time()
        with self._lock:
            if not self.feelings.unreviewed():
                return
            listing, moments, fresh = self._feelings_told(now)
            contact = self.self.get("contact")
        persona = self._persona(contact["app"], contact["session"]) if contact else ""
        answer, _ = self._ask(prompts.FEELINGS, f"Who they are:\n{persona[:6000]}\n\nTheir feelings:\n{listing}",
                              quick=False)
        if not isinstance(answer, dict) or not isinstance(answer.get("today"), list):
            logger.warning("Her sleep made nothing of her feelings (an answer it could not read); they are gone over "
                           "again next time")
            return

        def number(value) -> Optional[int]:
            text = str(value).strip().lstrip("#") if isinstance(value, (int, str)) and not isinstance(value, bool) else ""
            return int(text) if text.isdecimal() else None

        def items(key: str) -> List[dict]:
            found = answer.get(key)
            return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []
        with self._lock:
            if self.self.get("review") is not batch:
                return
            now, gone_over = time.time(), set()
            for item in items("today"):
                which, why = number(item.get("moment")), " ".join(str(item.get("why") or "").split())[:300]
                if which not in fresh or which in gone_over or not isinstance(item.get("felt"), bool):
                    continue
                gone_over.add(which)
                one = moments[which]
                home = next((f for f in self.feelings.known if any(one is other for other in f["said"])), None)
                if home is None:
                    continue
                one["reviewed"] = now
                if not item["felt"]:
                    emptied = self.feelings.set_aside(one, why, now)
                    if emptied is not None:
                        self.values.drop_feeling(emptied)
                    continue
                into = number(item.get("feeling"))
                if into is not None and into != home["id"] and self.feelings.find(into):
                    _, emptied = self.feelings.move(one, into, why, now)
                    if emptied is not None:
                        self.values.carry(emptied, into, keep=False)
                else:
                    self.feelings.confirm(home["id"], why, now)
            for item in items("join"):
                pair = [number(value) for value in item.get("feelings") or []] if isinstance(item.get("feelings"), list) else []
                why = " ".join(str(item.get("why") or "").split())[:300]
                if len(pair) == 2 and None not in pair and self.feelings.join(pair[0], pair[1], why, now):
                    self.values.carry(pair[1], pair[0], keep=False)
            for item in items("split"):
                which = number(item.get("feeling"))
                taken = [moments[n] for n in (number(v) for v in item.get("moments") or []) if n in moments] \
                    if isinstance(item.get("moments"), list) else []
                made = self.feelings.split(which, taken, " ".join(str(item.get("why") or "").split())[:300], now) \
                    if which is not None else None
                if made:
                    self.values.carry(which, made["id"], keep=True)
            self.save()

    def _feelings_told(self, now: float) -> Tuple[str, Dict[int, dict], List[int]]:
        """Her feelings as her sleep goes over them (under her lock): each with its number, what she calls it and
        its moments (the last few gone over before, and every one not yet), each moment numbered. (the listing,
        her namings by moment number, the numbers of those to go over)."""
        ids = {one["episode"] for feeling in self.feelings.known for one in feeling["said"] if one["episode"]}
        kept = {e["id"]: e for e in self.memory.by_ids(ids)}
        moments: Dict[int, dict] = {}
        fresh, blocks = [], []
        for feeling in self.feelings.known:
            shown = [one for one in feeling["said"] if one["reviewed"] is not None][-3:] + \
                [one for one in feeling["said"] if one["reviewed"] is None]
            lines = [f'Feeling {feeling["id"]}, "{self.feelings.word(feeling)}"'
                     + ("" if feeling["standing"] == "hers" else " (new: not gone over yet)") + ":"]
            for one in shown:
                moments[len(moments) + 1] = one
                if one["reviewed"] is None:
                    fresh.append(len(moments))
                lines.append(f"  moment {len(moments)}{' (to go over)' if one['reviewed'] is None else ''}: "
                             + self._moment_told(one, kept.get(one["episode"]), now))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks), moments, fresh

    @staticmethod
    def _moment_told(one: dict, episode: Optional[dict], now: float) -> str:
        """One moment of a feeling, as her sleep is told it: what she said, what was happening, how her body was
        moved (amounts, never numbers), what it meant for her needs and which way it moved her to act."""
        # the words taken as the feeling's name, apart from the sentence they are in: shown only the sentence, her
        # first review kept "the ugly part" and "holding him to it" with reasons that retold the sentence
        # (feelings-as-moments exam, 2026-11-20)
        said = f', saying: "{one["text"][:300]}"' if Feelings.key(one["text"]) != Feelings.key(one["words"]) else ""
        parts = [f'{_ago(now - one["at"])}, they called it "{one["words"]}"{said}']
        if one["named"] == "unresolved":
            parts.append(f'(of a moment they gave as "{one["asked"]}", which is not among their memories)')
        elif episode:
            parts.append(f"What was happening: {episode['text'][:300]}")
        way = (one["measure"] or {}).get("way") or (Memory.felt(episode) if episode else {})
        strong = sorted(((name, value) for name, value in way.items() if name in CHANNELS and abs(value) >= 0.3),
                        key=lambda item: -abs(item[1]))[:3]
        if strong:
            parts.append(f"Their body: {_amounts(strong)}")
        appraisal = Memory.appraisal(episode) if episode else None
        if appraisal:
            meant = [f"{'much ' if abs(appraisal[need]) >= 0.8 else 'a little ' if abs(appraisal[need]) < 0.5 else ''}"
                     f"{'more' if appraisal[need] > 0 else 'less'} of {NEEDS_TOLD[need]}"
                     for need in NEEDS_TOLD if abs(appraisal.get(need, 0.0)) >= 0.2]
            if abs(appraisal.get("theirs", 0.0)) >= 0.3:
                meant.append(f"things {'good' if appraisal['theirs'] > 0 else 'bad'} for the one who wrote")
            if meant:
                parts.append("It meant " + ", ".join(meant))
        leaned = Memory.leaned(episode) if episode else None
        if leaned and leaned.get("act"):
            parts.append(f"It moved them toward {prompts.LEANED.get(leaned['act'], leaned['act'])}"
                         + (f": {leaned['what'][:120]}" if leaned.get("what") else ""))
        return ". ".join(part.rstrip(".") for part in parts) + "."

    def _whose(self, about: str, now: float) -> List[str]:
        """Where the feeling words she asks about came from (under her lock): the times she said each herself. A
        word she is asked about and never said is not among them: looking inward, she finds it is not hers.
        "Permission" once came to her as something "you have called" it; she tried to explain it from
        experience, and only a search of her history showed she had never said it (the audit, finding 4)."""
        asked, found = about.casefold(), []
        for feeling in self.feelings.known:
            for word in {Feelings.key(one["words"]) for one in feeling["said"]}:
                said = [one for one in feeling["said"] if Feelings.key(one["words"]) == word]
                if word and re.search(rf"(?<!\w){re.escape(word)}(?!\w)", asked):
                    found.append(f'"{said[-1]["words"]}" is my own word: first said "{said[0]["text"]}" ({_ago(now - said[0]["at"])})'
                                 + (f', and last "{said[-1]["text"]}" ({_ago(now - said[-1]["at"])})' if len(said) > 1 else "")
                                 + ".")
        return found

    def attend(self, now: float, of: str, *, free: float = 1.0, asked: str = "", about: str = "", considered=(),
               temperature: Optional[float] = None, run: Optional[int] = None, chat: str = "", felt=None,
               deliberate: bool = False) -> Optional[dict]:
        """Whether her attention turns to herself now, and what little it takes in (attention.py; under her lock).
        What draws it: being asked about her inner life (``asked``: her reading's words for what), her body further
        from where it usually sits than she knows (a lot, as far as ``free`` (1 - focus held outward) and her
        insight leave her attention free; while she attends to herself, a meaningful change), being torn between
        two ways of acting (``considered``, ``temperature``: her will's). ``deliberate``: she looks on purpose
        (look_inward), for ``about``. ``of``: the moment ("turn", "thought", "look"); ``run``, ``chat``: the run
        it is part of and its chat (what was just said there is before her already). The stretch of attention keeps one identity while it lasts (self["attending"], on her mind as a
        noticed item) and takes in only what is new; her sleep forgets it. Noticing changes nothing in her body,
        names nothing and keeps no memory of its own: the moment it is part of does (_noticed_in). None when
        nothing draws her inward; else {key, why, taken, torn, at, text (for her note or thought), view
        (inward.view's parts, when she looks or is asked)}."""
        if self.body.asleep:
            return None
        felt = felt or feel(self.body, self.senses, now)
        state = self.self.get("attending")
        if state and state["at"] <= (self.self.get("slept") or 0.0):
            state = self.self["attending"] = None  # slept since: what she knew of herself then is gone
        far = dict(felt.standing_out(len(CHANNELS), attention.FLOOR, usual=True))
        known = {name: lots for name, lots in ((state or {}).get("known") or {}).items() if name in far}
        attending = bool(state) and not state.get("released")
        insight = self.body.temperament.insight
        body = attention.news(far, known, free * insight, attending)
        rival = attention.torn(list(considered), temperature)
        looking = bool(asked) or deliberate
        why = [reason for reason, on in (("asked", bool(asked)), ("deliberate", deliberate), ("body", bool(body)),
                                         ("torn", bool(rival))) if on]
        if state:
            state["known"] = known  # what went back under the floor is no longer known
        if not why:
            return None
        aware = self._clear() * insight
        lasting = {name: off(name, self.senses.used.get(name, felt.reading[name])) for name in far}
        taken = sorted(far if looking else body, key=lambda name: -abs(far[name]))[:self._span()]
        seen = attention.body_words(far, lasting, taken) if aware >= inward.AWARE else ""
        torn = ""
        if rival:
            picked = next(one for one in considered if one.get("picked"))
            pulls = reasons(rival["parts"], picked["parts"], rival["act"])[:2]
            torn = (f"Torn: {prompts.ACTS.get(rival['act'], rival['act'])}"
                    + (f" ({rival['what']})" if rival.get("what") else "") + " pulls as much"
                    + (f": {'; '.join(pulls)}" if pulls else "") + ".")
        if not state or not attending:  # a new stretch: what she knew before still holds
            state = {"key": f"noticed:{now:.3f}:{secrets.token_hex(3)}", "at": now, "of": [], "runs": [], "episodes": [], "known": known}
        state.update(last=now, why=why, released=None, text=" ".join(filter(None, (seen, torn))) or "nothing clear",
                     known={**known, **{name: round(far[name], 3) for name in taken}})
        if of not in state["of"]:
            state["of"].append(of)
        if run is not None and run not in state["runs"]:
            state["runs"].append(run)
        self.self["attending"] = state
        if asked:
            self.self["looked"] = {"at": now, "about": ""}
        view = self._looking(now, felt, seen, about, chat, whole=of != "turn") if looking else None
        tone, pace = felt.tone()
        body_text = seen or (f"On the whole it feels {tone}, with {pace}; nothing clearer than that right now."
                             if body else "")
        text = " ".join(filter(None, (inward.view(**view) if view else body_text, torn)))
        return {"key": state["key"], "why": why, "taken": {name: round(far[name], 3) for name in taken},
                "torn": rival["act"] if rival else None, "at": now, "text": text, "view": view}

    def _looking(self, now: float, felt, body: str, about: str = "", chat: str = "", whole: bool = True) -> dict:
        """What she finds as she turns to herself, on purpose or asked (under her lock): inward.view's parts, but
        for what comes back about ``about`` (look_inward recalls it). ``body``: her body against where it usually
        sits, as attention takes it in (attention.body_words); ``whole``: her day too, and her passing sense of her
        body; a turn's look (False) takes in only a little, herself now, what her note does not hold already: her
        body against usual and the feelings it is like (the turn's whole day, read again, was carried on in words:
        her last decision as a shell command, in 15 of 52 answers of the 0.48 exam); ``chat``: where she is asked
        (what was said there is before her)."""
        span = self._span()
        # the feelings of hers it is like, each by the moment of it it is likest, as she said it then
        familiar = [(self.feelings.word(feeling), one["text"], _ago(now - one["at"]))
                    for feeling, _, one in self._recognized(felt.noticed(), self._situation())][:span]
        aware = self._clear() * self.body.temperament.insight
        if not whole:
            return {"felt": body, "tone": felt.tone(), "aware": aware, "familiar": familiar}
        # her day: what her sleep has not yet gone over (being woken from a doze does not end it)
        woke = self.self.get("slept") or 0.0
        thoughts = [(t["thought"][:THOUGHT_CHARS], t.get("went"),
                     t["leaned"]["reasons"] if t.get("went") == "let be" else []) for t in self.self["thoughts"]
                    if t["at"] > woke][:2 * span]
        urge = self.self.get("urge")
        unsaid = None
        if urge and "mark" not in urge and urge.get("say") and urge["at"] > woke:
            person = self._with(urge["app"], urge["session"])
            unsaid = (urge["want"], person["name"] if person else "the user", urge["say"])
        space = self._in_mind(now)
        put_off = [item for item in space.by_activation(now) if item["kind"] == "put off"][:span]
        carried = {f"thought:{t.get('episode')}" for t in self.self["thoughts"] if t["at"] > woke} | {
            item["key"] for item in put_off} | {key for key, item in space.items.items()
                                                if item["kind"] in ("intends", "doing", "self", "noticed")} | {
            f"asked:{chat}"}
        also = self._before_her(None, now, carried, cued=False)  # the rest that is on her mind, the most active
        did, going = self._doings(woke, now)  # what she did today, the latest her span holds; what goes on
        stirred = sorted((e for e in self.memory.since(woke, kinds=("exchange", "event", "thought"))
                          if abs(e["sting"]) >= 0.1), key=lambda e: -abs(e["sting"]) * e["charge"])[:span]
        called = {one["episode"]: one["words"] for feeling in self.feelings.known for one in feeling["said"]
                  if one["episode"] and one["named"] in ("now", "past")}  # what she called a moment
        decided = self.self.get("decided")
        belief = self.self.get("self_view") or {}
        self_view = belief.get("text") or ""
        if self_view and belief.get("confidence") != "supported":
            self_view = "A tentative impression: " + self_view
        return {"felt": " ".join(filter(None, (felt.words(), body))), "tone": felt.tone(),
                "aware": aware, "thoughts": thoughts, "unsaid": unsaid,
                "put_off": [item["text"][:200] for item in put_off],
                "moved": [(f"#{e['id']} {self._line(e, now)}", e["sting"], called.get(e["id"])) for e in stirred],
                "leaned": ((prompts.ACTS.get(decided["act"], decided["act"])
                            + (f": {decided['what']}" if decided.get("what") else ""), decided.get("reasons") or [])
                           if decided and decided.get("gated") and now - decided["at"] < 6 * HOUR else None),
                "self_view": self_view, "about": about, "familiar": familiar,
                "did": did[-2 * span:], "going": going, "whose": self._whose(about, now) if about else [], "also": also}

    def _noticing(self, now: float, working: bool) -> Optional[float]:
        """How strongly her body draws her attention to itself now (the notice bid; None: it does not): a lot she
        does not know yet of how far it is from usual, as far as her attention is free (held by her work, as far
        as she is focused), pulls as a resting mind's wandering does (attention.py)."""
        if self.body.asleep:
            return None
        state = self.self.get("attending")
        if state and state["at"] <= (self.self.get("slept") or 0.0):
            state = None
        far = dict(feel(self.body, self.senses, now).standing_out(len(CHANNELS), attention.FLOOR, usual=True))
        free = (1.0 - self.body.levels["acetylcholine"] if working else 1.0) * self.body.temperament.insight
        found = attention.news(far, {name: lots for name, lots in ((state or {}).get("known") or {}).items()
                                     if name in far}, free, bool(state) and not state.get("released"))
        return RESTING * free * max(found.values()) if found else None

    def _noticed_in(self, key: str, episode: int) -> None:
        """What she noticed in herself was part of this kept moment (under her lock): its item and its stretch know
        it, so what she knew of herself is found from the moment and back."""
        self.workspace.link(key, episode)
        state = self.self.get("attending")
        if state and state["key"] == key and episode not in state["episodes"]:
            state["episodes"].append(episode)

    def _release(self, now: float) -> None:
        """Something else took her attention (under her lock): the stretch of attention to herself is over; what she
        took in stays known until it changes or she sleeps."""
        state = self.self.get("attending")
        if state and not state.get("released"):
            state["released"] = now

    def look_inward(self, about: str = "", naming: str = "", moment=None, *, strategy="notice", run=None,
                    call: Optional[str] = None) -> str:
        """She looks inside herself on purpose (inward.view): how her body feels, in body words as her note
        gives it, and how clearly she can tell; when it feels like a feeling she has named herself, the times
        she said so, in her own words (never a name she did not give it); what has been on her mind since
        she woke and what came of it, what she meant to say and put off, what got to her, what she leaned toward
        and why, what she knows about herself; with ``about``, what comes back about it and how clearly. As many
        things as her span holds; each moment with its number. ``naming``: she puts what she finds into words,
        her own, any (``_name``): what she is in now, or with ``moment`` (a number she was shown) that past
        moment; what comes back as she looks only reminds her (``reminded``), whatever its rank; ``call``: the
        tool call naming it (made again, it names nothing twice). That is what eases a feeling, looking
        alone does not (the attend, try a word, check it fits, felt shift of Gendlin's focusing). With only
        what each message's note handed her, asked what bothered her, she answered from the last topic while her
        thoughts all afternoon had been about wanting to be noticed (the user's brain, 2026-11-17)."""
        about = " ".join(str(about or "").split())[:300]
        receipt = None
        if strategy == "reappraise" and run:
            decision = run["options"].get("mind") or {}
            receipt = self._observed(decision.get("check"), self.brain.store.run_events(run["id"]))
        now = time.time()
        with self._lock:
            felt = feel(self.body, self.senses, now)
            span = self._span()
            seen = self.attend(now, "look", felt=felt, about=about, run=run["id"] if run else None,
                               chat=_chat(run["app"], run["session"]) if run else "", deliberate=True)["view"]
            decided = self.self.get("decided")
            self.self["looked"] = {"at": now, "about": about}
            if strategy == "reappraise":
                trace = self.self.get("reappraisal") or {}
                if receipt and receipt["status"] == "ok" and receipt.get("matched", True) and run["id"] == (decided or {}).get("run"):
                    if receipt["id"] != trace.get("event"):
                        before = self.body.stress_drive
                        self.body.stress_drive *= 0.85
                        self.self["reappraisal"] = {"event": receipt["id"], "run": run["id"],
                                                    "prediction": decision["check"]["tool"],
                                                    "change": self.body.stress_drive - before}
                    self.self["looked"]["evidence"] = receipt["id"]
                else:
                    receipt = None
            revision = self._revision
        recalled, came_back = None, []
        lookup = {}
        if about:  # sought on purpose: what comes back, and how strongly it is there to come back (Koriat 1993)
            came_back = self.memory.recall(about, felt.valence, now, count=span, status=lookup)
            recalled = [(f"#{e['id']} {self._line(e, now)}", Memory.strength_now(e, now)) for e in came_back]
        self.save()
        with self._lock:
            if revision != self._revision:
                return "It changed while looking: another look will show it as it is now."
            self._refeel([(e, e["relevance"]) for e in came_back], now)  # what she looked for, felt again
        report = inward.view(**{**seen, "recalled": recalled})
        naming = str(naming or "").strip()
        if naming:  # what she names: now, or the past moment she points to; what came back only reminded her
            current = self.brain.store.run(run["id"]) if run else None  # with the decision reading it left
            reminded = [e["id"] for e in came_back]
            with self._lock:
                now = time.time()
                target = self._moment(moment) if moment not in (None, "") else None
                if moment in (None, ""):
                    record = naming_record(naming, naming, now, "tool", "now", run=(current or {}).get("id"),
                                           event=self._input_event(current), call=call,
                                           episode=(self.memory.of_run(current["id"]) or {}).get("id") if current else None,
                                           measure=self._measure_now(current, now), reminded=reminded)
                elif target:
                    record = naming_record(naming, naming, now, "tool", "past", run=(current or {}).get("id"),
                                           event=self._input_event(current), call=call, episode=target["id"],
                                           measure=self._measure_past(target), reminded=reminded)
                else:
                    record = naming_record(naming, naming, now, "tool", "unresolved", run=(current or {}).get("id"),
                                           event=self._input_event(current), call=call, asked=str(moment),
                                           reminded=reminded)
                _, fit = self._name(record)
            self.save()
            report += f' Put into words: "{naming}".' + (f" {fit}" if fit else "")
            if record["named"] == "unresolved":
                report += f" No moment #{str(moment).strip().lstrip('#')} is among the memories: the words are kept, for no moment."
            elif record["named"] == "past":
                report += f" Moment #{target['id']} named."
        if strategy == "reappraise":
            report += (f" The record checked: {receipt['name']} succeeded on the expected target."
                       if receipt else " Still no matching successful observation for this concern.")
        if about and not lookup.get("available"):
            report += " The memory index can't be checked right now."
        if about and recalled:
            report += " This is how it came to mind; the original observation is what shows its contents."
        return report

    def _know_herself(self, since: float, batch=None) -> bool:
        """Sleep goes over what the day showed about who she is, once a night, thought through: what she knows
        about herself, in her own words, kept with what still holds (self-knowledge is learned from watching
        what you do and feel, slowly, and partly wrong: Bem 1972, Wilson 2002). Her persona is not shown: it is
        who she is meant to be, this is who she finds she is. Whether it changed."""
        now = time.time()
        with self._lock:
            moments = sorted(self.memory.by_ids(batch["ids"]) if batch else self._replay_items(since, now, 12),
                             key=lambda e: e["at"])
            thoughts = [t["thought"][:THOUGHT_CHARS] for t in self.self["thoughts"] if since < t["at"] <= (batch["to"] if batch else now)][:6]
            known = (self.self.get("self_view") or {}).get("text") or ""
        if not moments and not thoughts:
            return False
        asked = ("What they knew about themselves:\n" + (known or "nothing yet") + "\n\nToday, oldest first:\n"
                 + "\n".join(f"[{m['id']}] {line(m, now)} (it felt {_tone(m['valence'])})" for m in moments)
                 + ("\n\nTheir own thoughts today:\n" + "\n".join(f'- "{t}"' for t in thoughts) if thoughts else ""))
        answer, _ = self._ask(prompts.SELF, asked, quick=False)
        text = " ".join(str(answer.get("self") or "").split())[:SELF_CHARS]
        if not text or text == known:
            return False
        with self._lock:
            if batch and self.self.get("review") is not batch:
                return False
            old = self.self.get("self_view") or {}
            observed = {m["id"] for m in moments if m["kind"] in ("exchange", "event") and not m.get("superseded_by")}
            support = [i for i in answer.get("supports") or [] if type(i) is int and i in observed]
            against = [i for i in answer.get("against") or [] if type(i) is int and i in observed]
            self.self["self_view"] = {"text": text, "since": old.get("since") or now, "at": now,
                                      "kind": "self-inference", "origins": sorted(set(support)),
                                      "against": sorted(set(against)), "confidence": "supported"
                                      if len(set(support)) >= 2 and not against else "tentative"}
            if batch:
                batch["done"].append("self")
                self.save()
        self.save()
        return True

    def ways_section(self) -> str:
        """YOUR WAYS for a chat's system prompt (Ways.section), taken with the session's snapshot."""
        with self._lock:
            return self.ways.section()

    def with_section(self, app: str, session: str, own: bool = True) -> str:
        """Who she is with, for a chat's system prompt ("" when nobody shows): in the session's snapshot, so the
        cached prefix holds; taken again when someone else writes there or sleep changed what she knows."""
        with self._lock:
            handle = self.self.get("faces", {}).get(_chat(app, session))
            person = self._with(app, session)
        if person is None and not handle:
            return ""
        head = "## WHO YOU'RE WITH\n" if own else "## WHO THIS IS FOR\n"
        if person is None:
            return head + f'Someone who goes by "{handle}" here. You don\'t know yet who they are.'
        shown = f', who goes by "{handle}" here' if handle and handle.lower() != person["name"].lower() else ""
        basis = person.get("basis")
        gist = person.get("gist") or ""
        if gist and basis:
            gist = f"{gist} ({basis})"
        return head + f"{person['name']} ({person.get('pronoun') or 'they'}){shown}. {gist}".strip()

    def _named(self, text: str, app: Optional[str]) -> str:
        """A moment's words with who was in it: one kept as "The user said" (before she knew people, or before
        she knew them) reads with the name of whom that app's user is."""
        # shortcut: one person per app for those old moments; a moment does not keep whose face it was
        person = self.people.of_app(app) if "The user said" in text else None
        return text.replace("The user said", f"{person['name']} said", 1) if person else text

    def _line(self, episode: dict, now: float) -> str:
        """A memory as it comes back to her (memory.line), as much of it as she is told of one (and of what came of
        it, half as much again)."""
        return line(episode, now, width=THOUGHT_CHARS)  # the identity recorded at encoding, unknown speakers too

    def _retake(self, app: Optional[str] = None, sessions=()) -> None:
        store = getattr(self.brain, "store", None)
        if store is not None:
            store.drop_snapshots(app, sessions)

    def _remember_task(self, run: dict, now: float, text: str, newness: Optional[float]) -> None:
        """A task ended (under her lock): what she did is a moment of hers, or what she did and
        found on her own is gone from her memory. What was new
        to her in it fills her want of something new (resolving curiosity is itself rewarding: Kang et al. 2009,
        Gruber, Gelman & Ranganath 2014)."""
        valence, aroused = core(self.body.levels)
        levels = dict(self.body.levels)
        self.body.apply({"novelty": 0.3 * (0.5 if newness is None else newness)}, "new to her: " + text[:QUOTED])
        self.memory.add("event", text, valence, aroused, 0.4, app=run["app"], session=_kept_in(run), at=now,
                        run_id=run["id"], felt=moved(levels, self.body.levels), cues=self._cues(None, now, run["app"]))

    def _task_moment(self, run: dict, events: Optional[list] = None) -> str:
        """What a task of hers was, as she keeps it: what she set out to do (on her own or asked), how it went,
        and what her tools did (_account): what she looked at and changed, and the jobs and helpers it started,
        which may go on without it (without them, asked what job 447 was, she could not tell it
        was hers; without what its 34 calls did, a question about one address had become
        work on others: the audit, finding 1)."""
        own = _own(run)
        if own:
            goal = ("Out of my own curiosity I looked up: " if own.get("want") == "look_up"
                    else "I decided on my own to ") + str(own.get("what") or "")
        else:
            goal = "I worked on: " + " ".join(str(run["options"].get("goal") or "").split())
        reply = " ".join(signals.split(str((run.get("result") or {}).get("reply") or ""))[1].split())
        account = self._account(run, self.brain.store.run_events(run["id"]) if events is None else events)
        return _said(f"{goal[:300].rstrip('.')}. " + (f"How it went: {reply[:500]}" if reply else f"It {run['status']}")
                     + "." + account)

    def _when(self, chat: str, actor: Optional[str], now: float) -> str:
        """When each of them last wrote, the computer was last touched and she last slept (under her lock), each
        its own time, for her note. Back after 3 hours 8 minutes (turn 671), she said "two hours and change":
        nothing told her when anyone wrote, and she counted from her own last message; her thoughts had made the
        quiet computer "he's just gone" (2026-11-18)."""
        parts = []
        theirs = ((self.self.get("contacts", {}).get(chat) or {}).get(actor or "") or {}).get("at")
        if theirs:
            parts.append(f"they last wrote here {_span(now - theirs)} ago, at {_clock(theirs)}")
        hers = self.self.get("said") or {}
        if hers.get("at"):
            parts.append(f"last written {_span(now - hers['at'])} ago, at {_clock(hers['at'])}"
                         + ("" if hers.get("chat") == chat else ", in another chat"))
        if self.presence.touched:
            parts.append(f"the computer was last touched {_span(now - self.presence.touched)} ago")
        slept = getattr(self.body, "last_sleep", None) or {}
        if slept.get("to") and slept["to"] > (theirs or 0.0):  # she slept since they last wrote here
            parts.append(f"slept from {_clock(slept['from'])} to {_clock(slept['to'])}")
        return "; ".join(parts)

    def _doings(self, since: float, now: float) -> Tuple[List[str], List[str]]:
        """What she did from ``since`` on (her tasks' ends, and the ends of jobs they left running, as she keeps
        them), oldest first, and what of hers is still going: her tasks, her helpers at work and every job left
        running (whose it is: a task of hers, on her own or asked, or a chat). One brain does them all, whichever
        app she is in."""
        did = [self._line(e, now) for e in sorted(
            self.memory.since(since, kinds=("event",)), key=lambda e: e["at"])]
        store, going = self.brain.store, []
        for task in reversed(store.runs(kind="task", statuses=("queued", "working", "input_required"), limit=-1)):
            own = _own(task)
            going.append(f"task {task['id']} " + (f"of my own ({_doing(own)})" if own else
                         f"({' '.join(str(task['options'].get('goal') or '').split())[:160]})")
                         + f", started {_ago(now - task['created'])}")
        # her helpers at work (untold, the helper she started on the user's project in run 565 was
        # still at it when she told them nothing had been started)
        for helper in reversed(store.runs(kind="agent", statuses=("queued", "working", "input_required"), limit=-1)):
            record = self.brain.agents.record(helper["app"], helper["session"])
            parent = store.run(helper["parent"]) if helper.get("parent") else None
            own = _own(parent) if parent and parent["kind"] == "task" else None
            whence = (f"from my task {parent['id']}" + (f" of my own ({_doing(own)})" if own else "")
                      if parent and parent["kind"] == "task" else f"in {record.get('parent') or helper['session']}")
            task = " ".join(str(record.get("task") or "").split())[:160]
            going.append(f"helper {record.get('name') or helper['session']}" + (f" ({task})" if task else "")
                         + f", {whence}, started {_ago(now - helper['created'])}")
        for job in store.active_jobs():
            run = store.run(job["run"]) if job.get("run") else None
            own = _own(run) if run else None
            whence = (f"from my task {run['id']}" + (f" of my own ({_doing(own)})" if own else "")
                      if run and run["kind"] == "task" else f"in {job['session']}")
            going.append(f"job {job['id']}, {whence}: {_command(job)}, started {_ago(now - job['started'])}")
        return did, going

    def _recover_deeds(self) -> None:
        """A task of hers that ended while nothing took it in (the brain went down, or her mind failed as it
        ended) becomes a moment of hers as of when it ended, as she starts, with no feeling: how it moved her then
        is not known. In the user's brain (2026-11-18) seven of her twelve finished tasks had been lost so, and
        asked about the job one left running she searched her conversations in vain. Each task once: one that
        ended since she last looked."""
        store = self.brain.store
        checked = self.self.get("deeds_checked") or 0.0
        for run in store.runs(kind="task", limit=-1):
            if not _own(run):
                continue
            if run["status"] in ("completed", "failed") and run["updated"] > checked \
                    and not self.memory.recorded(run["id"]):
                self.memory.add("event", self._task_moment(run), 0.0, 0.0, 0.4, app=run["app"],
                                session=run["session"], at=run["updated"], run_id=run["id"],
                                cues=moment_cues(run["updated"], run["app"]))
        with self._lock:
            self.self["deeds_checked"] = time.time()
            self.save()

    def job_ended(self, job: dict, code: int, stopped: bool, tail: List[str]) -> None:
        """A job a task left running ended after the task did (while the task works, it reads the job's end
        itself): what came of it is a moment of hers, kept with the task. Not a note to the
        task's session, where nothing reads it any more: she would never know."""
        run = self.brain.store.run(job["run"]) if job.get("run") else None
        if not run or run["kind"] != "task" or run["status"] not in ("completed", "failed", "cancelled"):
            return
        own = _own(run)
        goal = " ".join(str(run["options"].get("goal") or "").split())
        whose = f"on my own ({_doing(own)})" if own else f"for a task ({goal[:120]})"
        lines = " / ".join(" ".join(line_.split()) for line_ in tail if line_.strip())
        text = (f"The job I left running {whose} ended: job {job['id']} ({_command(job)}) "
                + ("was stopped" if stopped else f"finished with exit code {code}") + "."
                + (f" Its last lines: {lines[-400:]}" if lines else ""))
        with self._lock:
            now = time.time()
            valence, aroused = core(self.body.levels)
            self.memory.add("event", text, valence, aroused, 0.3, app=run["app"], session=_kept_in(run), at=now,
                            cues=self._cues(None, now, run["app"]))
            self.save()

    def _meet_people(self, moments, batch=None) -> bool:
        """What she knows of the people in ``moments`` settles, as it does in sleep; whoever she met on few nights
        and has not seen for long is forgotten. Whether what she knows changed (each chat's prompt is then taken
        again)."""
        now = time.time()
        with self._lock:
            revision = self._revision
            known = [People.line(person) + "".join(f' (goes by "{h}" in {app})' for app, hs in person["goes_by"].items()
                                                   for h in hs) for person in self.people.known]
            faces = [f'in "{app}": ' + ", ".join(f'"{h}"' for h in handles) for app, handles in self.people.handles.items()]
            listed = [f"{index + 1}. ({_ago(now - m['at'])}" + (f", in {m['app']}" if m.get("app") else "") + ") "
                      + m["text"][:THOUGHT_CHARS] for index, m in enumerate(sorted(moments, key=lambda m: m["at"]))]
        if not listed:
            return False
        # not shown her persona: given it, her story's mother and father were met as people of her life (2 of 3)
        asked = ("The people they know:\n"
                 + ("\n".join(f"- {k}" for k in known) or "nobody yet") + "\n\nHow apps show the one they talk with: "
                 + ("; ".join(faces) or "nothing yet") + "\n"
                 + "\nWhat happened (oldest first):\n" + "\n".join(listed))
        # thought through (her settings' thinking): once a night, and quick she met 1 to 16 of the same people
        answer, _ = self._ask(prompts.PEOPLE, asked, quick=False)
        with self._lock:
            if revision != self._revision or (batch and self.self.get("review") is not batch):
                return False
            changes = []
            for change in answer.get("people") or []:
                if not isinstance(change, dict):
                    continue
                aliases = change.get("aka")
                names = [change.get("name"), *(aliases if isinstance(aliases, list) else [])]
                relevant = [m for m in moments if any(isinstance(n, str) and n and
                            re.search(rf"(?<!\w){re.escape(n)}(?!\w)", m["text"], re.I) for n in names)]
                if relevant:
                    direct = [m for m in relevant if m["text"].casefold().startswith(str(change.get("name") or "").casefold() + " said:")]
                    changes.append({**change, "basis": "inferred from a conversation" if direct else "reported by another source",
                                    "origins": [m["id"] for m in direct or relevant]})
            changed = self.people.update(changes, time.time())
            gone = self.people.fade(time.time())
            if batch:
                batch["done"].append("people")
                self.save()
        if changed or gone:
            self._retake()
            self.save()
        return changed

    # ============== For apps and the panel ==============

    def section(self) -> str:
        """Her inner life in the system prompt. Her story is not in it: measured
        live (2026-11-17, 12 messages, a blind judge on her persona), with it 7 replies brought in its details
        (a jar of crickets, a watcher's pid) and none without, the judge took the reply without it 7 to 5, and
        it cost 245 tokens a request. So there is none: her persona is who she is, what she
        learned is in her likes, her memories and what she keeps."""
        return prompts.INNER_LIFE

    def state(self, app: Optional[str] = None, idle: Optional[float] = None, brief: bool = False,
              locked: Optional[bool] = None, busy: Optional[bool] = None,
              around: Optional[Dict[str, str]] = None) -> dict:
        """How she is now: her face for ``app`` (from its declared expressions), what she feels, her levels,
        thoughts, concerns, likes and dislikes; for drawing her brain, every feeling she has named (``feelings``), her
        body's channels as she senses them (``sensed``: how far from usual, in units of a lot), what wants her
        attention (``attention``), her last decision (``decided``) and the connections her dynamics make
        now (``wiring``: [level, what it drives, weight]). ``idle``: seconds since the user last touched
        the computer. ``brief``: only what a face needs (``asleep``, ``present``, ``felt``, ``feeling``: a
        few words for it, ``valence``, ``arousal``, ``face``): an app's frequent look, kept small as she grows."""
        if app and any(value is not None for value in (idle, locked, busy, around)):
            self.seen(app, idle, locked, busy, around)
        options = {}
        if app:
            signals = ((self.brain.store.app(app) or {}).get("declaration") or {}).get("signals") or {}
            options = next((s["options"] for s in signals.values() if isinstance(s, dict)
                            and isinstance(s.get("options"), dict)), {})
        now = time.time()
        with self._lock:
            body = self.body
            felt = feel(body, self.senses, now)
            situation = self._situation()
            felt_now = self._recognized(felt.noticed(), situation)
            seen = {"asleep": body.asleep, "present": self.present(now), "felt": felt.words(),
                    "feeling": ", ".join(self.feelings.word(f) for f, _, _ in felt_now[:2]) or ", ".join(felt.tone()),
                    "valence": round(felt.valence, 3), "arousal": round(felt.arousal, 3),
                    "face": face(felt, options, body.asleep)}
            if brief:
                return seen
            feelings = self.feelings.shown({"way": felt.noticed(), "appraisal": situation["appraisal"]},
                                           self._kept_moments(), situation["near"])
            set_aside = [dict(one) for one in self.feelings.aside]
            likes, dislikes = self.values.leanings()
            bids, threshold, _, _ = self._drives(now)
            pulls, fired, night = bids(), self.self["fired"], body.night(now)

            def tone() -> Dict[str, float]:  # from her levels themselves: what they do to her core affect
                valence, arousal = core(body.levels)
                return {"valence": valence, "arousal": arousal}

            def pulled() -> Dict[str, float]:
                return {kind: value for kind, value in bids().items() if value is not None}
            wiring = body.influence(body.targets) + body.influence(tone, 0.1) + body.influence(pulled, 0.1)
            # what each does now (a level at rest does nothing, whatever it could do)
            pushing = body.effects(body.targets) + body.effects(tone, 0.01) + body.effects(pulled, 0.01)
            return {
                **seen, "model_revision": 2, "simulation_at": body.at,
                "reliability": {name: {**record, "estimate": (record["correct"] + 1) / (record["resolved"] + 2)}
                                for name, record in self.self.get("reliability", {}).items()},
                "phone_contact_at": self.self.get("phone_contact_at"),
                "tool_reliability": self.self.get("tool_reliability"), "review": self.self.get("review"), "stress_drive": round(body.stress_drive, 3), "nrem_seconds": round(body.nrem_seconds),
                # every feeling she has named (strength now, how often, place, the channels that set it apart)
                # and her body as she senses it (how far each channel is from usual, whatever she has got used to)
                "feelings": feelings, "set_aside": set_aside,
                "sensed": {name: round(far, 2) for name, far in felt.standing_out(len(felt.reading), 0.0, usual=True)},
                "night": round(night, 3),
                "needs": {need: round(body.deficit(need), 3) for need in NEEDS},  # how far each is unmet, 0..1
                "attention": {"bids": {kind: None if value is None else round(value, 3) for kind, value in pulls.items()},
                              # the bar each must reach: what comes by itself, and what she must set out to do
                              "threshold": round(threshold["reach_out"], 3), "musing": round(threshold["wonder"], 3),
                              "thinking": self._thinking,
                              "resting": [kind for kind in pulls if now - fired.get(kind, 0.0) < REFRACTORY[kind]],
                              "last": max(pulls, key=lambda kind: fired.get(kind, 0.0)) if any(
                                  kind in fired for kind in pulls) else None},
                "decided": self.self.get("decided"), "wiring": [list(edge) for edge in wiring],
                "pushing": [list(edge) for edge in pushing], "sleep": body.sleep_state(now),
                # the user at the computer (Presence), and how long a silence before she feels unanswered
                "user": {**self.presence.state(now), "patience": round(self.patience())},
                "slept": self.self.get("slept") or 0.0,
                # her memories' revision: an app draws them by GET /v1/mind/memory, fetched only when it changed
                "memory": {"revision": self.memory.revision(), "count": self.memory.count()},
                "levels": {name: round(value, 3) for name, value in body.levels.items()},
                # where each chemical is heading, how fast (seconds to go two thirds of the way), the needs'
                # set points, how responsive the habituating receptors are, and what she expects of the user
                "targets": {name: round(value, 3) for name, value in body.targets().items()},
                # each level at rest, and what pushed each and is still moving it (Body.pushed_now)
                "rest": {name: round(value, 3) for name, value in REST.items() if name in body.levels},
                "pushed": body.pushed_now(now),
                "paces": {name: level.tau for name, level in CHEMICALS.items()},
                "set_points": dict(SET_POINTS), "receptors": {name: round(value, 3) for name, value in body.sensitivity.items()},
                "expected": round(self.self["expected"], 3),
                # how clearly her cortex can think now, and "reflex" when she answers without thinking it through
                "clear": round(self._clear(), 3), "depth": "reflex" if self.reflexive() else None,
                "trust": {guide: {name: round(error, 3) for name, error in errors.items()}
                          for guide, errors in self.self["trust"].items()},
                "fatigue": round(body.fatigue(), 3), "temperament": body.temperament.to_dict(),
                "thoughts": list(self.self["thoughts"]), "concerns": list(self.self["concerns"]),
                "remembered": list(self.self.get("remembered", [])),
                "reactions": self._reactions_seen(now), "reacted": list(self.self.get("reacted", [])),
                "likes": _about(likes), "dislikes": _about(dislikes),
                "memories": self.memory.count(), "people": self.people.listed(), "ways": self.ways.listed(),
                "self_evidence": self.self.get("self_view"),
                "self_view": (self.self.get("self_view") or {}).get("text"), "looked": self.self.get("looked"),
            }
