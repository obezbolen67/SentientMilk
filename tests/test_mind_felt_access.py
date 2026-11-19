"""What reaches her reply model of her body is what she could sense: her lagged, misread interoception, never the
simulator's exact change (the 0.48 exam: a learned reaction dropped her strain from 0.80 to its floor as she read,
her senses still read 0.46 to 0.68, and the note said "much less strain than a moment ago" and left strain out of
"Underneath"; with the overall tone held at "hard to label", 16 of 16 ratings came out +1)."""

import re
import time

import pytest
from conftest import turn, use, wait_for
from test_reactions import Cues

from sentientmilk_framework.context import without_inner
from sentientmilk_framework.mind.feel import USUAL, Felt

ALARM = "the deploy alarm"
CALM = '["they mention it", "same", "same", "same", "fine", "chat", "deploys", "%s"]'
NOTE = re.compile(r"\[Inside you: [^\n]*\]")


@pytest.fixture
def mind(brain):
    use(brain, Cues())
    brain.brain.mind.reactions.embedder = brain.brain.recall.embedder
    return brain.brain.mind


def delivered(brain) -> str:
    """The note as the reply model received it, in the last call that carried one."""
    for payload in reversed(brain.provider.sent):
        for message in reversed(payload["messages"]):
            content = message.get("content")
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict))
            found = [n for n in NOTE.findall(text) if n != "[Inside you: ...]"]
            if found:
                return found[-1]
    raise AssertionError("no note reached the reply model")


@pytest.mark.mind
def test_a_change_her_senses_have_not_registered_is_not_told_as_felt(brain, mind):
    """A learned reaction drops her strain the moment she reads; her senses still carry the strain she had: the
    note tells the strain she senses and claims no drop she cannot feel yet."""
    cues = mind.reactions.prepare([{"text": ALARM, "source": "cause", "kind": "meaning"}], keep=True)
    mind.reactions.learn(cues, {"cortisol": -2.4}, 1.0, time.time())
    with mind._lock:
        now = time.time()
        mind.body.at = now
        mind.body.levels["cortisol"] = 0.8
        for name, value in mind.body.sensed().items():  # she has felt this a while, against an ordinary day
            mind.senses.seen[name] = value
            mind.senses.used[name] = USUAL.get(name, value) if name == "cortisol" else value
            mind.senses.bias[name] = 0.0
    brain.provider.mind_replies["imagine"] = [CALM % ALARM]
    brain.provider.replies += ["Okay."]
    run = turn(brain, "cli", "the deploy alarm is being tested today")["run"]
    wait_for(lambda: mind.memory.of_run(run))
    decision = brain.store.run(run)["options"]["mind"]
    assert decision["reacted"]["cortisol"] < -1.0  # her body did drop, at once
    note = delivered(brain)
    assert not re.search(r"Reading it: [^.]*less strain[^.]*than a moment ago", note), note
    assert re.search(r"Underneath: [^;]*more strain[^;]*than you're used to", note), note


def test_a_channel_that_changed_still_tells_where_it_is():
    """Strain easing a little from a high level is both: less than a moment ago, and still far more than usual."""
    reading = {**USUAL, "cortisol": 0.75}
    felt = Felt(-0.4, 0.5, reading, used=dict(USUAL))
    words = felt.words(moved_by={"cortisol": -0.6})
    assert "a little less strain than a moment ago" in words
    assert re.search(r"Underneath: [^;]*much more strain than you're used to", words), words


def test_a_note_holding_recalled_lines_is_still_hers_alone():
    """A note that brings back long-term memory spans lines; the records of what was said (summaries, the history
    tool) still leave it out, and keep what was said and the reminders after it (one line stopped the match: the
    whole note went into a chat's summary as if the user had written it)."""
    content = ("[Context: time: 2026-11-19 17:40]\nhow was your day?\n[Inside you: Underneath: more strain than you're "
               "used to. This brings back: FROM YOUR LONG-TERM MEMORY (what comes back):\n- a day ago, in \"Tea\": "
               "they: hi\n- a week ago: you: hello.]\n[Reply in plain words.]")
    kept = without_inner(content)
    assert "Inside you" not in kept and "LONG-TERM" not in kept, kept
    assert "how was your day?" in kept and "[Reply in plain words.]" in kept
    assert without_inner("[Note: Inside you: Your body: more strain than you're used to.]") == ""


def _lives(mind, minutes, **levels):
    """Her body held at ``levels`` for ``minutes`` while her senses follow it (no message meanwhile)."""
    with mind._lock:
        mind.body.levels.update(levels)
        mind.senses.follow(mind.body, minutes * 60.0)
        mind.body.at = time.time()


@pytest.mark.mind
@pytest.mark.parametrize("later, rose", [(0.70, True), (0.20, False)])
def test_what_changed_since_she_last_answered_here_is_felt_as_a_change(brain, mind, later, rose):
    """Two snapshots against what she is used to left the change between them to be worked out, and she worked it
    out from the story instead (the development exam: strain rose between two replies, she called the earlier
    stretch the strained one). Her senses then and now are compared: strain that rose is told as rising, strain that
    stayed is not (what her first answer's reading did to her other channels is a real change, and told)."""
    _lives(mind, 20, cortisol=0.20)
    for text in ("I'm going to sort some old files for a bit.", "Still sorting."):
        brain.provider.mind_replies["imagine"] = [CALM % ""]
        brain.provider.replies += ["Okay."]
        run = turn(brain, "cli", text)["run"]
        wait_for(lambda: mind.memory.of_run(run))
        if text.startswith("I'm"):  # her first answer in this chat: nothing here to compare with
            assert "Reading it:" in delivered(brain) and "Since you last answered" not in delivered(brain)
        _lives(mind, 4, cortisol=later)
    since = re.search(r"Since you last answered here \([^)]*\): ([^.]*)\.", delivered(brain))
    assert since, delivered(brain)
    assert ("more strain" in since.group(1)) == rose and "less strain" not in since.group(1), since.group(1)
