"""@ mentions: what the user points the brain at in a message (one of the app's sessions, an agent of this
session, a plugin, a file or folder), as a compact card the model reads with the message. The same cards
serve an app's picker preview and the sessions toolkit; the matches for the picker come from here too.
A card is stored with the message it came with, so the model sees the same text on every later call.

An attachment is a file mention with ``attached``: its card says Attached, a picture comes with the message as
an image the model sees (when it sees images), and the model may read the file (and inside an attached folder)
with the file tools from then on, wherever it is."""

import base64
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from . import transport
from .toolkits import ToolError
from .toolkits.files import IMAGES, closed

KINDS = ("session", "agent", "plugin", "file")
PICTURE_BYTES = 20 * 1024 * 1024  # an attached picture bigger than this goes as its path only
CARD_CHARS, CARDS_CHARS = 1_500, 10_000  # one card; all the cards of a message
PER_KIND, ONE_KIND = 5, 30  # matches of each kind, or of the one kind asked for
LAST_TURNS = 4  # entries in a session card: the last two exchanges
TURN_CHARS, SUMMARY_CHARS = 200, 600
FILE_LINES, FILE_CHARS, FOLDER_ENTRIES = 40, 2_000, 30
PATH = re.compile(r"^(~|/|\\|[A-Za-z]:)")


class Missing(ValueError):
    """What a mention names is not there (any more)."""


