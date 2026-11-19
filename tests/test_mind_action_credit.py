"""What she did is the way whose operation actually went through, told apart by its receipt; what cannot be
established teaches nothing (docs/superpowers/specs/2026-11-19-attention-and-action-credit-design.md, part 3)."""

import json

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.loop import Toolset
from sentientmilk_framework.testing import leaning, tool_call
from sentientmilk_framework.toolkits import Tool, ToolError

pytestmark = pytest.mark.mind  # her mind lives in these tests

CARD = {"type": "object", "properties": {"disposition": {"type": "string", "enum": ["open", "later"]}},
        "required": ["disposition"]}
MAIL = {"type": "object", "properties": {"to": {"type": "string"}, "body": {"type": "string"}}, "required": ["to"]}


def offer(*options):
    return json.dumps(["they offer something", 0.1, 0.1, 0.0, "fine", "request", "puzzles", "", "", *options])


OPEN = ["do", "open the card", 0.2, 0.9, 1, {"tool": "choose_card", "target": {"disposition": "open"}}]
LATER = ["later", "file the card for later", 0.05, 0.9, 0, {"tool": "choose_card", "target": {"disposition": "later"}}]
SEND = ["do", "send the note to Sam", 0.3, 0.8, 1, {"tool": "mail_send", "target": {}}]
DRAFT = ["part", "draft the note for them to check", 0.2, 0.9, 0.6, {"tool": "mail_draft", "target": {}}]


@pytest.fixture
def desk(brain, monkeypatch):
    """A card that can be opened or filed for later, and a stand-in inbox with drafts, beside her usual tools;
    ``failing``: how many sends fail before one goes through."""
    box = {"cards": [], "drafts": [], "sent": [], "failing": 0}

    def choose_card(ctx, disposition):
        box["cards"].append(disposition)
        return "Card opened: unscramble LIMK." if disposition == "open" else \
            "Filed in the later tray." if disposition == "later" else "Unknown disposition."

    def mail_send(ctx, to, body=""):
        if box["failing"]:
            box["failing"] -= 1
            raise ToolError("The mail server did not answer.")
        box["sent"].append((to, body))
        return "Sent."

    def mail_draft(ctx, to, body=""):
        box["drafts"].append((to, body))
        return "Saved as a draft."

    extra = [Tool("choose_card", "Open the optional card now, or put it unopened in the later tray.", CARD, choose_card,
                  policy="auto", toolkit="cards", core=True),
             Tool("mail_send", "Send a message to someone's inbox.", MAIL, mail_send, policy="auto", toolkit="mail",
                  core=True),
             Tool("mail_draft", "Save a message as a draft without sending it.", MAIL, mail_draft, policy="auto",
                  toolkit="mail", core=True)]
    original = brain.brain.toolset

    def toolset(profile, kind):
        base = original(profile, kind)
        return Toolset([*base.by_name.values(), *extra], [], dict(base.kits, cards="A card.", mail="Mail."),
                       base.parts, [*base.order, "cards", "mail"])
    monkeypatch.setattr(brain.brain, "toolset", toolset)
    return box


def decided(brain, result):
    mind = brain.brain.mind
    wait_for(lambda: (mind.self["decided"] or {}).get("run") == result["run"] and mind.self["decided"]["outcome"])
    return mind.self["decided"]["outcome"], brain.store.run(result["run"])["options"]["mind"]


def test_her_reading_sees_what_she_can_do_here_and_the_values_its_arguments_take(brain, desk):
    brain.provider.mind_replies["imagine"] = [offer(OPEN, LATER)]
    brain.provider.replies += ["Hm."]
    turn(brain, "milk", "there's a puzzle card here, open it now or file it, up to you")
    asked = next(r for r in brain.provider.mind_requests if r["messages"][0]["content"].startswith("[mind:imagine]"))
    listed = asked["messages"][1]["content"].split("Operations they can do here:")[1]
    assert "choose_card: Open the optional card now, or put it unopened in the later tray (disposition: open|later)" \
        in listed and "mail_draft:" in listed
    assert "memory_" not in listed and "context_compact" not in listed and "look_inward" not in listed


