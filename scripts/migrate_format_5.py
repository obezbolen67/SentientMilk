"""One-off: bring a SentientMilk home at data format 4 to format 5, once, with the brain stopped.

    python scripts/migrate_format_5.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-5-<time>/ (SQLite's backup, WAL and all). Then:

brain.sqlite3  each turn's decision keeps what her learned reactions called for as she read it as ``called`` (in
               lots; format 4 kept it as ``reacted``, though it was not what they did), and, apart from it, what they
               measurably moved: ``reacted``, from her body's push log (each push of a reaction, or of the relief
               from one, in the turn's chat from the turn's coming to her decision; a channel they called for that
               did not move is 0), and ``external``, how reading it moved her less that. A turn from before her push
               log began keeps ``called`` only: what its reactions moved was not measured, and it has no ``external``.
mind.sqlite3   her last decision's path keeps what its reactions called for as ``predicted`` and what they
               measurably moved, read as for its turn, as ``moved`` (from before the log: let go, not known). Her
               last reactions (``self["reacted"]``, what an app shows of her latest) are let go: what each moved is not
               in the log as its own (several set off in one tick of her body's clock are logged at one time), and
               her next ones are kept as they are. Nothing she learned is in them.

What she learned (the ``reactions`` table) is not touched: what to do with what the fault taught her is the
user's to decide (scripts/replay_reactions.py shows it, as a dry run). No table changes shape: every table,
column, index and trigger is checked to be as in a database made now (anything else stops it, nothing changed),
and each database is stamped with format 5 and opened with the current code. A home at format 5 is left as it is.
The script lives on only in git.
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
from sentientmilk_framework.mind import workspace  # noqa: E402
from sentientmilk_framework.mind.feel import CHANNELS  # noqa: E402
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

NAMES = ("brain", "mind", "recall")
FROM = 4
REACTING = ("reacting to:", "relief:")
# her body's clock is brought up to the present in steps of this many seconds before a reaction: a push logged
# for a reading is at most this much before the turn came
TICK = 5.0


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
    workspace.Workspace(memory._db, memory._lock)
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
    out += [f"table {name} is missing" for name in wanted["tables"] if name not in found["tables"]]
    for name, columns in found["tables"].items():
        if name in wanted["tables"] and columns != wanted["tables"][name]:
            out.append(f"table {name}: has {sorted(columns - wanted['tables'][name])}, "
                       f"lacks {sorted(wanted['tables'][name] - columns)}")
    out += [f"{kind} {name} on {table} is not made now" for kind, name, table in found["others"] - wanted["others"]]
    return out


def _back_up(home: Path) -> Path:
    folder = home / time.strftime("before-format-5-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _lots(change: dict) -> dict:
    return {name: value / CHANNELS[name][1] for name, value in change.items() if name in CHANNELS}


def _reading(mind: sqlite3.Connection, chat: str, came: float, decided: float, called: dict) -> dict:
    """What her reactions measurably moved as she read a turn, in lots: their pushes (and the relief from one) in
    its chat from its coming to her decision; a channel they called for that did not move is 0."""
    moved = dict.fromkeys(called, 0.0)
    for why, change in mind.execute("SELECT why, moved FROM body_pushes WHERE chat = ? AND at > ? AND at <= ?",
                                    (chat, came - TICK, decided)):
        if (why or "").startswith(REACTING):
            for name, value in _lots(json.loads(change)).items():
                moved[name] = moved.get(name, 0.0) + value
    return {name: round(value, 4) for name, value in moved.items()}


def _brain(brain: sqlite3.Connection, mind: sqlite3.Connection, logged: float) -> dict:
    measured = unmeasured = 0
    for row in brain.execute("SELECT id, created, app, session, options FROM runs").fetchall():
        options = json.loads(row["options"] or "{}")
        decision = options.get("mind")
        if not isinstance(decision, dict) or "reacted" not in decision or "called" in decision:
            continue
        decision["called"] = decision.pop("reacted") or {}
        if row["created"] - TICK >= logged:
            decision["reacted"] = _reading(mind, f"{row['app']}\n{row['session']}", row["created"], decision["at"],
                                           decision["called"])
            decision["external"] = {name: round(change - decision["reacted"].get(name, 0.0), 4)
                                    for name, change in (decision.get("way") or {}).items()}
            measured += 1
        else:
            unmeasured += 1
        brain.execute("UPDATE runs SET options = ? WHERE id = ?", (json.dumps(options), row["id"]))
    return {"turns measured": measured, "turns from before the push log": unmeasured}


def _mind(mind: sqlite3.Connection, brain: sqlite3.Connection, logged: float) -> dict:
    row = mind.execute("SELECT value FROM state WHERE key = 'self'").fetchone()
    if row is None:
        return {"latest reactions let go": 0}
    me = json.loads(row["value"])
    # what each of her latest reactions measurably moved is not in the log as its own: several set off in one
    # tick of her body's clock (a busy turn's actions) are logged at one time, and summed they moved more than a
    # level can (on a copy of the user's brain); they are let go, and her next reactions are kept as they are
    gone = len(me.get("reacted") or [])
    me["reacted"] = []
    path = (me.get("decided") or {}).get("path") or {}
    if path.get("reacted"):
        run = brain.execute("SELECT created FROM runs WHERE id = ?", (me["decided"]["run"],)).fetchone()
        old = path["reacted"]
        path["reacted"] = {"text": old["text"], "predicted": old["moved"],
                           "moved": _reading(mind, f"{me['decided']['app']}\n{me['decided']['session']}", run["created"],
                                             me["decided"]["at"], old["moved"])} \
            if run is not None and run["created"] - TICK >= logged else None
    mind.execute("UPDATE state SET value = ? WHERE key = 'self'", (json.dumps(me),))
    return {"latest reactions let go": gone}


def migrate(home: Path) -> dict:
    """Format 5 for the home's databases: what was done (counts), and where the copy from before is."""
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
        return {"done": f"already at format {dataformat.FORMAT}"}
    if any(version != FROM for version in versions.values()):
        raise Refused(f"Formats {versions}: this script knows format {FROM} only.")
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
        logged = dbs["mind"].execute("SELECT MIN(at) FROM body_pushes").fetchone()[0]
        logged = float("inf") if logged is None else logged
        report.update(_brain(dbs["brain"], dbs["mind"], logged))
        report.update(_mind(dbs["mind"], dbs["brain"], logged))
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
    Memory(paths["mind"]).close()
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
