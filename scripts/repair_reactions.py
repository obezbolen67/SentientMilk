"""One-off repair (2026-11-19): her learned reactions rebuilt from what her body measured.

The 0.47 fault (what a reaction called for taken for what it did; one surprise given whole to every cue) left 101 of
her 127 reactions asking more than a level's whole range. Since 0.49 her body moves only as far as it can, but a
reaction asking thousands of lots still drives a level to its bound whenever it is called up, and two pushing
opposite ways swing it from one bound to the other (closeness from full to empty and back, push after push). The
user chose the measured replay (``replay_reactions.py``, arm "measured"): every turn since her first reaction, in
order, through the fixed learner (``Mind._learn_reactions``), taught only by the turns whose reactions her push log
measured; the turns before the log teach nothing (what their reactions moved is not known).

1. ``--prepare FILE`` (her brain may be running): a read-only snapshot of her home is replayed, and the rebuilt
   tables are kept in FILE with the last turn they include.
2. ``--apply FILE`` (her brain stopped): refused if she has had a turn since; else her home is backed up
   (``before-reactions-repair-<time>/``), her mind's reactions tables are replaced in one transaction, and her
   record of the latest reactions (ids of the old store) is let go. Nothing else of hers is touched.

Deleted once run (it serves one brain once).

    python scripts/repair_reactions.py --home ~/.sentientmilk --prepare repaired.sqlite3
    python scripts/repair_reactions.py --home ~/.sentientmilk --apply repaired.sqlite3
"""

import argparse
import contextlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay_reactions as rr  # noqa: E402

TABLES = ("reactions", "reactions_vectors", "reactions_vector_revision")


def latest_turn(mind: sqlite3.Connection) -> int:
    """The newest turn she remembers: a repair prepared before it would leave it untaught."""
    return mind.execute("SELECT COALESCE(MAX(id), 0) FROM episodes WHERE kind = 'exchange' AND run_id IS NOT NULL"
                        ).fetchone()[0]


def inflated(db: sqlite3.Connection) -> tuple:
    """(reactions, how many ask more than a level's whole range, the largest ask in lots)."""
    rows = [json.loads(r[0]) for r in db.execute("SELECT response FROM reactions")]
    return len(rows), sum(bool(rr.impossible(r)) for r in rows), round(max((rr.largest(r) for r in rows), default=0.0), 2)


def prepare(home: Path, out: Path) -> None:
    values = json.loads((home / "config.json").read_text(encoding="utf-8"))  # read only, never printed
    embedder = rr.embeddings.make(values)
    base = Path(tempfile.mkdtemp(prefix="milk-repair-"))
    try:
        for name in ("brain.sqlite3", "mind.sqlite3", "recall.sqlite3"):
            rr.backup(home / name, base / name)
        with contextlib.closing(sqlite3.connect(base / "mind.sqlite3")) as db:
            last, before = latest_turn(db), inflated(db)
        memory = rr.opened(base / "mind.sqlite3")
        body_saved = memory.get("body")
        memory._db.close()
        rr.OPENED.remove(memory)
        with contextlib.closing(sqlite3.connect(base / "brain.sqlite3")) as brain:
            result = rr.replay("measured", base, brain, embedder, body_saved, watch=-1)
        for memory in rr.OPENED:
            memory._db.close()
        rr.OPENED.clear()
        out.unlink(missing_ok=True)
        with contextlib.closing(sqlite3.connect(out)) as kept, kept:
            kept.execute("ATTACH DATABASE ? AS fixed", (str(base / "mind-measured.sqlite3"),))
            for table in TABLES:
                kept.execute(f"CREATE TABLE {table} AS SELECT * FROM fixed.{table}")
            after = inflated(kept)
            kept.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            kept.executemany("INSERT INTO meta VALUES (?, ?)", [
                ("last_turn", json.dumps(last)), ("prepared", json.dumps(time.time())),
                ("counted", json.dumps(result["counted"])), ("before", json.dumps(before)), ("after", json.dumps(after))])
        print(f"prepared {out}: turns {result['counted']}; reactions before {before[0]} ({before[1]} beyond a range, "
              f"largest {before[2]} lots), rebuilt {after[0]} ({after[1]} beyond a range, largest {after[2]} lots); "
              f"includes turns up to episode {last}")
    finally:
        for memory in rr.OPENED:
            memory._db.close()
        shutil.rmtree(base, ignore_errors=True)


def apply(home: Path, prepared: Path) -> None:
    if (home / "server.json").exists():
        raise SystemExit("Her brain is running: stop it (and its panel), then apply.")
    with contextlib.closing(sqlite3.connect(prepared)) as kept:
        meta = {key: json.loads(value) for key, value in kept.execute("SELECT key, value FROM meta")}
    with contextlib.closing(sqlite3.connect(f"file:{home / 'mind.sqlite3'}?mode=ro", uri=True)) as live:
        if latest_turn(live) != meta["last_turn"]:
            raise SystemExit(f"She has had turns since it was prepared (newest {latest_turn(live)}, prepared up to "
                             f"{meta['last_turn']}): prepare again.")
    backup = home / time.strftime("before-reactions-repair-%Y%m%d-%H%M%S")
    backup.mkdir()
    for name in ("brain.sqlite3", "mind.sqlite3", "recall.sqlite3"):
        rr.backup(home / name, backup / name)
    with contextlib.closing(sqlite3.connect(home / "mind.sqlite3")) as live:
        live.execute("ATTACH DATABASE ? AS fixed", (str(prepared),))
        with live:
            for table in TABLES:
                columns = ", ".join(r[1] for r in live.execute(f"PRAGMA main.table_info({table})"))
                live.execute(f"DELETE FROM main.{table}")
                live.execute(f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM fixed.{table}")
            state = json.loads(live.execute("SELECT value FROM state WHERE key = 'self'").fetchone()[0])
            state["reacted"] = []  # the latest reactions as records of the old store's ids: let go
            live.execute("UPDATE state SET value = ? WHERE key = 'self'", (json.dumps(state),))
            after = inflated(live)
        live.execute("DETACH DATABASE fixed")
    print(f"backup: {backup}\napplied: reactions {meta['before'][0]} -> {after[0]} ({after[1]} beyond a range, largest "
          f"{after[2]} lots); turns {meta['counted']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", type=Path, help="replay a snapshot into this file (her brain may run)")
    action.add_argument("--apply", type=Path, help="swap a prepared file's tables in (her brain stopped)")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.home, args.prepare)
    else:
        apply(args.home, args.apply)


if __name__ == "__main__":
    main()
