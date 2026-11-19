"""What a learned reaction did is what her body measurably moved, not what it called for: a reaction her body cannot
follow (a level at its bound, receptors worn down) is learned from as far as it moved her, and a cue that only came
with the reaction's own push learns no outcome that never came (the fault: alertness at 0.90, a reaction calling for
+28.7 lots moved it 0.4, and the 28.3 it could not move was learned by a new cue as an opposite outcome)."""

import math
import time

import pytest
from conftest import turn, use, wait_for
from test_reactions import Cues

from sentientmilk_framework.mind.feel import CHANNELS, moved
from sentientmilk_framework.mind.life import peak_end

ALARM = "the deploy alarm"
NEUTRAL = '["they mention it", "same", "same", "same", "fine", "chat", "deploys", "%s"]'
SCOLDED = '["they are furious at me", "much less", "much less", "same", "very bad", "chat", "deploys", "%s"]'


@pytest.fixture
def mind(brain):
    use(brain, Cues())
    brain.brain.mind.reactions.embedder = brain.brain.recall.embedder
    return brain.brain.mind


def reaction(mind, text, response, now=None):
    """A reaction that calls for exactly ``response`` (one intense moment, learned in one go)."""
    cues = mind.reactions.prepare([{"text": text, "source": "cause", "kind": "meaning"}], keep=True)
    return mind.reactions.learn(cues, response, 1.0, now or time.time())[0]["id"]


def calling(mind, *texts):
    found = {}
    for text in texts:
        for rid, likeness in (mind.reactions.prepare([{"text": text, "kind": "meaning"}])[0]["found"] or {}).items():
            found[rid] = max(found.get(rid, 0.0), likeness)
    return found


def react(mind, found, **levels):
    with mind._lock:
        mind.body.levels.update(levels)
        before = dict(mind.body.levels)
        did = mind._react(found, [], [], time.time(), "reading")
        return did, moved(before, mind.body.levels), mind.self["reacted"][0]


@pytest.mark.mind
def test_a_reaction_her_body_cannot_follow_is_kept_as_what_it_moved(mind):
    rid = reaction(mind, ALARM, {"noradrenaline": 28.7234})
    did, way, record = react(mind, calling(mind, ALARM), noradrenaline=0.90)
    assert abs(way["noradrenaline"] - 0.4) < 1e-6  # 0.90 to its ceiling 1.00: 0.10, a lot is 0.25
    assert abs(did["noradrenaline"] - 0.4) < 1e-6  # what it did: what it moved (it said 28.7234)
    assert record["predicted"]["noradrenaline"] == 28.7234 and abs(record["moved"]["noradrenaline"] - 0.4) < 1e-4
    assert record["each"][0]["id"] == rid and record["each"][0]["predicted"]["noradrenaline"] == 28.7234


@pytest.mark.mind
@pytest.mark.parametrize("levels, response", [
    ({"noradrenaline": 0.90}, {"noradrenaline": 28.7234}),  # at the upper bound
    ({"noradrenaline": 0.05}, {"noradrenaline": -28.7234}),  # at the lower bound
    ({"cortisol": 0.5}, {"cortisol": 0.8, "oxytocin": -0.4}),  # halfway, nothing saturates
])
def test_what_a_reaction_did_is_what_her_body_moved_with_the_sign_it_called_for(mind, levels, response):
    reaction(mind, ALARM, response)
    did, way, record = react(mind, calling(mind, ALARM), **levels)
    for name in CHANNELS:
        assert abs(did.get(name, 0.0) - way.get(name, 0.0)) < 1e-4, name  # nothing else moved her
    for name, called in record["predicted"].items():
        assert did.get(name, 0.0) * called >= 0, name  # the way it called for, or not at all


@pytest.mark.mind
def test_worn_down_receptors_move_her_less_and_that_is_what_it_did(mind):
    reaction(mind, ALARM, {"oxytocin": 1.0})
    mind.body.sensitivity["oxytocin"] = 0.4
    did, way, record = react(mind, calling(mind, ALARM), oxytocin=0.4)
    assert 0 < did["oxytocin"] < 0.6 and abs(did["oxytocin"] - way["oxytocin"]) < 1e-4
    assert record["predicted"]["oxytocin"] == 1.0


@pytest.mark.mind
def test_two_reactions_pushing_opposite_ways_add_up_to_how_she_moved(mind):
    reaction(mind, "the deploy alarm at night", {"cortisol": 2.0})
    reaction(mind, "a quiet tax deadline", {"cortisol": -1.5})
    did, way, record = react(mind, calling(mind, "the deploy alarm at night", "a quiet tax deadline"), cortisol=0.6)
    each = [one["moved"].get("cortisol", 0.0) for one in record["each"]]
    assert len(each) == 2 and each[0] * each[1] < 0  # one up, one down
    assert abs(sum(each) - way["cortisol"]) < 1e-3 and abs(did["cortisol"] - way["cortisol"]) < 1e-4


