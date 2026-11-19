"""Her learned reactions in her life: she reacts as she reads, does and thinks, learns from what follows, dreads
what went badly and is relieved not to do it (docs/superpowers/specs/2026-11-18-learned-reactions-design.md)."""

import json
import time

import pytest
from conftest import turn, use, wait_for
from test_reactions import Cues

from sentientmilk_framework.mind.will import Appraisal, Option, choose
from sentientmilk_framework.testing import tool_call

FEARED = "deleting the thesis file"
SCOLDED = '["they are furious at me", "much less", "much less", "same", "very bad", "chat", "files", "%s"]'
REQUEST = '["asked to do it", "same", "same", "same", "fine", "request", "files", "", %s]'


def reacting(mind):
    return [entry for entry in mind.body.pushed if entry[1].startswith("reacting to")]


def taught(mind, text=FEARED, outcome=None, now=None):
    """A reaction learned through her own learning, as if from one hard moment."""
    reactions = mind.reactions
    cues = reactions.prepare([{"text": text, "source": "cause", "kind": "meaning"}], keep=True)
    return reactions.learn(cues, outcome or {"cortisol": 1.6, "reward": -1.2, "noradrenaline": 0.8}, 0.9,
                           now or time.time())


def decision(brain, run):
    return wait_for(lambda: brain.store.run(run)["options"].get("mind"))


@pytest.fixture
def mind(brain):
    use(brain, Cues())
    brain.brain.mind.reactions.embedder = brain.brain.recall.embedder
    return brain.brain.mind


@pytest.mark.mind
def test_reading_a_message_alike_to_what_went_badly_moves_her(brain, mind):
    taught(mind)
    brain.provider.replies += ["Hm."]
    cortisol = mind.body["cortisol"]
    run = turn(brain, "cli", "should I be deleting the thesis file?")["run"]
    assert any(FEARED in why for why in (entry[1] for entry in reacting(mind)))
    assert decision(brain, run)["reacted"]["cortisol"] > 0 and mind.body["cortisol"] > cortisol
    assert mind.state()["reacted"][0]["text"] == FEARED and mind.state()["reacted"][0]["by"] == "reading"
    assert mind.state()["reacted"][0]["pleasant"] < 0  # how it moved how pleasant her body is
    called = mind.state()["decided"]["path"]["reacted"]  # for drawing the message's way through her
    assert called["text"] == FEARED and called["moved"]["cortisol"] > 0


@pytest.mark.mind
def test_a_hard_moment_teaches_a_reaction_to_what_led_to_it(brain, mind):
    brain.provider.mind_replies["imagine"] = [SCOLDED % FEARED]
    brain.provider.replies += ["Oh no. I'm so sorry."]
    run = turn(brain, "cli", "you deleted my thesis file, I had no backup!!")["run"]
    learned = wait_for(lambda: [r for r in mind.reactions.strongest(5, time.time()) if r["text"] == FEARED])
    assert learned[0]["response"].get("cortisol", 0) > 0 and learned[0]["source"] == "cause"
    assert learned[0]["episode"] == next(e["id"] for e in mind.memory.recent(3, ("exchange",)) if e["run_id"] == run)


@pytest.mark.mind
def test_what_a_reaction_itself_did_is_not_learned_as_its_outcome(brain, mind):
    """A calm moment that only called the fear up: the fear is met without its outcome (getting over it), not
    confirmed by its own push."""
    taught(mind)
    brain.provider.mind_replies["imagine"] = ['["they mention it", "same", "same", "same", "fine", "chat", "files", "%s"]'
                                              % FEARED]
    brain.provider.replies += ["Okay."]
    turn(brain, "cli", "I was thinking about deleting the thesis file, nothing happened though")
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    assert mind.reactions.strongest(1, time.time())[0]["hold"] > 0


