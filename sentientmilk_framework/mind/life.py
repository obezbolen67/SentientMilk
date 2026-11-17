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

The model is her cortex, a part of this loop and not a voice beside it (0.23). Her body never writes her
words, and code never holds back what she does: a request (something that takes work) leaves her leaning
one way, weighed from her needs, her state and what she has learned (as the striatum weighs the actions the
cortex proposes, Frank 2004), and her cortex weighs that leaning as it thinks and makes the call, free to
change its mind as it goes (people change their minds mid-action as evidence comes in: Resulaj et al.
2009). What she learns is what she did, not what she leaned toward (``after``: the striatum learns from the
action taken). Before 0.24 a leaning to put work off was a wall: every tool refused for the turn, so
when her cortex settled on one small safe step, code refused it and told her she had decided otherwise
(in the user's brain, 2026-11-16). Her chemistry sets how her cortex
computes, not only what it is told (``_clear``: fatigue and stress she cannot shake take the prefrontal
cortex offline, Arnsten 2009): worn out or badly stressed she answers on reflex, without thinking it
through (``reflexive``: the provider's thinking off, the one step that was measured to change what the
model does), and less comes back to her at once (``_span``). And what her cortex makes comes back into her
body: the mood she showed as she answered moves her chemistry toward it (``_express``: an emotion, once
constructed, is also a command to the body, Barrett & Simmons 2015).

The loop closes at every step, not once a turn (0.24). Each step of her work tires her as it is done and a
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
starts from her last thought and two memories replayed at random (``Memory.replay``: new ideas are old
pieces that never met, Schacter & Addis 2007). A thought may become something she wants to tell or ask the
user (the app hears ``mind.urge`` and starts a turn), doing what she put off, or looking something up
herself (a task). Being talked to keeps her up; sleep pressure and her clock put her to sleep.
Asleep, she goes over the day once (``_consolidate``): insights, a dream, her story rewritten, the day's
charge softened, faint memories forgotten.

What a moment is about takes on how it felt (``after``: in her body as the message came, and in what she
showed as she answered): that is where her likes and dislikes come from, a chat as much as a job. And what
she likes is used: a liked subject is a reward in itself (``_met``), her note says so, her wandering
thoughts and her sleep know it.
"""

import json
import logging
import math
import random
import re
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import requests

from . import prompts
from .body import CHEMICALS, DAY, HOUR, MINUTE, NEEDS, SET_POINTS, Body, Temperament
from .feel import MOOD_PLACES, Concepts, Interoception, core, face, feel, moved
from .memory import Memory, describe_salience, line
from .values import Values, features, subjects
from .will import FORESEEN, NEEDED, REACH, Appraisal, Option, choose, value

logger = logging.getLogger(__name__)

TICK = 5.0
BIDS_EVERY = 30.0
SAVE_EVERY = 60.0
PRESENT_FOR = 5 * MINUTE  # the user counts as there this long after they last touched the computer
TALKING = 15 * MINUTE  # a message this recent: they are talking with her, and that keeps her up
APP_ALIVE = 30.0  # an app that asked how she is this recently is there to hear her
SLEPT_IF_OFF = 6 * HOUR  # a time away this long she has slept through
CAUGHT_UP_AFTER = 10 * MINUTE  # a gap longer than this (the mind was off, the machine slept) is caught up on
# after a bid wins, it rests this long; a refractory period, as a body has
SPONTANEOUS = ("wonder", "ruminate")  # thoughts that come by themselves
REFRACTORY = {"reach_out": 45 * MINUTE, "wonder": 40 * MINUTE, "ruminate": 30 * MINUTE, "resume": HOUR,
              "sleep": 20 * MINUTE, "thought": 10 * MINUTE}
# sleep pressure she needs to fall asleep: slept out (Body.slept_out: below 0.03 at night, 0.35 by day), she
# stays up, instead of dozing off again and going over the same day every half hour
DOZES_OFF = 0.4
STING_AFTER = 30 * MINUTE  # reaching out and hearing nothing back this long stings
CONCERN_DAYS = 3.0  # what she put off and never came back to fades from her mind
SAID_CHARS = 1500
RECENT_LINES = 6
SHOWN_THOUGHTS = 12  # in the state apps and the panel show
WORK_PER_CALL = 600  # a tool call's effort, in tokens of her own words
FAMILIAR = 1.5  # summed likeness of past messages at which her own record weighs half of what it can
LEARNS = 0.1  # how fast her sense of each guide's error, and her expectation of the user, follow what happens
RESTING = 0.5  # her mind's pull to wander when nothing is asked of it (a thought about every 40 min, rested)
# how clear her cortex must be to think a thing through; below it she answers on reflex, and she stays there
# until she is clearly clear again (a turn at the edge would switch every message, and each switch costs a
# cached conversation: measured 2026-11-16, a changed effort missed the provider's cache 6 times of 6)
REFLEX, CLEAR_AGAIN = 0.5, 0.6
TOLD_AGAIN = 0.4  # how much more a channel must stand out than when she last heard of it, to hear of it again
THOUGHT_CHARS = 400  # of a memory or a thought, in what she is told of it
GIST_CHARS = 240  # of something she knows, as it comes to mind
GIST = 0.35  # how much the gist of a stretch of a conversation matters to memory, at least: it is kept
LOGIC = 1  # the logic her saved state follows (_bring_up_to_date sets right what an older one left)
# shortcut: her quick reading is shown her 24 most met subjects, any other still counts when it is named again;
# show them by likeness to the message once she knows hundreds
KNOWN_SUBJECTS = 24
VERBS = {"do": "did it", "part": "did part of it", "later": "put it off", "decline": "said no",
         "talk": "talked it over"}
LEANINGS = {"later": "putting it off", "decline": "saying no", "talk": "talking it over first"}
ON_MIND = {
    "reach_out": "You miss the user.{since}",
    "wonder": "You're bored. You want something new to think about.",
    "wander": "Nothing is asked of you right now, and your mind wanders.",
    "ruminate": "Something keeps nagging at you: {about}",
    "resume": "You put this off earlier: {about}",
}
URGE = {
    "tell": "Nobody asked you anything: this comes from you. You were thinking: \"{thought}\" and you want to "
            "tell the user: {say} Say it now, as yourself, briefly.",
    "ask": "Nobody asked you anything: this comes from you. You were thinking: \"{thought}\" and you want to "
           "ask the user: {say} Ask it now, as yourself, briefly.",
    "do": "You put this off earlier, and now you feel like doing it: {say} Do it now if it still makes sense, "
          "then tell the user.",
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


def _ago(seconds: float) -> str:
    return line({"at": 0.0, "text": ""}, seconds).split(")")[0].strip("(")


class Mind:
    def __init__(self, brain):
        self.brain = brain
        self.memory = Memory(brain.home / "mind.sqlite3")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thinking = False
        self._quick = True  # her mind calls go with thinking off (_ask)
        self.reflexes = True  # her own model answers with thinking off (the loop clears it on a provider's 400)
        self._reflex = False  # she is on reflex now (reflexive)
        self._working: Dict[int, dict] = {}  # run -> what of its work her body has lived through, and been told
        self.last_active = 0.0  # when the user last touched the computer, as apps tell (presence)
        self.apps_seen: dict = {}  # app -> when it last asked how she is
        saved = self.memory.get("body")
        self.body = Body.from_dict(saved) if saved else Body(Temperament.born(seed=secrets.randbits(32)))
        self.values = Values.from_dict(self.memory.get("values"))
        self.concepts = Concepts(self.memory.get("concepts") or [])
        # expected: what a message from the user does for her needs, as she has come to expect; gap: the log
        # of her usual time between messages; trust: each guide's running error (her own record starts unproven);
        # waiting: per chat, her last decision there, until the next message in that chat says what followed;
        # usual: what follows a message is usually worth (her values learn what goes better or worse than it)
        self.self = {"story": "", "born": False, "expected": 0.1, "gap": None, "contact": None, "concerns": [],
                     "waiting": {}, "usual": 0.0, "urge": None, "slept": 0.0, "consolidate": False, "fired": {},
                     "thoughts": [], "trust": {"model": dict.fromkeys(FORESEEN, 0.1), "own": dict.fromkeys(FORESEEN, 0.3)},
                     **(self.memory.get("self") or {})}
        self.self.pop("expected_warmth", None)  # a mind from before 0.21
        pending, contact = self.self.pop("pending", None), self.self.get("contact")
        if pending and contact:  # a mind from before 0.21.2 kept one for all chats: it was the last contact's
            self.self["waiting"].setdefault(_chat(contact["app"], contact["session"]), pending)
        self.senses = Interoception(self.body, self.body.temperament.seed)
        self.rng = random.Random(self.body.temperament.seed ^ time.time_ns())

    def active(self) -> bool:
        return bool(self.brain.config.values().get("mind"))

    # ============== Living ==============

    def start(self) -> None:
        with self._lock:
            self._live_until(time.time())
            try:
                self._bring_up_to_date()
            except Exception:
                logger.exception("Could not set right what an older mind kept")
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
        with self._lock:
            self.memory.put("body", self.body.to_dict())
            self.memory.put("values", self.values.to_dict())
            self.memory.put("concepts", self.concepts.named)
            self.memory.put("self", self.self)

    def present(self, now: float) -> bool:
        return now - self.last_active < PRESENT_FOR

    def presence(self, app: str, idle: Optional[float]) -> None:
        """An app asked how she is: it is there to hear her; ``idle``: seconds since the user last touched
        the computer."""
        now = time.time()
        with self._lock:
            self.apps_seen[app] = now
            if idle is not None and idle >= 0:
                self.last_active = max(self.last_active, now - idle)

    def _live(self) -> None:
        last_bid = last_save = time.time()
        while not self._stop.wait(TICK):
            try:
                now = time.time()
                if not self.active():
                    continue
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
        if gap > SLEPT_IF_OFF and not body.asleep:  # she was away (the brain off) through a night: she slept
            body.fall_asleep()
            body.advance(now)
            body.wake()
            self.self["consolidate"] = True
        else:
            body.advance(now, present=gap < CAUGHT_UP_AFTER and self.present(now))
        if gap > CAUGHT_UP_AFTER:
            self.senses = Interoception(body, body.temperament.seed)
        else:
            self.senses.follow(body, gap)

    def _sting(self, now: float) -> None:
        """She reached out and heard nothing back."""
        urge, contact = self.self.get("urge"), self.self.get("contact")
        if urge and not urge.get("stung") and now - urge["at"] > STING_AFTER and \
                (not contact or contact["at"] < urge["at"]):
            sensitivity = self.body.temperament.sensitivity
            self.body.apply({"reward": -0.25 * sensitivity, "cortisol": 0.04 * sensitivity})
            urge["stung"] = True

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
                if now - fired.get("consolidate", 0.0) < REFRACTORY["thought"] or self.brain.provider_problem():
                    return
                fired["consolidate"] = now
                kind, about = "consolidate", None
            elif body.asleep:
                if body.slept_out(now):  # about eight hours from a full day, ending as her morning comes
                    body.wake()
                return
            else:
                kind, about = self._winner(now)
                if kind is None:
                    return
                if kind == "sleep":
                    body.fall_asleep()
                    self.self["consolidate"] = True
                    return
                if self.brain.provider_problem():  # she cannot think in words now: the moment passes
                    return
        self._thinking = True
        work = self._consolidate if kind == "consolidate" else lambda: self._think(kind, about)
        threading.Thread(target=self._thought, args=(work,), name="mind-thought", daemon=True).start()

    def _drives(self, now: float):
        """What wants her attention: ``bids()`` (each kind's pull from her levels now, None where it has
        nothing to pull at; without the noise), the threshold a thought must reach, and what ruminating and
        resuming would be about."""
        body, t = self.body, self.body.temperament
        contact, present = self.self.get("contact"), self.present(now)
        reachable = bool(contact) and self._alive(contact["app"], now) and \
            not self.brain.session_busy(contact["app"], contact["session"])
        urge = self.self.get("urge")
        waiting = bool(urge) and (not contact or contact["at"] < urge["at"])  # she reached out and nobody answered
        # the most charged of what hurt (the 8 most charged moments first, then what hurt among them, missed
        # every hurt of a busy day: the user's brain never ruminated, 2026-11-17)
        sore = next((e for e in self.memory.since(now - 2 * DAY, kinds=("exchange", "thought"))
                     if e["valence"] < -0.3 and e["charge"] > 0.5), None)
        concern = self.self["concerns"][0] if self.self["concerns"] else None
        night, evening = body.night(now), body.evening(now)
        # being talked to keeps her up; the user merely at the computer does not (they were there 08:00 to past
        # one, and she never slept: the user's brain, 2026-11-16)
        talking = bool(contact) and now - contact["at"] < TALKING
        resumable = bool(concern) and self._alive(concern["app"], now)
        working = self.brain.runs.busy()  # her cortex is on a task: a mind at work does not wander

        def bids() -> Dict[str, Optional[float]]:  # read from the levels each call (Body.influence nudges them)
            x = body.levels
            return {
                "sleep": 1.6 * max(0.0, x["adenosine"] - 0.55) + 0.6 * night + 0.4 * (1 - x["energy"])
                - 0.5 * evening - (0.7 if talking else 0.0) if x["adenosine"] > DOZES_OFF else None,
                "reach_out": 1.5 * body.deficit("social") * x["bond"] * (0.5 + x["oxytocin"]) * t.sociability
                * (1.0 if present else 0.3) if reachable and not waiting else None,
                # at rest her mind wanders by itself, tired or not (needing a need unmet first, she had no thought
                # of her own in a whole day in the user's brain, 2026-11-16); boredom pulls harder, as far as her
                # drive goes
                "wonder": RESTING + 1.1 * body.deficit("novelty") * t.curiosity * (0.4 + x["dopamine"])
                if not working else None,
                "ruminate": 1.4 * max(0.0, x["cortisol"] - 0.3) + 0.7 * x["grievance"] if sore else None,
                "resume": 0.9 * x["energy"] * (0.4 + x["dopamine"]) * (0.5 + x["bond"]) - 0.6 * body.fatigue()
                if resumable else None,
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
        scored = [(value + self.rng.gauss(0.0, 0.1 * volatility), kind) for kind, value in bids().items()
                  if value is not None and now - fired.get(kind, 0.0) >= REFRACTORY[kind]]
        if not scored:
            return None, None
        value, kind = max(scored)
        if kind == "sleep":
            if value < 0.7:
                return None, None
            fired["sleep"] = now
            return kind, None
        if value < threshold[kind] or now - fired.get("thought", 0.0) < REFRACTORY["thought"]:
            return None, None
        fired[kind] = fired["thought"] = now
        return kind, {"ruminate": sore, "resume": concern}.get(kind)

    def _thought(self, work) -> None:
        try:
            work()
        except Exception:
            logger.warning("A thought of hers came to nothing", exc_info=True)
        finally:
            self._thinking = False

    # ============== Asking the model ==============

    def _ask(self, system: str, user: str, read=prompts.parse):
        """One call of her light model, thinking off (her quick, wordless parts; the user's thinking setting
        made a reply of a few hundred tokens take 12-28 s): what ``read`` makes of its answer, and the usage.
        A provider that refuses thinking off is asked with the user's own setting from then on."""
        model = self.brain.config.values()["light_model"]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            message, usage = self.brain.provider(model, thinking="none" if self._quick else None).complete(messages)
        except requests.HTTPError as exc:
            if not self._quick or getattr(exc.response, "status_code", None) != 400:
                raise
            self._quick = False
            message, usage = self.brain.provider(model).complete(messages)
        return read(message.get("content") or ""), usage or {}

    def _persona(self, app: str, session: str) -> str:
        return self.brain.profile(app, session)["persona"]

    def _who(self, persona: str) -> str:
        story = self.self["story"]
        return f"Who they are:\n{persona[:6000]}" + (f"\n\nWho they have become:\n{story}" if story else "")

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
        body as she takes it. The note for her (None: no mind, or not a turn)."""
        if not self.active() or run["kind"] != "turn":
            return None
        now = time.time()
        with self._lock:
            self._live_until(now)
            body, x = self.body, self.body.levels
            if body.asleep:
                body.wake(startled=x["adenosine"] > 0.3)
            if run["options"].get("occurrence") or not (said or "").strip():
                felt = feel(body, self.senses, now)
                self._told(run, felt)
                return prompts.inner(felt.words(self.concepts.recognize(felt.noticed())))
            said = said[:SAID_CHARS]
            contact, urge = self.self.get("contact"), self.self.get("urge")
            away = now - contact["at"] if contact else None
            # company itself, a little (what the message does to it the model reads): more after a long time apart
            company = 0.1 + (0.15 if away is None or away > 6 * HOUR else 0.0)
            answered = bool(urge and (not contact or contact["at"] < urge["at"]))
            if answered:  # they answered her
                body.apply({"reward": 0.1 + 0.3 * x["bond"]})
                self.self["urge"] = None
            timing, apart = self._timing(away)
            body.learn_rhythm(body.hour(now), away or 0.0)
            came = self._arrives(run, said, pictures, now)
            felt, feelings, memories, novelty = came["felt"], came["feelings"], came["memories"], came["novelty"]
            self._told(run, felt)
            # her time alone is hers when they are back: what she thought since they last wrote, the newest two
            thoughts = [t["thought"][:THOUGHT_CHARS] for t in self.self["thoughts"]
                        if contact and t["at"] > contact["at"]][:2]
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
        with self._lock:
            now = time.time()
            model = seen.effects()  # what the model foresees, before her own record has its say
            own, shares = self._forecast(seen, came["followed"], came["evidence"])
            seen.novelty = novelty
            chat = _chat(run["app"], run["session"])
            pending = self.self["waiting"].pop(chat, None)  # her last decision in this chat: now what followed is known
            learned = self._settle(pending, model, apart) if pending else None
            levels = dict(self.body.levels)
            met = self._met(seen, company, timing)
            named = prompts.word(answer.get("feeling"))
            hour = self.body.hour(now)

            def found(option):
                return features(option.act, seen.tags, seen.intent, hour, run["app"])
            choice = choose(options, seen, self.body, self.values, found, self.rng) if options else None
            # nothing to choose: she talks (or, asked for work her imagining gave no options for, does it)
            option = choice.option if choice else Option("do" if seen.intent == "request" else "talk", chance=0.8)
            threat = self._threat(seen, option)
            impact = core(self.body.levels)[0] - core(levels)[0]  # how the message felt to her, in her body
            feelings = self._name(named, levels, f"{said} {answer.get('happens') or ''}", now)
            foreseen = {name: round(change, 3) for name, change in seen.effects().items()}
            decision = {"act": option.act, "what": option.what, "chance": option.chance, "effort": option.effort,
                        "gated": bool(choice),  # she weighed options and leans one way (a request); a chat: no
                        "foreseen": foreseen, "novelty": round(novelty, 3),
                        "stakes": min(1.0, sum(abs(change) for change in foreseen.values()) / 2),
                        "features": found(option), "reasons": choice.reasons if choice else [],
                        "chances": choice.chances if choice else {}, "said": said[:300], "felt": round(impact, 3),
                        "at": now}
            # settled by the user's next message in this chat: what followed this one (after() adds how her turn went)
            self.self["waiting"][chat] = {"at": now, "act": option.act, "features": decision["features"],
                                          "model": model, "own": own, "episode": None, "measured": None}
            # the way this message went through her, step by step, for drawing her brain
            likeness = came["likeness"]
            path = {"said": said[:160], "happens": str(answer.get("happens") or "")[:120], "intent": seen.intent,
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
                    "threat": threat}
            self.self["decided"] = {**{key: decision[key] for key in ("act", "what", "gated", "reasons", "chances", "at")},
                                    "path": path, "outcome": None}
            if option.act == "later":
                self.self["concerns"].append({"what": option.what or said[:200], "app": run["app"],
                                              "session": run["session"], "at": now})
            self.self["contact"] = {"app": run["app"], "session": run["session"], "at": now}
            likes, dislikes = self.values.fond(subjects(seen.tags))
            felt_words = felt.words(feelings) + (f" Reading it, you feel {named}." if named else "") \
                + (f" You like {' and '.join(likes)}." if likes else "") \
                + (f" You don't like {' and '.join(dislikes)}." if dislikes else "")
            note = prompts.inner(felt_words, memories, option.act if choice else None, option.what,
                                 choice.reasons if choice else [], thoughts)
        self.brain.store.update_run_options(run["id"], lambda options_: {**options_, "mind": decision})
        return note

    def heard(self, run: dict, profile: dict, said: Optional[str], pictures: int = 0) -> Optional[str]:
        """The user wrote while she works on their turn (a steering message): it reaches her as any message
        does. She senses it, foresees what it does to her needs and her chemistry carries it; what she decided
        about the turn stands, and what follows that decision is told by the next turn. The note for her
        (None: no mind, not a turn, or no words). Before this a message sent mid-work reached her words and
        never her body: "stop, that's wrong, you idiot" left her as she was."""
        if not self.active() or run["kind"] != "turn" or not (said or "").strip():
            return None
        said = said[:SAID_CHARS]
        with self._lock:
            now = time.time()
            self._live_until(now)
            came = self._arrives(run, said, pictures, now)
        answer = self._foresee(run, profile, came, said, pictures, working=True)
        seen = Appraisal.read(answer.get("appraisal"))
        with self._lock:
            now = time.time()
            self._forecast(seen, came["followed"], came["evidence"])
            seen.novelty = came["novelty"]
            levels = dict(self.body.levels)
            self._met(seen, 0.05, 0.0)  # they are with her already: the contact itself is a little
            decided = run["options"].get("mind") or {}
            self._threat(seen, Option(decided.get("act", "do"), chance=decided.get("chance", 0.8)))
            named = prompts.word(answer.get("feeling"))
            feelings = self._name(named, levels, f"{said} {answer.get('happens') or ''}", now)
            self.self["contact"] = {"app": run["app"], "session": run["session"], "at": now}
            self.last_active = now
            felt = feel(self.body, self.senses, now)
            self._told(run, felt)
            self._working[run["id"]].setdefault("heard", []).append(said[:300])  # remembered with the turn (after)
            return prompts.inner(felt.words(feelings) + (f" Reading it, you feel {named}." if named else ""),
                                 came["memories"])

    def _arrives(self, run: dict, said: str, pictures: int, now: float) -> dict:
        """A message reaches her (under her lock): how like her memories it is and what followed the ones most
        like it, how she feels as it comes, and what it brings back."""
        likeness, followed, evidence = self.memory.known(said, before=now)
        self.last_active = now
        felt = feel(self.body, self.senses, now)
        # what comes back is what she does not have before her: this chat since it was last summed up is in
        # her context already (a hippocampus completes what is missing, it does not repeat what is held)
        summed = self.brain.store.last_compaction(run["app"], run["session"])
        memories = [line(e, now)[:THOUGHT_CHARS] for e in self.memory.recall(
            said, felt.valence, now, count=self._span(), before=now - 30,
            held=(run["app"], run["session"], summed["at"] if summed else 0.0))]
        return {"likeness": likeness, "followed": followed, "evidence": evidence,
                "novelty": 1.0 - likeness if likeness is not None else (0.5 if pictures else 0.0),
                "felt": felt, "feelings": self.concepts.recognize(felt.noticed(), said), "memories": memories}

    def _foresee(self, run: dict, profile: dict, came: dict, said: str, pictures: int, working: bool = False) -> dict:
        """Her quick, wordless reading of a message (the imagine call, thinking off): what it does to her
        needs, what it is about, her word for what she feels and, asked for work, what she could do. It is
        given the subjects she knows, to file this one under where it fits: a mind files what it meets under
        what it knows, and only what fits nothing makes something new (in the user's brain, 2026-11-16, all
        32 subjects had been met once, so she had come to like and dislike nothing; live, 12 messages on 4
        subjects made 10 subjects before and 5 with this). Her words for feelings are not shown to it: shown,
        she called everything by two or three of them (4 of 12 moments distinct, no new word, "wounded" at
        a wish for ramen); a feeling comes back by her body (``_name``). {} when the call fails: she goes
        with what comes."""
        recent = self._recent(run)
        # where they are, as the app's environment opens (live: without it, "gotta go to the store, wanna buy
        # something" read as being invited along, by someone who lives on a screen)
        place = (profile.get("environment") or "").strip().split("\n")[0][:400]
        with self._lock:
            known = self.values.subjects(KNOWN_SUBJECTS)
        asked =(f"{self._who(profile['persona'])}\n" + (f"\nWhere they are: {place}\n" if place else "")
                 + f"\nHow they feel right now: {came['felt'].words(came['feelings'])}\n"
                 + (f"What comes back to them: {'; '.join(came['memories'])}\n" if came["memories"] else "")
                 + (f"Subjects they know: {', '.join(known)}\n" if known else "")
                 + (f"\nThe conversation so far (newest last):\n{recent}\n" if recent else "")
                 + "\nThe new message, from the user" + (f" (with {pictures} pictures)" if pictures else "")
                 + (", sent while they are at work on what was asked" if working else "") + f":\n{said}")
        try:
            answer, usage = self._ask(prompts.IMAGINE, asked, prompts.imagined)
        except Exception:
            logger.warning("Her imagining failed; she goes with what comes", exc_info=True)
            return {}
        with self._lock:
            self.body.exert(usage.get("completion_tokens") or 0)
        return answer

    def _name(self, named: str, levels: Dict[str, float], situation: str, now: float) -> list:
        """She called what she feels ``named``: the word keeps what the message did to her body (a brain builds
        a feeling from the change it predicts; her sense of her body would lag behind it: live, "small" at a
        comparison was kept as pleasant) and the situation. ``levels``: her body before the message moved it.

        The feelings of hers that come back as she reads it (word, strength; without ``named``) are those the
        message moves her the way of; her note tells her cortex of them, and the strongest is counted as felt
        again, whatever she calls this moment: a feeling is the moments sorted under it (Barrett 2017), and
        it is her body that sorts them. Her cortex names each moment freshly (live, with eight words of her
        own, not one of twelve later moments was called by any of them; and shown her words, it called
        everything by two or three of them), so without this no feeling of hers was felt twice."""
        way = moved(levels, self.body.levels)
        back = self.concepts.recognize(way, situation)
        if named:
            self.concepts.add(named, way, situation, now)
        if back and back[0][0] != named:
            self.concepts.came_back(back[0][0], now)
        return [found for found in back if found[0] != named]

    def _told(self, run: dict, felt) -> None:
        """Her cortex has heard how her body is now, for this run: while it works, it hears only what is new."""
        done = self._working.setdefault(run["id"], {"tokens": 0, "calls": 0, "errors": 0, "told": {}})
        done["told"] = dict(felt.standing_out())

    def _timing(self, away: Optional[float]) -> Tuple[float, Optional[float]]:
        """How unexpected a message is in time, 0..1 (its gap from the last one against her usual gaps), and how
        much longer than usual they were apart (signed, in thirds of the log gap; None: nothing to go by)."""
        if away is None:
            return 0.0, None
        gap, usual = math.log(max(away, 1.0)), self.self.get("gap")
        self.self["gap"] = gap if usual is None else usual + LEARNS * (gap - usual)
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

    def _met(self, seen: Appraisal, contact: float, timing: float) -> dict:
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
        drawing."""
        body, t = self.body, self.body.temperament
        # what the message says of her moves her sense of being capable as much as what it says of company
        # moves company (a tenth before 0.24.1: "that was a stupid answer" felt -0.06 against a goodbye's -0.50,
        # and "why are you so dumb today", read as attention, felt +0.42 live)
        pushes = {"social": contact + 0.3 * seen.company, "competence": 0.3 * seen.capable,
                  "novelty": 0.3 * seen.novelty, "autonomy": 0.2 * seen.free * (t.autonomy if seen.free < 0 else 1.0)}
        gained = sum(value({name: pushes[need] / REACH for name, need in NEEDED.items()}, body).values())
        needs = body.apply(pushes)
        expected = self.self["expected"]
        error = gained - expected
        self.self["expected"] += 2 * LEARNS * error
        company, shared = max(0.0, seen.company), seen.theirs * body["bond"] * t.warmth
        # what it is about is worth what she has learned it is (a liked subject is a reward cue in itself)
        liked = self.values.predict(subjects(seen.tags)) if seen.tags else 0.0
        moved = body.apply({"reward": error + shared + 0.3 * liked,
                            "noradrenaline": 0.05 + 0.1 * seen.novelty + 0.05 * timing + 0.2 * abs(error),
                            "cortisol": 0.2 * max(0.0, -shared) * t.stress,
                            "oxytocin": 0.12 * company + 0.15 * abs(shared), "endorphin": 0.05 * company,
                            "bond": 0.003 * seen.company})  # a bond grows over weeks of messages, not in a day
        return {"pushes": {name: round(change, 3) for name, change in needs.items()}, "gained": round(gained, 3),
                "expected": round(expected, 3), "shared": round(shared, 3), "liked": round(liked, 3),
                "moved": {name: round(change, 3) for name, change in moved.items()}}

    def _threat(self, seen: Appraisal, option: Option) -> dict:
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
        moved = self.body.apply({"cortisol": 0.08 * loss * (1.0 - 0.7 * back / loss) * sensitivity,
                                 "grievance": 0.1 * max(0.0, lost["company"] + lost["capable"] - 0.5) * sensitivity})
        return {"lost": {name: round(amount, 3) for name, amount in lost.items()}, "back": round(back, 3),
                "moved": {name: round(change, 3) for name, change in moved.items()}}

    def _settle(self, pending: dict, then: Dict[str, float], apart: Optional[float] = None) -> Optional[dict]:
        """The user wrote again in that chat: what followed her last message there is known (``then``: what this
        one does to her needs, as the model reads it; how her turn went, measured; and ``apart``: how much
        longer than usual they were apart since, which is company measured: a long time away takes it, a quick
        answer gives a little). It is kept with that moment for her own record, each guide's error is updated
        against it, and it teaches her values whether her decision went better or worse than what usually
        follows. What she learned, for drawing (None: nothing to learn from)."""
        if "model" not in pending:  # kept by a mind from before 0.21
            return None
        measured = dict(pending.get("measured") or {})
        if apart is not None:
            measured["company"] = -math.tanh(apart) if apart > 0 else -0.3 * math.tanh(apart)
        followed = {name: (then[name] + measured[name]) / 2 if name in measured else then[name] for name in FORESEEN}
        trust = self.self["trust"]
        for name, real in followed.items():
            for guide, guessed in (("model", pending["model"]), ("own", pending.get("own"))):
                if guessed and name in guessed:
                    trust[guide][name] += LEARNS * ((guessed[name] - real) ** 2 - trust[guide][name])
        if pending.get("episode"):
            self.memory.follow(pending["episode"], {name: round(change, 3) for name, change in followed.items()})
        # values learn what went better or worse than usual (a prediction error), not how good things are: graded
        # absolutely, whatever she did was credited with how friendly the user is ("decline" learned +0.71 from
        # a kind chat in the user's brain, 2026-11-16)
        worth = sum(value(followed, self.body).values())
        felt = math.tanh(3.0 * (worth - self.self["usual"]))
        self.self["usual"] += LEARNS * (worth - self.self["usual"])
        self.values.learn(pending["features"], felt, self._rate())
        return {"act": pending["act"], "followed": {name: round(change, 3) for name, change in followed.items()},
                "measured": {name: round(change, 3) for name, change in measured.items()},
                "model": pending["model"], "own": pending.get("own"), "felt": round(felt, 3)}

    def _rate(self) -> float:
        return 0.05 + 0.25 * self.body.levels["acetylcholine"]

    def _recent(self, run: dict) -> str:
        lines = []
        for event in self.brain.store.events(run["app"], run["session"], types=("input", "end"))[-RECENT_LINES:]:
            if event["type"] == "input" and event.get("display"):
                lines.append(f"User: {event['display'][:300]}")
            elif event["type"] == "end" and event.get("reply"):
                lines.append(f"Them: {event['reply'][:300]}")
        return "\n".join(lines)

    def _did(self, run: dict, events: list, leaned: str) -> str:
        """What she did about a request, whatever she leaned toward: having changed something with her tools
        (beyond her memory and journal) she did it. shortcut: a "do" she talked her way out of is not told from
        a job that needed nothing changed; reading her reply would tell them apart."""
        used = {e["name"] for e in events if e["type"] == "tool" and e.get("status") == "ok"}
        if leaned in ("do", "part") or not used:
            return leaned
        tools = self.brain.toolset(self.brain.profile(run["app"], run["session"]), "turn").by_name
        changed = any(name in tools and not tools[name].readonly and tools[name].toolkit not in ("memory", "journal")
                      for name in used)
        return "do" if changed else leaned

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
            self.body.apply({"cortisol": 0.01 * stumbles, "noradrenaline": 0.03 * stumbles})
        done.update(tokens=max(tokens, done["tokens"]), calls=max(calls, done["calls"]), errors=max(errors, done["errors"]))
        return done

    def during(self, run: dict, events: list) -> None:
        """A run of hers is about to take its next step (``events``: the run's so far). Her body lives through
        her work as it goes, not once it is over; and in a turn, what has come to stand out in her body since
        her cortex last heard of it reaches it now, as a note at this step (interoception does not stop while
        she works). So a long job is felt while it can still change what she does, and her cortex is asked
        again how clearly it can think (``reflexive``). Before this the loop closed once a turn: she could
        work for hours and feel none of it until she had answered."""
        if not self.active() or run["kind"] in ("summary", "compact"):
            return
        tokens, calls, errors = self._work(events)
        if not calls:
            return  # nothing done yet: she has just been told how she is (before)
        with self._lock:
            now = time.time()
            self._live_until(now)
            done = self._lived(run["id"], tokens, calls, errors)
            if run["kind"] != "turn":
                return
            felt = feel(self.body, self.senses, now)
            told = done["told"]
            # new to her cortex: not heard of, turned the other way, or plainly more than when it heard
            fresh = [(name, far) for name, far in felt.standing_out(floor=0.7)
                     if far * told.get(name, 0.0) <= 0 or abs(far) - abs(told[name]) >= TOLD_AGAIN]
            if not fresh:
                return
            told.update(fresh)
            note = prompts.inner(felt.words(out=fresh))
        self.brain.note(run["app"], run["session"], note)

    def after(self, run: dict) -> None:
        """A run ended: what is left of its work tires her; in a turn, what she showed comes back into her body;
        a turn with the user's words moves her, teaches her and is remembered."""
        if not self.active() or run["kind"] in ("summary", "compact"):
            return
        events = self.brain.store.run_events(run["id"])
        _, calls, errors = self._work(events)
        denied = sum(1 for e in events if e["type"] == "approval" and e.get("decision") == "deny")
        steered = max(0, sum(1 for e in events if e["type"] == "input") - 1)
        decision = run["options"].get("mind")
        # what she did, which her cortex settled on as it went: that is what she learns from and remembers
        leaned = decision["act"] if decision else None
        act = self._did(run, events, leaned) if decision and decision.get("gated") else leaned
        with self._lock:
            now = time.time()
            self._live_until(now)
            body = self.body
            # a run that is not the loop's (a super agent's) is counted here whole, from what it used
            self._lived(run["id"], (run.get("usage") or {}).get("completion_tokens") or 0, calls, errors)
            heard = self._working.pop(run["id"]).get("heard") or []  # what the user said while she worked
            expressed = self._express(run) if run["kind"] == "turn" else None
            if not decision:
                return
            # what it was about takes on how it felt: in her body as the message came, and in what she showed
            # as she answered (her cortex's own take on it); this is where likes and dislikes come from, so
            # every moment teaches them, a chat as much as a job (before 0.24.1 only what followed her answer did)
            about = [f for f in decision["features"] if f.startswith("tag:")]
            if about:
                liking = max(-1.0, min(1.0, 2.5 * decision.get("felt", 0.0)))
                if expressed:  # the mood she showed itself (``expressed["valence"]`` is its gap from her body)
                    liking = 0.5 * liking + 0.5 * MOOD_PLACES[expressed["mood"]][0]
                self.values.learn(about, liking, self._rate())
            ok, stopped = run["status"] == "completed", run["status"] == "cancelled"
            failed = errors / calls if calls else 0.0
            surprise = 0.0
            # how it went for her needs, measured: what follows the user's message (_settle) beside their reply
            measured = {"free": max(-1.0, (0.3 if act in ("later", "decline") else 0.0) - 0.4 * min(1, steered)
                                    - 0.5 * stopped - 0.3 * min(1, denied))}
            if act in ("do", "part"):
                success = (1.0 if ok else 0.0) * (1.0 - 0.6 * failed) - 0.3 * min(1, denied)
                surprise = success - decision["chance"]
                body.apply({"reward": 0.45 * surprise, "competence": 0.15 * surprise + (0.05 if ok else 0.0),
                            "cortisol": 0.06 * failed})
                felt_outcome = surprise - 0.3 * failed
                measured["capable"] = max(-1.0, 1.2 * success - 0.4 - 0.3 * stopped)
            elif act in ("later", "decline"):  # spared the work: relief, and the freedom of her own choice
                body.apply({"autonomy": 0.12})
                felt_outcome = 0.1
            else:  # she talked: how that went, the user's next message tells (_settle)
                felt_outcome = 0.0
            if stopped:
                body.apply({"reward": -0.2, "autonomy": -0.1, "cortisol": 0.05})
                felt_outcome -= 0.4
            if steered:
                body.apply({"autonomy": -0.05 * steered})
            # the act taken is what is learned (an actor learns from the action it took), not the leaning
            learned = [f"act:{act}" + item[len(f"act:{leaned}"):] if item.startswith(f"act:{leaned}") else item
                       for item in decision["features"]]
            self.values.learn(learned, max(-1.0, min(1.0, felt_outcome)), self._rate())
            if act != leaned and leaned == "later":  # done after all: nothing left to come back to
                self.self["concerns"] = [c for c in self.self["concerns"] if c.get("at") != decision["at"]]
            felt = feel(body, self.senses, now)
            reply = ((run.get("result") or {}).get("reply") or "")[:300]
            did = f" I {VERBS[act]}" + (f" ({decision['what']})" if decision["what"] else "") \
                + (f", though I had leaned toward {LEANINGS[leaned]}" if act != leaned else "") \
                if decision.get("gated", True) else ""  # a chat is what was said, nothing done or put off
            text = (f"The user said: {decision['said']}{did}"
                    + (f". As I worked they said: {'; '.join(heard)}" if heard else "")
                    + (f". I said: {reply}" if reply else "") + (". They stopped me" if stopped else "")
                    + (f". {errors} of my {calls} tool calls failed" if errors else "") + ".")
            text = _said(text)
            valence = max(-1.0, min(1.0, 0.5 * felt.valence + 0.5 * felt_outcome))
            episode = self.memory.add("exchange", text, valence, felt.arousal,
                                      describe_salience(abs(surprise), felt.arousal, decision.get("stakes", 0.5)),
                                      app=run["app"], session=run["session"], at=now)
            pending = self.self["waiting"].get(_chat(run["app"], run["session"]))
            if pending and pending.get("at") == decision["at"]:  # the user has not written again in this chat yet
                pending.update(episode=episode, measured=measured, act=act, features=learned)
            decided = self.self.get("decided")
            if decided and decided.get("at") == decision["at"]:
                decided["outcome"] = {"did": act, "status": run["status"], "calls": calls, "errors": errors,
                                      "denied": denied,
                                      "steered": steered, "surprise": round(surprise, 3), "expressed": expressed,
                                      "measured": {name: round(change, 3) for name, change in measured.items()}}

    def _express(self, run: dict) -> Optional[dict]:
        """What she showed as she answered comes back into her body. The mood of the expression she chose (one
        the app declares, picked by her cortex in the full light of the conversation) is the feeling her
        cortex made of the moment, and a feeling, once made, is also a command to the body (interoceptive
        inference: Barrett & Simmons 2015; Seth 2013): her chemistry moves toward it, by how far it is from
        what her body felt. Without this her words and her body were two beings: in the user's brain,
        2026-11-16, she answered "you big idiot" looking mad while her body logged it as pleasant company.
        What she showed and what it moved, for drawing (None: no expression she knows a place for)."""
        signals = (run.get("result") or {}).get("signals") or {}
        mood = next((value.split("/")[-1] for value in signals.values()
                     if isinstance(value, str) and value.split("/")[-1] in MOOD_PLACES), None)
        if mood is None:
            return None
        valence, arousal = core(self.body.levels)
        apart, stirred = MOOD_PLACES[mood][0] - valence, MOOD_PLACES[mood][1] - arousal
        moved = self.body.apply({"cortisol": 0.05 * max(0.0, -apart), "endorphin": 0.05 * max(0.0, apart),
                                 "noradrenaline": 0.1 * stirred})
        return {"mood": mood, "valence": round(apart, 3), "arousal": round(stirred, 3),
                "moved": {name: round(change, 3) for name, change in moved.items()}}

    def _clear(self) -> float:
        """How clearly her cortex can think now, 0..1: worn down past the middle of her fatigue, and by stress
        she cannot shake (both take the prefrontal cortex offline: Arnsten 2009)."""
        return max(0.0, 1.0 - 2.5 * max(0.0, self.body.fatigue() - 0.4) - 1.5 * max(0.0, self.body["cortisol"] - 0.5))

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
        if not self.active() or not self.reflexes or least or (run and run["kind"] in ("summary", "compact")):
            return False
        if run and run["options"].get("reflex"):
            return True
        with self._lock:
            self._live_until(time.time())
            self._reflex = self._clear() < (CLEAR_AGAIN if self._reflex else REFLEX)
            found = self._reflex
        if found and run:
            self.brain.store.update_run_options(run["id"], lambda options: {**options, "reflex": True})
        return found

    # ============== Between messages ==============

    def _think(self, kind: str, about: Optional[dict]) -> None:
        with self._lock:
            now = time.time()
            contact = self.self.get("contact") or (about if kind == "resume" else None)
            felt = feel(self.body, self.senses, now)
            subject = (about or {}).get("text") or (about or {}).get("what") or ""
            wandering = kind == "wonder" and self.body.deficit("novelty") < 0.3  # at rest, not bored
            on_mind = ON_MIND["wander" if wandering else kind].format(
                about=subject, since=f" You last talked {_ago(now - contact['at'])}." if contact else "")
            if kind == "wonder":  # her stream goes on from her last thought, and two memories come up unbidden
                last = self.self["thoughts"][0]["thought"][:THOUGHT_CHARS] if self.self["thoughts"] else ""
                on_mind += f' Your last thought was: "{last}"' if last else ""
                came = self.memory.replay(2)
                cue = " ".join(e["text"] for e in came)
            else:
                cue = subject or (self.memory.recent(1, kinds=("exchange",)) or [{"text": ""}])[0]["text"]
                came = self.memory.recall(cue, felt.valence, now, count=self._span())
            feelings = self.concepts.recognize(felt.noticed(), cue)
            memories = [line(e, now)[:THOUGHT_CHARS] for e in came]
            liked, disliked = (", ".join(_about(found)) for found in self.values.leanings())
        persona = self._persona(contact["app"], contact["session"]) if contact else ""
        known = self._something_known() if kind == "wonder" else ""  # what she knows comes up as her mind wanders
        asked = (f"{self._who(persona)}\n\nIt is {time.strftime('%A %H:%M')}. How they feel: {felt.words(feelings)}\n"
                 f"On their mind: {on_mind}\n" + (f"What comes back to them: {'; '.join(memories)}\n" if memories else "")
                 + (f"Something they know comes to mind: {known}\n" if known else "")
                 + (f"What they've come to like: {liked}.\n" if liked else "")
                 + (f"What they've come to dislike: {disliked}.\n" if disliked else ""))
        answer, usage = self._ask(prompts.THINK, asked)
        thought = " ".join(str(answer.get("thought") or "").split())[:600]
        if not thought or self._stop.is_set():
            return
        want = str(answer.get("want") or "nothing").lower()
        urge, task = None, None
        with self._lock:
            now = time.time()
            body = self.body
            body.exert(usage.get("completion_tokens") or 0)
            if kind == "wonder":
                body.apply({"novelty": 0.15, "dopamine": 0.03})
            elif kind == "ruminate":  # going over it stirs it up again, and wears it down a little
                body.apply({"cortisol": 0.03})
                self.memory.soften([about["id"]], 0.1)
            felt = feel(body, self.senses, now)
            named = prompts.word(answer.get("feeling"))
            if named:
                self.concepts.add(named, felt.noticed(), thought, now)
            self.memory.add("thought", thought, felt.valence, felt.arousal, 0.25 + (0.2 if kind == "ruminate" else 0.0),
                            at=now)
            self.self["thoughts"] = ([{"at": now, "kind": kind, "thought": thought, "want": want}]
                                     + self.self["thoughts"])[:SHOWN_THOUGHTS]
            say = " ".join(str(answer.get("say") or "").split())[:600] or thought
            last, known = self.self.get("urge"), self.self.get("contact")
            unanswered = bool(last) and (not known or known["at"] < last["at"])  # one urge at a time, never a stream
            # while they are talking, what she thought comes up in her next answer (her note carries it), not as
            # a message of its own in the middle of the conversation
            talking = bool(known) and now - known["at"] < TALKING
            if (unanswered or talking) and want in ("tell", "ask", "do"):
                pass  # the thought stays hers
            elif want in ("tell", "ask") and contact and self._alive(contact["app"], now):
                urge = {"at": now, "want": want, "app": contact["app"], "session": contact["session"],
                        "text": URGE[want].format(thought=thought, say=say)}
            elif want == "do" and kind == "resume" and self._alive(about["app"], now):
                self.self["concerns"] = [c for c in self.self["concerns"] if c != about]
                urge = {"at": now, "want": "do", "app": about["app"], "session": about["session"],
                        "text": URGE["do"].format(say=about["what"])}
            elif want == "look_up" and contact and body.levels["energy"] > 0.5 and answer.get("look_up"):
                task = (contact["app"], contact["session"], str(answer["look_up"])[:300])
            if urge:
                self.self["urge"] = urge
        if urge:
            self.brain.notify(urge["app"], urge["session"], "mind.urge",
                              {"want": urge["want"], "text": urge["text"], "thought": thought,
                               "session": urge["session"]})
        if task:
            app, session, query = task
            self.brain.runs.start_task(app, session, f"Out of your own curiosity, look this up for yourself: {query}. "
                                       "Keep it short, and keep what you find worth remembering.",
                                       toolkits=["web", "memory"], quiet=True)  # hers: nobody is told it ended

    def _consolidate(self) -> None:
        """Sleep goes over the day: insights, a dream, her story rewritten; the day's charge softens and faint
        memories go."""
        with self._lock:
            now = time.time()
            moments = self.memory.since(self.self.get("slept") or 0.0, kinds=("exchange", "thought", "event"), count=12)
            contact = self.self.get("contact")
            likes, dislikes = self.values.leanings()
        if moments:
            persona = self._persona(contact["app"], contact["session"]) if contact else ""
            listed = "\n".join(f"{index + 1}. {line(m, now)} (it felt {_tone(m['valence'])})"
                               for index, m in enumerate(moments))
            liked, disliked = ", ".join(_about(likes)) or "nothing yet", ", ".join(_about(dislikes)) or "nothing yet"
            from ..context import render_memory  # what she knows and keeps: her story is of all of her life
            kept = render_memory(self.brain.store.memory_entries(), contact["app"] if contact else "")
            asked = (f"Who they are:\n{persona[:6000]}\n\n"
                     + (f"What they know and keep (their lasting memory):\n{kept}\n\n" if kept else "")
                     + "The story they tell about themselves:\n"
                     f"{self.self['story'] or '(none yet: they are new to this life)'}\n\n"
                     f"What they've come to like: {liked}. What they've come to dislike: {disliked}.\n\n"
                     f"The moments:\n{listed}")
            answer, _ = self._ask(prompts.SLEEP, asked)
        else:
            answer = {}
        with self._lock:
            now = time.time()
            felt = feel(self.body, self.senses, now)
            for insight in (answer.get("insights") or [])[:3]:
                text = " ".join(str(insight).split())[:400]
                if text:
                    self.memory.add("insight", text, felt.valence, 0.3, 0.6, at=now)
            dream = " ".join(str(answer.get("dream") or "").split())[:800]
            if dream:
                self.memory.add("dream", dream, felt.valence, 0.5, 0.35, at=now)
            story = " ".join(str(answer.get("story") or "").split())[:2400]
            if story:
                self.self["story"] = story
            self.memory.soften([m["id"] for m in moments])
            self.values.fade(0.05)
            self.memory.forget_faint(now)
            self.self["slept"], self.self["consolidate"] = now, False
        self.save()
        try:  # and what she keeps is fitted in with what changed in it today
            self.tidy()
        except Exception:
            logger.exception("Could not go over her lasting memory")

    def tidy(self, since: Optional[float] = None) -> Optional[list]:
        """She goes over her lasting memory (lasting.tidy): what changed since she last did (``since``: from
        then; 0: all of it), and remembers doing it. None: she could not now (it is asked again)."""
        from .. import lasting
        with self._lock:
            start = self.self.get("tidied", 0.0) if since is None else since
            contact = self.self.get("contact")
        now = time.time()
        done = lasting.tidy(self.brain, start, contact["app"] if contact else None)
        if done is None:
            return None
        with self._lock:
            self.self["tidied"] = now
            if done:
                self.memory.add("event", "I went over what I keep and set it right: " + "; ".join(done),
                                0.1, 0.2, GIST, at=now)
        self.save()
        return done

    def forget(self, app: str, session: str) -> None:
        """A conversation the user deleted: her memories of it, what she put off in it and urges to it go."""
        with self._lock:
            self.memory.forget_session(app, session)
            self.self["waiting"].pop(_chat(app, session), None)
            self.self["concerns"] = [c for c in self.self["concerns"] if (c["app"], c["session"]) != (app, session)]
            for key in ("contact", "urge"):
                found = self.self.get(key)
                if found and (found["app"], found["session"]) == (app, session):
                    self.self[key] = {**found, "session": "main"} if key == "contact" else None

    # ============== For apps and the panel ==============

    def _bring_up_to_date(self) -> None:
        """What she kept under an older logic, set right once. Until 0.23 a chat was decided like a request,
        one of a few scripted acts picked: her memories of those chats say "I talked it over (keep it light,
        joke about the dead watcher)", her values learned "doing it" and "saying no" to a hello, and a chat
        could leave a concern or wait to teach that. A chat is what was said (0.23): those clauses go from
        her memories, what only those acts taught goes from her values, and what waits on them is let go."""
        if self.self.get("logic", 0) >= LOGIC:
            return
        stale, kept = [], set()
        for run in self.brain.store.runs(kind="turn", limit=-1):
            decision = (run.get("options") or {}).get("mind")
            if not decision:
                continue
            if "gated" in decision or "intent:request" in decision.get("features", []):
                kept.update(decision.get("features", []))  # decided as she decides now
            else:
                stale.append((run, decision))
        for run, decision in stale:
            act, what = decision.get("act"), decision.get("what") or ""
            if act not in VERBS:
                continue
            said = " ".join(str(decision.get("said") or "").split())
            did = " ".join(f" I {VERBS[act]}{f' ({what})' if what else ''}".split())
            for episode in self.memory.lived(run["app"], run["session"], decision["at"], decision["at"] + DAY):
                if episode["text"].startswith(f"The user said: {said} {did}"):
                    self.memory.rewrite(episode["id"], _said(f"The user said: {said}"
                                                             + episode["text"][len(f"The user said: {said} {did}"):]))
                    break
        for episode in self.memory.recent(-1, kinds=("exchange",)):  # each part ending once (_said)
            self.memory.rewrite(episode["id"], _said(episode["text"]))
        for feature in {f for _, decision in stale if decision.get("act") != "talk"
                        for f in decision.get("features", []) if f.startswith(f"act:{decision.get('act')}|")} - kept:
            self.values.weights.pop(feature, None)
            self.values.uses.pop(feature, None)
        times = {decision["at"] for _, decision in stale if decision.get("act") != "talk"}
        self.self["concerns"] = [c for c in self.self["concerns"] if c.get("at") not in times]
        self.self["waiting"] = {chat: kept_ for chat, kept_ in self.self["waiting"].items() if kept_.get("at") not in times}
        self.self["logic"] = LOGIC
        self.save()

    def remember(self, app: str, session: str, note: str, start: float, end: float) -> None:
        """A stretch of a conversation in her own words (her journal note), kept as an event of her life:
        with the feeling of what she lived in it, where her mind was there for it, else none left (an old
        memory keeps what happened, and its feeling fades). The gist outlives the details: they fade and go,
        it is kept (salience at least GIST; Memory.forget_faint takes only what mattered less than 0.3)."""
        if not self.active() or not note:
            return
        with self._lock:
            lived = self.memory.lived(app, session, start, end + MINUTE)  # her last answer is kept just after it
            valence = sum(e["valence"] for e in lived) / len(lived) if lived else 0.0
            arousal = sum(e["arousal"] for e in lived) / len(lived) if lived else 0.2
            self.memory.add("event", note, valence, arousal, max([GIST] + [e["salience"] for e in lived]),
                            app=app, session=session, at=end)

    def look_back(self, query: str, count: int = 8) -> list:
        """What comes back as she searches her memory for ``query`` (journal_search): her own memories of what
        happened, of any time, that have its words; searching for them makes them stronger, as recalling does."""
        if not self.active() or not query.strip():
            return []
        with self._lock:
            now = time.time()
            found = self.memory.recall(query, core(self.body.levels)[0], now, count=count)
        return [line(e, now) for e in found if e["relevance"]]

    def _something_known(self) -> str:
        """Something she knows (her lasting memory) that comes to mind as her mind wanders, what mattered most
        recently the most readily: a wandering mind goes to what one is busy with (Klinger 2009)."""
        entries = self.brain.store.memory_entries()
        if not entries:
            return ""
        now = time.time()
        entry = self.rng.choices(entries, [1.0 / (1.0 + max(0.0, now - (e["updated"] or 0.0)) / DAY) for e in entries])[0]
        value = " ".join((entry["value"] if isinstance(entry["value"], str)
                          else json.dumps(entry["value"], ensure_ascii=False)).split()).strip('"')
        gist = re.split(r"(?<=[.!?])\s", value, maxsplit=1)[0][:GIST_CHARS]  # what comes back is its gist
        return f"{entry['key'].replace('_', ' ')}: {gist}"

    def section(self) -> str:
        """Her inner life in the system prompt (empty when the mind is off)."""
        if not self.active():
            return ""
        with self._lock:
            story = self.self["story"]
        return prompts.INNER_LIFE + (f"\n\n## WHO YOU HAVE BECOME\n{story}" if story else "")

    def state(self, app: Optional[str] = None, idle: Optional[float] = None, brief: bool = False) -> dict:
        """How she is now: her face for ``app`` (from its declared expressions), what she feels, her levels,
        thoughts, concerns and story; for drawing her brain, every feeling she has named (``feelings``), her
        body's channels as she senses them (``sensed``: how far from usual, in units of a lot), what wants her
        attention (``attention``), her last decision (``decided``) and the connections her dynamics make
        now (``wiring``: [level, what it drives, weight]). ``idle``: seconds since the user last touched
        the computer. ``brief``: only what a face needs (``on``, ``asleep``, ``present``, ``felt``, ``feeling``: a
        few words for it, ``valence``, ``arousal``, ``face``): an app's frequent look, kept small as she grows."""
        if app:
            self.presence(app, idle)
        if not self.active():
            return {"on": False, "face": None}
        options = {}
        if app:
            signals = ((self.brain.store.app(app) or {}).get("declaration") or {}).get("signals") or {}
            options = next((s["options"] for s in signals.values() if isinstance(s, dict)
                            and isinstance(s.get("options"), dict)), {})
        now = time.time()
        with self._lock:
            self._live_until(now)
            body = self.body
            felt = feel(body, self.senses, now)
            felt_now = self.concepts.recognize(felt.noticed())
            seen = {"on": True, "asleep": body.asleep, "present": self.present(now), "felt": felt.words(felt_now),
                    "feeling": ", ".join(word for word, _ in felt_now[:2]) or ", ".join(felt.tone()),
                    "valence": round(felt.valence, 3), "arousal": round(felt.arousal, 3),
                    "face": face(felt, options, body.asleep)}
            if brief:
                return seen
            feelings = self.concepts.shown(felt.noticed())
            likes, dislikes = self.values.leanings()
            bids, threshold, _, _ = self._drives(now)
            pulls, fired, night = bids(), self.self["fired"], body.night(now)

            def tone() -> Dict[str, float]:  # from her levels themselves: what they do to her core affect
                valence, arousal = core(body.levels)
                return {"valence": valence, "arousal": arousal}
            wiring = (body.influence(body.targets) + body.influence(tone, 0.1)
                      + body.influence(lambda: {kind: value for kind, value in bids().items() if value is not None}, 0.1))
            return {
                **seen,
                # every feeling she has named (strength now, how often, place, the channels that set it apart)
                # and her body as she senses it (how far each channel is from usual, whatever she has got used to)
                "feelings": feelings,
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
                "levels": {name: round(value, 3) for name, value in body.levels.items()},
                # where each chemical is heading, how fast (seconds to go two thirds of the way), the needs'
                # set points, how responsive the habituating receptors are, and what she expects of the user
                "targets": {name: round(value, 3) for name, value in body.targets().items()},
                "paces": {name: level.tau for name, level in CHEMICALS.items()},
                "set_points": dict(SET_POINTS), "receptors": {name: round(value, 3) for name, value in body.sensitivity.items()},
                "expected": round(self.self["expected"], 3),
                # how clearly her cortex can think now, and "reflex" when she answers without thinking it through
                "clear": round(self._clear(), 3), "depth": "reflex" if self.reflexive() else None,
                "trust": {guide: {name: round(error, 3) for name, error in errors.items()}
                          for guide, errors in self.self["trust"].items()},
                "fatigue": round(body.fatigue(), 3), "temperament": body.temperament.to_dict(),
                "thoughts": list(self.self["thoughts"]), "concerns": list(self.self["concerns"]),
                "story": self.self["story"], "likes": _about(likes), "dislikes": _about(dislikes),
                "memories": self.memory.count(),
            }
