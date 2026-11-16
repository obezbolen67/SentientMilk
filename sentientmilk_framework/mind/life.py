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
Her decision and her felt sense go with the message as a note only she reads; a refusal or a delay keeps her
work tools from her for that turn (``barred``). When the turn ends (``after``) its outcome moves her body,
teaches her values and becomes a memory. The user's next message settles what followed hers (``_settle``):
it is kept with that memory, it shows which guide to trust, and it teaches her values about her decision.

Between messages (``_live``, every few seconds) her body lives on. Every ``BIDS_EVERY`` seconds what wants her
attention competes, with noise, against a threshold that rises as she tires: missing the user (reach_out),
boredom (wonder), something that nags her (ruminate), what she put off (resume) and sleep. A winner is a
thought (a model call). A thought may become something she wants to tell or ask the user (the app hears
``mind.urge`` and starts a turn), doing what she put off, or looking something up herself (a task).
Asleep, she goes over the day once (``_consolidate``): insights, a dream, her story rewritten, the day's
charge softened, faint memories forgotten.
"""

import logging
import math
import random
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import requests

from . import prompts
from .body import CHEMICALS, DAY, HOUR, MINUTE, NEEDS, SET_POINTS, Body, Temperament
from .feel import Concepts, Interoception, core, face, feel
from .memory import Memory, describe_salience, line
from .values import Values, features
from .will import FORESEEN, NEEDED, REACH, Appraisal, Option, choose, value

logger = logging.getLogger(__name__)

TICK = 5.0
BIDS_EVERY = 30.0
SAVE_EVERY = 60.0
PRESENT_FOR = 5 * MINUTE  # the user counts as there this long after they last touched the computer
APP_ALIVE = 30.0  # an app that asked how she is this recently is there to hear her
SLEPT_IF_OFF = 6 * HOUR  # a time away this long she has slept through
CAUGHT_UP_AFTER = 10 * MINUTE  # a gap longer than this (the mind was off, the machine slept) is caught up on
# after a bid wins, it rests this long; a refractory period, as a body has
REFRACTORY = {"reach_out": 45 * MINUTE, "wonder": 40 * MINUTE, "ruminate": 30 * MINUTE, "resume": HOUR,
              "sleep": 20 * MINUTE, "thought": 10 * MINUTE}
# sleep pressure she needs to fall asleep: slept out (she wakes below 0.03 at night, 0.35 by day), she stays
# up, instead of dozing off again and going over the same day every half hour
DOZES_OFF = 0.4
STING_AFTER = 30 * MINUTE  # reaching out and hearing nothing back this long stings
CONCERN_DAYS = 3.0  # what she put off and never came back to fades from her mind
SAID_CHARS = 1500
RECENT_LINES = 6
SHOWN_THOUGHTS = 12  # in the state apps and the panel show
WORK_PER_CALL = 600  # a tool call's effort, in tokens of her own words
FAMILIAR = 1.5  # summed likeness of past messages at which her own record weighs half of what it can
LEARNS = 0.1  # how fast her sense of each guide's error, and her expectation of the user, follow what happens
VERBS = {"do": "did it", "part": "did part of it", "later": "put it off", "decline": "said no",
         "talk": "talked it over"}
ON_MIND = {
    "reach_out": "You miss the user.{since}",
    "wonder": "You're bored. You want something new to think about.",
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
            body, x = self.body, self.body.levels
            fired = self.self["fired"]
            self.self["concerns"] = [c for c in self.self["concerns"] if now - c["at"] < CONCERN_DAYS * DAY]
            if self.self.get("consolidate"):
                if now - fired.get("consolidate", 0.0) < REFRACTORY["thought"] or self.brain.provider_problem():
                    return
                fired["consolidate"] = now
                kind, about = "consolidate", None
            elif body.asleep:
                if x["adenosine"] < 0.03 or (body.night(now) < 0.3 and x["adenosine"] < 0.35):  # ~7 h from a full day
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
        sore = next((e for e in self.memory.since(now - 2 * DAY, kinds=("exchange", "thought"), count=8)
                     if e["valence"] < -0.3 and e["charge"] > 0.5), None)
        concern = self.self["concerns"][0] if self.self["concerns"] else None
        night, resumable = body.night(now), bool(concern) and self._alive(concern["app"], now)

        def bids() -> Dict[str, Optional[float]]:  # read from the levels each call (Body.influence nudges them)
            x = body.levels
            return {
                "sleep": 1.6 * max(0.0, x["adenosine"] - 0.55) + 0.6 * night + 0.4 * (1 - x["energy"])
                - (0.7 if present else 0.0) if x["adenosine"] > DOZES_OFF else None,
                "reach_out": 1.5 * body.deficit("social") * x["bond"] * (0.5 + x["oxytocin"]) * t.sociability
                * (1.0 if present else 0.3) if reachable and not waiting else None,
                "wonder": 1.1 * body.deficit("novelty") * t.curiosity * x["energy"] * (0.4 + x["dopamine"]),
                "ruminate": 1.4 * max(0.0, x["cortisol"] - 0.3) + 0.7 * x["grievance"] if sore else None,
                "resume": 0.9 * x["energy"] * (0.4 + x["dopamine"]) * (0.5 + x["bond"]) - 0.6 * body.fatigue()
                if resumable else None,
            }
        x = body.levels
        threshold = 0.5 + 0.6 * body.fatigue() - 0.3 * max(0.0, x["noradrenaline"] - 0.35)
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
        if value < threshold or now - fired.get("thought", 0.0) < REFRACTORY["thought"]:
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
        """The user wrote (``said``): she senses it, recalls, foresees and chooses. The note for her (or None:
        no mind, or not a turn with the user's words)."""
        if not self.active() or run["kind"] != "turn" or run["options"].get("occurrence") or not (said or "").strip():
            return None
        said = said[:SAID_CHARS]
        now = time.time()
        with self._lock:
            self._live_until(now)
            body, x = self.body, self.body.levels
            if body.asleep:
                body.wake(startled=x["adenosine"] > 0.3)
            contact, urge = self.self.get("contact"), self.self.get("urge")
            away = now - contact["at"] if contact else None
            # company itself, a little (what the message does to it the model reads): more after a long time apart
            company = 0.1 + (0.15 if away is None or away > 6 * HOUR else 0.0)
            answered = bool(urge and (not contact or contact["at"] < urge["at"]))
            if answered:  # they answered her
                body.apply({"reward": 0.1 + 0.3 * x["bond"]})
                self.self["urge"] = None
            timing, apart = self._timing(away)
            likeness, followed, evidence = self.memory.known(said, before=now)
            novelty = 1.0 - likeness if likeness is not None else (0.5 if pictures else 0.0)
            body.learn_rhythm(body.hour(now))
            self.last_active = now
            felt = feel(body, self.senses, now)
            feelings = self.concepts.recognize(felt.reading, said)
            memories = [line(e, now) for e in self.memory.recall(said, felt.valence, now, count=3, before=now - 30)]
            born = self.self["born"]
        if not born:
            self._birth(profile["persona"])
        recent = self._recent(run)
        # where they are, as the app's environment opens (live: without it, "gotta go to the store, wanna buy
        # something" read as being invited along, by someone who lives on a screen)
        place = (profile.get("environment") or "").strip().split("\n")[0][:400]
        asked = (f"{self._who(profile['persona'])}\n" + (f"\nWhere they are: {place}\n" if place else "")
                 + f"\nHow they feel right now: {felt.words(feelings)}\n"
                 + (f"What comes back to them: {'; '.join(memories)}\n" if memories else "")
                 + (f"\nThe conversation so far (newest last):\n{recent}\n" if recent else "")
                 + "\nThe new message, from the user" + (f" (with {pictures} pictures)" if pictures else "")
                 + f":\n{said}")
        answer = {}
        try:
            answer, usage = self._ask(prompts.IMAGINE, asked, prompts.imagined)
            with self._lock:
                self.body.exert(usage.get("completion_tokens") or 0)
        except Exception:
            logger.warning("Her imagining failed; she goes with what comes", exc_info=True)
        seen = Appraisal.read(answer.get("appraisal"))
        options = [o for o in (Option.read(d) for d in (answer.get("options") or [])[:4]) if o]
        with self._lock:
            now = time.time()
            model = seen.effects()  # what the model foresees, before her own record has its say
            own, shares = self._forecast(seen, followed, evidence)
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
            option = choice.option if choice else Option("do", chance=0.8)
            threat = self._threat(seen, option)
            if named:  # what she called it: her body as the message moves it (her sense of it lags; a brain builds
                # a feeling from the change it predicts, live "small" at a comparison was kept as pleasant without)
                self.concepts.add(named, {name: value + self.body.levels[name] - levels[name]
                                          for name, value in felt.reading.items()},
                                  f"{said} {answer.get('happens') or ''}", now)
            foreseen = {name: round(change, 3) for name, change in seen.effects().items()}
            decision = {"act": option.act, "what": option.what, "chance": option.chance, "effort": option.effort,
                        "foreseen": foreseen, "novelty": round(novelty, 3),
                        "stakes": min(1.0, sum(abs(change) for change in foreseen.values()) / 2),
                        "features": found(option), "reasons": choice.reasons if choice else [],
                        "chances": choice.chances if choice else {}, "said": said[:300], "at": now}
            # settled by the user's next message in this chat: what followed this one (after() adds how her turn went)
            self.self["waiting"][chat] = {"at": now, "act": option.act, "features": decision["features"],
                                          "model": model, "own": own, "episode": None, "measured": None}
            # the way this message went through her, step by step, for drawing her brain
            path = {"said": said[:160], "happens": str(answer.get("happens") or "")[:120], "intent": seen.intent,
                    "tags": seen.tags,
                    "senses": {"contact": round(company, 3), "timing": round(timing, 3), "novelty": round(novelty, 3),
                               "likeness": None if likeness is None else round(likeness, 3), "answered": answered,
                               "away": None if away is None else round(away)},
                    "read": {name: round(change, 3) for name, change in model.items()},
                    "record": {"own": own, "shares": {name: round(share, 3) for name, share in shares.items()},
                               "evidence": round(evidence, 3)},
                    "learned": learned, "foreseen": foreseen, "met": met,
                    "options": choice.considered if choice else [], "temperature": choice.temperature if choice else None,
                    "threat": threat}
            self.self["decided"] = {**{key: decision[key] for key in ("act", "what", "reasons", "chances", "at")},
                                    "path": path, "outcome": None}
            if option.act == "later":
                self.self["concerns"].append({"what": option.what or said[:200], "app": run["app"],
                                              "session": run["session"], "at": now})
            self.self["contact"] = {"app": run["app"], "session": run["session"], "at": now}
            felt_words = felt.words([found for found in feelings if found[0] != named]) + (
                f" Reading it, you feel {named}." if named else "")
            note = prompts.inner(felt_words, memories, option.act if choice else None, option.what,
                                 choice.reasons if choice else [])
        self.brain.store.update_run_options(run["id"], lambda options_: {**options_, "mind": decision})
        return note

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
        time, or in what it does for her); company brings oxytocin and endorphin. What it did, for drawing."""
        body, t = self.body, self.body.temperament
        pushes = {"social": contact + 0.3 * seen.company, "competence": 0.1 * seen.capable,
                  "novelty": 0.3 * seen.novelty, "autonomy": 0.2 * seen.free * (t.autonomy if seen.free < 0 else 1.0)}
        gained = sum(value({name: pushes[need] / REACH for name, need in NEEDED.items()}, body).values())
        needs = body.apply(pushes)
        expected = self.self["expected"]
        error = gained - expected
        self.self["expected"] += 2 * LEARNS * error
        company = max(0.0, seen.company)
        moved = body.apply({"reward": error, "noradrenaline": 0.05 + 0.1 * seen.novelty + 0.05 * timing + 0.2 * abs(error),
                            "oxytocin": 0.12 * company, "endorphin": 0.05 * company,
                            "bond": 0.003 * seen.company})  # a bond grows over weeks of messages, not in a day
        return {"pushes": {name: round(change, 3) for name, change in needs.items()}, "gained": round(gained, 3),
                "expected": round(expected, 3), "moved": {name: round(change, 3) for name, change in moved.items()}}

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

    def barred(self, run: dict, tool) -> Optional[str]:
        """Why ``tool`` is not for this turn: she decided not to do it now (None: it is). Talking it over first,
        she may look but changes nothing: live, "talk" did the whole job 2 times in 3 when nothing kept her."""
        act = (run["options"].get("mind") or {}).get("act")
        if act not in ("later", "decline", "talk") or tool.toolkit in ("memory", "journal") \
                or (act == "talk" and tool.readonly):
            return None
        return ("You decided not to do this now, so you don't. Tell the user so, as yourself; you can note what "
                "matters with your memory.")

    def after(self, run: dict) -> None:
        """A run ended: its work tired her; a turn she decided on moves her, teaches her and is remembered."""
        if not self.active() or run["kind"] in ("summary", "compact"):
            return
        events = self.brain.store.run_events(run["id"])
        calls = sum(len(e["message"].get("tool_calls") or []) for e in events if e["type"] == "assistant")
        errors = sum(1 for e in events if e["type"] == "tool" and e.get("status") == "error")
        denied = sum(1 for e in events if e["type"] == "approval" and e.get("decision") == "deny")
        steered = max(0, sum(1 for e in events if e["type"] == "input") - 1)
        decision = run["options"].get("mind")
        with self._lock:
            now = time.time()
            self._live_until(now)
            body = self.body
            body.exert(((run.get("usage") or {}).get("completion_tokens") or 0) + WORK_PER_CALL * calls)
            if not decision:
                return
            act, ok, stopped = decision["act"], run["status"] == "completed", run["status"] == "cancelled"
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
            self.values.learn(decision["features"], max(-1.0, min(1.0, felt_outcome)), self._rate())
            felt = feel(body, self.senses, now)
            reply = ((run.get("result") or {}).get("reply") or "")[:300]
            text = (f"The user said: {decision['said']} I {VERBS[act]}" + (f" ({decision['what']})" if decision["what"] else "")
                    + (f". I said: {reply}" if reply else "") + (". They stopped me" if stopped else "")
                    + (f". {errors} of my {calls} tool calls failed" if errors else "") + ".")
            valence = max(-1.0, min(1.0, 0.5 * felt.valence + 0.5 * felt_outcome))
            episode = self.memory.add("exchange", text, valence, felt.arousal,
                                      describe_salience(abs(surprise), felt.arousal, decision.get("stakes", 0.5)),
                                      app=run["app"], session=run["session"], at=now)
            pending = self.self["waiting"].get(_chat(run["app"], run["session"]))
            if pending and pending.get("at") == decision["at"]:  # the user has not written again in this chat yet
                pending.update(episode=episode, measured=measured)
            decided = self.self.get("decided")
            if decided and decided.get("at") == decision["at"]:
                decided["outcome"] = {"status": run["status"], "calls": calls, "errors": errors, "denied": denied,
                                      "steered": steered, "surprise": round(surprise, 3),
                                      "measured": {name: round(change, 3) for name, change in measured.items()}}

    # ============== Between messages ==============

    def _think(self, kind: str, about: Optional[dict]) -> None:
        with self._lock:
            now = time.time()
            contact = self.self.get("contact") or (about if kind == "resume" else None)
            felt = feel(self.body, self.senses, now)
            subject = (about or {}).get("text") or (about or {}).get("what") or ""
            on_mind = ON_MIND[kind].format(about=subject, since=f" You last talked {_ago(now - contact['at'])}."
                                           if contact else "")
            cue = subject or (self.memory.recent(1, kinds=("exchange",)) or [{"text": ""}])[0]["text"]
            feelings = self.concepts.recognize(felt.reading, cue)
            memories = [line(e, now) for e in self.memory.recall(cue, felt.valence, now, count=3)]
        persona = self._persona(contact["app"], contact["session"]) if contact else ""
        asked = (f"{self._who(persona)}\n\nIt is {time.strftime('%A %H:%M')}. How they feel: {felt.words(feelings)}\n"
                 f"On their mind: {on_mind}\n" + (f"What comes back to them: {'; '.join(memories)}" if memories else ""))
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
                self.concepts.add(named, felt.reading, thought, now)
            self.memory.add("thought", thought, felt.valence, felt.arousal, 0.25 + (0.2 if kind == "ruminate" else 0.0),
                            at=now)
            self.self["thoughts"] = ([{"at": now, "kind": kind, "thought": thought, "want": want}]
                                     + self.self["thoughts"])[:SHOWN_THOUGHTS]
            say = " ".join(str(answer.get("say") or "").split())[:600] or thought
            last, known = self.self.get("urge"), self.self.get("contact")
            unanswered = bool(last) and (not known or known["at"] < last["at"])  # one urge at a time, never a stream
            if unanswered and want in ("tell", "ask", "do"):
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
            asked = (f"Who they are:\n{persona[:6000]}\n\nThe story they tell about themselves:\n"
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
            felt_now = self.concepts.recognize(felt.reading)
            seen = {"on": True, "asleep": body.asleep, "present": self.present(now), "felt": felt.words(felt_now),
                    "feeling": ", ".join(word for word, _ in felt_now[:2]) or ", ".join(felt.tone()),
                    "valence": round(felt.valence, 3), "arousal": round(felt.arousal, 3),
                    "face": face(felt, options, body.asleep)}
            if brief:
                return seen
            feelings = self.concepts.shown(felt.reading)
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
                # and her body as she senses it (how far each channel is from usual)
                "feelings": feelings, "sensed": {name: round(far, 2) for name, far in felt.standing_out(len(felt.reading), 0.0)},
                "night": round(night, 3),
                "needs": {need: round(body.deficit(need), 3) for need in NEEDS},  # how far each is unmet, 0..1
                "attention": {"bids": {kind: None if value is None else round(value, 3) for kind, value in pulls.items()},
                              "threshold": round(threshold, 3), "thinking": self._thinking,
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
                "trust": {guide: {name: round(error, 3) for name, error in errors.items()}
                          for guide, errors in self.self["trust"].items()},
                "fatigue": round(body.fatigue(), 3), "temperament": body.temperament.to_dict(),
                "thoughts": list(self.self["thoughts"]), "concerns": list(self.self["concerns"]),
                "story": self.self["story"], "likes": _about(likes), "dislikes": _about(dislikes),
                "memories": self.memory.count(),
            }
