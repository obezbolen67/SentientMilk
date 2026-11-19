"""Her learned reactions, assessed and replayed from what her body measured: a dry run on a disposable copy.

    python scripts/replay_reactions.py --out DIR [--home ~/.sentientmilk] [--watch EPISODE]

Her live databases are only read (SQLite backups opened read-only, into a temp folder deleted after); nothing of
hers is written. It reports:

1. Each kept reaction against what its channels can move at all (a learned response larger than the whole range
   of its level cannot have come from a measured outcome), how much of what taught it the fault touched (turns
   whose reactions pushed her), and what it does now under the fixed code: what calling it up asks, what her body
   would follow (Body.would), and the dread of a choice that calls it up (Mind._dread).
2. Whether the fixed code alone wears an inflated reaction down: each met again and again with nothing following,
   by the fixed learner, on a copy.
3. A replay of every turn since her first reaction, in order, through the fixed learner (Reactions.learn): the
   cues as each turn kept them (what led to it, what she chose and did, what was around, prepared by her own
   embedder), the outcome as her body measured it (each turn's decision as data format 5 keeps it: what its
   reactions measurably moved as she read it, and what came beyond them; their pushes as she worked, from her push
   log), learned through the fixed code's own Mind._learn_reactions. Turns from before her push log began have no
   measurement of what their reactions moved: in arm "measured" they teach nothing (as the fixed code treats an
   outcome it did not measure); in arm "estimated" what the reading's reactions moved is estimated as what their
   call would have moved her recorded levels (her present temperament and receptors: an assumption), and their
   end, with reactions during work unlogged, is left out. Each kept reaction is matched to the replayed one its
   words are the same cue as (by her embedder, as learning matches them).
4. One turn (``--watch``), as the installed code learned from it and as the replay does.

Not replayed: reminders opening a reconsolidation window (when each was called up is not kept), causes the user
gave while she worked (kept in memory only), and how rare what was around her was at the time (as rare as it is
now). The embedder is her own (her config's key, never printed)."""

import argparse
import contextlib
import datetime
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentientmilk_framework import embeddings  # noqa: E402
from sentientmilk_framework.mind.body import Body  # noqa: E402
from sentientmilk_framework.mind.feel import CHANNELS, CHEMICALS, moved  # noqa: E402
from sentientmilk_framework.mind.life import Mind, peak_end  # noqa: E402
from sentientmilk_framework.mind.memory import Memory  # noqa: E402
from sentientmilk_framework.mind.reactions import REACTS, SAME_CUE, Reactions, _once, anxious  # noqa: E402

REACTING = ("reacting to:", "relief:")
HOUR = 3600.0
HERE = ["in front: where she met it"]
OPENED: list = []  # every copy opened, closed at the end whatever happens (Windows keeps an open file)


def opened(path: Path) -> Memory:
    memory = Memory(path, seed=0)
    OPENED.append(memory)
    return memory


def backup(source: Path, target: Path) -> None:
    with contextlib.closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as live, \
            contextlib.closing(sqlite3.connect(target)) as copy:
        live.backup(copy)


def span(name: str) -> float:
    """The whole range of a level, in its lots: the most any measured outcome can move it."""
    level = CHEMICALS.get(name)
    return ((level.high - level.low) if level else 1.0) / CHANNELS[name][1]


def lots(change: dict) -> dict:
    return {name: value / CHANNELS[name][1] for name, value in change.items() if name in CHANNELS}


def day(at: float) -> str:
    return datetime.datetime.fromtimestamp(at).strftime("%m-%d %H:%M")


def rounded(change: dict, digits: int = 2) -> dict:
    return {name: round(value, digits) for name, value in sorted(change.items(), key=lambda kv: -abs(kv[1]))
            if abs(value) >= 10 ** -digits}


def largest(change: dict) -> float:
    return max((abs(change.get(name, 0.0)) for name in REACTS), default=0.0)


def impossible(response: dict) -> dict:
    return {name: value for name, value in response.items() if name in CHANNELS and abs(value) > span(name)}


def store_of(memory: Memory, embedder) -> Reactions:
    reactions = Reactions(memory._db, threading.RLock())
    reactions.embedder = embedder
    return reactions


def doing_now(reactions: Reactions, body_saved: dict, row: dict, now: float) -> dict:
    """What calling this reaction up asks of her body now (``row["now"]``, as strongest() read it), what her body
    would follow, and the dread of a choice that calls it up whole (the fixed code's Body.would and Mind._dread)."""
    body = Body.from_dict(body_saved)
    followed = lots(body.would({name: value * CHANNELS[name][1] for name, value in row["now"].items() if name in CHANNELS}))
    dread = Mind._dread(SimpleNamespace(reactions=reactions, body=body), {row["id"]: 1.0}, 1.0, now, [])
    return {"asked": rounded(row["now"]), "followed": rounded(followed), "dread": dread}