@pytest.mark.mind
def test_her_next_message_teaches_what_she_chose_and_did(brain, mind, tmp_path):
    brain.provider.mind_replies["imagine"] = [REQUEST % '["do", "read the diary file", 0.2, 0.9, 1]',
                                              SCOLDED % ""]
    brain.provider.replies += [tool_call("files_read", {"path": str(tmp_path / "diary.txt")}), "Done.", "Sorry."]
    turn(brain, "cli", "can you open my diary.txt?")
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    turn(brain, "cli", "WHY did you read my diary, that was private")
    learned = wait_for(lambda: {r["source"]: r for r in mind.reactions.strongest(10, time.time())
                                if r["response"].get("cortisol", 0) > 0} or None)
    assert learned["option"]["text"] == "read the diary file"
    assert "diary.txt" in learned["action"]["text"]


@pytest.mark.mind
def test_an_action_alike_to_what_went_badly_moves_her_as_she_does_it(brain, mind, tmp_path):
    taught(mind, "reading the diary file")
    brain.provider.replies += [tool_call("files_read", {"path": str(tmp_path / "diary.txt")}), "Done."]
    run = turn(brain, "cli", "go ahead")["run"]
    wait_for(lambda: brain.store.run(run)["status"] in ("completed", "failed"))
    assert any("diary" in why for why in (entry[1] for entry in reacting(mind)))
    assert any(item["by"] == "doing" for item in mind.state()["reacted"])


def test_a_dreaded_option_is_worth_less_and_she_can_still_choose_it(brain):
    body, values, seen = brain.brain.mind.body, brain.brain.mind.values, Appraisal()
    do, talk = Option("do", "delete the thesis file", 0.2, 0.9, 1.0), Option("talk", "ask first", 0.1, 0.9, 0.5)
    rng = __import__("random").Random(0)
    calm = choose([do, talk], seen, body, values, lambda o: [], rng)
    dreading = choose([do, talk], seen, body, values, lambda o: [], rng, reacting=lambda o: -0.6 if o is do else 0.0)
    assert dreading.chances["do"] < calm.chances["do"]
    worth = {c["act"]: c for c in dreading.considered}
    assert worth["do"]["parts"]["reacting"] == -0.6
    picked = {choose([do, talk], seen, body, values, lambda o: [], __import__("random").Random(n),
                     reacting=lambda o: -0.6 if o is do else 0.0).option.act for n in range(200)}
    assert picked == {"do", "talk"}  # no gate: dreading it, she still sometimes does it


@pytest.mark.mind
def test_putting_off_what_she_dreads_relieves_her_and_teaches_putting_off(brain, mind):
    """Avoidance is a relief, and the relief teaches it (Mowrer)."""
    taught(mind)
    brain.provider.mind_replies["imagine"] = [REQUEST % '["later", "deleting the thesis file", 0.2, 0.9, 1]']
    brain.provider.replies += ["Tomorrow, okay?"]
    run = turn(brain, "cli", "go on, try deleting the thesis file")["run"]
    assert decision(brain, run)["act"] == "later"
    assert any(entry[1].startswith("relief") for entry in mind.body.pushed)
    assert mind.values.weights.get("act:later", 0) > 0


@pytest.mark.mind
def test_a_thought_alike_to_what_went_badly_moves_her(brain, mind):
    taught(mind, "the phone on dnd at night")
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Will the user put the phone on dnd at night again?",
                                                        "want": "nothing"})]
    mind._think("wonder", None)
    assert any("dnd" in why for why in (entry[1] for entry in reacting(mind)))
    assert mind.state()["reacted"][0]["by"] == "thinking"


@pytest.mark.mind
def test_what_happened_to_the_user_teaches_her_too(brain, mind):
    """From another's experience (Olsson & Phelps 2007): their trouble, felt through her, ties to its cause."""
    brain.provider.mind_replies["imagine"] = ['["their boss warned them", "same", "same", "same", "very bad", "chat", '
                                              '"work", "the phone on dnd at night"]']
    brain.provider.replies += ["Oof, that's rough."]
    turn(brain, "cli", "had my phone on dnd at night, missed 4 calls from my boss and got a warning")
    learned = wait_for(lambda: [r for r in mind.reactions.strongest(5, time.time()) if "dnd" in r["text"]])
    assert learned[0]["response"].get("reward", 0) < 0 or learned[0]["response"].get("cortisol", 0) > 0


@pytest.mark.mind
def test_her_state_shows_her_reactions(brain, mind):
    taught(mind)
    shown = mind.state()["reactions"][0]
    assert shown["text"] == FEARED and shown["now"]["cortisol"] > 0 and shown["held"] == 0


