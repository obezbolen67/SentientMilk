"""One-off: bring a SentientMilk home at data format 1 to format 2, once, with the brain stopped.

    python scripts/migrate_format_2.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-2-<time>/ (SQLite's backup, WAL and all). Then:

mind.sqlite3   each time she named a feeling, as format 1 kept it (a sentence, when, and the moment the old code
               took as the one named: the first that came back as she looked, whatever she meant), becomes a
               naming stored by older software: her words as the feeling's, the sentence, the moment kept as
               it was stored, no numbers of its own (format 1 kept only the feeling's mean of every naming,
               which stays) and what she meant to name not reconstructed. A feeling counts every naming of
               then as measured, so the next one weighs as it would have; when it was last recognized by
               likeness, and in which run, was not kept.

No table changes shape: every table, column, index and trigger is checked to be as in a database made now
(anything else stops it, nothing changed), and each database is stamped with format 2 and opened with the
current code. A home at format 2 is left as it is. The script lives on only in git.
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
from sentientmilk_framework.mind.feel import Concepts, naming  # noqa: E402
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

NAMES = ("brain", "mind", "recall")
FROM = 1


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
    folder = home / time.strftime("before-format-2-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _mind(mind: sqlite3.Connection) -> dict:
    row = mind.execute("SELECT value FROM state WHERE key = 'concepts'").fetchone()
    if row is None:
        return {"namings kept as stored by older software": 0}
    concepts, namings = [], 0
    for old in json.loads(row["value"]):
        said = [naming(old["word"], one["text"], one["at"], "legacy", "legacy", episode=one.get("episode"))
                for one in old["said"]]
        namings += len(said)
        concepts.append(Concepts._read({"word": old["word"], "moved": old["moved"], "about": old["about"],
                                        "count": old["count"], "measured": old["count"], "back": old["back"],
                                        "back_at": None, "back_run": None, "at": old["at"], "said": said}))
    mind.execute("UPDATE state SET value = ? WHERE key = 'concepts'", (json.dumps(concepts),))
    return {"feelings": len(concepts), "namings kept as stored by older software": namings}


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