def pushes(mind: sqlite3.Connection, chat: str, after: float, until: float) -> list:
    """Her reactions' pushes in this chat in (after, until], each as (at, lots moved): what they measurably did."""
    found = []
    for at, why, change in mind.execute("SELECT at, why, moved FROM body_pushes WHERE chat = ? AND at > ? AND at <= ? "
                                        "ORDER BY at", (chat, after, until)):
        if (why or "").startswith(REACTING):
            found.append((at, lots(json.loads(change))))
    return found


def total(found: list) -> dict:
    summed = {}
    for _at, change in found:
        for name, value in change.items():
            summed[name] = summed.get(name, 0.0) + value
    return summed


def turns_of(db: sqlite3.Connection, brain: sqlite3.Connection, first: float) -> list:
    """Every turn since ``first``, in order: (episode, at, run, chat, decision, the chat's previous turn's end)."""
    found, ended_in = [], {}
    for episode, at, run_id, app, session in db.execute(
            "SELECT id, at, run_id, app, session FROM episodes WHERE kind = 'exchange' AND at >= ? AND run_id IS NOT NULL "
            "ORDER BY at", (first - 60,)).fetchall():
        chat = f"{app}\n{session}"
        previous, ended_in[chat] = ended_in.get(chat, 0.0), at
        row = brain.execute("SELECT options FROM runs WHERE id = ?", (run_id,)).fetchone()
        decision = (json.loads(row[0] or "{}").get("mind") or {}) if row else {}
        if decision.get("levels"):
            found.append((episode, at, run_id, chat, decision, previous))
    return found


def replay(arm: str, base: Path, brain: sqlite3.Connection, embedder, body_saved: dict, watch: int) -> dict:
    """Every turn since her first reaction, in order, through the fixed learner, on a copy of her mind whose
    reactions start empty."""
    path = base / f"mind-{arm}.sqlite3"
    shutil.copyfile(base / "mind.sqlite3", path)
    memory = opened(path)
    db = memory._db
    first = db.execute("SELECT MIN(learned) FROM reactions").fetchone()[0]
    for table in ("reactions", "reactions_vectors", "reactions_vector_revision"):
        db.execute(f"DELETE FROM {table}")
    db.commit()
    reactions = store_of(memory, embedder)
    counted = {"turns": 0, "measured": 0, "estimated": 0, "untaught": 0, "taught something": 0}
    traced = None
    for episode, at, run_id, chat, decision, previous in turns_of(db, brain, first):
        counted["turns"] += 1
        end = db.execute("SELECT levels FROM body_levels WHERE chat = ? AND moment = 'turn ended' AND at BETWEEN ? AND ? "
                         "ORDER BY abs(at - ?) LIMIT 1", (chat, at - 5, at + 5, at)).fetchone()
        end = json.loads(end[0]) if end else None
        body = Body.from_dict(body_saved)  # her body as the turn ended (the learner reads how anxious, how roused)
        body.levels = {**body.levels, **(end or decision["levels"])}
        way = decision.get("way") or {}
        if "external" in decision:  # measured: what its reactions moved, as she read it and as she worked
            counted["measured"] += 1
            kept = decision
            during = pushes(db, chat, decision["at"], at)
            whole = moved(decision["levels"], end) if end is not None else None
        elif arm == "estimated":
            counted["estimated"] += 1
            then = Body.from_dict(body_saved)
            then.levels = {**then.levels, **decision["levels"]}
            estimate = lots(then.would({name: value * CHANNELS[name][1] for name, value in decision.get("called", {}).items()
                                        if name in CHANNELS}))
            kept = {**decision, "reacted": estimate,
                    "external": {name: way.get(name, 0.0) - value
                                 for name, value in {**dict.fromkeys(way, 0.0), **estimate}.items()}}
            during, whole = [], None  # what her reactions did as she worked was not logged: the end is left out
        else:
            counted["untaught"] += 1
            continue
        done = {"reacted": [{"at": pushed_at, "moved": change} for pushed_at, change in during]}
        followed = decision.get("then") or {}
        cues = reactions.prepare(
            [{"text": decision.get("cause") or "", "kind": "meaning", "source": "cause"},
             {"text": followed.get("option") or "", "kind": "meaning", "source": "option"}]
            + [{"text": text, "kind": "meaning", "source": "action"} for text in followed.get("actions") or []],
            anxious(body.levels), keep=True)
        before = {r["id"]: dict(r["response"]) for r in reactions.strongest(10_000, at)}
        foreseen = reactions.predict({rid: likeness for cue in cues for rid, likeness in (cue.get("found") or {}).items()},
                                     at, decision.get("context") or [], anxious(body.levels)) if before else {}
        # the fixed code's own learning from a turn (Mind._learn_reactions), on this copy
        mind = SimpleNamespace(body=body, memory=memory, reactions=reactions)
        changed = Mind._learn_reactions(mind, kept, done, cues, whole, episode, at)
        counted["taught something"] += bool(changed)
        if episode == watch:
            rest = None
            if whole is not None:
                rest = dict(whole)
                for pushed_at, change in [(decision["at"], kept["reacted"])] + during:
                    for name, left in body.left(change, pushed_at, at).items():
                        rest[name] = rest.get(name, 0.0) - left
            traced = {"cues": [(cue["kind"], cue["text"][:80]) for cue in _once(cues)],
                      "joint prediction": rounded(foreseen), "its reactions called for": rounded(decision.get("called") or {}),
                      "reading moved": rounded(way), "its reactions moved": rounded(kept["reacted"]),
                      "reactions as she worked": rounded(total(during)),
                      "external": rounded(kept["external"]), "end less what is left of reactions": rounded(rest or {}),
                      "outcome taught": rounded(peak_end(kept["external"], rest)),
                      "learned": [(c["text"][:80], "new" if c["id"] not in before else "kept",
                                   rounded({n: v - before.get(c["id"], {}).get(n, 0.0) for n, v in c["response"].items()}, 4))
                                  for c in changed if largest({n: v - before.get(c["id"], {}).get(n, 0.0)
                                                               for n, v in c["response"].items()}) >= 0.0005]}
    return {"store": reactions, "counted": counted, "traced": traced}


