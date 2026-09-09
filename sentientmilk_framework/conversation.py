"""Lossless, append-only model transcript; UI text is a separate projection."""

import copy
import json
import sqlite3
from pathlib import Path


class Conversation(list):
    """Optional SQLite journal or synchronous persistence callback.

    Append commits before returning. Do not mutate stored messages in place.
    A failed persistence callback stops execution before the next tool runs.
    One owner must serialize turns (this is not a concurrent chat queue).
    """

    def __init__(self, messages=(), *, path=None, on_append=None):
        self.path = Path(path) if path else None
        self.on_append = on_append
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                saved = [json.loads(row[0]) for row in db.execute("SELECT payload FROM messages ORDER BY id")]
            super().__init__(saved)
            if not saved:
                self.extend(messages)
        else:
            super().__init__(copy.deepcopy(list(messages)))

    def append(self, message):
        if message.get("role") == "user":
            self.recover_pending()
        message = copy.deepcopy(message)
        if self.path:
            with sqlite3.connect(self.path) as db:
                db.execute("INSERT INTO messages(payload) VALUES (?)", (json.dumps(message, ensure_ascii=False),))
        if self.on_append:
            self.on_append(message)
        super().append(message)

    def extend(self, messages):
        for message in messages:
            self.append(message)

    def clear(self):
        if self.path:
            with sqlite3.connect(self.path) as db:
                db.execute("DELETE FROM messages")
        super().clear()

    def recover_pending(self):
        """Close an interrupted tool group without rerunning potential side effects."""
        pending = {}
        for message in self:
            if message.get("role") == "assistant":
                pending = {call["id"]: call for call in message.get("tool_calls", [])}
            elif message.get("role") == "tool":
                pending.pop(message.get("tool_call_id"), None)
        for call_id, call in pending.items():
            self.append({
                "role": "tool", "tool_call_id": call_id,
                "name": call.get("function", {}).get("name", ""),
                "content": '{"error":"Execution interrupted; outcome unknown. Not automatically replayed. Inspect state before retrying."}',
            })
