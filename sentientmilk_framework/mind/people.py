"""The people in her life, known as a person knows people (0.31; design: docs/superpowers/specs/2026-11-17-people-design.md).

Nothing here is typed in by anyone: she recognizes whoever an app shows as the person she talks with (its
handle, "user: plays" in a turn's context, is her face: it brings the whole person to mind), remembers moments
with who was in them, hears a name and thinks of that person, and learns who people are the way memory does,
in her sleep: going over what happened, she updates what she knows of each person in it (Mind._meet_people).
Someone met on few days and not seen for a long time is forgotten; whoever is around stays.

Before this her mind's prompts said only "the user": a rumination of hers called the user "she", and a chat
knew his name only while lasting memory was in every prompt (until 0.30).
"""

import re
from typing import Dict, Iterable, List, Optional

DAY = 86400.0
FADES = 90 * DAY  # someone not seen this long...
FAMILIAR = 3  # ...goes, unless they came up in at least this many of her nights
GIST_CHARS = 400
PRONOUNS = ("he", "she", "they")


def _clean(value, limit: int = 80) -> str:
    return " ".join(str(value or "").split())[:limit]


class People:
    def __init__(self, saved: Optional[dict] = None):
        saved = saved or {}
        self.known: List[dict] = list(saved.get("known") or [])
        # app -> handle -> when she last saw it: the faces she has seen, known or not
        self.handles: Dict[str, Dict[str, float]] = dict(saved.get("handles") or {})
        self.met_past: bool = bool(saved.get("met_past"))  # she went over her life before 0.31 for its people

    def to_dict(self) -> dict:
        return {"known": self.known, "handles": self.handles, "met_past": self.met_past}

    # ============== Recognizing ==============

    def recognize(self, app: str, handle: Optional[str]) -> Optional[dict]:
        """Who goes by ``handle`` in ``app`` (None: nobody she knows)."""
        wanted = _clean(handle).lower()
        return next((person for person in self.known if wanted and wanted in
                     (h.lower() for h in person.get("goes_by", {}).get(app, []))), None)

    def present(self, app: str, handle: Optional[str], now: float) -> Optional[dict]:
        """Someone writes to her in ``app`` as ``handle``: the face is seen, and the person, if she knows them."""
        handle = _clean(handle)
        if handle:
            self.handles.setdefault(app, {})[handle] = now
        person = self.recognize(app, handle)
        if person is not None:
            person["seen"] = now
        return person

    def of_app(self, app: Optional[str]) -> Optional[dict]:
        """Whom "the user" of ``app`` was in what she kept before she knew people: who goes by a handle there."""
        found = [person for person in self.known if app and person.get("goes_by", {}).get(app)]
        return max(found, key=lambda person: person.get("seen", 0.0), default=None)

    def find(self, name: str) -> Optional[dict]:
        wanted = _clean(name).lower()
        return next((person for person in self.known
                     if wanted and wanted in [n.lower() for n in [person["name"], *person.get("aka", [])]]), None)

    def mentioned(self, text: str, besides: Iterable[Optional[dict]] = ()) -> List[dict]:
        """The people she knows named in ``text`` (a name heard brings its person to mind), but ``besides``."""
        skip = {id(person) for person in besides if person}
        found = []
        for person in self.known:
            names = [n for n in [person["name"], *person.get("aka", [])] if n]
            if id(person) not in skip and any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text or "", re.IGNORECASE)
                                              for n in names):
                found.append(person)
        return found

    @staticmethod
    def line(person: dict) -> str:
        """A person as they come to her mind: name, how she refers to them, what she keeps in mind of them."""
        gist = person.get("gist") or "you know little of them yet"
        return f"{person['name']} ({person.get('pronoun') or 'they'}): {gist}"

    # ============== Learning ==============

    def update(self, changes, now: float) -> bool:
        """What sleep made of the people in what happened (the people step's answer): each one known is set
        right, each new one is met. A handle counts only if she has seen it in that app (a face she never saw is
        no face of theirs). Whether anything changed."""
        changed = False
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict) or not _clean(change.get("name")):
                continue
            name = _clean(change["name"])
            faces = {h.lower() for handles in self.handles.values() for h in handles}
            # a handle is a face, not a name: "plays" as a name brought him to mind wherever the word was
            aka = [_clean(n) for n in change.get("aka") or [] if _clean(n) and _clean(n).lower() not in faces] \
                if isinstance(change.get("aka"), list) else []
            person = self.find(name) or next((self.find(n) for n in aka if self.find(n)), None)
            if person is None:
                person = {"name": name, "aka": [], "pronoun": "they", "gist": "", "goes_by": {}, "met": now,
                          "seen": now, "times": 0}
                self.known.append(person)
            before = dict(person, aka=list(person["aka"]), goes_by={k: list(v) for k, v in person["goes_by"].items()})
            if name.lower() != person["name"].lower():  # what she calls them now; the old name is another of theirs
                person["aka"].append(person["name"])
                person["name"] = name
            person["aka"] = list(dict.fromkeys(n for n in person["aka"] + aka if n.lower() != name.lower()))
            pronoun = _clean(change.get("pronoun")).lower()
            if pronoun in PRONOUNS:
                person["pronoun"] = pronoun
            gist = _clean(change.get("gist"), GIST_CHARS)
            if gist:
                person["gist"] = gist
                person["origins"] = change.get("origins", [])
                person["basis"] = change.get("basis", "unknown source")
            goes_by = change.get("goes_by") if isinstance(change.get("goes_by"), dict) else {}
            for app, handles in goes_by.items():
                for handle in handles if isinstance(handles, list) else [handles]:
                    seen = next((h for h in self.handles.get(app, {}) if h.lower() == _clean(handle).lower()), None)
                    if seen and seen not in person["goes_by"].get(app, []):
                        for other in self.known:  # a face is one person's
                            if other is not person and seen in other["goes_by"].get(app, []):
                                other["goes_by"][app].remove(seen)
                        person["goes_by"].setdefault(app, []).append(seen)
            person["times"] = person.get("times", 0) + 1
            person["seen"] = max(person.get("seen", 0.0), now)
            changed = changed or {k: v for k, v in before.items() if k not in ("times", "seen")} != \
                {k: v for k, v in person.items() if k not in ("times", "seen")}
        return changed

    def fade(self, now: float) -> List[str]:
        """Someone she met on few nights and has not seen for long is forgotten (the names that went)."""
        gone = [p["name"] for p in self.known if p.get("times", 0) < FAMILIAR and now - p.get("seen", now) > FADES]
        self.known = [p for p in self.known if p["name"] not in gone]
        return gone

    def listed(self) -> List[dict]:
        """For apps and the panel: everyone she knows, the most recently seen first."""
        return [{key: person.get(key) for key in ("name", "aka", "pronoun", "gist", "goes_by", "seen", "times")}
                for person in sorted(self.known, key=lambda p: -p.get("seen", 0.0))]
