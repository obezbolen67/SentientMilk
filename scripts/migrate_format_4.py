"""One-off: bring a SentientMilk home at data format 3 to format 4, once, with the brain stopped.

    python scripts/migrate_format_4.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-4-<time>/ (SQLite's backup, WAL and all). Then:

mind.sqlite3   what is on her mind (0.47) gets its table, ``workspace``, and the vectors of its words beside it
               (``workspace_vectors``, as her moments and learned cues have theirs); empty: her records come onto
               it as she reads them. Each thing she put off keeps the turn she put it off in (``run``), as
               concerns have since it was added: the turn whose moment of that chat was kept first after it, if
               that turn had begun by then; else None (it was not kept). A thought taking it up goes over that
               turn and what came of it.

No other table changes shape: every table, column, index and trigger is checked to be as in a database made now
(anything else stops it, nothing changed), and each database is stamped with format 4 and opened with the
current code. A home at format 4 is left as it is. The script lives on only in git.
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
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402
from sentientmilk_framework.vectors import schema  # noqa: E402

NAMES = ("brain", "mind", "recall")
FROM = 3


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
    folder = home / time.strftime("before-format-4-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _turn(mind: sqlite3.Connection, brain: sqlite3.Connection, concern: dict):
    """The run of the turn she put ``concern`` off in: the first moment of its chat kept after it, if its turn
    had begun by then (before() puts it off, after() keeps the moment); None if that turn was not kept."""
    row = mind.execute("SELECT run_id FROM episodes WHERE app = ? AND session = ? AND kind = 'exchange' AND at >= ? "
                       "AND run_id IS NOT NULL ORDER BY at LIMIT 1",
                       (concern["app"], concern["session"], concern["at"])).fetchone()
    if row is None:
        return None
    run = brain.execute("SELECT created FROM runs WHERE id = ?", (row["run_id"],)).fetchone()
    return row["run_id"] if run is not None and run["created"] <= concern["at"] else None


def _statements(script: str) -> list:
    """A script's statements one by one (a trigger's body holds semicolons), to run in the migration's
    transaction (executescript would commit it)."""
    out, current = [], ""
    for line in script.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            out.append(current.strip())
            current = ""
    return out


def _mind(mind: sqlite3.Connection, brain: sqlite3.Connection) -> dict:
    for statement in _statements(workspace.SCHEMA + "\n" + schema("workspace")):
        mind.execute(statement)
    row = mind.execute("SELECT value FROM state WHERE key = 'self'").fetchone()
    if row is None:
        return {"concerns given their turn": 0, "concerns whose turn was not kept": 0}
    me = json.loads(row["value"])
    given = lost = 0
    for concern in me.get("concerns") or []:
        if "run" not in concern:
            concern["run"] = _turn(mind, brain, concern)
            given, lost = given + (concern["run"] is not None), lost + (concern["run"] is None)
    mind.execute("UPDATE state SET value = ? WHERE key = 'self'", (json.dumps(me),))
    return {"concerns given their turn": given, "concerns whose turn was not kept": lost}


def migrate(home: Path) -> dict:
    """Format 4 for the home's databases: what was done (counts), and where the copy from before is."""
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
        report.update(_mind(dbs["mind"], dbs["brain"]))
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