def matched(store: Reactions, rows: list) -> dict:
    """Each kept row's replayed counterpart: the replayed reaction its words are the same cue as (as learning
    matches a cue: likeness at least SAME_CUE), else its nearest, as (row, likeness)."""
    found = []
    for start in range(0, len(rows), 8):  # a turn's worth at a time (one call for all of them failed: none found)
        found += store.prepare([{"text": row["text"], "kind": row["kind"]} for row in rows[start:start + 8]])
    if any(cue["kind"] == "meaning" and cue.get("found") is None for cue in found):
        raise SystemExit(f"her embedder could not match the kept reactions: {store.embedder.problem()}")
    replayed = {r["id"]: r for r in store.strongest(10_000, 1e12)}
    pairs = {}
    for row, cue in zip(rows, found):
        alike = store.around([row["text"]]) if row["kind"] == "around" else (cue.get("found") or {})
        best = max(alike.items(), key=lambda kv: kv[1], default=(None, 0.0))
        pairs[row["id"]] = (replayed.get(best[0]), best[1])
    return pairs


def wear(base: Path, embedder, rows: list, now: float) -> dict:
    """Whether the fixed code alone wears an inflated reaction down: each met by itself in one place, once an hour,
    with nothing following (no reminder opening a window first); what it would ask there after 5, 20 and 60
    meetings, and after the 60th: somewhere else (renewal), there under stress (reinstatement), and there a day
    later (spontaneous recovery). Getting over it is learned where it was: the response itself is kept."""
    path = base / "mind-wear.sqlite3"
    shutil.copyfile(base / "mind.sqlite3", path)
    store = store_of(opened(path), embedder)
    worn = {}
    for row in rows:  # each met as itself only (found: it alone), so one copy serves them all
        asked = {}
        for n in range(1, 61):
            at = now + n * HOUR
            # as in a turn: reading it calls the reaction up, and the turn's end teaches seconds later (inside
            # OPENS: no window for changing it is open, it is held back)
            store.called([row["id"]], at - 30.0)
            store.learn([{"text": row["text"], "kind": "meaning", "source": "cause", "found": {row["id"]: 1.0}}],
                        {}, 0.5, at, HERE)
            if n in (5, 20, 60):
                asked[n] = largest(store.expressed(store._rows([row["id"]])[0], at, HERE, 0.0))
        last = store._rows([row["id"]])[0]
        asked["elsewhere"] = largest(store.expressed(last, now + 60 * HOUR, ["in front: somewhere else"], 0.0))
        asked["stressed"] = largest(store.expressed(last, now + 60 * HOUR, HERE, 1.0))
        asked["a day later"] = largest(store.expressed(last, now + 84 * HOUR, HERE, 0.0))
        worn[row["id"]] = asked
    return worn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", type=Path, default=Path.home() / ".sentientmilk")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--watch", type=int, default=378, help="an episode whose replay is traced in full")
    args = parser.parse_args()
    values = json.loads((args.home / "config.json").read_text(encoding="utf-8"))  # read only, never printed
    embedder = embeddings.make(values)
    args.out.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="milk-replay-"))
    out = []
    try:
        for name in ("brain.sqlite3", "mind.sqlite3", "recall.sqlite3"):
            backup(args.home / name, base / name)
        with contextlib.closing(sqlite3.connect(base / "brain.sqlite3")) as brain:
            memory = opened(base / "mind.sqlite3")
            body_saved = memory.get("body")
            now = Body.from_dict(body_saved).at
            kept_store = store_of(memory, embedder)
            kept = kept_store.strongest(10_000, now)
            full = {row["id"]: row for row in kept_store._rows([row["id"] for row in kept])}
            db = memory._db
            logged_from = db.execute("SELECT MIN(at) FROM body_pushes").fetchone()[0]
            # which turns the fault touched: her reactions pushed her in them (as measured, or as recorded called)
            touched = {}
            for episode, at, _run, chat, decision, previous in turns_of(db, brain, min(r["learned"] for r in kept)):
                touched[episode] = bool(pushes(db, chat, previous, at)) if "external" in decision \
                    else bool(decision.get("called"))
            watched_run = (db.execute("SELECT run_id FROM episodes WHERE id = ?", (args.watch,)).fetchone() or [None])[0]
            doing = {row["id"]: doing_now(kept_store, body_saved, row, now) for row in kept}
            memory._db.close()
            OPENED.remove(memory)
            inflated = [row for row in kept if impossible(row["response"])]
            worn = wear(base, embedder, inflated, now)
            arms = {arm: replay(arm, base, brain, embedder, body_saved, args.watch) for arm in ("measured", "estimated")}
            watched = brain.execute("SELECT options FROM runs WHERE id = ?", (watched_run,)).fetchone()                 if watched_run else None
        for result in arms.values():
            result["pairs"] = matched(result["store"], kept)
            result["doing"] = {row["id"]: doing_now(result["store"], body_saved, row, now)
                               for row in result["store"].strongest(10_000, now)}
            result["rows"] = result["store"].strongest(10_000, now)

        def share(row) -> str:
            origins = [o for o in full[row["id"]]["origins"] if o in touched]
            return f"{sum(touched[o] for o in origins)}/{len(origins)}" if origins else "-"
        texts = {}
        for row in kept:
            texts.setdefault((row["kind"], row["text"]), []).append(row["id"])
        out.append("# Her learned reactions: assessed, and replayed from what her body measured\n")
        out.append(f"A dry run on a disposable copy of her mind as of {day(now)}; push log from {day(logged_from)}. "
                   f"Lots per channel; a level's whole range is {', '.join(f'{n} {span(n):.1f}' for n in REACTS)}.\n")
        out.append(f"- Kept: {len(kept)} reactions; {len(inflated)} ask more than the whole range of a level; "
                   f"{sum(len(ids) - 1 for ids in texts.values())} are the same words as another kept one.")
        out.append(f"- Turns since her first reaction: {len(touched)}; her reactions pushed her in {sum(touched.values())}.")
        for arm, result in arms.items():
            rows = result["rows"]
            out.append(f"- Replay, {arm}: {json.dumps(result['counted'])}; {len(rows)} reactions, "
                       f"{sum(bool(impossible(r['response'])) for r in rows)} beyond a range; the largest asks "
                       f"{max((largest(r['response']) for r in rows), default=0):.2f} lots.")
        dreading = {"kept": sum(abs(doing[r["id"]]["dread"]) >= 0.05 for r in kept)}
        for arm, result in arms.items():
            dreading[arm] = sum(abs(d["dread"]) >= 0.05 for d in result["doing"].values())
        out.append(f"- Reactions whose call would weigh a choice by a dread of 0.05 or more: {dreading}.\n")
        out.append("## Does the fixed code alone wear them down?\n")
        out.append("Each inflated reaction met by itself in one place once an hour with nothing following (largest "
                   "channel asked, lots): kept -> after 5 / 20 / 60 meetings there || after the 60th: somewhere else, "
                   "there under stress, there a day later.\n")
        seen = set()
        for row in sorted(inflated, key=lambda r: -largest(r["now"])):
            if row["text"][:60] in seen or len(seen) == 20:
                continue
            seen.add(row["text"][:60])
            w = worn[row["id"]]
            out.append(f"- {largest(row['now']):.1f} -> {w[5]:.1f} / {w[20]:.1f} / {w[60]:.1f} || {w['elsewhere']:.1f}, "
                       f"{w['stressed']:.1f}, {w['a day later']:.1f}: {row['text'][:70]}")
        bound = min(span(n) for n in REACTS)
        for case in (60, "elsewhere", "stressed", "a day later"):
            out.append(f"- {'there after 60' if case == 60 else case}: {sum(w[case] > bound for w in worn.values())} of "
                       f"{len(worn)} still ask more than the smallest level's whole range ({bound:.1f} lots).")
        out.append("")
        out.append("## Each kept reaction, and its replayed counterpart\n")
        out.append("kept response | fault-touched teaching turns | now: asked, followed, dread || per arm: the replayed "
                   "reaction its words are (likeness) and the same.\n")
        for row in sorted(kept, key=lambda r: -largest(r["response"])):
            d = doing[row["id"]]
            twin = "" if len(texts[(row["kind"], row["text"])]) == 1 else f" [same words as {len(texts[(row['kind'], row['text'])]) - 1} other]"
            out.append(f"\n- **#{row['id']} {row['text'][:90]}** ({row['kind']}; trials {row['trials']}, hold "
                       f"{row['hold']:.2f}, met mostly without it {row['extinctions']}x){twin}\n"
                       f"  - kept {rounded(row['response'])} | touched {share(row)} | asks {d['asked']}, follows "
                       f"{d['followed']}, dread {d['dread']}")
            for arm, result in arms.items():
                again, likeness = result["pairs"][row["id"]]
                if again is None or likeness < SAME_CUE:
                    near = f" (nearest {likeness:.2f}: {again['text'][:50]})" if again else ""
                    out.append(f"  - {arm}: no replayed reaction is the same cue{near}")
                    continue
                d = result["doing"][again["id"]]
                out.append(f"  - {arm}: #{again['id']} ({likeness:.2f}) {rounded(again['response'])} | asks {d['asked']}, "
                           f"follows {d['followed']}, dread {d['dread']}")
        out.append("\n## The ones the fault touched least\n")
        out.append("Kept reactions none of whose teaching turns had her reactions push her, against their replayed "
                   "counterparts (largest change, lots):\n")
        for row in kept:
            origins = [o for o in full[row["id"]]["origins"] if o in touched]
            if not origins or any(touched[o] for o in origins):
                continue
            line = [f"- #{row['id']} {row['text'][:70]}: kept {rounded(row['response'])}"]
            for arm, result in arms.items():
                again, likeness = result["pairs"][row["id"]]
                line.append(f"{arm} " + (f"{rounded(again['response'])} (change {largest({n: again['response'].get(n, 0) - row['response'].get(n, 0) for n in REACTS}):.2f})"
                                         if again is not None and likeness >= SAME_CUE else "none"))
            out.append("; ".join(line))
        if args.watch:
            decision = json.loads(watched[0] or "{}").get("mind") or {} if watched else {}
            read = decision.get("called") or {}  # what the installed code took as what its reactions did
            old = {name: change - read.get(name, 0.0) for name, change in {**read, **(decision.get("way") or {})}.items()}
            taught_then = [r for r in kept if full[r["id"]]["episode"] == args.watch]
            out.append(f"\n## Episode {args.watch}: as the installed code learned from it, and as the replay does\n")
            out.append(f"- Installed: her reactions called for {rounded(read)} and measurably moved "
                       f"{rounded(decision.get('reacted') or {})}; the reading moved her "
                       f"{rounded(decision.get('way') or {})}; it took as the outcome (moved less called for) "
                       f"{rounded(old)}.")
            out.append("- Reactions it made new, as kept now: " + "; ".join(
                f"#{r['id']} {r['text'][:60]} {rounded(r['response'])} (trials {r['trials']})" for r in taught_then))
            for arm, result in arms.items():
                out.append(f"- Replay, {arm}:\n```json\n{json.dumps(result['traced'], indent=1, ensure_ascii=False)}\n```")
        (args.out / "replay.md").write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"wrote {args.out / 'replay.md'}")
    finally:
        for memory in OPENED:
            with contextlib.suppress(Exception):
                memory._db.close()
        shutil.rmtree(base, ignore_errors=True)
        if base.exists():
            print(f"could not remove {base}: delete it by hand")


if __name__ == "__main__":
    main()
