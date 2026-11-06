"""The journal: short, timestamped notes about sessions in every app, written off the request path.

A note is written when a session has been quiet for a while, at compaction and when a
task ends. All notes together stay under CAPACITY characters: the oldest go first.
"""

import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

CAPACITY = 24_000  # characters, about 6,000 tokens
NOTE_CHARS = 400
QUIET_SECONDS = 20 * 60
TRANSCRIPT_CHARS = 12_000
PROMPT = """Write one journal note about the conversation below, for your own later reference: 1 to 3 short
sentences, at most 400 characters. Say what was discussed or done, decisions and anything worth
remembering. Plain text, no preamble, in English."""


class Journal:
    def __init__(self, brain):
        self.brain = brain
        self._queue: queue.Queue = queue.Queue()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="journal", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Let a note being written finish (a model call), so the store outlives it."""
        self._queue.put(None)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)

    def request(self, app: str, session: str) -> None:
        self._queue.put((app, session))

    def _loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=60)
            except queue.Empty:
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
                if session.startswith("agent-") or session.startswith("task-"):
                    continue  # helpers never; tasks when they end
                if last > self.brain.store.session(app, session)["state"].get("journaled_upto", 0):
                    self.request(app, session)
        except Exception:
            logger.exception("Journal check failed")

    def write(self, app: str, session: str) -> None:
        brain = self.brain
        profile = brain.profile(app, session)
        state = brain.store.session(app, session)["state"]
        upto = state.get("journaled_upto", 0)
        events = brain.store.events(app, session, after=upto)
        if not events:
            return
        lines = []
        for event in events:
            if event["type"] == "input" and event.get("display"):
                lines.append(f"User: {event['display'][:500]}")
            elif event["type"] == "end" and event.get("reply"):
                lines.append(f"You: {event['reply'][:500]}")
            elif event["type"] == "assistant":
                for call in event["message"].get("tool_calls") or []:
                    lines.append(f"(used {call['function']['name']})")
        if profile["journal"]["write"] and any(not line.startswith("(") for line in lines) and \
                brain.config.values()["api_key"]:
            transcript = "\n".join(lines)[-TRANSCRIPT_CHARS:]
            header = f"App: {profile['name']} ({app}), session {session}"
            if session.startswith("task-"):
                run = brain.store.run(int(session.split("-", 1)[1]))
                header += f", a background task: {run['options'].get('goal', '')[:300]}" if run else ""
            message, _ = brain.provider(profile["light_model"]).complete(
                [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"{header}\n\n{transcript}"}])
            note = " ".join((message.get("content") or "").split())[:NOTE_CHARS]
            if note:
                brain.store.add_note(app, session, note, CAPACITY)
        last = events[-1]["id"]

        def change(state):
            state["journaled_upto"] = max(state.get("journaled_upto", 0), last)
            return state
        brain.store.update_session(app, session, "state", change)