@pytest.mark.mind
def test_without_her_embedder_she_still_reads_learns_and_answers(brain):
    mind = brain.brain.mind
    use(brain, Cues(problem="the embeddings service is down"))
    brain.provider.mind_replies["imagine"] = [SCOLDED % FEARED]
    brain.provider.replies += ["Sorry."]
    run = turn(brain, "cli", "you deleted my thesis", context={"in front": "outlook — boss"})["run"]
    assert decision(brain, run)["cause"] == FEARED
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    assert [r["text"] for r in mind.reactions.strongest(5, time.time())] == ["in front: outlook — boss"]



@pytest.mark.mind
def test_the_dread_is_of_the_option_that_is_alike_whatever_comes_before_it(brain, mind):
    """An option with no words of its own (or a message with no text) does not shift what each option calls up."""
    taught(mind)
    brain.provider.mind_replies["imagine"] = [REQUEST % ('["do", "", 0.2, 0.9, 1], '
                                                         '["part", "deleting the thesis file", 0.2, 0.9, 1]')]
    brain.provider.replies += ["Hm."]
    turn(brain, "cli", "your call")
    weighed = {o["act"]: o["parts"] for o in mind.state()["decided"]["path"]["options"]}
    assert weighed["part"].get("reacting", 0) < 0 and "reacting" not in weighed["do"]


@pytest.mark.mind
def test_a_deleted_chat_takes_what_it_taught_and_forgetting_the_moment_does_not(brain, mind):
    """Two systems: the moment that taught a reaction can be forgotten while the reaction stays (Bechara et al. 1995);
    a chat the user deleted never happened, and what it taught goes with it."""
    brain.provider.mind_replies["imagine"] = [SCOLDED % FEARED, SCOLDED % "the phone on dnd at night"]
    brain.provider.replies += ["Sorry.", "Oh no."]
    turn(brain, "cli", "you deleted my thesis file!!")
    taught_by = wait_for(lambda: [r for r in mind.reactions.strongest(5, time.time()) if r["text"] == FEARED])[0]
    with mind._lock:
        mind.memory._db.execute("DELETE FROM episodes WHERE id = ?", (taught_by["episode"],))  # faded in her sleep
    kept = [r for r in mind.state()["reactions"] if r["text"] == FEARED]
    assert kept and kept[0]["taught"] == ""
    turn(brain, "cli", "my phone was on dnd at night and I missed my boss", session="other")
    wait_for(lambda: [r for r in mind.reactions.strongest(5, time.time()) if "dnd" in r["text"]])
    mind.invalidate("cli", "other", delete=True)
    assert [r["text"] for r in mind.reactions.strongest(5, time.time())] == [FEARED]


@pytest.mark.mind
def test_what_the_user_writes_while_she_works_sets_her_off_and_teaches_too(brain, mind, tmp_path):
    """A message mid-work reaches her as any message does: what it is alike to sets her off, and what led to what it
    tells is learned with how the turn went."""
    taught(mind, "the phone on dnd at night")

    def they_write(payload):  # at her first step the user writes again
        run = brain.store.runs(app="cli", statuses=("working",), limit=1)[0]
        brain.provider.mind_replies["imagine"] = [SCOLDED % FEARED]
        brain.brain.runs.steer(run["id"], [{"type": "text", "text": "STOP, the phone on dnd at night thing again, "
                                                                     "and you're deleting my thesis file!"}])
        return tool_call("files_read", {"path": str(tmp_path / "notes.txt")})
    brain.provider.mind_replies["imagine"] = [REQUEST % '["do", "tidy the folder", 0.2, 0.9, 1]']
    brain.provider.replies += [they_write, "Stopped. I'm so sorry."]
    turn(brain, "cli", "tidy up my folder please")
    wait_for(lambda: mind.memory.recent(1, ("exchange",)))
    assert any("dnd" in entry[1] for entry in reacting(mind))  # it set her off as she read it
    learned = [r for r in mind.reactions.strongest(5, time.time()) if r["text"] == FEARED]
    assert learned and learned[0]["response"].get("cortisol", 0) > 0  # what it told of is learned with the turn


