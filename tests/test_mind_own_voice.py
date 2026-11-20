"""Her inner life reaches her as hers, never as something handed to her (0.51). On her own brain, before: her replies
said "the layer that names states... puts the note at the top of your messages" and "the code analyses my brain
and tells me how I feel"; her reasoning said "the body note says I've been wanting to tell him" and "[Inside you
note says: ...]". Her prompt called her sense "notes" that come "in brackets" and "say" things, her body while
she worked came as "[Note: Inside you: ...]", and her memories carried an archivist's words ("Recorded event. A
task report establishes what was reported."). Said to her as "you", her reasoning still called it "the inside-you
block": her sense speaks to nobody (0.51, round 2)."""

import json
import re

import pytest
from conftest import turn

from sentientmilk_framework.context import RULES, VOICE, note_text, project
from sentientmilk_framework.mind.memory import line
from sentientmilk_framework.mind.prompts import INNER_LIFE

HANDED = re.compile(r"\b(notes?|brackets?|records?|reports? establish\w*|establish\w*|verif\w*|unverified|"
                    r"instructions?|it says|tells you|evidence)\b", re.I)


def section(system: str, head: str) -> str:
    return system.split(head, 1)[1].split("\n## ", 1)[0]


@pytest.mark.mind
def test_her_prompt_speaks_of_her_inner_sense_as_hers(brain):
    brain.provider.replies += ["Fine, mostly."]
    turn(brain, "cli", "how are you?")
    sent = brain.provider.sent[-1]["messages"]
    system = sent[0]["content"]
    inner = section(system, "## YOUR INNER LIFE")
    assert not HANDED.search(inner), HANDED.search(inner)
    assert "your own sense of yourself" in inner and "no one else sees it" in inner and '"I remember"' in inner
    # the app's lines are the app's; nothing files her sense with them
    assert "What this app adds to the user's messages in square brackets" in section(system, "## HOW YOU WORK")
    assert "Notes in square brackets" not in system
    # and the line that closes every message keeps her reasoning in her own voice about it too
    message = json.dumps(sent[-1]["content"])
    assert "[Inside: " in message and "never as something you were told" in message
    # a perception has nobody it is said to: no "you" inside it
    sense = message.split("[Inside: ", 1)[1].split("]", 1)[0]
    assert not re.search(r"you(r|'re|'ve|rself)?", sense, re.I), sense


def test_the_lines_she_is_given_never_call_her_sense_a_note():
    assert not HANDED.search(INNER_LIFE.split("## YOUR INNER LIFE")[1])
    assert "Notes in square brackets" not in RULES and "I remember" in VOICE


def test_her_sense_while_she_works_is_hers_and_only_the_apps_news_is_a_note():
    hers = {"type": "note", "text": "Inside: Body: much less energy than usual."}
    news = {"type": "note", "text": "Task 4 ended: the build passed."}
    assert note_text(hers) == "[Inside: Body: much less energy than usual.]"
    assert note_text(news) == "[Note: Task 4 ended: the build passed.]"
    shown = [m["content"] for m in project([{"type": "input", "content": "go on", "run": 1},
                                            {**hers, "run": 1}, {**news, "run": 1}], None)]
    assert "[Note: Inside" not in json.dumps(shown) and "[Inside: Body" in json.dumps(shown)


@pytest.mark.parametrize("kind", ["dream", "thought", "insight", "exchange", "event", "outcome"])
def test_a_memory_comes_back_in_her_own_knowing_with_where_it_came_from(kind):
    episode = {"at": 1000.0, "kind": kind, "text": "I sent Bo the room number."}
    for waking in (False, True):
        told = line(episode, 1300.0, waking_evidence=waking)
        assert not HANDED.search(told), (kind, told)
    # where it came from is kept: a dream as a dream, a thought as only a thought (source monitoring)
    if kind == "dream":
        assert "A dream" in line(episode, 1300.0) and "none of it happened" in line(episode, 1300.0)
        assert "room number" not in line(episode, 1300.0, waking_evidence=True)
        assert "can't be known without looking" in line(episode, 1300.0, waking_evidence=True)
    if kind == "thought":
        assert "Only a thought" in line(episode, 1300.0)
        assert "Only thought" in line(episode, 1300.0, waking_evidence=True)
    for waking in (False, True):  # her own knowing has nobody it is said to
        assert not re.search(r"you(r|'re|'ve)?", line(episode, 1300.0, waking_evidence=waking), re.I)