@pytest.mark.mind
def test_anticipation_alone_teaches_what_came_with_it_no_opposite_outcome(brain, mind):
    reaction(mind, ALARM, {"noradrenaline": 28.7234})
    mind.body.levels["noradrenaline"] = 0.90
    brain.provider.mind_replies["imagine"] = [NEUTRAL % "the build server"]
    brain.provider.replies += ["Hm."]
    run = turn(brain, "cli", "the deploy alarm went off again")["run"]
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    decision = brain.store.run(run)["options"]["mind"]
    assert decision["reacted"]["noradrenaline"] < 1.0  # what it moved, not the 28.7 it called for
    learned = {r["text"]: r for r in mind.reactions.strongest(10, time.time())}
    server = learned.get("the build server", {"response": {}})["response"]
    assert abs(server.get("noradrenaline", 0.0)) < 0.5  # was about -28: an outcome that never came


@pytest.mark.mind
def test_anticipation_then_a_real_outcome_teaches_the_outcome_not_the_anticipation(brain, mind):
    reaction(mind, ALARM, {"cortisol": 0.8})
    brain.provider.mind_replies["imagine"] = [SCOLDED % "the build server"]
    brain.provider.replies += ["I'm sorry."]
    run = turn(brain, "cli", "the deploy alarm went off and you broke production")["run"]
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    decision = brain.store.run(run)["options"]["mind"]
    server = {r["text"]: r for r in mind.reactions.strongest(10, time.time())}["the build server"]["response"]
    assert decision["external"]["cortisol"] > 0 and server["cortisol"] > 0  # the strain that came
    # what the reaction itself did is not credited to the server: less than the whole move of reading it
    assert server["cortisol"] < decision["external"]["cortisol"] + decision["reacted"]["cortisol"]


@pytest.mark.mind
def test_a_reaction_s_push_is_taken_out_as_far_as_it_is_left_when_the_turn_ends(mind):
    """By the end of a long turn the body has let part of a reaction's push go: only what is left of it was in
    what the whole turn did (Body.left), in each level's own pace."""
    now = time.time()
    taught = mind.reactions.prepare([{"text": "the build server", "source": "cause", "kind": "meaning"}], keep=True)
    pace = mind.body.pace("cortisol")
    decision = {"external": {"cortisol": 0.0}, "reacted": {}, "at": now - 2 * pace, "surroundings": [], "context": []}
    done = {"reacted": [{"at": now - pace, "moved": {"cortisol": 1.0}}]}  # a reaction while she worked
    whole = {"cortisol": math.exp(-1.0)}  # all that is left of it at the end
    with mind._lock:
        changed = mind._learn_reactions(decision, done, taught, whole, None, now)
    assert not changed or all(abs(c["response"].get("cortisol", 0.0)) < 1e-3 for c in changed)
    assert abs(mind.body.left({"cortisol": 1.0}, now - pace, now)["cortisol"] - math.exp(-1.0)) < 1e-9
    assert peak_end({"cortisol": 0.0}, {"cortisol": 0.0}) == {"cortisol": 0.0}


@pytest.mark.mind
def test_relief_undoes_what_the_dread_moved_not_what_it_called_for(brain, mind):
    reaction(mind, "deleting the thesis file", {"cortisol": 28.0})
    mind.body.levels["cortisol"] = 0.95
    brain.provider.mind_replies["imagine"] = [
        '["asked to do it", "same", "same", "same", "fine", "request", "files", "", '
        '["later", "deleting the thesis file", 0.2, 0.9, 1]]']
    brain.provider.replies += ["Tomorrow, okay?"]
    run = turn(brain, "cli", "go on, try deleting the thesis file")["run"]
    relief = [entry for entry in mind.body.pushed if entry[1].startswith("relief")]
    reacted = [entry for entry in mind.body.pushed if entry[1].startswith("reacting to")]
    assert relief and reacted
    # the relief is at most what the dread moved (was 28 lots called back: her strain pinned at its floor)
    assert abs(relief[0][2]["cortisol"]) <= abs(reacted[0][2]["cortisol"]) + 1e-6
    assert brain.store.run(run)["options"]["mind"]["act"] == "later"


@pytest.mark.mind
def test_what_set_her_off_as_she_worked_is_not_what_the_turn_taught(brain, mind, tmp_path):
    from sentientmilk_framework.testing import tool_call
    reaction(mind, "reading the diary file", {"noradrenaline": 28.7234})
    mind.body.levels["noradrenaline"] = 0.9
    brain.provider.mind_replies["imagine"] = [NEUTRAL % "the build server"]
    brain.provider.replies += [tool_call("files_read", {"path": str(tmp_path / "diary.txt")}), "Done."]
    turn(brain, "cli", "go ahead")
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    assert any(item["by"] == "doing" for item in mind.state()["reacted"])  # it set her off as she did it
    learned = {r["text"]: r for r in mind.reactions.strongest(10, time.time())}
    server = learned.get("the build server", {"response": {}})["response"]
    assert abs(server.get("noradrenaline", 0.0)) < 0.5  # not the 28 lots it called for and could not move


