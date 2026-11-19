"""What a naming names (docs/superpowers/specs/2026-11-19-feeling-attribution-and-sleep-learning-design.md, part 1).

In the user's brain a naming made while she looked for an earlier moment took that moment, the first thing
retrieval returned, as the one she named: its body response, its link and a softening of its charge. A naming
now names now; a past moment is named only when she says which one; what came back is a reminder."""

import pytest
from conftest import Meaning, turn, use, wait_for

from sentientmilk_framework.mind.feel import Concepts, naming
from sentientmilk_framework.testing import tool_call


class Garden(Meaning):
    CONCEPTS = {**Meaning.CONCEPTS, "garden": ("tomato", "tomatoes", "seedlings", "sprouted", "greenhouse", "garden")}


GLAD = '["they say the tomato seedlings sprouted", "same", "much more", "same", "good", "chat", "garden"]'
LEFT = '["they say they are leaving for a month", "much less", "same", "less", "fine", "chat", "plans"]'


def embed_all(mind, embedder):
    """Her memory's vectors, as its sweep fills them (the sweep may have been first)."""
    found = mind.memory.vectors.texts(mind.memory.vectors.pending(embedder.name, 100))
    if found:
        mind.memory.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))],
                                embedder.name)


def softened(mind):
    """Every softening of a memory's charge, as (ids, share)."""
    calls, soften = [], mind.memory.soften

    def spy(ids, share=0.35):
        calls.append((sorted(ids), share))
        return soften(ids, share)
    mind.memory.soften = spy
    return calls


def input_event(brain, run):
    return next(e["id"] for e in brain.store.events("cli", "main", types=("input",)) if e["run"] == run)


def two_turns(brain, arguments):
    """A glad exchange, then a sad one in which she looks inward with ``arguments`` (made from the first
    exchange's moment): the two moved her differently."""
    mind = brain.brain.mind
    embedder = use(brain, Garden())
    brain.provider.mind_replies["imagine"] = [GLAD, LEFT, LEFT]
    brain.provider.replies += ["They sprouted! I'm so glad."]
    first = turn(brain, "cli", "the tomato seedlings sprouted in the greenhouse")["run"]
    earlier = wait_for(lambda: mind.memory.of_run(first))
    embed_all(mind, embedder)
    brain.provider.replies += [tool_call("look_inward", arguments(earlier), call_id="call_naming"), "Oh. A month."]
    calls = softened(mind)
    second = turn(brain, "cli", "I'm leaving for a month next week")["run"]
    later = wait_for(lambda: mind.memory.of_run(second))
    ways = [brain.store.run(run)["options"]["mind"]["way"] for run in (first, second)]
    assert ways[0] != ways[1]
    return mind, first, second, earlier, later, ways, calls


