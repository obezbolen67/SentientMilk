"""The people in her life, known as a person knows people (design: docs/superpowers/specs/2026-11-17-people-design.md).

Nothing here is typed in by anyone: she recognizes whoever an app shows as the person she talks with (its
handle, "user: plays" in a turn's context, is her face: it brings the whole person to mind), remembers moments
with who was in them, hears a name and thinks of that person, and learns who people are the way memory does,
in her sleep: going over what happened, she updates what she knows of each person in it (Mind._meet_people).
Someone met on few days and not seen for a long time is forgotten; whoever is around stays.

With her mind's prompts saying only "the user", a rumination of hers called the user "she".
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
        # the name she goes by, as her nights settled it from what she lived through (None: not settled yet)
        self.me: Optional[dict] = saved.get("me")

    def to_dict(self) -> dict:
        return {"known": self.known, "handles": self.handles, "me": self.me}

    def _mine(self, name: str) -> bool:
        """Whether ``name`` is one of hers."""
        return bool(self.me) and _clean(name).lower() in [n.lower() for n in [self.me["name"], *self.me["aka"]]]

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
        gist = person.get("gist") or "little known of them yet"
        return f"{person['name']} ({person.get('pronoun') or 'they'}): {gist}"

    # ============== Learning ==============

    def update(self, changes, now: float) -> bool:
        """What sleep made of the people in what happened (the people step's answer): each one known is set
        right, each new one is met. A handle counts only if she has seen it in that app (a face she never saw is
        no face of theirs). Whether anything changed."""
        changed = False
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict) or not _clean(change.get("name")) or self._mine(change["name"]):
                continue  # she is not one of the people in her life
            name = _clean(change["name"])
            aka = [n for n in self._names(change.get("aka")) if not self._mine(n)]
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

    def _names(self, names) -> List[str]:
        """Other names as an answer gave them, never an app's handle: a handle is a face, not a name ("plays" as a
        name brought him to mind wherever the word was)."""
        faces = {h.lower() for handles in self.handles.values() for h in handles}
        return [_clean(n) for n in names if _clean(n) and _clean(n).lower() not in faces] \
            if isinstance(names, list) else []

    def name_me(self, change, now: float, origins: Iterable[int] = ()) -> bool:
        """The name she goes by now, as sleep settled it from the moments ``origins`` (the people step's "self"):
        a new one makes the old one another of hers, and her names are nobody else's. Whether it changed."""
        if not isinstance(change, dict) or not _clean(change.get("name")):
            return False
        name, before = _clean(change["name"]), self.me
        renamed = before is None or name.lower() != before["name"].lower()
        names = ([before["name"]] if renamed and before else []) + (before["aka"] if before else []) \
            + self._names(change.get("aka"))
        aka = []
        for other in names:
            if other.lower() not in [n.lower() for n in [name, *aka]]:
                aka.append(other)
        self.me = {"name": name if renamed else before["name"], "aka": aka, "since": now if renamed else before["since"],
                   "origins": list(origins) if renamed or not before else before["origins"]}
        self.known = [person for person in self.known if not self._mine(person["name"])]
        for person in self.known:
            person["aka"] = [n for n in person["aka"] if not self._mine(n)]
        return self.me != before

    def fade(self, now: float) -> List[str]:
        """Someone she met on few nights and has not seen for long is forgotten (the names that went)."""
        gone = [p["name"] for p in self.known if p.get("times", 0) < FAMILIAR and now - p.get("seen", now) > FADES]
        self.known = [p for p in self.known if p["name"] not in gone]
        return gone

    def listed(self) -> List[dict]:
        """For apps and the panel: everyone she knows, the most recently seen first."""
        return [{key: person.get(key) for key in ("name", "aka", "pronoun", "gist", "goes_by", "seen", "times")}
                for person in sorted(self.known, key=lambda p: -p.get("seen", 0.0))]