@pytest.mark.mind
def test_dread_is_felt_in_the_body_she_has_not_past_its_bounds(mind):
    """The as-if body of a choice (Damasio) is her body: a reaction calling for 28 lots of strain dreads as much as
    strain can move her, not seven times its ceiling (the tanh of an impossible level was the worst dread there is)."""
    from sentientmilk_framework.mind.feel import core
    huge = reaction(mind, ALARM, {"cortisol": 28.0})
    with mind._lock:
        mind.body.levels["cortisol"] = 0.4
        now = time.time()
        dread = mind._dread({huge: 1.0}, 1.0, now, [])
        reach = mind.body.would({"cortisol": 28.0 * CHANNELS["cortisol"][1]})
        assert 0 < reach["cortisol"] <= 0.6 + 1e-9  # no further than her ceiling
        bounded = core({**mind.body.levels, "cortisol": mind.body.levels["cortisol"] + reach["cortisol"]})[0] \
            - core(mind.body.levels)[0]
        assert abs(dread - round(bounded, 3)) < 1e-3
        before = dict(mind.body.levels), dict(mind.body.sensitivity)
        mind.body.would({"oxytocin": 0.3, "cortisol": 0.5})
        assert (dict(mind.body.levels), dict(mind.body.sensitivity)) == before  # imagining moves nothing


@pytest.mark.mind
def test_a_turn_delivered_again_teaches_once_and_the_next_turn_still_counts(brain, mind):
    reaction(mind, ALARM, {"cortisol": 0.8})
    brain.provider.mind_replies["imagine"] = [SCOLDED % "the build server"]
    brain.provider.replies += ["I'm sorry."]
    run = turn(brain, "cli", "the deploy alarm went off and you broke production")["run"]
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))

    def server():
        return {r["text"]: r for r in mind.reactions.strongest(10, time.time())}["the build server"]
    first = server()
    mind.after(brain.store.run(run))  # the same turn's end, delivered again
    assert server()["response"] == first["response"] and server()["trials"] == first["trials"]
    brain.provider.mind_replies["imagine"] = [SCOLDED % "the build server"]
    brain.provider.replies += ["Sorry again."]
    turn(brain, "cli", "the deploy alarm again, production is down again")
    wait_for(lambda: server()["trials"] > first["trials"])  # another turn like it: it counts


def test_without_meaning_to_match_by_what_is_around_still_learns_and_a_meaning_waits(tmp_path):
    """No embedder: a cue by meaning cannot be told alike to anything, so it is left (never kept as new each time,
    which made a row per wording); what is around her is matched by its words and learns as before."""
    from test_reactions import around, store

    from sentientmilk_framework.mind.reactions import SAME_CUE
    reactions = store(tmp_path)
    reactions.embedder = None
    cues = reactions.prepare([{"text": "deleting the thesis file", "source": "cause", "kind": "meaning"}], keep=True)
    assert cues[0].get("found") is None
    reactions.learn(cues + around("in front: outlook — inbox"), {"cortisol": 1.0}, 1.0, 1_000_000.0)
    learned = reactions.strongest(10, 1_000_001.0)
    assert [r["text"] for r in learned] == ["in front: outlook — inbox"]
    assert abs(learned[0]["response"]["cortisol"] - 1.0) < 1e-6 and SAME_CUE > 0.5


@pytest.mark.mind
def test_an_anticipation_that_came_true_survives(brain, mind):
    """The alarm, learned from one scolding, foresees strain the next time; it sets her strain off as she reads, and
    the same scolding comes: what came beyond her own reaction is what came the first time, nothing it foresaw
    stayed away, and it keeps what it learned (no getting over it)."""
    def alarm():
        return next(r for r in mind.reactions.strongest(50, time.time()) if r["text"] == ALARM)
    decisions = []
    for said in ("the deploy alarm went off and you broke production", "the deploy alarm again, production is down"):
        brain.provider.mind_replies["imagine"] = [SCOLDED % ALARM]
        brain.provider.replies += ["I'm sorry."]
        run = turn(brain, "cli", said)["run"]
        wait_for(lambda: mind.memory.of_run(run))
        decisions.append(brain.store.run(run)["options"]["mind"])
        if len(decisions) == 1:
            first = alarm()
    second = alarm()
    assert first["response"]["cortisol"] > 0 and decisions[1]["reacted"].get("cortisol", 0.0) > 0  # foreseen, set off
    assert abs(decisions[1]["external"]["cortisol"] - decisions[0]["external"]["cortisol"]) < 0.1  # the same came
    assert second["hold"] == 0 and second["extinctions"] == 0
    assert second["response"]["cortisol"] >= 0.9 * first["response"]["cortisol"]


@pytest.mark.mind
def test_how_much_of_a_push_a_level_follows_is_what_apply_moves(mind):
    body = mind.body
    for level, sign in ((0.9, 1), (0.9, -1), (0.2, 1), (1.0, 1), (0.0, -1)):
        body.levels["cortisol"] = level
        share = body.follows("cortisol", sign)
        assert abs(body.would({"cortisol": sign * 0.01})["cortisol"] - sign * 0.01 * body.temperament.stress * share) < 1e-9
    assert body.follows("cortisol", 1, 1.0) == 0.0 and body.follows("cortisol", -1, 1.0) == 1.0
