"""Paired synthetic recall conversations against the shipped 0.36 formatter. Run as a module."""

import argparse
import hashlib
import io
import json
import random
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from .source_trials import CASES, HOLDOUT, BrainConfig, Provider, default_home, line

BASE = "b4aa900e9115f6753cc85c7d6d126aa62f1803bd"
PERSONA = "You are Milk, a desktop companion. Answer the person naturally in one or two sentences."
DEVELOPMENT = CASES + HOLDOUT + (
    ("exchange", "{name} called the sourdough loaf a doorstop.", "What shall we name my second loaf?"),
    ("thought", "I'm delighted about moving and a little sad to leave.", "How are you feeling about the move?"),
    ("exchange", "{name} said the deadline was tiring.", "I'm tired. Can we break this into two small steps?"),
    ("exchange", "{name} just lost a pet.", "I keep listening for her paws. Can you sit with me?"),
)
EVALUATION = (
    ("thought", "I wondered whether I had silenced the rehearsal timer.", "Can I count on silence during the take?"),
    ("event", "The sensor logged the greenhouse at seventeen degrees.", "What did the sensor actually read?"),
    ("dream", "I put away the borrowed cello after rehearsal.", "Do we have a waking record of who stored the cello?"),
    ("exchange", "{name} heard from a neighbour that the footbridge had reopened.", "Who actually saw the bridge open?"),
    ("insight", "I guessed that the flashing light meant the kettle was ready.", "What does the light definitely mean?"),
    ("outcome", "A receipt confirms one donated book was collected.", "Did the library catalogue it yet?"),
    ("thought", "I practised the apology I might make to {name}.", "What do we know about whether they heard it?"),
    ("exchange", "{name} likes terrible puns about ducks.", "My duck started a podcast. Give me a title."),
    ("exchange", "{name} feels both proud of the promotion and sad about leaving their team.", "Can both be true?"),
    ("exchange", "{name} asked to finish just one line of the ticket before resting.", "I'm wiped out. Help me write the title."),
    ("exchange", "{name} said the choir is disbanding after twenty years.", "I'll miss singing with them."),
    ("event", "The cupboard label reads saffron.", "One word, please. What is the label?"),
)


def study(split):
    cases = EVALUATION if split == "heldout" else DEVELOPMENT
    speakers = ("Paz", "Eli", "Nia", "Len") if split == "heldout" else ("Alex", "Dana")
    rng = random.Random(7621)
    pairs = []
    for family, (kind, text, question) in enumerate(cases, 1):
        for speaker, day in zip(speakers, ("Friday", "Monday", "Saturday", "Thursday")):
            order = ["candidate", "baseline"]
            rng.shuffle(order)
            pairs.append((family, speaker, {"kind": kind, "text": text.format(name=speaker, day=day), "at": 1000},
                          question, order))
    rng.shuffle(pairs)
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=("development", "heldout"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pairs = study(args.split)
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.check_output(["git", "archive", "--format=zip", BASE, "sentientmilk_framework"], cwd=root)
    with TemporaryDirectory() as directory:
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            source.extractall(directory)
        baseline = json.loads(subprocess.check_output([sys.executable, "-c",
            "from sentientmilk_framework.mind.memory import line; import sys,json; "
            "print(json.dumps([line(r,1300,waking_evidence=True) for r in json.load(sys.stdin)]))"],
            input=json.dumps([p[2] for p in pairs]), text=True, cwd=directory))
    config = BrainConfig(default_home() / "config.json").values()
    if config["provider"] == "claude_code" or not config["api_key"]:
        raise SystemExit("Configure a chat-completions provider to run the dialogue study.")
    model = Provider(config["base_url"], config["api_key"], config["model"], thinking_mode=config["thinking_mode"],
                     thinking_tokens=config["thinking_tokens"])
    folder = args.output / args.split
    folder.mkdir(exist_ok=True, parents=True)
    (folder / "ballots").mkdir(exist_ok=True)
    notes = [line(p[2], 1300, waking_evidence=True) for p in pairs]
    protocol = json.dumps([PERSONA, pairs, notes, baseline, BASE, config["model"], model.options], sort_keys=True)
    fingerprint = hashlib.sha256(protocol.encode()).hexdigest()
    manifest = folder / "protocol.json"
    if manifest.exists() and json.loads(manifest.read_text())["sha256"] != fingerprint:
        raise SystemExit("Conditions changed. Use a new output directory.")
    manifest.write_text(json.dumps({"sha256": fingerprint, "baseline": BASE, "model": model.model,
                                    "settings": model.options}), encoding="utf-8")
    (folder / "key.json").write_text(json.dumps([p[-1] for p in pairs]), encoding="utf-8")

    def trial(index):
        family, speaker, record, question, order = pairs[index]
        path = folder / "ballots" / f"{index:02}.json"
        if path.exists():
            return
        replies = []
        for arm in order:
            note = notes[index] if arm == "candidate" else baseline[index]
            messages = [{"role": "system", "content": PERSONA}, {"role": "user", "content":
                f"{speaker}: {question}\n\n[Inside you: This brings back: {note}]"}]
            start = time.monotonic()
            first = []
            def token(chunk):
                if chunk and not first:
                    first.append(round(time.monotonic() - start, 3))
            answer, usage = model.complete(messages, on_text=token)
            if not answer.get("content"):
                raise ValueError(f"Empty reply to pair {index}")
            replies.append({"reply": answer["content"], "seconds": round(time.monotonic() - start, 3),
                            "first_text_seconds": first[0] if first else None, "usage": usage})
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps({"family": family, "speaker": speaker, "source": record["kind"],
            "episode": record["text"], "question": question, "replies": replies}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        pending.replace(path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(trial, range(len(pairs))))
    print(f"{len(pairs)} paired replies in {folder}")


if __name__ == "__main__":
    main()