def test_one_tool_with_two_effects_credits_the_way_its_arguments_carried_out(brain, desk):
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = [offer(OPEN, LATER)]
    brain.provider.replies += [tool_call("choose_card", {"disposition": "later"}), "Filed it for later."]
    result = turn(brain, "milk", "there's a puzzle card here, open it now or file it, up to you")
    outcome, decision = decided(brain, result)
    assert outcome["did"] == "later" and desk["cards"] == ["later"]  # not "do": a successful call is not doing it
    assert outcome["enacted"]["tool"] == "choose_card" and outcome["enacted"]["status"] == "ok"
    assert [one["check"]["target"] for one in decision["could"]] == [{"disposition": "open"}, {"disposition": "later"}]
    assert any(c["run"] == result["run"] for c in mind.self["concerns"])  # put off: still to come back to
    waiting = mind.self["waiting"]["milk\nmain"]
    assert waiting["act"] == "later" and "act:later" in waiting["features"]
    brain.provider.mind_replies["imagine"] = [offer(OPEN, LATER)]
    brain.provider.replies += [tool_call("choose_card", {"disposition": "open"}), "Opened it: MILK."]
    result = turn(brain, "milk", "another card for you, same deal")
    outcome, _ = decided(brain, result)
    assert outcome["did"] == "do" and outcome["enacted"]["tool"] == "choose_card"


def test_a_draft_is_part_of_it_and_a_send_is_all_of_it(brain, desk):
    for calls, did in (([("mail_draft", {"to": "sam", "body": "hi"})], "part"),
                       ([("mail_send", {"to": "sam", "body": "hi"})], "do"),
                       ([("mail_draft", {"to": "sam", "body": "hi"}), ("mail_send", {"to": "sam", "body": "hi"})], "do")):
        brain.provider.mind_replies["imagine"] = [offer(SEND, DRAFT)]
        brain.provider.replies += [tool_call(name, args, f"call_{name}") for name, args in calls] + ["Done."]
        result = turn(brain, "milk", "could you write Sam a note saying hi?")
        outcome, _ = decided(brain, result)
        assert outcome["did"] == did and outcome["enacted"]["tool"] == calls[-1][0] if did == "do" else \
            outcome["did"] == did and outcome["enacted"]["tool"] == "mail_draft"
    assert desk["drafts"] and desk["sent"]


def test_a_send_that_fails_then_goes_through_is_credited_once(brain, desk):
    mind = brain.brain.mind
    desk["failing"] = 1
    brain.provider.mind_replies["imagine"] = [offer(SEND, DRAFT)]
    brain.provider.replies += [tool_call("mail_send", {"to": "sam"}, "call_1"), tool_call("mail_send", {"to": "sam"}, "call_2"),
                               "Sent on the second try."]
    result = turn(brain, "milk", "please send Sam a hello")
    outcome, decision = decided(brain, result)
    assert outcome["did"] == "do" and outcome["enacted"]["call"] == "call_2"
    acts = [f for f in decision["features"] if f.startswith("act:")]
    assert all(mind.values.uses.get(f.replace(f"act:{decision['act']}", "act:do"), 0) <= 1 for f in acts)


def test_a_call_no_way_foresaw_leaves_what_she_did_unresolved_and_teaches_nothing(brain, desk):
    mind = brain.brain.mind
    weights = dict(mind.values.weights)
    brain.provider.mind_replies["imagine"] = [offer(OPEN, LATER)]
    brain.provider.replies += [tool_call("choose_card", {"disposition": "shred"}), "I did something with it."]
    result = turn(brain, "milk", "there's a puzzle card here, open it now or file it, up to you")
    outcome, _ = decided(brain, result)
    assert outcome["did"] == "unresolved" and outcome["evidence"] == "no option foresaw what was done"
    assert outcome["learned"]["values"] == {} and not any(k.startswith("act:") and k not in weights
                                                          for k in mind.values.weights)
    waiting = mind.self["waiting"]["milk\nmain"]
    assert waiting["act"] == "unresolved" and waiting["features"] == []  # the next message teaches no act either
    assert "Which of the ways I weighed that was, nothing shows." in mind.memory.of_run(result["run"])["text"]


