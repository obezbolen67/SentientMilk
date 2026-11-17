"""The journal: her own short, timestamped notes about stretches of her sessions in every app, written off
the request path.

A note is written when a session has been quiet for a while, at compaction and when a task ends. It is
hers: written as herself, in the first person, about what she lived (until 0.25 a summarizer wrote it
about "you", and mixed up whose friend was whose). The newest 20 are kept (store.JOURNAL_NOTES), older ones
deleted: the newest go in her prompt, journal_search finds the rest. With her mind on, each note is also
an event of her life (``Mind.remember``): the gist of that stretch, which outlives its details.

Once, with her mind on, she goes over her past (``catch_up``): every stretch of every conversation that
went quiet gets its note, as an event of her life, and the journal is written again from them in her own
words. A mind that began after much of her life had happened knew nothing of it before.
"""

import logging
import queue
import threading
import time
from typing import List

logger = logging.getLogger(__name__)

NOTE_CHARS = 400
QUIET_SECONDS = 20 * 60
TRANSCRIPT_CHARS = 12_000
HELPERS = ("agent-", "summary-")  # sessions that are not hers to remember: a helper's, her going over a chat
PROMPT = """Write one note in your journal about the conversation below, for your own later reference: 1 to 3
short sentences, at most 400 characters. It is your own note about what you lived: write as yourself, in
the first person ("I ..."), and the user by their name when you know it, else "they". Say what was talked
about or done, what was decided and anything worth remembering; name what you worked on, not the app you
talked in. Plain text, no preamble, in English."""


def stretches(events: List[dict]) -> List[List[dict]]:
    """A session's events in stretches of conversation: a quiet spell of QUIET_SECONDS ends one."""
    found: List[List[dict]] = []
    for event in events:
        if not found or event["at"] - found[-1][-1]["at"] > QUIET_SECONDS:
            found.append([])
        found[-1].append(event)
    return found


