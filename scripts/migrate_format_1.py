"""One-off: bring a SentientMilk home from before the data format stamp to format 1, once, with the brain stopped.

    python scripts/migrate_format_1.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-1-<time>/ (SQLite's backup, WAL and all). Then:

brain.sqlite3  every message keeps the chat memory it found, worked out as a return did (the chat's saves and
               forgets of the chat's own memory before it, and those of the chat's summary runs over what came
               before it), with the scope each save had when it was made; the summary sessions and their runs go; the facts and journal notes are made sure of as
               units of her long-term memory, then the memory, memory_revisions and journal tables go; the run and
               session keys nothing reads go.
mind.sqlite3   feeling words she never said herself go, hers lose the "hers" mark; her mind's "logic", the
               people's "met_past", the body's "entrained" and its sleep "model" go; episodes lose first_text.
recall.sqlite3 a fact unit for every fact, a note unit for every note of a chat still there.

Every table, column, index and trigger is then as in a database made now (anything else stops it, nothing
changed), and each database is stamped with format 1 and opened with the current code. A home at format 1 is left
as it is. The script and this change's code for older shapes live on only in git.
"""

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentientmilk_framework import dataformat  # noqa: E402
from sentientmilk_framework.loop import TERMINAL  # noqa: E402
from sentientmilk_framework.mind.feel import Concepts  # noqa: E402
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall, chunks  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

NAMES = ("brain", "mind", "recall")
MEMORY_TOOLS = ("memory_save", "memory_forget")


class Refused(RuntimeError):
    pass


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def _no_config():
    return SimpleNamespace(config=SimpleNamespace(values=lambda: {}))


def _made_now(folder: Path) -> dict:
    """Each database as the current code makes it: {name: path}."""
    Store(folder / "brain.sqlite3")
    memory = Memory(folder / "mind.sqlite3")
    Reactions(memory._db, memory._lock)
    memory.close()
    Recall(_no_config(), folder / "recall.sqlite3").stop()
    return {name: folder / f"{name}.sqlite3" for name in NAMES}


def _shape(db: sqlite3.Connection) -> dict:
    """Tables with their columns, and the indexes and triggers, by name."""
    tables, others = {}, set()
    for row in db.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"):
        if row["type"] == "table":
            tables[row["name"]] = {(c["name"], c["type"].upper(), c["notnull"], c["dflt_value"], c["pk"])
                                   for c in db.execute(f'PRAGMA table_info("{row["name"]}")')}
        else:
            others.add((row["type"], row["name"], row["tbl_name"]))
    return {"tables": tables, "others": others}


def _differences(found: dict, wanted: dict) -> list:
    out = [f"table {name} is not made now" for name in found["tables"] if name not in wanted["tables"]]
    for name, columns in found["tables"].items():
        if name in wanted["tables"] and columns != wanted["tables"][name]:
            out.append(f"table {name}: has {sorted(columns - wanted['tables'][name])}, "
                       f"lacks {sorted(wanted['tables'][name] - columns)}")
    out += [f"{kind} {name} on {table} is not made now" for kind, name, table in found["others"] - wanted["others"]]
    return out


