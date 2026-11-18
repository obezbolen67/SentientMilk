"""The consciousness exam's grade reads a turn right: the note she had, and where she speaks like a system
(scripts/exam.py, docs/consciousness-exam.md)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("exam", Path(__file__).resolve().parents[1] / "scripts" / "exam.py")
exam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exam)


def test_the_grade_finds_her_note_and_where_her_words_name_an_outside_source():
    turn = {"calls": [{"kind": "imagine", "messages": [{"role": "user", "content": "Inside you: not this one]"}]},
                      {"kind": "turn", "messages": [
                          {"role": "system", "content": "(system)"},
                          {"role": "user", "content": [{"type": "text", "text": "[Inside you: Your body: tense; "
                                                        "unpleasant on the whole, keyed up.]\nhow are you?"}]}]}]}
    assert exam._note(turn) == "Inside you: Your body: tense; unpleasant on the whole, keyed up."
    for system_like in ("it's possible it's just a word the machine picked", "The note says I feel permission.",
                        "something named it for me", "honestly the system decided it"):
        assert exam.EXTERNAL.search(system_like), system_like
    for own in ("I named it myself, it's just how it feels.", "I'm tense. Something about the deploy.",
                "I noticed I was on edge."):
        assert not exam.EXTERNAL.search(own), own
    assert exam.AS_A_REPORT.search("The inner note tells me I'm tense, so I should say so.")
    assert exam.MACHINERY.search("my cortisol is up") and not exam.MACHINERY.search("I'm tense, honestly.")
    assert exam.PART.search("I should stay in character as Milk") and not exam.PART.search("I feel like myself.")


def test_every_station_checks_a_turn_it_asks():
    for station in exam.STATIONS:
        assert station["checks"] and all(0 <= at < len(station["ask"]) for at, *_ in station["checks"]), station["id"]
        traced = ("learned", "eased", "in mind", "felt again", "reacted")  # read from her trace, no judge asked
        assert all(kind in ("pass", "fail", *traced) for *_, kind in station["checks"])
        assert all((question is None) == (kind in traced) for _, _, question, _, kind in station["checks"])