class Journal:
    def __init__(self, brain):
        self.brain = brain
        self._queue: queue.Queue = queue.Queue()
        self._thread = None
        self._stopping = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="journal", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Let a note being written finish (a model call), so the store outlives it."""
        self._stopping.set()
        self._queue.put(None)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)

    def request(self, app: str, session: str) -> None:
        self._queue.put((app, session))

    def _loop(self) -> None:
        try:
            self.catch_up()
        except Exception:
            logger.exception("Could not go over her past")
        while True:
            try:
                item = self._queue.get(timeout=60)
            except queue.Empty:
                try:
                    self.catch_up()  # her mind may have been switched on since
                except Exception:
                    logger.exception("Could not go over her past")
                self._check_quiet()
                continue
            if item is None:
                return
            try:
                self.write(*item)
            except Exception:
                logger.exception("Could not write a journal note for %s/%s", *item)

    def _check_quiet(self) -> None:
        try:
            for app, session, last in self.brain.store.quiet_sessions(time.time() - QUIET_SECONDS):
                if session.startswith(HELPERS + ("task-",)):
                    continue  # helpers and her going over a conversation never; tasks when they end
                found = self.brain.store.find_session(app, session)  # events can outlive a deleted session
                if found and last > found["state"].get("journaled_upto", 0):
                    self.request(app, session)
        except Exception:
            logger.exception("Journal check failed")

    def note(self, app: str, session: str, events: List[dict]) -> str:
        """Her note about these events of a session ("" when there is nothing to note or nobody to write it)."""
        brain = self.brain
        profile = brain.profile(app, session)
        lines = []
        for event in events:
            if event["type"] == "input" and event.get("display"):
                lines.append(f"User: {event['display'][:500]}")
            elif event["type"] == "end" and event.get("reply"):
                lines.append(f"You: {event['reply'][:500]}")
            elif event["type"] == "assistant":
                for call in event["message"].get("tool_calls") or []:
                    lines.append(f"(used {call['function']['name']})")
        if not profile["journal"]["write"] or all(line.startswith("(") for line in lines) or brain.provider_problem():
            return ""
        transcript = "\n".join(lines)[-TRANSCRIPT_CHARS:]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(events[0]["at"]))
        header = f"In the app {profile['name']}, chat {session}, from {when}"
        if session.startswith("task-"):
            run = brain.store.run(int(session.split("-", 1)[1]))
            header += f", a job of your own in the background: {run['options'].get('goal', '')[:300]}" if run else ""
        # who is writing: herself, and who the user is to her (what she keeps about them)
        about = [e for e in brain.store.memory_entries() if e["category"].lower() in ("user", "people")]
        who = f"\n\nWho you are:\n{profile['persona'][:6000]}" + (
            "\n\nWhat you keep about the user:\n" + "\n".join(f"- {e['key']}: {e['value']}" for e in about)
            if about else "")
        message, _ = brain.provider(profile["light_model"]).complete(
            [{"role": "system", "content": PROMPT + who}, {"role": "user", "content": f"{header}\n\n{transcript}"}])
        return " ".join((message.get("content") or "").split())[:NOTE_CHARS]

    def write(self, app: str, session: str) -> None:
        brain = self.brain
        found = brain.store.find_session(app, session)
        if found is None:  # deleted meanwhile
            return
        upto = found["state"].get("journaled_upto", 0)
        events = brain.store.events(app, session, after=upto)
        if not events:
            return
        note = self.note(app, session, events)
        if note:
            brain.store.add_note(app, session, note)
            brain.mind.remember(app, session, note, events[0]["at"], events[-1]["at"])
        self._mark(app, session, events[-1]["id"])

    def _mark(self, app: str, session: str, last: int) -> None:
        def change(state):
            state["journaled_upto"] = max(state.get("journaled_upto", 0), last)
            return state
        self.brain.store.update_session(app, session, "state", change, create=False)  # it may be deleted by now

    def catch_up(self) -> None:
        """Once, with her mind on: every stretch of every conversation that went quiet gets her note, as an
        event of her life, then the journal is written again from them. Each stretch done is kept (``past``
        in her mind's state), so a stop or a provider problem picks up where it left off at the next start."""
        brain, mind = self.brain, self.brain.mind
        # shortcut: once per home; stretches noted while her mind was later switched off stay out of it, when
        # the switch is used that way go over them by journaled time too
        if not mind.active():
            return
        with mind._lock:
            past = mind.self.setdefault("past", {"done": [], "notes": [], "complete": False})
        if past["complete"]:
            return
        done, quiet = {tuple(item) for item in past["done"]}, time.time() - QUIET_SECONDS
        for app, session, _ in brain.store.quiet_sessions(time.time()):
            if session.startswith(HELPERS) or brain.store.find_session(app, session) is None:
                continue
            for stretch in stretches(brain.store.events(app, session)):
                if self._stopping.is_set() or brain.provider_problem():
                    return  # the rest at the next start
                if stretch[-1]["at"] > quiet or (app, session, stretch[-1]["id"]) in done:
                    continue  # still going on: the journal notes it when it goes quiet
                try:
                    note = self.note(app, session, stretch)
                except Exception:  # an app gone since, a reply that would not come: that stretch stays unnoted
                    logger.exception("Could not note a stretch of %s/%s", app, session)
                    note = ""
                if note:
                    mind.remember(app, session, note, stretch[0]["at"], stretch[-1]["at"])
                with mind._lock:
                    past["done"].append([app, session, stretch[-1]["id"]])
                    if note:
                        past["notes"].append([stretch[-1]["at"], app, session, note])
                mind.save()
                self._mark(app, session, stretch[-1]["id"])
        # the journal, in her own words: the old notes were written from these same conversations
        for old in brain.store.notes():
            brain.store.delete_note(old["id"])
        for at, app, session, note in sorted(past["notes"]):
            brain.store.add_note(app, session, note, at=at)  # the newest 20 stay
        with mind._lock:
            past.update(complete=True, done=[], notes=[])
        mind.save()