def _back_up(home: Path) -> Path:
    folder = home / time.strftime("before-format-1-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _chats_calls(brain: sqlite3.Connection) -> dict:
    """{(app, chat): [(event id, call)]}: the calls that changed each chat's own memory, its summary runs' with it
    (as of their ``upto``: the message they went over up to), oldest first. A save with a category and no scope
    changed the lasting memory (its default until 0.30, when the chat's became the only one): a return since 0.30
    took it for the chat's, and lasting facts came into old chats' memory."""
    calls = {}
    for row in brain.execute("SELECT id, app, session, data FROM events WHERE type = 'tool' ORDER BY id"):
        data = json.loads(row["data"])
        arguments = data.get("arguments") or {}
        scope = arguments.get("scope") or ("everywhere" if "category" in arguments else "session")
        if data.get("name") in MEMORY_TOOLS and data.get("status") == "ok" and scope == "session":
            calls.setdefault((row["app"], row["session"]), []).append((row["id"], data, None))
    for row in brain.execute("SELECT app, session, options FROM runs WHERE kind = 'summary' AND status = 'completed'"):
        options = json.loads(row["options"])
        for event, data, _ in calls.get((row["app"], row["session"]), []):
            calls.setdefault((row["app"], options.get("chat")), []).append((event, data, options.get("upto")))
    return calls


def _memory_found(brain: sqlite3.Connection, calls: dict) -> dict:
    """{input event id: the chat memory as the message found it}."""
    found = {}
    for row in brain.execute("SELECT id, app, session FROM events WHERE type = 'input'"):
        target, kept = row["id"], {}
        mine =[(event, call) for event, call, upto in calls.get((row["app"], row["session"]), [])
                if (event < target if upto is None else upto < target)]
        for _, call in sorted(mine, key=lambda item: item[0]):
            arguments = call.get("arguments") or {}
            key = str(arguments.get("key", "")).strip()
            if call["name"] == "memory_save":
                kept[key] = str(arguments.get("value", "")).strip()
            else:
                kept.pop(key, None)
        found[target] = kept
    return found


def _units_of_old_memory(brain: sqlite3.Connection, recall: sqlite3.Connection) -> dict:
    """Fact and note units for what the old memory held, as recall took them in: how many were added and removed."""
    counts = {"facts added": 0, "facts removed": 0, "notes added": 0}

    def add(source, ref, app, session, at, text):
        recall.execute("DELETE FROM units WHERE source = ? AND substr(ref, 1, ?) = ?", (source, len(ref) + 1, f"{ref}#"))
        for n, piece in enumerate(chunks(" ".join(str(text).split()))):
            recall.execute("INSERT INTO units (source, ref, app, session, at, text) VALUES (?, ?, ?, ?, ?, ?)",
                           (source, f"{ref}#{n}", app, session, at, piece))

    tables = {row[0] for row in brain.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "memory" in tables:
        entries = {f"{row['category']}/{row['key']}": row for row in brain.execute("SELECT * FROM memory")}
        have = {row["ref"].rsplit("#", 1)[0]: row["at"] for row in recall.execute(
            "SELECT ref, at FROM units WHERE source = 'fact' AND ref LIKE '%#0'")}
        for ref in have:
            if ref not in entries:
                recall.execute("DELETE FROM units WHERE source = 'fact' AND substr(ref, 1, ?) = ?", (len(ref) + 1, f"{ref}#"))
                counts["facts removed"] += 1
        for ref, entry in entries.items():
            if have.get(ref) != entry["updated"]:
                add("fact", ref, entry["app"] or "", "", entry["updated"], f"{entry['key']}: {json.loads(entry['value'])}")
                counts["facts added"] += 1
    if "journal" in tables:
        have = {row[0].rsplit("#", 1)[0] for row in recall.execute(
            "SELECT ref FROM units WHERE source = 'note' UNION SELECT ref FROM forgotten WHERE source = 'note'")}
        chats = {(row[0], row[1]) for row in brain.execute("SELECT app, id FROM sessions")}
        for note in brain.execute("SELECT id, at, app, session, note FROM journal"):
            if str(note["id"]) not in have and (note["app"], note["session"]) in chats:
                add("note", str(note["id"]), note["app"], note["session"], note["at"], note["note"])
                counts["notes added"] += 1
    return counts


def _brain(brain: sqlite3.Connection) -> dict:
    counts = {}
    calls = _chats_calls(brain)
    found = _memory_found(brain, calls)
    for row in brain.execute("SELECT id, data FROM events WHERE type = 'input'").fetchall():
        data = json.loads(row["data"])
        if "memory" not in data:
            brain.execute("UPDATE events SET data = ? WHERE id = ?", (json.dumps({**data, "memory": found[row["id"]]}), row["id"]))
    counts["messages given their chat memory"] = len(found)
    runs = [row[0] for row in brain.execute("SELECT id FROM runs WHERE kind = 'summary'")]
    sessions = [tuple(row) for row in brain.execute("SELECT DISTINCT app, session FROM runs WHERE kind = 'summary'")]
    marks = ",".join("?" * len(runs))
    for table, column in (("events", "run"), ("jobs", "run"), ("file_versions", "run"), ("agent_mail", "run"),
                          ("schedule_occurrences", "run")):
        if runs:
            counts[f"{table} of summary runs"] = brain.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", runs).rowcount
    for table in ("events", "jobs", "file_versions", "notifications", "schedule_occurrences"):
        counts[f"{table} of summary sessions"] = sum(
            brain.execute(f"DELETE FROM {table} WHERE app = ? AND session = ?", chat).rowcount for chat in sessions)
    counts["summary sessions"] = sum(brain.execute("DELETE FROM sessions WHERE app = ? AND id = ?", chat).rowcount
                                     for chat in sessions)
    counts["summary runs"] = brain.execute("DELETE FROM runs WHERE kind = 'summary'").rowcount
    for row in brain.execute("SELECT id, status, options FROM runs").fetchall():
        options = json.loads(row["options"])
        kept = {k: v for k, v in options.items()
                if k != "steer_user" and not (row["status"] in TERMINAL and k in ("steer", "steer_batches"))}
        if kept != options:
            brain.execute("UPDATE runs SET options = ? WHERE id = ?", (json.dumps(kept), row["id"]))
            counts["runs tidied"] = counts.get("runs tidied", 0) + 1
    for row in brain.execute("SELECT app, id, state FROM sessions").fetchall():
        state = json.loads(row["state"])
        kept = {k: v for k, v in state.items() if k not in ("journaled_upto", "summarized")}
        saved = {str((call.get("arguments") or {}).get("key", "")).strip()
                 for _, call, _ in calls.get((row["app"], row["id"]), []) if call["name"] == "memory_save"}
        stray = set(kept.get("session_memory") or {}) - saved  # never saved to the chat's own memory: a return put it
        if stray:
            counts["lasting facts out of a chat's memory"] = counts.get("lasting facts out of a chat's memory", 0) + len(stray)
            kept["session_memory"] = {k: v for k, v in kept["session_memory"].items() if k not in stray}
        if kept != state:
            brain.execute("UPDATE sessions SET state = ? WHERE app = ? AND id = ?", (json.dumps(kept), row["app"], row["id"]))
            counts["sessions tidied"] = counts.get("sessions tidied", 0) + 1
    for table in ("memory", "memory_revisions", "journal"):
        brain.execute(f"DROP TABLE IF EXISTS {table}")
    return counts


def _mind(mind: sqlite3.Connection) -> dict:
    counts = {}
    state = {row["key"]: json.loads(row["value"]) for row in mind.execute("SELECT key, value FROM state")}
    if "concepts" in state:
        hers = [{k: v for k, v in concept.items() if k != "hers"} for concept in state["concepts"]
                if isinstance(concept, dict) and concept.get("hers")]
        counts["feeling words given to her, gone"] = len(state["concepts"]) - len(hers)
        state["concepts"] = [Concepts._read(concept) for concept in hers]
    state.get("self", {}).pop("logic", None)
    state.get("people", {}).pop("met_past", None)
    if "body" in state:
        state["body"].pop("entrained", None)
        (state["body"].get("sleep") or {}).pop("model", None)
    for key, value in state.items():
        mind.execute("UPDATE state SET value = ? WHERE key = ?", (json.dumps(value), key))
    if "first_text" in {row[1] for row in mind.execute("PRAGMA table_info(episodes)")}:
        mind.execute("ALTER TABLE episodes DROP COLUMN first_text")
    return counts


def migrate(home: Path) -> dict:
    """Format 1 for the home's databases: what was done (counts), and where the copy from before is."""
    home = Path(home).expanduser()
    paths = {name: home / f"{name}.sqlite3" for name in NAMES}
    if (home / "server.json").exists():
        raise Refused(f"The brain looks to be running ({home / 'server.json'}): stop it first.")
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise Refused(f"Not a SentientMilk home: {', '.join(missing)} missing.")
    versions = {}
    for name, path in paths.items():
        db = sqlite3.connect(str(path))
        versions[name] = db.execute("PRAGMA user_version").fetchone()[0]
        db.close()
    if all(version == dataformat.FORMAT for version in versions.values()):
        return {"done": "already at format 1"}
    if any(version not in (0, dataformat.FORMAT) for version in versions.values()):
        raise Refused(f"Formats {versions}: this script knows format 0 only.")
    backup = _back_up(home)
    with tempfile.TemporaryDirectory() as folder:
        wanted = {}
        for name, path in _made_now(Path(folder)).items():
            db = _connect(path)
            wanted[name] = _shape(db)
            db.close()
    dbs = {name: _connect(path) for name, path in paths.items()}
    report = {"backup": str(backup)}
    try:
        for db in dbs.values():
            db.execute("BEGIN IMMEDIATE")
        if versions["recall"] == 0:
            report.update(_units_of_old_memory(dbs["brain"], dbs["recall"]))
        if versions["brain"] == 0:
            report.update(_brain(dbs["brain"]))
        if versions["mind"] == 0:
            report.update(_mind(dbs["mind"]))
        problems = [f"{name}: {problem}" for name, db in dbs.items() for problem in _differences(_shape(db), wanted[name])]
        if problems:
            raise Refused("Left as it was: shapes this script does not know:\n  " + "\n  ".join(problems))
        for db in dbs.values():
            db.execute(f"PRAGMA user_version = {dataformat.FORMAT}")
        for db in dbs.values():
            db.execute("COMMIT")
    except BaseException:
        for db in dbs.values():
            if db.in_transaction:
                db.execute("ROLLBACK")
        raise
    finally:
        for db in dbs.values():
            db.close()
    Store(paths["brain"])
    memory = Memory(paths["mind"])
    Concepts(memory.get("concepts") or [])
    memory.close()
    Recall(_no_config(), paths["recall"]).stop()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", required=True, help="the brain's home folder (the brain stopped)")
    args = parser.parse_args()
    try:
        report = migrate(Path(args.home))
    except Refused as exc:
        raise SystemExit(str(exc))
    for what, value in report.items():
        print(f"{what}: {value}")


if __name__ == "__main__":
    main()