def short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def plural(count: int, word: str, many: Optional[str] = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


def stamp(at: Optional[float]) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if at else "never"


def size(count: int) -> str:
    for unit, step in (("B", 1), ("KB", 1024), ("MB", 1024 ** 2)):
        if count < step * 1024 or unit == "MB":
            return f"{count} B" if unit == "B" else f"{count / step:.1f} {unit}"
    return f"{count} B"


def shown(path: Path) -> str:
    """A path as the user writes it: their home folder as ~."""
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if os.path.normcase(text).startswith(os.path.normcase(home)) else text


# ============== Sessions ==============

def chats(brain, app: str) -> List[dict]:
    """The app's conversations that have something in them, newest first: not its agents' or tasks' sessions."""
    agents = {session for _, session, _ in brain.store.agent_sessions(app)}
    found = [s for s in brain.store.sessions(app) if s["last_active"] and s["id"] not in agents
             and not s["id"].startswith(("task-", "agent-", "summary-"))]
    return sorted(found, key=lambda s: s["last_active"], reverse=True)


def label(session: dict) -> str:
    return session["title"] or session["preview"] or session["id"]


def find_session(brain, app: str, ref: str) -> dict:
    """One of the app's conversations by id, or by its exact title."""
    text = str(ref or "").strip()
    found = chats(brain, app)
    match = next((s for s in found if s["id"] == text), None) or next(
        (s for s in found if (s["title"] or "").casefold() == text.casefold()), None)
    if match is None:
        raise Missing(f"No session {text} here; sessions_list shows them.")
    return match


def summary(brain, app: str, session: str) -> str:
    """The newest of its journal note and its compaction summary; '' while it has neither."""
    note = next(iter(brain.store.notes(limit=1, app=app, session=session)), None)
    compaction = brain.store.last_compaction(app, session)
    picks = ([(note["at"], note["note"])] if note else []) + ([(compaction["at"], compaction["summary"])]
                                                             if compaction and compaction.get("summary") else [])
    return max(picks)[1] if picks else ""


def journal_notes(brain, app: str, session: str) -> List[dict]:
    return brain.store.notes(app=app, session=session)


def turns(brain, app: str, session: str) -> List[List[dict]]:
    """Its plain turns (no tool calls): each a user message and the replies after it."""
    grouped: List[List[dict]] = []
    for entry in brain.history(app, session):
        if entry["role"] == "user" or not grouped:
            grouped.append([])
        grouped[-1].append(entry)
    return grouped


def speaker(entry: dict) -> str:
    return "user" if entry["role"] == "user" else "you"


def _session_card(brain, app: str, session: str, ref: str, kits: set) -> str:
    found = find_session(brain, app, ref)
    entries = brain.history(app, found["id"])
    said = [e for e in entries if e["role"] == "user"]
    lines = [f'[Mentioned session "{label(found)}" ({found["id"]}) · {plural(len(said), "turn")} · '
             f'last active {stamp(found["last_active"])}]']
    known = summary(brain, app, found["id"])
    lines.append("Summary: " + (short(known, SUMMARY_CHARS) if known else
                                f"none yet; it began with: {short(said[0]['text'], TURN_CHARS)}" if said else "none yet"))
    if entries:
        lines.append("Last turns:")
        lines += [f"  {speaker(e)}: {short(e['text'], TURN_CHARS)}" for e in entries[-LAST_TURNS:]]
    if "sessions" in kits:
        lines.append(f'If this is not enough: sessions_read(session="{found["id"]}", part="turns")')
    return "\n".join(lines)


# ============== Agents, plugins ==============

def _agent_card(brain, app: str, session: str, ref: str, kits: set) -> str:
    try:
        found = brain.agents.find(app, session, ref)
    except ToolError as exc:
        raise Missing(str(exc).replace("You have", "This chat has").replace("Your agents", "Its agents"))
    head = f'[Mentioned agent "{found["name"]}" (#{found["id"]}) · {found["status"]}'
    lines = [head + (f" · now: {short(found['activity'], 120)}]" if found["working"] and found["activity"] else "]"),
             "Task: " + short(found["task"], 400)]
    if found["report"]:
        lines.append("Report: " + short(found["report"], 700))
    elif found["error"]:
        lines.append("Error: " + short(found["error"], 300))
    else:
        progress = brain.agents.details(app, found)["progress"]
        if progress:
            lines.append("Progress: " + short(progress, 500))
    if "agents" in kits:
        lines.append(f'If this is not enough: agents_status(agent="{found["name"]}")')
    return "\n".join(lines)


def _plugin_card(brain, app: str, session: str, ref: str, kits: set) -> str:
    found = next((p for p in brain.plugins.public() if p["name"] == str(ref).strip()), None)
    if found is None:
        raise Missing(f"No plugin {ref} is installed.")
    head = (f'[Mentioned plugin "{found["name"]}" · {"on" if found["enabled"] else "off"} · '
            f'{"trusted" if found["trusted"] else "untrusted"} · {plural(found["tools"], "tool")}]')
    lines = [head, short(found["description"], 400) or "(no description)"]
    if found["toolkits"]:
        lines.append("Toolkits: " + ", ".join(found["toolkits"]))
    if found["error"]:
        lines.append("It failed to load: " + short(found["error"], 300))
    elif not found["enabled"]:
        lines.append("It is off: the user turns it on in SentientMilk's control panel (Plugins).")
    elif not found["trusted"]:
        lines.append("Its tools ask the user every time until they trust it.")
    return "\n".join(lines)


# ============== Files ==============

def _file_card(brain, app: str, session: str, ref: str, kits: set) -> str:
    path = Path(os.path.expanduser(str(ref).strip())).resolve()
    if closed(brain.home, path):
        raise ValueError(f"{path} is in SentientMilk's own folder (its settings, keys and plugins): it cannot be "
                         "mentioned.")
    if not path.exists():
        raise Missing(f"There is no file or folder {path}.")
    if path.is_dir():
        entries = sorted(_entries(path), key=lambda e: (not e[1], e[0].name.casefold()))
        lines = [f"[Mentioned folder {path} · {plural(len(entries), 'entry', 'entries')}]"]
        lines += [f"  {e.name}/" if is_dir else f"  {e.name} · {size(bytes_)}" for e, is_dir, bytes_ in
                  entries[:FOLDER_ENTRIES]]
        if len(entries) > FOLDER_ENTRIES:
            lines.append(f"  … {len(entries) - FOLDER_ENTRIES} more")
        if "files" in kits:
            lines.append(f'If this is not enough: files_find(pattern="*", path="{path}")')
        return "\n".join(lines)
    info = path.stat()
    lines = [f"[Mentioned file {path} · {size(info.st_size)} · modified {stamp(info.st_mtime)}]"]
    with open(path, "rb") as source:
        start = source.read(FILE_CHARS * 4)
    if b"\0" in start[:8192]:
        lines.append("It is binary: not shown.")
    else:
        text = start.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")
        body = "\n".join(text.split("\n")[:FILE_LINES])[:FILE_CHARS]
        lines.append(body)
        if body != text or info.st_size > len(start):
            lines.append(f"[only its first {plural(len(body.splitlines()), 'line')}]")
    if "files" in kits:
        lines.append(f'If this is not enough: files_read(path="{path}")')
    return "\n".join(lines)


def _entries(folder: Path) -> List[tuple]:
    """(entry, is a folder, size) of a folder's entries it can see."""
    found = []
    try:
        listed = list(folder.iterdir())
    except OSError:
        return []
    for entry in listed:
        try:
            is_dir = entry.is_dir()
            found.append((entry, is_dir, 0 if is_dir else entry.stat().st_size))
        except OSError:
            continue
    return found


def _files(brain, query: str) -> List[dict]:
    """The entries of the folder a typed path names that start with its last part, folders first."""
    raw = os.path.expanduser(query)
    if re.fullmatch(r"[A-Za-z]:", raw):
        raw += "\\"
    folder, start = (raw, "") if raw.endswith(("/", "\\")) else os.path.split(raw)
    base = Path(folder or os.sep)
    found = [(e, is_dir, bytes_) for e, is_dir, bytes_ in _entries(base)
             if e.name.casefold().startswith(start.casefold()) and (start.startswith(".") or not e.name.startswith("."))
             and not closed(brain.home, e.resolve())]
    found.sort(key=lambda e: (not e[1], e[0].name.casefold()))
    return [{"kind": "file", "ref": str(e), "label": shown(e), "note": "folder" if is_dir else size(bytes_),
             "time": None} for e, is_dir, bytes_ in found[:ONE_KIND]]


# ============== Cards and matches ==============

CARDS = {"session": _session_card, "agent": _agent_card, "plugin": _plugin_card, "file": _file_card}


def card(brain, app: str, session: str, kind: str, ref: str) -> str:
    """The card for what a mention names, made in ``session`` (its agents are that session's)."""
    if kind not in KINDS:
        raise ValueError(f"mention kind must be one of: {', '.join(KINDS)}")
    if not str(ref or "").strip():
        raise ValueError("a mention needs a ref: the session, agent, plugin or path it names")
    kits = set(brain.profile(app, session)["toolkits"])
    text = CARDS[kind](brain, app, session, str(ref), kits)
    return text if len(text) <= CARD_CHARS else text[:CARD_CHARS - 1] + "…"


def candidates(brain, app: str, session: str, query: str = "", kind: Optional[str] = None) -> List[dict]:
    """What a picker offers for ``query``: {kind, ref, label, note, time}, grouped by kind. A query that looks
    like a path lists that folder; sessions are newest first and the open one is left out."""
    if kind is not None and kind not in KINDS:
        raise ValueError(f"mention kind must be one of: {', '.join(KINDS)}")
    text = (query or "").strip()
    if PATH.match(text):
        return _files(brain, text) if kind in (None, "file") else []
    limit, needle, found = ONE_KIND if kind else PER_KIND, text.casefold(), []
    if kind in (None, "session"):
        rows = [s for s in chats(brain, app) if s["id"] != session
                and needle in f"{s['title'] or ''} {s['preview']} {s['id']}".casefold()]
        found += [{"kind": "session", "ref": s["id"], "label": label(s), "note": "", "time": s["last_active"]}
                  for s in rows[:limit]]
    if kind in (None, "agent"):
        rows = [a for a in brain.agents.open(app, session) if needle in f"{a['name']} {a['task']}".casefold()]
        found += [{"kind": "agent", "ref": a["name"], "label": a["name"], "note": a["status"], "time": a["updated"]}
                  for a in rows[:limit]]
    if kind in (None, "plugin"):
        rows = [p for p in brain.plugins.public() if needle in f"{p['name']} {p['description']}".casefold()]
        found += [{"kind": "plugin", "ref": p["name"], "label": p["name"],
                   "note": "broken" if p["error"] else plural(p["tools"], "tool") if p["enabled"] else "off",
                   "time": None} for p in rows[:limit]]
    return found


def resolve(brain, app: str, session: str, items: List[dict]) -> List[dict]:
    """Turn input with each mention's card filled in, and each attached picture after its card. One that names
    nothing any more becomes a line saying so; the turn goes on either way."""
    room, result, pictures = CARDS_CHARS, [], 0
    for item in items:
        if item["type"] != "mention" or "card" in item:
            result.append(item)
            continue
        verb, picture = "Attached" if item.get("attached") else "Mentioned", None
        try:
            if item.get("attached"):
                text, picture = attachment(brain, app, session, item["ref"], pictures)
            else:
                text = card(brain, app, session, item["kind"], item["ref"])
        except Missing:
            text = f"[{verb} {item['kind']} {item['ref']}: it no longer exists]"
        except (ValueError, OSError) as exc:
            text = f"[{verb} {item['kind']} {item['ref']}: {exc}]"
        if len(text) > room:  # past the room each card keeps its first line, what it names; the tools show the rest
            text = text.split("\n", 1)[0] + ("" if item.get("attached") else
                                             "\n[The rest of this card is left out for room: your tools show it.]")
        room -= len(text)
        result.append({**item, "card": text})
        if picture:
            result.append(picture)
            pictures += 1
    return result


def attachment(brain, app: str, session: str, ref: str, pictures: int = 0) -> tuple:
    """(card, picture or None) for a file the user attached: a picture comes as an image item the model sees,
    or, when it cannot, its path and why. From now on the model may read it with the file tools."""
    path = Path(os.path.expanduser(str(ref).strip())).resolve()
    if closed(brain.home, path):
        raise ValueError(f"{path} is in SentientMilk's own folder (its settings, keys and plugins): it cannot be "
                         "attached.")
    if not path.exists():
        raise Missing(f"There is no file or folder {path}.")
    _open_to(brain, app, session, path)
    if not (path.is_file() and path.suffix.lower() in IMAGES):
        return _file_card(brain, app, session, str(path), set(brain.profile(app, session)["toolkits"])).replace(
            "[Mentioned", "[Attached", 1), None
    info = path.stat()
    head = f"[Attached picture {path} · {size(info.st_size)} · modified {stamp(info.st_mtime)}"
    if not brain.config.values()["vision"]:
        return f"{head}: only its path, as images are off here]", None
    if info.st_size > PICTURE_BYTES:
        return f"{head}: only its path, as it is bigger than {size(PICTURE_BYTES)}]", None
    try:
        url = transport.validate_image(f"data:{IMAGES[path.suffix.lower()]};base64,"
                                       + base64.b64encode(path.read_bytes()).decode("ascii"))
    except ValueError:
        return f"{head}: only its path, as it does not read as a picture]", None
    return f"{head}: picture {pictures + 1} with this message]", {
        "type": "image", "url": transport.encode_image(url, brain.config.values()["image_pixels"])}


def _open_to(brain, app: str, session: str, path: Path) -> None:
    """The model may read what the user attached, wherever it is (files.resolve)."""
    def change(state):
        opened = state.setdefault("attached", [])
        if str(path) not in opened:
            opened.append(str(path))
        return state
    brain.store.update_session(app, session, "state", change)


def stored(items: List[dict]) -> dict:
    """What an input event keeps of its mentions, for apps to show them again: {} without any."""
    found = [{"kind": i["kind"], "ref": i["ref"], "label": i["label"], **({"attached": True} if i.get("attached") else {})}
             for i in items if i["type"] == "mention"]
    return {"mentions": found} if found else {}