@pytest.mark.mind
def test_naming_now_while_an_earlier_moment_comes_back_first_names_the_exchange_she_is_in(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(
        brain, lambda _: {"about": "the tomato seedlings sprouted", "naming": "Hollow, a Little, Like an Echo!"})
    concept = mind.concepts.named[0]
    naming = concept["said"][-1]
    assert naming["words"] == "Hollow, a Little, Like an Echo!"  # her wording, as she wrote it
    assert (naming["named"], naming["how"], naming["run"], naming["event"], naming["call"]) == (
        "now", "tool", second, input_event(brain, second), "call_naming")
    assert naming["measure"] == {"of": "message", "run": second, "way": ways[1]}  # this exchange's response
    assert concept["moved"] == ways[1] and concept["count"] == 1
    assert naming["reminded"][0] == earlier["id"]  # retrieval returned the earlier moment first: a reminder
    assert wait_for(lambda: mind.concepts.named[0]["said"][-1]["episode"]) == later["id"]  # linked once kept
    assert not any(earlier["id"] in ids for ids, _ in calls)  # no softening reserved for naming a past moment
    assert mind.memory.by_ids([earlier["id"]])[0]["charge"] < earlier["charge"]  # retrieval's own wear stays


@pytest.mark.mind
def test_naming_a_past_moment_she_points_to_takes_its_response_and_softens_it_once(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(
        brain, lambda moment: {"about": "the tomato seedlings", "naming": "proud of them", "moment": moment["id"]})
    concept = mind.concepts.named[0]
    naming = concept["said"][-1]
    assert (naming["named"], naming["episode"], naming["run"]) == ("past", earlier["id"], second)
    assert naming["measure"] == {"of": "message", "run": first, "episode": earlier["id"], "way": ways[0]}
    assert concept["moved"] == ways[0]
    assert [call for call in calls if earlier["id"] in call[0]] == [([earlier["id"]], 0.15)]
    run = brain.store.run(second)
    again = mind.look_inward("the tomato seedlings", "proud of them", earlier["id"], run=run, call="call_naming")
    assert "proud of them" in again and len(mind.concepts.named[0]["said"]) == 1  # the same call: nothing twice
    assert [call for call in calls if earlier["id"] in call[0]] == [([earlier["id"]], 0.15)]


@pytest.mark.mind
def test_a_past_moment_she_names_that_cannot_be_found_stays_unresolved(brain):
    mind = brain.brain.mind
    calls = softened(mind)
    for asked in (987654, "the day it rained"):
        seen = mind.look_inward(naming="a dull ache", moment=asked)
        assert f"No moment #{asked}" in seen
    concept = mind.concepts.named[0]
    assert [(n["named"], n["episode"], n["measure"], n["asked"]) for n in concept["said"]] == [
        ("unresolved", None, None, "987654"), ("unresolved", None, None, "the day it rained")]
    assert concept["moved"] == {} and concept["count"] == 2 and calls == []


@pytest.mark.mind
def test_a_later_likeness_is_a_recognition_never_a_naming(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(
        brain, lambda _: {"naming": "hollow, a little"})
    brain.provider.replies += ["Again? That's a long time."]
    third = turn(brain, "cli", "I might stay away even longer, two months")["run"]
    concept = wait_for(lambda: mind.concepts.named[0] if mind.concepts.named[0]["back"] else None)
    assert (concept["count"], concept["back"], concept["back_run"]) == (1, 1, third)
    assert len(concept["said"]) == 1 and concept["at"] < concept["back_at"]


@pytest.mark.mind
def test_a_naming_made_before_its_turn_was_kept_is_linked_when_she_starts(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(brain, lambda _: {"naming": "hollow, a little"})
    naming = mind.concepts.named[0]["said"][-1]
    assert naming["episode"] == later["id"]
    naming["episode"] = None  # the brain stopped after the naming and before the turn's moment was kept
    mind._link_namings()  # as she starts
    assert mind.concepts.named[0]["said"][-1]["episode"] == later["id"]


def test_a_record_stored_by_older_software_keeps_its_link_as_uncertain():
    # older software kept the last three sentences and the mean of every naming, no numbers of each
    legacy = {"words": "something warm", "text": "something warm", "at": 5.0, "how": "legacy", "named": "legacy",
              "run": None, "event": None, "call": None, "episode": 341, "asked": None, "measure": None,
              "reminded": []}
    concepts = Concepts([{"word": "something warm", "moved": {"reward": 0.2}, "about": {}, "count": 4,
                          "measured": 4, "back": 0, "back_at": None, "back_run": None, "at": 5.0, "said": [legacy]}])
    shown = concepts.shown({"reward": 0.2})[0]
    assert shown["said"] == [legacy] and (shown["count"], shown["measured"]) == (4, 4)
    concepts.add(naming("something warm", "something warm", 6.0, "tool", "now",
                        measure={"of": "reading", "way": {"reward": 0.7}}))
    assert concepts.named[0]["moved"] == {"reward": 0.3}  # one more of five, as before: the mean it had is kept
