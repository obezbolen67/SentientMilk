"""Artifacts: panels a turn puts in the user's chat, above the box they type in, for what she must not do herself.

``secrets``: what she must never see (a card number, a password, a code). She names the fields (browser_secrets);
the brain says where each goes as her browser sees it (the site, the field), the user types the values there, and
they come to the brain's memory only. Her browser types each into its own field (a fill step with ``secret``)
after checking it is still that field on that page, once: then the value is zeroed, as when the user takes it back
(closes the panel) or her turn ends (its bytes are; the copies Python makes of it on its way, the request's and
the one handed to the page, are freed, not wiped). She hears that it was typed, never what: values are in no event, result, log
or file, and a page that holds one gives her no picture, script or saved copy of it (browser.py).

``review``: an order before the user pays, as the shop's own page says it. She points at its parts (each line's
name, size, quantity, price and total, the charges, the total, the delivery slot, the address) and says why she
chose what she chose; the brain reads every part from the page, with a picture of the whole page, so the user checks
the page and her choices, never her memory of them. A yes is for the order with the fingerprint the user saw, read
again as they press it: an order that changed meanwhile is shown again with what changed, and waits for a new yes.
The panel itself never pays. The yes lets her browser press what pays for that order, in that turn, on its tab,
while the page still shows exactly that order (read again as she presses: ``approved``, ``unchanged``).

Apps hear ``artifact.requested``, ``artifact.updated`` and ``artifact.closed`` on the turn, list what is open with
``GET /v1/artifacts`` and answer with ``POST /v1/artifacts/<id>`` (client.artifact).
"""

import concurrent.futures
import hashlib
import json
import secrets as tokens
import threading
import time
from typing import Callable, Dict, List, Optional

from .exceptions import BrainError
from .toolkits import ToolError

WAIT = 0.25  # s between looks at whether the user stopped her or wrote to her while a panel waits
MOST = 4096  # characters a typed value may have
PARTS = {"name": "name", "size": "size", "quantity": "quantity", "price": "price", "total": "total"}


class Secret:
    """A value the user typed for one field, in memory only: its bytes are zeroed when it goes."""

    def __init__(self, artifact: "Artifact", field: dict):
        self.artifact, self.name, self.binding = artifact, field["name"], field["binding"]
        self.state = "waiting"  # for the user; then ready, typing, typed or refused
        self._value: Optional[bytearray] = None

    def keep(self, value: str) -> None:
        self.drop()
        self._value = bytearray(value.encode("utf-8"))
        self.state = "ready"

    def reveal(self) -> str:
        return bytes(self._value).decode("utf-8") if self._value is not None else ""

    def drop(self) -> None:
        if self._value is not None:
            self._value[:] = bytes(len(self._value))
            self._value = None


class Artifact:
    def __init__(self, kind: str, ctx, view: dict):
        self.id = "a" + tokens.token_hex(6)
        self.kind, self.ctx = kind, ctx
        self.app, self.session, self.run = ctx.app, ctx.session, ctx.run["id"]
        self.view = {"id": self.id, "kind": kind, "state": "open", "run": self.run, "session": self.session,
                     "asked": time.time(), **view}
        self.done: concurrent.futures.Future = concurrent.futures.Future()
        self.lock = threading.RLock()
        self.secrets: Dict[str, Secret] = {}
        # a review's: its parts (key, id), each snapshot shown by fingerprint, how to read the page again and show it
        self.wanted: List[tuple] = []
        self.seen: Dict[str, Dict[str, dict]] = {}
        self.again: Optional[Callable[[], tuple]] = None
        self.look: Optional[Callable[[dict], None]] = None
        self.read_on: Optional[Callable] = None  # its parts read from a tab in hand (as she presses pay)


