"""Which embedding model finds her past best? Measured on a copy of her own brain (spec 2026-11-17, Task 3).

    python scripts/recall_eval.py --home COPY --out DIR --models qwen/qwen3-embedding-8b,google/gemini-embedding-2

COPY: a folder holding a copy of brain.sqlite3 (sqlite backup API, never the live file). It indexes her
rounds once per model (recall.Recall, the real code) and asks her light model once (cached in
DIR/questions.json) for questions about sampled rounds: in other words (no names or rare words of the round)
and naming an exact term from it. It prints, per model and for words only, recall@1, recall@5 and MRR for
meaning only, words only and both (hybrid), plus a query's latency, the indexing time and what it cost.

Keys: the embeddings key from the env var EMBED_API_KEY (or a file in EMBED_API_KEY_FILE), the light model's
from the brain's config; neither is printed.
"""

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentientmilk_framework import embeddings  # noqa: E402
from sentientmilk_framework.brain import Brain  # noqa: E402
from sentientmilk_framework.mind.prompts import parse  # noqa: E402
from sentientmilk_framework.provider import Provider  # noqa: E402
from sentientmilk_framework.recall import Recall  # noqa: E402
from sentientmilk_framework.store import Store  # noqa: E402

ASK = """Below is one moment from a past chat between a user and their assistant. Write ONE question the user
might ask weeks later, in a new chat, whose answer is in this moment. {how} Answer with JSON only:
{{"question": "..."}}"""
OTHER_WORDS = ("Use different words: do not reuse its names, numbers, file names or any uncommon word; "
               "describe what it was about instead, the way one half-remembers.")
EXACT = "Name one exact detail from it (a name, a file, a number or an uncommon word) in the question."


class Stub:
    """What Recall reads of a brain: the store, the settings, and history as the brain gives it."""

    def __init__(self, store, values):
        self.store, self.values = store, values
        self.config = SimpleNamespace(values=lambda: self.values)

    def history(self, app, session):
        return Brain.history(self, app, session)


def questions(brain, out: Path, count: int, light) -> list:
    path = out / "questions.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    recall = Recall(brain, out / "words.sqlite3")
    recall._take_in_chats()
    rows = recall._db.execute("SELECT ref, text FROM units WHERE source = 'turn' AND ref LIKE '%#0' "
                              "AND length(text) BETWEEN 120 AND 1600").fetchall()
    picked = random.Random(7).sample(list(rows), min(count, len(rows)))
    asked = []
    for n, row in enumerate(picked):
        how = OTHER_WORDS if n % 3 else EXACT
        message, _ = light.complete([{"role": "system", "content": ASK.format(how=how)},
                                     {"role": "user", "content": row["text"]}])
        question = str(parse(message.get("content") or "").get("question") or "").strip()
        if question:
            asked.append({"ref": row["ref"].rsplit("#", 1)[0], "kind": "exact" if how == EXACT else "other",
                          "question": question})
        time.sleep(1.0)  # the provider 429s on bursts
    path.write_text(json.dumps(asked, ensure_ascii=False, indent=1), encoding="utf-8")
    return asked


def ranks(recall: Recall, asked: list, mode: str) -> list:
    found = []
    embedder = recall.embedder
    for item in asked:
        if mode == "meaning":
            try:
                vector = embedder.embed([item["question"]], query=True)[0]
            except embeddings.NotReady:
                found.append(None)
                continue
            ids = [i for i, _ in recall.vectors.nearest(vector, embedder.name, 40)]
            order = {i: n for n, i in enumerate(ids)}
            rows = sorted(recall._db.execute(f"SELECT id, ref FROM units WHERE id IN ({','.join('?' * len(ids))})",
                                             ids).fetchall(), key=lambda r: order[r[0]]) if ids else []
            refs = list(dict.fromkeys(r[1].rsplit("#", 1)[0] for r in rows))
        else:
            recall.embedder = embedder if mode == "both" else None
            refs = [hit["ref"].rsplit("#", 1)[0] for hit in recall.search(item["question"], count=10, sources=("turn",))]
            recall.embedder = embedder
        found.append(refs.index(item["ref"]) + 1 if item["ref"] in refs else None)
    return found


def scores(found: list) -> str:
    total = len(found) or 1
    at1 = sum(1 for r in found if r == 1) / total
    at5 = sum(1 for r in found if r and r <= 5) / total
    mrr = sum(1 / r for r in found if r) / total
    return f"@1 {at1:.2f}  @5 {at5:.2f}  MRR {mrr:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", default=embeddings.DEFAULT_MODEL)
    parser.add_argument("--questions", type=int, default=60)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("EMBED_API_KEY") or Path(os.environ["EMBED_API_KEY_FILE"]).read_text(encoding="utf-8").strip()
    real = json.loads((Path.home() / ".sentientmilk" / "config.json").read_text(encoding="utf-8"))
    light = Provider(real["base_url"], real["api_key"], real.get("light_model") or real["model"], thinking_mode="none")
    store = Store(Path(args.home) / "brain.sqlite3")
    words = Stub(store, {"embeddings": "off"})
    asked = questions(words, out, args.questions, light)
    print(f"{len(asked)} questions ({sum(q['kind'] == 'exact' for q in asked)} naming an exact term)")
    groups = {"all": asked, "other words": [q for q in asked if q["kind"] == "other"],
              "exact term": [q for q in asked if q["kind"] == "exact"]}
    recall = Recall(words, out / "words.sqlite3")
    for name, group in groups.items():
        print(f"words only        {name:12} {scores(ranks(recall, group, 'words'))}")
    for spec in args.models.split(","):
        model, _, dims = spec.partition("@")
        values = {"embeddings": "api", "embeddings_base_url": embeddings.DEFAULT_URL, "embeddings_api_key": key,
                  "embeddings_model": model, "embeddings_dimensions": int(dims or 0)}
        recall = Recall(Stub(store, values), out / f"recall-{spec.replace('/', '_').replace(':', '_')}.sqlite3")
        started = time.time()
        try:
            recall.sweep()
        except Exception as exc:
            print(f"{spec}: could not index ({exc})")
            continue
        took = time.time() - started
        units, embedded = recall.status()["units"], recall.status()["embedded"]
        if embedded < units:
            print(f"{spec}: embedded {embedded} of {units} ({recall.embedder.problem()})")
            continue
        latencies, slow = [], 0
        for item in asked[:20]:  # each kept after: the ranks below do not wait again
            start = time.perf_counter()
            try:
                recall.embedder.embed([item["question"]], query=True)
            except embeddings.NotReady:
                slow += 1
            latencies.append(time.perf_counter() - start)
        for name, group in groups.items():
            print(f"{spec:30} meaning {name:12} {scores(ranks(recall, group, 'meaning'))}")
            print(f"{spec:30} both    {name:12} {scores(ranks(recall, group, 'both'))}")
        print(f"{spec:30} query p50 {statistics.median(latencies) * 1000:.0f} ms, max {max(latencies) * 1000:.0f} ms, "
              f"{slow} of {len(latencies)} over {embeddings.QUERY_WAIT:.0f} s; "
              f"indexed {units} units in {took:.0f} s; spent ${recall.embedder.spent:.4f}; dim {recall.embedder.dim}")


if __name__ == "__main__":
    main()
