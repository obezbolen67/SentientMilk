"""One-off: bring a SentientMilk home at data format 5 to format 6, once, with the brain stopped.

    python scripts/migrate_format_6.py --home ~/.sentientmilk

First it copies the three databases to <home>/before-format-6-<time>/ (SQLite's backup, WAL and all). Then:

mind.sqlite3   each kept moment gains ``appraisal`` (what it meant for her needs as she read it) and ``leaned``
               (which way it moved her to act): an exchange takes them from its turn's decision in brain.sqlite3
               (``foreseen``; how things were for the one who wrote was not kept then, so it has none; ``act`` and
               ``what``), a thought takes what she leaned toward from her latest thoughts, where it is among them.
               Others have neither: what was not kept is not made up.
               Her feelings (state ``concepts``: a word, the mean of how her body was moved the times she said it
               and a bag of the words around it) become ``feelings`` (feel.Feelings): each concept a feeling of
               its namings, ``provisional`` until her first sleep goes over every one of them (``reviewed`` None).
               A naming older software kept without numbers gets the mean the concept had as its measurement
               (``legacy``), so what it was like is not lost; the mean and the bag of words go.

brain.sqlite3 and recall.sqlite3 do not change. Every table, column, index and trigger is checked to be as in a
database made now (anything else stops it, nothing changed), and each database is stamped with format 6 and opened
with the current code. A home at format 6 is left as it is. The script lives on only in git.
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
from sentientmilk_framework.mind.feel import Feelings  # noqa: E402
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import Reactions  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

NAMES = ("brain", "mind", "recall")
FROM = 5


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
    folder = home / time.strftime("before-format-6-%Y%m%d-%H%M%S")
    folder.mkdir()
    for name in NAMES:
        source, target = sqlite3.connect(str(home / f"{name}.sqlite3")), sqlite3.connect(str(folder / f"{name}.sqlite3"))
        with target:
            source.backup(target)
        source.close()
        target.close()
    return folder


def _moments(mind: sqlite3.Connection, brain: sqlite3.Connection) -> dict:
    """Each kept moment's appraisal and leaning, where what it came from was kept."""
    mind.execute("ALTER TABLE episodes ADD COLUMN appraisal TEXT")
    mind.execute("ALTER TABLE episodes ADD COLUMN leaned TEXT")
    exchanges = 0
    for episode in mind.execute("SELECT id, run_id FROM episodes WHERE kind = 'exchange' AND run_id IS NOT NULL").fetchall():
        run = brain.execute("SELECT options FROM runs WHERE id = ?", (episode["run_id"],)).fetchone()
        decision = (json.loads(run["options"] or "{}").get("mind") or {}) if run else {}
        if not decision.get("foreseen"):
            continue
        mind.execute("UPDATE episodes SET appraisal = ?, leaned = ? WHERE id = ?",
                     (json.dumps(decision["foreseen"]), json.dumps({"act": decision["act"], "what": decision.get("what") or ""}),
                      episode["id"]))
        exchanges += 1
    me = json.loads((mind.execute("SELECT value FROM state WHERE key = 'self'").fetchone() or {"value": "{}"})["value"])
    thoughts = 0
    for thinking in me.get("thoughts") or []:
        if thinking.get("episode") and thinking.get("leaned"):
            option = next((o for o in thinking["leaned"].get("considered") or [] if o.get("picked")), {})
            done = mind.execute("UPDATE episodes SET leaned = ? WHERE id = ? AND kind = 'thought'",
                                (json.dumps({"act": thinking["leaned"]["act"], "what": option.get("what") or ""}),
                                 thinking["episode"])).rowcount
            thoughts += done
    return {"exchanges given what they meant and her leaning": exchanges, "thoughts given her leaning": thoughts}


def _feelings(mind: sqlite3.Connection) -> dict:
    """Her concepts as feelings of their moments, every one provisional until her sleep goes over it."""
    row = mind.execute("SELECT value FROM state WHERE key = 'concepts'").fetchone()
    concepts = json.loads(row["value"]) if row else []
    feelings, given = [], 0
    for number, concept in enumerate(concepts, 1):
        said = []
        for one in concept["said"]:
            one = {**one, "reviewed": None}
            if one["measure"] is None and one["named"] == "legacy" and concept["moved"]:
                one["measure"], given = {"of": "legacy", "way": dict(concept["moved"])}, given + 1
            said.append(one)
        feelings.append({"id": number, "standing": "provisional", "at": concept["at"], "said": said, "revisions": [],
                         "back": concept["back"], "back_at": concept["back_at"], "back_run": concept["back_run"]})
    saved = Feelings({"next": len(feelings) + 1, "feelings": feelings, "set_aside": []}).saved()  # read as it will be
    mind.execute("DELETE FROM state WHERE key = 'concepts'")
    mind.execute("INSERT INTO state (key, value) VALUES ('feelings', ?)", (json.dumps(saved, ensure_ascii=False),))
    return {"feelings (all provisional)": len(feelings), "namings": sum(len(f["said"]) for f in feelings),
            "older namings given their concept's mean": given}


def migrate(home: Path) -> dict:
    """Format 6 for the home's databases: what was done (counts), and where the copy from before is."""
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
        report.update(_moments(dbs["mind"], dbs["brain"]))
        report.update(_feelings(dbs["mind"]))
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