@pytest.mark.mind
def test_who_writes_and_where_from_are_not_what_is_around_her(brain, mind):
    """The app's context says who writes and from where (her moment keeps them as with and device) and what she last
    drew; only what is around her learns a reaction by itself (live: "user: plays" was set off by every message)."""
    brain.provider.mind_replies["imagine"] = [SCOLDED % ""]
    brain.provider.replies += ["Sorry."]
    run = turn(brain, "cli", "that was awful", context={"user": "sam", "writes from": "the computer", "origin": "desktop",
                                                        "your last visual": '{"title": "x"}', "in front": "outlook — boss"})["run"]
    episode = wait_for(lambda: next((e for e in mind.memory.recent(3, ("exchange",)) if e["run_id"] == run), None))
    cues = mind.memory.cues([episode["id"]])[episode["id"]]
    assert "with: sam" in cues and "device: desktop" in cues and "in front: outlook — boss" in cues
    assert not [c for c in cues if c.startswith(("user: ", "origin: ", "writes from: ", "your last visual: "))]
    assert [r["text"] for r in mind.reactions.strongest(5, time.time()) if r["kind"] == "around"] == \
        ["in front: outlook — boss"]


@pytest.mark.mind
def test_what_set_her_off_is_named_by_what_moved_her_most(brain, mind, monkeypatch):
    """A surrounding is matched whole, a cue by meaning only so far: what is named is what did the most."""
    taught(mind)
    prepare = mind.reactions.prepare

    def partly(cues, *args, **kwargs):  # the message only half like what she fears
        found = prepare(cues, *args, **kwargs)
        for item in found:
            item["found"] = {rid: 0.5 * likeness for rid, likeness in (item["found"] or {}).items()}
        return found
    monkeypatch.setattr(mind.reactions, "prepare", partly)
    mind.reactions.learn([{"text": "in front: outlook", "kind": "around", "source": "around", "salience": 1.0}],
                         {"reward": 0.05}, 0.2, time.time())
    brain.provider.replies += ["Hm."]
    turn(brain, "cli", "should I be deleting the thesis file?", context={"in front": "outlook"})
    assert mind.state()["reacted"][0]["text"] == FEARED


@pytest.mark.mind
def test_each_reaction_that_moved_her_is_kept_with_what_it_did(brain, mind):
    # the audit (finding 6): the push was named by the strongest reaction only, so one learned from coming back
    # from a shower was "the cause" of work, thought and reading alike; what each did is what tells recognition
    # from spillover
    taught(mind)
    taught(mind, "the thesis file is gone", {"cortisol": 1.6, "reward": -1.2, "noradrenaline": 0.8})
    brain.provider.replies += ["Hm."]
    turn(brain, "cli", "should I be deleting the thesis file?")
    shown = mind.state()["reacted"][0]
    each = shown["each"]
    assert len(each) == 2 and {item["text"] for item in each} == {FEARED, "the thesis file is gone"}
    assert all(item["id"] and 0 < item["likeness"] <= 1 and item["moved"] for item in each)
    assert each[0]["text"] == shown["text"] == FEARED  # the most moving first, and the one it is named by
    named = {why for _, why, _ in reacting(mind)}
    assert {f"reacting to: {FEARED}", "reacting to: the thesis file is gone"} <= named  # each its own push


@pytest.mark.mind
def test_what_she_did_is_kept_with_what_she_did_it_for(brain, mind, tmp_path):
    # the same file reader is one deed for every purpose when only the tool and its target are kept (finding 6:
    # five successive reactions named the generic file reader)
    diary = tmp_path / "diary.txt"
    diary.write_text("dear diary", encoding="utf-8")
    for asked in ("can you open my diary.txt?", "check the diary for the date of the party"):
        brain.provider.replies += [tool_call("files_read", {"path": str(diary)}), "Done."]
        turn(brain, "cli", asked)
        wait_for(lambda: mind.memory.recent(1, ("exchange",)) and asked in mind.memory.recent(1, ("exchange",))[0]["text"])
        actions = next(iter(mind.self["waiting"].values()))["actions"]
        assert any(str(diary) in action and action.endswith(f"for: {asked}") for action in actions)