def test_a_denied_operation_carries_nothing_out_and_teaches_nothing(brain, desk, monkeypatch):
    for tool in brain.brain.toolset(brain.brain.profile("milk", "main"), "turn").by_name.values():
        if tool.name == "mail_send":
            monkeypatch.setattr(tool, "policy", "ask")
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = [offer(SEND, DRAFT)]
    brain.provider.replies += [tool_call("mail_send", {"to": "sam"}), "It was not allowed."]
    result = turn(brain, "milk", "please send Sam a hello", on_approval=lambda _: "deny")
    outcome, _ = decided(brain, result)
    assert outcome["evidence"] == "denied" and outcome["enacted"] is None and outcome["learned"]["values"] == {}
    assert not mind.memory.of_run(result["run"]) or "denied" not in outcome["did"]


def test_putting_it_off_by_scheduling_it_keeps_it_to_come_back_to(brain):
    mind = brain.brain.mind
    write = ["do", "write the summary file", 0.5, 0.8, 1, {"tool": "files_write", "target": {}}]
    later = ["later", "remind themselves tomorrow", 0.05, 0.9, 0, {"tool": "schedule_create", "target": {}}]
    brain.provider.mind_replies["imagine"] = [offer(write, later)]
    brain.provider.replies += [tool_call("schedule_create", {"when": "in 1d", "text": "write the summary"}),
                               "I'll do it tomorrow morning."]
    result = turn(brain, "cli", "write up the summary when you can", on_approval=lambda _: "allow")
    outcome, decision = decided(brain, result)
    assert outcome["did"] == "later" and outcome["enacted"]["tool"] == "schedule_create"
    assert any(c["run"] == result["run"] and c["at"] == decision["at"] for c in mind.self["concerns"])
    assert not any(e.get("name") == "files_write" for e in brain.store.run_events(result["run"]))


def test_looking_inward_or_noting_something_down_is_not_acting_in_the_world(brain, desk):
    mind = brain.brain.mind
    brain.provider.mind_replies["imagine"] = [offer(OPEN, LATER)]
    brain.provider.replies += [tool_call("look_inward", {}), tool_call("choose_card", {"disposition": "later"}),
                               "Filed it."]
    outcome, _ = decided(brain, turn(brain, "milk", "there's a puzzle card here, open it now or file it, up to you"))
    assert outcome["did"] == "later"  # was "do": the look counted as work done
    brain.provider.mind_replies["imagine"] = ['["they say hi", 0.2, 0.1, 0.0, "fine", "chat", "greeting", ""]']
    brain.provider.replies += [tool_call("look_inward", {}), tool_call("todo_write", {"todos": []}), "Hi!"]
    result = turn(brain, "milk", "hey you")
    decision = brain.store.run(result["run"])["options"]["mind"]
    assert decision["act"] == "talk" and "acted" not in decision  # a chat stays a chat
    wait_for(lambda: mind.memory.of_run(result["run"]))


def test_her_reading_of_an_operation_is_read_by_shape_with_its_arguments_beside_the_tool():
    from sentientmilk_framework.mind.will import Option
    flat = Option.read({"act": "later", "what": "file it", "check": {"tool": "choose_card", "disposition": "later"}})
    assert flat.check == {"tool": "choose_card", "target": {"disposition": "later"}}
    assert Option.read({"act": "do", "check": {"tool": "mail_send", "target": {}}}).check == {"tool": "mail_send", "target": {}}


def test_with_no_operation_foreseen_a_call_is_her_doing_only_when_she_leaned_to_do_it(brain, desk, monkeypatch):
    bare = [option[:5] for option in (OPEN, LATER)]  # her reading foresaw no operation
    for leans, did in (("later", "unresolved"), ("do", "do")):  # was "do" both times: filing it learned as done
        leaning(monkeypatch, leans)
        brain.provider.mind_replies["imagine"] = [offer(*bare)]
        brain.provider.replies += [tool_call("choose_card", {"disposition": "later"}, f"call_{leans}"), "Done."]
        outcome, decision = decided(brain, turn(brain, "milk", "there's a puzzle card here, open it now or file it"))
        assert decision["act"] == leans and outcome["did"] == did
