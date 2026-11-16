"""Her mind, alive: the body ticks on, needs build, bids compete for her attention, thoughts come, she sleeps.

One being for every app (Brain.mind). For each message the user sends (a turn with their words) she feels
it, recalls, imagines what she could do and chooses (``before``): her decision and her felt sense go with the
message as a note only she reads; a refusal or a delay keeps her work tools from her for that turn
(``barred``). When the turn ends (``after``) its outcome moves her body, teaches her values and becomes a
memory. The user's next message tells her how her decision was taken.

Between messages (``_live``, every few seconds) her body lives on. Every ``BIDS_EVERY`` seconds what wants her
attention competes, with noise, against a threshold that rises as she tires: missing the user (reach_out),
boredom (wonder), something that nags her (ruminate), what she put off (resume) and sleep. A winner is a
thought (a model call). A thought may become something she wants to tell or ask the user (the app hears
``mind.urge`` and starts a turn), doing what she put off, or looking something up herself (a task).
Asleep, she goes over the day once (``_consolidate``): insights, a dream, her story rewritten, the day's
charge softened, faint memories forgotten.
"""

import logging
import random
import secrets
import threading
import time
from typing import Optional

import requests

from . import prompts
from .body import DAY, HOUR, MINUTE, Body, Temperament
from .feel import Concepts, Interoception, face, feel
from .memory import Memory, describe_salience, line
from .values import Values, features
from .will import Appraisal, Option, choose

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
        self.self = {"story": "", "born": False, "expected_warmth": 0.2, "contact": None, "concerns": [],
                     "pending": None, "urge": None, "slept": 0.0, "consolidate": False, "fired": {},
                     "thoughts": [], **(self.memory.get("self") or {})}
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

    def _winner(self, now: float):
        body, x, t = self.body, self.body.levels, self.body.temperament
        fired, contact = self.self["fired"], self.self.get("contact")
        present, fatigue = self.present(now), body.fatigue()
        reachable = bool(contact) and self._alive(contact["app"], now) and \
            not self.brain.session_busy(contact["app"], contact["session"])
        urge = self.self.get("urge")
        waiting = bool(urge) and (not contact or contact["at"] < urge["at"])  # she reached out and nobody answered
        sore = next((e for e in self.memory.since(now - 2 * DAY, kinds=("exchange", "thought"), count=8)
                     if e["valence"] < -0.3 and e["charge"] > 0.5), None)
        concern = self.self["concerns"][0] if self.self["concerns"] else None
        bids = {
            "sleep": 1.6 * max(0.0, x["adenosine"] - 0.55) + 0.6 * body.night(now) + 0.4 * (1 - x["energy"])
            - (0.7 if present else 0.0) if x["adenosine"] > DOZES_OFF else None,
            "reach_out": 1.5 * body.deficit("social") * x["bond"] * (0.5 + x["oxytocin"]) * t.sociability
            * (1.0 if present else 0.3) if reachable and not waiting else None,
            "wonder": 1.1 * body.deficit("novelty") * t.curiosity * x["energy"] * (0.4 + x["dopamine"]),
            "ruminate": 1.4 * max(0.0, x["cortisol"] - 0.3) + 0.7 * x["grievance"] if sore else None,
            "resume": 0.9 * x["energy"] * (0.4 + x["dopamine"]) * (0.5 + x["bond"]) - 0.6 * fatigue
            if concern and self._alive(concern["app"], now) else None,
        }
        scored = [(value + self.rng.gauss(0.0, 0.1 * t.volatility), kind) for kind, value in bids.items()
                  if value is not None and now - fired.get(kind, 0.0) >= REFRACTORY[kind]]
        if not scored:
            return None, None
        value, kind = max(scored)
        if kind == "sleep":
            if value < 0.7:
                return None, None
            fired["sleep"] = now
            return kind, None
        threshold = 0.5 + 0.6 * fatigue - 0.3 * max(0.0, x["noradrenaline"] - 0.35)
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
        """The user wrote (``said``): she feels it, recalls, imagines and chooses. The note for her (or None:
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
            body.apply({"social": 0.25 + (0.15 if away is None or away > 6 * HOUR else 0.0), "noradrenaline": 0.05})
            if urge and (not contact or contact["at"] < urge["at"]):  # they answered her
                body.apply({"reward": 0.1 + 0.3 * x["bond"]})
                self.self["urge"] = None
            body.learn_rhythm(body.hour(now))
            self.last_active = now
            felt = feel(body, self.senses, now)
            like = self.concepts.like(felt.vector())
            memories = [line(e, now) for e in self.memory.recall(said, felt.valence, now, count=3, before=now - 30)]
            born = self.self["born"]
        if not born:
            self._birth(profile["persona"])
        recent = self._recent(run)
        asked = (f"{self._who(profile['persona'])}\n\nHow they feel right now: {felt.words(like)}\n"
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
            self._appraised(seen)
            named = prompts.word(answer.get("feeling"))
            if named:
                self.concepts.add(named, felt.vector())
            hour = self.body.hour(now)

            def found(option):
                return features(option.act, seen.tags, seen.intent, hour, run["app"])
            choice = choose(options, seen, self.body, self.values, found, self.rng) if options else None
            option = choice.option if choice else Option("do", chance=0.8, gives=1.0)
            decision = {"act": option.act, "what": option.what, "chance": option.chance, "effort": option.effort,
                        "fun": option.fun, "importance": seen.importance, "features": found(option),
                        "reasons": choice.reasons if choice else [], "chances": choice.chances if choice else {},
                        "said": said[:300], "at": now}
            self.self["pending"] = decision
            if option.act == "later":
                self.self["concerns"].append({"what": option.what or said[:200], "app": run["app"],
                                              "session": run["session"], "at": now})
            self.self["contact"] = {"app": run["app"], "session": run["session"], "at": now}
            felt_words = felt.words(like if like != named else None) + (f" Reading it, you feel {named}." if named else "")
            note = prompts.inner(felt_words, memories, option.act if choice else None, option.what,
                                 choice.reasons if choice else [])
        self.brain.store.update_run_options(run["id"], lambda options_: {**options_, "mind": decision})
        return note

    def _appraised(self, seen: Appraisal) -> None:
        """What the message does to her body, and how her last decision was taken (the warmth of the answer)."""
        body, t = self.body, self.body.temperament
        warmth, expected = seen.warmth, self.self["expected_warmth"]
        pushes = {"reward": 0.35 * (warmth - expected), "novelty": 0.3 * seen.novelty,
                  "noradrenaline": 0.1 * seen.novelty + 0.08 * seen.pressure,
                  # being asked is no threat; being pushed is (a polite request read as 0.6 pressure live)
                  "autonomy": -0.3 * max(0.0, seen.pressure - 0.5) * t.autonomy,
                  "bond": 0.003 * warmth}  # a bond grows over weeks of messages, not in a day
        if warmth > 0:
            pushes.update(oxytocin=0.12 * warmth, endorphin=0.05 * warmth)
        else:
            pushes["cortisol"] = -0.15 * warmth * t.sensitivity
        if warmth < -0.3:
            pushes["grievance"] = 0.25 * (-warmth - 0.3) * t.sensitivity
        body.apply(pushes)
        self.self["expected_warmth"] = expected + 0.2 * (warmth - expected)
        pending = self.self.get("pending")
        if pending:
            self.values.learn(pending["features"], warmth + 0.5 * (warmth - expected), self._rate())
            self.self["pending"] = None

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

    def barred(self, run: dict, toolkit: str) -> Optional[str]:
        """Why a tool of ``toolkit`` is not for this turn: she decided not to do it now (None: it is)."""
        decision = run["options"].get("mind")
        if not decision or decision["act"] not in ("later", "decline") or toolkit in ("memory", "journal"):
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
            if act in ("do", "part"):
                success = (1.0 if ok else 0.0) * (1.0 - 0.6 * failed) - 0.3 * min(1, denied)
                surprise = success - decision["chance"]
                body.apply({"reward": 0.45 * surprise, "competence": 0.15 * surprise + (0.05 if ok else 0.0),
                            "endorphin": 0.15 * max(0.0, decision["fun"]) if ok else 0.0,
                            "cortisol": 0.06 * failed})
                felt_outcome = surprise + 0.3 * decision["fun"] - 0.3 * failed
            else:  # spared the work: relief, and the freedom of her own choice
                body.apply({"autonomy": 0.12})
                felt_outcome = 0.1
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
            self.memory.add("exchange", text, valence, felt.arousal,
                            describe_salience(abs(surprise), felt.arousal, decision["importance"]),
                            app=run["app"], session=run["session"], at=now)

    # ============== Between messages ==============

    def _think(self, kind: str, about: Optional[dict]) -> None:
        with self._lock:
            now = time.time()
            contact = self.self.get("contact") or (about if kind == "resume" else None)
            felt = feel(self.body, self.senses, now)
            like = self.concepts.like(felt.vector())
            subject = (about or {}).get("text") or (about or {}).get("what") or ""
            on_mind = ON_MIND[kind].format(about=subject, since=f" You last talked {_ago(now - contact['at'])}."
                                           if contact else "")
            cue = subject or (self.memory.recent(1, kinds=("exchange",)) or [{"text": ""}])[0]["text"]
            memories = [line(e, now) for e in self.memory.recall(cue, felt.valence, now, count=3)]
        persona = self._persona(contact["app"], contact["session"]) if contact else ""
        asked = (f"{self._who(persona)}\n\nIt is {time.strftime('%A %H:%M')}. How they feel: {felt.words(like)}\n"
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
                self.concepts.add(named, felt.vector())
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

    def state(self, app: Optional[str] = None, idle: Optional[float] = None) -> dict:
        """How she is now: her face for ``app`` (from its declared expressions), what she feels, her levels,
        thoughts, concerns and story. ``idle``: seconds since the user last touched the computer."""
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
            like = self.concepts.like(felt.vector())
            likes, dislikes = self.values.leanings()
            return {
                "on": True, "asleep": body.asleep, "present": self.present(now), "felt": felt.words(like),
                "sensations": {name: round(value, 2) for name, value in felt.strongest(5)},
                "valence": round(felt.valence, 3), "arousal": round(felt.arousal, 3),
                "face": face(felt, options, body.asleep),
                "levels": {name: round(value, 3) for name, value in body.levels.items()},
                "fatigue": round(body.fatigue(), 3), "temperament": body.temperament.to_dict(),
                "thoughts": list(self.self["thoughts"]), "concerns": list(self.self["concerns"]),
                "story": self.self["story"], "likes": _about(likes), "dislikes": _about(dislikes),
                "memories": self.memory.count(),
                "named": [word for word, _ in self.concepts.named[-8:]],
            }
