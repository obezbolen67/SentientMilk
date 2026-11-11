"""Going over a conversation as it ends: what she settled on, learned about the user or decided goes to her
memory, written by her own model as herself (the app's persona, the conversation's settings) with
memory_save, as in any turn.

An app asks when one of its conversations ends (left, closed, the app quits) and, at its start, for all of
them: a crash or a machine turned off ended some unasked. She goes over each in a run of its own, kind
"summary", in a session summary-<run> no app shows, one at a time and after the turns going on now. That run
has memory_save alone and nothing that waits for the user; the conversation's log stays as it was, and its
next turn takes her memory afresh. The conversation's state keeps how far she went: ``summarized``, the
newest event she went over (its id, which never changes, and its time). With fewer than MESSAGES of the
user's messages since, there is nothing to go over yet.
"""

import logging
import queue
import threading
import time
from typing import List, Optional

from . import mentions
from . import signals as signal_format

logger = logging.getLogger(__name__)

MESSAGES = 4  # the user's, since she last went over it: a short chat waits for more
SHARE = 0.4  # of the context window for what one run goes over (some 3 characters a token); more goes in parts
CALL_CHARS, NOTE_CHARS = 200, 300
WAIT = 2.0  # seconds between looks while a turn goes on: the user's replies come first
INSTRUCTIONS = """You are going over one of your conversations on your own, after it ended. Nobody else sees
this and nobody will answer: the user is not here. What you keep with memory_save you will know in every
later chat; nothing else of this run stays."""
PROMPT = """The conversation "{title}" ended. This is what was said in it since you last went over it:

{transcript}

Go over it as yourself and decide what to keep. Keep only:
- what you settled on: opinions and stances you reached and would hold to next time
- facts about the user: their name, the people in their life, where they live, their work, plans and tastes
- decisions made, names, addresses, accounts, and where a project stands now
Keep what you would be annoyed to have forgotten and what will still be true next week. Leave out stray
leanings, one-off moods, small talk, what happened once and is done, and whatever YOUR MEMORY or THIS
SESSION'S MEMORY holds already: if it is there, even in other words, skip it; if it changed, save it under
the same key so the new one replaces it. Write each in your own words, in the first person where it is
yours ("I decided ..."), in a sentence or two. Scope everywhere for what lasts beyond this conversation
(category user, preferences or projects); scope session for what matters only in it. Most conversations
leave little or nothing worth keeping: then save nothing. When you are done, say in one line what you kept,
or "nothing"."""


def said_by_user(events: List[dict]) -> int:
    """How many of the events are messages the user wrote (not a job's news or a schedule's run)."""
    return sum(1 for event in events if event["type"] == "input" and event.get("display"))


def line_of(event: dict) -> str:
    """One event as she goes over it: the user's words and hers, and the tools she used (not what they gave)."""
    kind = event["type"]
    if kind == "input":
        return f"USER: {event['display']}" if event.get("display") else ""
    if kind == "assistant":
        message = event["message"]
        text = message.get("content") if isinstance(message.get("content"), str) else ""
        text = signal_format.split(text)[1] if text else ""  # what she said, not how she looked saying it
        lines = [f"YOU: {text}"] if text else []
        lines += [f"  (you used {call['function']['name']}({call['function']['arguments'][:CALL_CHARS]}))"
                  for call in message.get("tool_calls") or []]
        return "\n".join(lines)
    if kind == "note":
        return f"NOTE: {str(event.get('text', ''))[:NOTE_CHARS]}"
    return ""


class Summaries:
    def __init__(self, brain):
        self.brain, self.store = brain, brain.store
        self._queue: queue.Queue = queue.Queue()
        self._queued: set = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="summaries", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)

    def ask(self, app: str, session: str) -> dict:
        """She goes over ``session`` soon if enough is new in it: ``queued``, and ``messages``, the user's
        since she last went over it."""
        on = self.brain.config.values()["session_summaries"]
        messages = said_by_user(self.new(app, session)) if on else 0
        queued = messages >= MESSAGES
        if queued:
            with self._lock:
                fresh = (app, session) not in self._queued
                self._queued.add((app, session))
            if fresh:
                self._queue.put((app, session))
        return {"queued": queued, "messages": messages}

    def sweep(self, app: str) -> dict:
        """Every conversation of the app with enough new in it: ``queued``, their ids."""
        return {"queued": [found["id"] for found in mentions.chats(self.brain, app)
                           if self.ask(app, found["id"])["queued"]]}

    def new(self, app: str, session: str) -> List[dict]:
        """The conversation's events she has not gone over."""
        mark = ((self.store.find_session(app, session) or {}).get("state") or {}).get("summarized") or {}
        return self.store.events_since(app, session, mark.get("event", 0), mark.get("at", 0))

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            with self._lock:
                self._queued.discard(item)  # asked again from now on: what comes meanwhile waits its turn
            try:
                while self.store.runs(kind="turn", statuses=("queued", "working"), limit=1) and \
                        not self.brain.stopping.is_set():
                    time.sleep(WAIT)
                self.go_over(*item)
            except Exception:
                logger.exception("Could not go over %s/%s", *item)

    def go_over(self, app: str, session: str) -> List[dict]:
        """Her runs over what is new in ``session``, the oldest part first; none when too little is new. The
        mark moves past each part she went over to the end."""
        runs = []
        budget = int(self.brain.config.values()["context_window"] * SHARE * 3)
        while not self.brain.stopping.is_set():
            events = self.new(app, session)
            if said_by_user(events) < MESSAGES:
                break
            part, lines, size = [], [], 0
            for event in events:
                line = line_of(event)
                if part and size + len(line) > budget:
                    break
                part.append(event)
                if line:
                    lines.append(line)
                    size += len(line) + 2
            run = self._run(app, session, lines, part[-1]["id"])
            runs.append(run)
            if run["status"] != "completed":
                break
            last = part[-1]
            if self.store.update_session(app, session, "state", lambda state: {
                    **state, "summarized": {"event": last["id"], "at": last["at"]}}, create=False) is None:
                break  # deleted meanwhile
            if any(event["type"] == "tool" and event.get("name") == "memory_save" and event.get("status") == "ok"
                   for event in self.store.run_events(run["id"])):
                self.store.drop_snapshots(app, [session])  # its next turn takes her memory as it is now
            if len(part) == len(events):
                break
        return runs

    def _run(self, app: str, session: str, lines: List[str], upto: int) -> dict:
        title = ((self.store.find_session(app, session) or {}).get("settings") or {}).get("title") or session
        options = {"input": [{"type": "text", "text": PROMPT.format(title=title, transcript="\n\n".join(lines))}],
                   "chat": session, "upto": upto,  # the newest event she goes over: a return before it undoes
                   "profile": {"from_session": session, "toolkits": ["memory"], "signals": False,  # what she kept
                               "instructions": INSTRUCTIONS}}
        run_id = self.store.add_run(app, "pending", "summary", options, status="working")
        self.store.update_run(run_id, session=f"summary-{run_id}")
        self.brain.runs.loop.execute(run_id)
        run = self.store.run(run_id)
        if run["status"] not in ("completed", "failed", "cancelled"):  # nothing it may wait for: never left
            self.brain.runs.cancel(run_id, reason="Nobody answers a summary.", now=True)
            run = self.store.run(run_id)
        return run