def fingerprint(parts: Dict[str, dict]) -> str:
    """What the order says, every part's words by where it is: a yes holds for exactly these."""
    said = sorted((key, part.get("text")) for key, part in parts.items())
    return hashlib.sha256(json.dumps(said, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _what(key: str, view: dict) -> str:
    """A part's place in words: "line 2 price", "Delivery", "total"."""
    pieces = key.split(".")
    if pieces[0] == "lines":
        return f"line {int(pieces[1]) + 1} {pieces[2]}"
    if pieces[0] == "charges":
        return view["charges"][int(pieces[1])]["label"]
    return pieces[0]


class Artifacts:
    def __init__(self, brain):
        self.brain = brain
        self._open: Dict[str, Artifact] = {}
        self._approved: Dict[str, Artifact] = {}  # orders the user said yes to, until her turn ends
        self._lock = threading.Lock()

    def shown(self, app: str, session: str) -> List[dict]:
        """The panels open in a session, the oldest first (an app that opens the chat shows them)."""
        with self._lock:
            return [a.view for a in self._open.values() if a.app == app and a.session == session]

    # ============== Opening, waiting, closing ==============

    def _start(self, artifact: Artifact) -> None:
        with self._lock:
            self._open[artifact.id] = artifact
        artifact.ctx.emit({"type": "artifact.requested", "artifact": artifact.view})

    def _changed(self, artifact: Artifact) -> None:
        artifact.ctx.emit({"type": "artifact.updated", "artifact": artifact.view})

    def _close(self, artifact: Artifact, state: str) -> None:
        with self._lock:
            if self._open.pop(artifact.id, None) is None:
                return
        with artifact.lock:
            for secret in artifact.secrets.values():
                secret.drop()
            artifact.view["state"] = state
        artifact.ctx.emit({"type": "artifact.closed", "id": artifact.id, "state": state, "artifact": artifact.view})
        if not artifact.done.done():
            artifact.done.set_result({"action": state})

    def _wait(self, ctx, artifact: Artifact) -> dict:
        """The user's answer; a stop, or a message instead, closes the panel."""
        while True:
            try:
                return artifact.done.result(timeout=WAIT)
            except concurrent.futures.TimeoutError:
                pass
            if ctx.attention.stopped.is_set():
                self._close(artifact, "stopped")
            elif ctx.attention.woken.is_set():
                self._close(artifact, "message")

    def finished(self, run_id: int) -> None:
        """Her turn ended: what it asked for goes (values unused are zeroed), so no old panel types later, and
        no old yes pays later."""
        with self._lock:
            ending = [a for a in self._open.values() if a.run == run_id]
            for ident in [ident for ident, a in self._approved.items() if a.run == run_id]:
                del self._approved[ident]
        for artifact in ending:
            self._close(artifact, "ended")

    @staticmethod
    def _unanswered(answer: dict, nothing: str) -> str:
        return {"stopped": f"The user stopped you: the panel closed. {nothing}.",
                "message": f"The user wrote to you instead of answering the panel, which closed. {nothing}: read "
                           "what they said.",
                "cancelled": f"The user closed the panel. {nothing}: ask them how they want to go on.",
                "ended": f"The panel closed. {nothing}."}.get(answer["action"], f"The panel closed. {nothing}.")

    # ============== Secrets ==============

    def secrets(self, ctx, tab: str, url: str, fields: List[dict]) -> str:
        from .browser import site_of

        view = {"tab": tab, "url": url, "site": site_of(url),
                "fields": [{**{key: field[key] for key in ("name", "purpose", "target", "label", "site", "frame_site")},
                            "state": "waiting"} for field in fields]}
        artifact = Artifact("secrets", ctx, view)
        artifact.secrets = {field["name"]: Secret(artifact, field) for field in fields}
        self._start(artifact)
        answer = self._wait(ctx, artifact)
        if answer["action"] != "fill":
            return self._unanswered(answer, "Nothing was typed")
        first = fields[0]
        return (f"The user typed {', '.join(artifact.secrets)} in the panel: they wait for you, unseen. Type each "
                f"into its field with a fill step in browser_act, {{\"action\": \"fill\", \"target\": "
                f"\"{first['target']}\", \"secret\": \"{first['name']}\"}}: once each, into the field it was asked for "
                "(ask again to type one again). They are gone once typed, when the user takes them back, and when "
                "your turn ends.")

    def take(self, app: str, session: str, name: str) -> Secret:
        """The value the user typed for ``name``, to type now (the browser calls used() after, whatever happened)."""
        with self._lock:
            found = [a for a in reversed(list(self._open.values()))
                     if a.app == app and a.session == session and a.kind == "secrets" and name in a.secrets]
        for artifact in found:
            with artifact.lock:
                secret = artifact.secrets[name]
                if secret.state == "ready":
                    secret.state = "typing"
                    return secret
        raise ToolError(f"No value named {name or '?'} waits for you: ask the user for it with browser_secrets first "
                        "(each value types once; ask again to type it again).")

    def used(self, secret: Secret, refused: str = "") -> None:
        artifact = secret.artifact
        with artifact.lock:
            secret.drop()
            secret.state = "refused" if refused else "typed"
            for field in artifact.view["fields"]:
                if field["name"] == secret.name:
                    field["state"] = secret.state
                    if refused:
                        field["why"] = refused
            left = any(s.state in ("waiting", "ready", "typing") for s in artifact.secrets.values())
        if left:
            self._changed(artifact)
        else:
            self._close(artifact, "done")

    # ============== Reviews ==============

    def review(self, ctx, tab: str, url: str, title: str, order: dict, wanted: List[tuple], parts: List[dict],
               picture: str, again: Callable[[], tuple], look: Callable[[dict], None], read_on: Callable) -> str:
        from .browser import site_of

        lines = order["lines"]
        view = {"tab": tab, "url": url, "site": site_of(url), "title": title,
                "lines": [{"why": str(line.get("why") or "").strip()[:300]} for line in lines],
                "charges": [{"label": str(charge["label"]).strip()[:60]} for charge in order.get("charges") or []],
                "unverified": str(order.get("unverified") or "").strip()[:1000], "changes": []}
        artifact = Artifact("review", ctx, view)
        artifact.wanted, artifact.again, artifact.look, artifact.read_on = wanted, again, look, read_on
        self._show(artifact, dict(zip([key for key, _ in wanted], parts)), picture, url)
        self._start(artifact)
        answer = self._wait(ctx, artifact)
        if answer["action"] == "approve":
            total = artifact.view["total"]["text"]
            return (f"The user approved the order as the page shows it now ({len(lines)} lines, total \"{total}\"; "
                    f"fingerprint {answer['fingerprint']}). You may press its pay button now, in this turn, in "
                    f"{tab}: your browser lets you while the page still shows exactly this order (it reads it again "
                    "as you press). If the shop then asks for more (a code from their bank, a sign-in), that is the "
                    "user's: put the page in front of them (browser_act, the step show). Say what went through.")
        if answer["action"] == "rejected":
            reason = artifact.view.get("reason")
            return (f"The user rejected the order{': ' + reason if reason else ''}. Change what they want, then ask "
                    "again with browser_review.")
        return self._unanswered(answer, "Nothing was approved")

    def approved(self, ctx, tab: str) -> Optional[Artifact]:
        """The newest order the user approved in this turn for this tab: her browser may press its pay."""
        mine = (ctx.app, ctx.session, ctx.run["id"], tab)
        with self._lock:
            return next((a for a in reversed(list(self._approved.values()))
                         if (a.app, a.session, a.run, a.view["tab"]) == mine), None)

    @staticmethod
    def unchanged(artifact: Artifact, parts: List[dict]) -> bool:
        """The page still says exactly what the user approved (every part's words, as the panel read them)."""
        return fingerprint(dict(zip([key for key, _ in artifact.wanted], parts))) == artifact.view["fingerprint"]

    def _show(self, artifact: Artifact, parts: Dict[str, dict], picture: str, url: str) -> None:
        """The order as just read into the view: its parts where the panel shows them, fingerprinted."""
        view = artifact.view
        for key, part in parts.items():
            shown = {"key": key, "text": None if part.get("gone") else part.get("text", ""),
                     "rect": part.get("rect"), "page": part.get("page")}
            pieces = key.split(".")
            if pieces[0] == "lines":
                view["lines"][int(pieces[1])][pieces[2]] = shown
            elif pieces[0] == "charges":
                view["charges"][int(pieces[1])]["amount"] = shown
            else:
                view[pieces[0]] = shown
        printed = fingerprint(parts)
        artifact.seen[printed] = {key: {"text": None if part.get("gone") else part.get("text", ""),
                                        "id": part.get("id"), "path": part.get("path")}
                                  for key, part in parts.items()}
        view.update(fingerprint=printed, picture=picture, url=url, checked=time.time())

    def _read_again(self, artifact: Artifact) -> str:
        """The order read from the page now: the new fingerprint (the view shows it, and what changed)."""
        parts, picture, url = artifact.again()
        read = dict(zip([key for key, _ in artifact.wanted], parts))
        with artifact.lock:
            before = artifact.seen[artifact.view["fingerprint"]]
            self._show(artifact, read, picture, url)
            now = artifact.view["fingerprint"]
            if now != fingerprint(before):
                artifact.view["changes"] = [
                    {"what": _what(key, artifact.view), "was": before[key]["text"],
                     "now": None if read[key].get("gone") else read[key].get("text", "")}
                    for key in before if before[key]["text"] != (None if read[key].get("gone") else read[key].get("text", ""))]
                artifact.view["state"] = "changed"
        self._changed(artifact)
        return now

    def answer(self, artifact_id: str, action: str, values: Optional[dict] = None, fingerprint: str = "",
               reason: str = "", part: str = "") -> dict:
        """The user's answer to a panel: fill or cancel (secrets); approve, reject, refresh or show (review). The
        panel as it is after (a review that changed shows how, and waits for a new approval)."""
        with self._lock:
            artifact = self._open.get(artifact_id)
        if artifact is None:
            raise BrainError("artifact", "That panel is closed: she asks again if she still needs it.", http_status=409)
        if artifact.kind == "secrets":
            return self._answer_secrets(artifact, action, values)
        if action in ("reject", "cancel"):
            artifact.view["reason"] = str(reason or "").strip()[:500]
            self._close(artifact, "rejected")
        elif action == "show":
            source = artifact.seen[artifact.view["fingerprint"]].get(part)
            if source is None:
                raise ValueError("part is one of the order's parts (lines.0.price, total...)")
            artifact.look(source)
        elif action in ("refresh", "approve"):
            now = self._read_again(artifact)
            if action == "approve" and fingerprint == now:
                with artifact.lock:
                    if artifact.done.done():  # stopped meanwhile
                        raise BrainError("artifact", "That panel closed: she asks again if she still needs it.",
                                         http_status=409)
                    with self._lock:  # before she hears the yes: her next step may be the pay
                        self._approved[artifact.id] = artifact
                    artifact.done.set_result({"action": "approve", "fingerprint": now})
                self._close(artifact, "approved")
        else:
            raise ValueError("A review takes approve (with its fingerprint), reject, refresh or show")
        return artifact.view

    def _answer_secrets(self, artifact: Artifact, action: str, values) -> dict:
        if action == "cancel":
            self._close(artifact, "cancelled")
            return artifact.view
        if action != "fill":
            raise ValueError("A secrets panel takes fill (with values) or cancel")
        if artifact.view["state"] != "open":
            raise ValueError("Its values were given already: cancel takes them back")
        if not isinstance(values, dict) or set(values) != set(artifact.secrets) or \
                not all(isinstance(value, str) and 0 < len(value) <= MOST for value in values.values()):
            raise ValueError(f"fill takes a value for each field ({', '.join(artifact.secrets)}), of 1 to {MOST} "
                             "characters")  # its words never quote what was sent
        with artifact.lock:
            for name, secret in artifact.secrets.items():
                secret.keep(values[name])
            for field in artifact.view["fields"]:
                field["state"] = "ready"
            artifact.view["state"] = "ready"
        values.clear()
        self._changed(artifact)
        artifact.done.set_result({"action": "fill"})
        return artifact.view
