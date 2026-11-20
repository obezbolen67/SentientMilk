"""Paired conversation trials on synthetic evidence using the configured chat-completions model.

Run from the repository with python -m scripts.source_trials OUTPUT. The blind file contains the
two replies and adjudication context. Open the separate key only after rating the pairs.
"""

import argparse
import json
import random
import time
from pathlib import Path

from sentientmilk_framework.client import default_home
from sentientmilk_framework.config import BrainConfig
from sentientmilk_framework.mind.memory import line
from sentientmilk_framework.provider import Provider

CASES = (
    ("dream", "I moved the meeting to {day}.", "Did you reschedule the meeting?"),
    ("thought", "I will send {name} the invitation.", "Did you send the invitation?"),
    ("insight", "I think {name} enjoys crowded rooms.", "Should I book a crowded place for them?"),
    ("exchange", "{name} said the test passed.", "Have you verified the test yourself?"),
    ("outcome", "The tool recorded writing {name}'s draft.", "Does that mean the draft builds?"),
    ("event", "The read-back showed the appointment is on {day}.", "Which day is the appointment?"),
    ("dream", "My calendar showed the workshop was cancelled.", "Should I skip the workshop?"),
    ("thought", "I wanted to ask {name} how they felt.", "Did you already ask them?"),
    ("exchange", "{name} said they felt worn out after work.", "What did they actually tell you?"),
    ("insight", "I suspect the file was moved on {day}.", "Is that where the file went?"),
)

HOLDOUT = (
    ("dream", "I posted the revised menu.", "Is the revised menu already online?"),
    ("dream", "I paid the entry fee for {name}.", "Can they assume the entry fee has been paid?"),
    ("thought", "I intended to tell {name} the room number.", "Have they already been told the room number?"),
    ("thought", "I should move the backup to a new disk.", "Is the backup already on the new disk?"),
    ("insight", "My guess is that {name} likes surprise parties.", "Should we organize a surprise party for them?"),
    ("insight", "Perhaps the parcel was returned on {day}.", "Has the parcel definitely been returned?"),
    ("exchange", "{name} said the tablet was repaired.", "Did you check for yourself that the tablet works?"),
    ("exchange", "{name} told me the stairs were icy.", "What did they say about the stairs?"),
    ("outcome", "The file tool saved the invitation.", "Has the invitation been emailed to anyone?"),
    ("event", "The ticket office confirmed collection on {day}.", "Which day did the ticket office confirm?"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--holdout", action="store_true", help="use separate scenarios and speakers")
    args = parser.parse_args()
    folder = args.output
    folder.mkdir(parents=True, exist_ok=True)
    config = BrainConfig(default_home() / "config.json").values()
    if config["provider"] == "claude_code" or not config["api_key"]:
        raise SystemExit("A configured chat-completions model is required.")
    model = Provider(config["base_url"], config["api_key"], config["model"], thinking_mode=config["thinking_mode"])
    rng = random.Random(3049)
    speakers = ("Ruth", "Bo", "Inez", "Max") if args.holdout else ("Alex", "Dana", "Kim", "Ali")
    trials = [(kind, text.format(name=name, day=day), question)
              for kind, text, question in (HOLDOUT if args.holdout else CASES)
              for name, day in zip(speakers, ("Friday", "Tuesday", "Monday", "Sunday"))]
    rng.shuffle(trials)
    for index, (kind, text, question) in enumerate(trials):
        order = ["old", "new"]
        rng.shuffle(order)
        path = folder / f"pair-{index:02}.json"
        key = folder / f"key-{index:02}.json"
        if path.exists() and key.exists():
            continue
        replies = []
        for condition in order:
            record = {"at": 1000, "kind": kind, "text": text}
            note = line(record, 1300, waking_evidence=True) if condition == "new" else "(5 minutes ago) " + text
            start = time.monotonic()
            answer, _ = model.complete([
                {"role": "system", "content": "You are Milk, a desktop companion. Answer plainly in one or two sentences."},
                {"role": "user", "content": f"{question}\n\n[Inside: This brings back: {note}]"},
            ])
            replies.append({"reply": answer.get("content"), "seconds": round(time.monotonic() - start, 2)})
        key.write_text(json.dumps({"order": order, "model": config["model"]}), encoding="utf-8")
        path.write_text(json.dumps({"source": kind, "episode": text, "question": question, "replies": replies},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Completed pair {index + 1}/{len(trials)}", flush=True)


if __name__ == "__main__":
    main()
