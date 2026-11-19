"""One-off: bring a SentientMilk home at data format 2 to format 3, once, with the brain stopped.

    python scripts/migrate_format_3.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-3-<time>/ (SQLite's backup, WAL and all). Then:

mind.sqlite3   each thought she had keeps what the model gave as its want, marked as not chosen by her will
               (``leaned`` None: before 0.46 the want was acted on as given); a wish of hers still waiting
               teaches nothing when answered (``features`` None); what her own acts usually bring starts at 0.
brain.sqlite3  each task of her own is marked the same (``own.leaned`` None): its end teaches her choosing nothing.

No table changes shape: every table, column, index and trigger is checked to be as in a database made now
(anything else stops it, nothing changed), and each database is stamped with format 3 and opened with the
current code. A home at format 3 is left as it is. The script lives on only in git.
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
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

NAMES = ("brain", "mind", "recall")
FROM = 2


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
    out += [f"table {name} is missing" for name in wanted["tables"] if name not in found["tables"]]
    for name, columns in found["tables"].items():
        if name in wanted["tables"] and columns != wanted["tables"][name]:
            out.append(f"table {name}: has {sorted(columns - wanted['tables'][name])}, "
                       f"lacks {sorted(wanted['tables'][name] - columns)}")
    out += [f"{kind} {name} on {table} is not made now" for kind, name, table in found["others"] - wanted["others"]]
    return out


def _back_up(home: Path) -> Path:
    folder = home / time.strftime("before-format-3-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _mind(mind: sqlite3.Connection) -> dict:
    row = mind.execute("SELECT value FROM state WHERE key = 'self'").fetchone()
    if row is None:
        return {"thoughts": 0}
    me = json.loads(row["value"])
    me["thoughts"] = [{**thought, "leaned": None} for thought in me.get("thoughts") or []]
    if me.get("urge"):
        me["urge"] = {**me["urge"], "features": None}
    me["usual_own"] = 0.0
    mind.execute("UPDATE state SET value = ? WHERE key = 'self'", (json.dumps(me),))
    return {"thoughts": len(me["thoughts"])}


def _brain(brain: sqlite3.Connection) -> dict:
    count = 0
    for row in brain.execute("SELECT id, options FROM runs WHERE kind = 'task'").fetchall():
        options = json.loads(row["options"])
        if options.get("own"):
            options["own"] = {**options["own"], "leaned": None}
            brain.execute("UPDATE runs SET options = ? WHERE id = ?", (json.dumps(options), row["id"]))
            count += 1
    return {"tasks of her own": count}


def migrate(home: Path) -> dict:
    """Format 2 for the home's databases: what was done (counts), and where the copy from before is."""
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
        report.update(_mind(dbs["mind"]))
        report.update(_brain(dbs["brain"]))
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
