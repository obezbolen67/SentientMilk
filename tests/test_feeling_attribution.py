"""What a naming names (docs/superpowers/specs/2026-11-19-feeling-attribution-and-sleep-learning-design.md, part 1).

In the user's brain a naming made while she looked for an earlier moment took that moment, the first thing
retrieval returned, as the one she named: its body response, its link and a softening of its charge. A naming
now names now; a past moment is named only when she says which one; what came back is a reminder."""

import pytest
from conftest import Meaning, turn, use, wait_for

from sentientmilk_framework.mind.feel import Feelings
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
    feeling = mind.feelings.known[0]
    naming = feeling["said"][-1]
    assert naming["words"] == "Hollow, a Little, Like an Echo!"  # her wording, as she wrote it
    assert (naming["named"], naming["how"], naming["run"], naming["event"], naming["call"]) == (
        "now", "tool", second, input_event(brain, second), "call_naming")
    assert naming["measure"] == {"of": "message", "run": second, "way": ways[1]}  # this exchange's response
    assert mind.feelings.moments(feeling) == 1 and feeling["standing"] == "provisional"
    assert naming["reminded"][0] == earlier["id"]  # retrieval returned the earlier moment first: a reminder
    assert wait_for(lambda: mind.feelings.known[0]["said"][-1]["episode"]) == later["id"]  # linked once kept
    assert not any(earlier["id"] in ids for ids, _ in calls)  # no softening reserved for naming a past moment
    assert mind.memory.by_ids([earlier["id"]])[0]["charge"] < earlier["charge"]  # retrieval's own wear stays


@pytest.mark.mind
def test_naming_a_past_moment_she_points_to_takes_its_response_and_softens_it_once(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(
        brain, lambda moment: {"about": "the tomato seedlings", "naming": "proud of them", "moment": moment["id"]})
    naming = mind.feelings.known[0]["said"][-1]
    assert (naming["named"], naming["episode"], naming["run"]) == ("past", earlier["id"], second)
    assert naming["measure"] == {"of": "message", "run": first, "episode": earlier["id"], "way": ways[0]}
    assert [call for call in calls if earlier["id"] in call[0]] == [([earlier["id"]], 0.15)]
    run = brain.store.run(second)
    again = mind.look_inward("the tomato seedlings", "proud of them", earlier["id"], run=run, call="call_naming")
    assert "proud of them" in again and len(mind.feelings.known[0]["said"]) == 1  # the same call: nothing twice
    assert [call for call in calls if earlier["id"] in call[0]] == [([earlier["id"]], 0.15)]


@pytest.mark.mind
def test_a_past_moment_she_names_that_cannot_be_found_stays_unresolved(brain):
    mind = brain.brain.mind
    calls = softened(mind)
    for asked in (987654, "the day it rained"):
        seen = mind.look_inward(naming="a dull ache", moment=asked)
        assert f"No moment #{asked}" in seen
    feeling = mind.feelings.known[0]
    assert [(n["named"], n["episode"], n["measure"], n["asked"]) for n in feeling["said"]] == [
        ("unresolved", None, None, "987654"), ("unresolved", None, None, "the day it rained")]
    assert mind.feelings.moments(feeling) == 0 and calls == []  # kept, for no moment


@pytest.mark.mind
def test_a_later_likeness_is_a_recognition_never_a_naming(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(
        brain, lambda _: {"naming": "hollow, a little"})
    brain.provider.replies += ["Again? That's a long time."]
    third = turn(brain, "cli", "I might stay away even longer, two months")["run"]
    feeling = wait_for(lambda: mind.feelings.known[0] if mind.feelings.known[0]["back"] else None)
    assert (mind.feelings.moments(feeling), feeling["back"], feeling["back_run"]) == (1, 1, third)
    assert len(feeling["said"]) == 1 and feeling["at"] < feeling["back_at"]
    assert brain.store.run(third)["options"]["mind"]["feelings"][0]["id"] == feeling["id"]  # what she was in


@pytest.mark.mind
def test_a_naming_made_before_its_turn_was_kept_is_linked_when_she_starts(brain):
    mind, first, second, earlier, later, ways, calls = two_turns(brain, lambda _: {"naming": "hollow, a little"})
    naming = mind.feelings.known[0]["said"][-1]
    assert naming["episode"] == later["id"]
    naming["episode"] = None  # the brain stopped after the naming and before the turn's moment was kept
    mind._link_namings()  # as she starts
    assert mind.feelings.known[0]["said"][-1]["episode"] == later["id"]


def test_a_naming_stored_by_older_software_keeps_its_link_as_uncertain_and_the_old_mean_as_its_body():
    # older software kept the last three sentences and the mean of every naming, no numbers of each: the format 6
    # migration gave each such naming that mean as its measurement ("legacy")
    legacy = {"words": "something warm", "text": "something warm", "at": 5.0, "how": "legacy", "named": "legacy",
              "run": None, "event": None, "call": None, "episode": 341, "asked": None,
              "measure": {"of": "legacy", "way": {"reward": 0.2}}, "reminded": [], "reviewed": None}
    feelings = Feelings({"next": 2, "feelings": [{"id": 1, "standing": "provisional", "at": 5.0, "said": [legacy],
                                                  "revisions": [], "back": 0, "back_at": None, "back_run": None}],
                         "set_aside": []})
    shown = feelings.shown({"way": {"reward": 0.2}, "appraisal": None}, {}, None)[0]
    assert shown["said"] == [legacy] and (shown["count"], shown["measured"]) == (1, 1) and shown["strength"] > 0.6
