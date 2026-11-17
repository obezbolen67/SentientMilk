"""Her ways (0.34): how she does things, kept as if-then ways that hold in every chat, grow as she keeps them and
are gone over in her sleep (design: docs/superpowers/specs/2026-11-17-ways-design.md)."""

import json
import time

import pytest
from conftest import turn

from sentientmilk_framework.mind.ways import DAY, Ways
from sentientmilk_framework.testing import tool_call

NOW = 1_800_000_000.0


def test_a_way_is_kept_once_by_its_name_and_grows_as_she_keeps_it():
    ways = Ways()
    ways.keep("Sign Replies", "I answer", "I sign with a milk glass", "told", NOW)
    ways.keep("sign_replies", "I answer the user", "I end with a milk glass", "told", NOW)
    assert [(w["name"], w["when"], w["then"], w["strength"]) for w in ways.known] == [
        ("sign_replies", "I answer the user", "I end with a milk glass", 0.5)]
    for night, expected in enumerate((0.625, 0.71875, 0.7890625), 1):
        assert ways.review(["sign_replies"], [], NOW + night * DAY)
        assert ways.known[0]["strength"] == pytest.approx(expected)
    ways.review([], ["Sign replies"], NOW + 4 * DAY)  # a lapse costs a little, it does not undo the way
    assert ways.known[0]["strength"] == pytest.approx(0.7890625 * 0.85)
    assert ways.known[0]["kept"] == 3 and ways.known[0]["broken"] == 1
    assert not ways.review(["never_heard_of"], ["nor_this"], NOW + 5 * DAY)


def test_an_unused_way_fades_and_goes():
    ways = Ways()
    ways.keep("tabs", "I write code", "I indent with tabs", "decided", NOW)
    assert ways.fade(NOW + 29 * DAY) == [] and ways.known[0]["strength"] == 0.5  # used lately: it holds
    night, gone = 31, []
    while not gone:
        gone = ways.fade(NOW + night * DAY)
        night += 1
    faded = night - 31  # nights it faded, the last one taking it under 0.1
    assert gone == ["tabs"] and not ways.known and 0.5 * 0.95 ** faded < 0.1 <= 0.5 * 0.95 ** (faded - 1)


def test_her_ways_read_as_habits_and_as_what_she_took_on():
    ways = Ways()
    assert ways.section() == ""
    ways.keep("test_first", "I finish a piece of code", "I run it before I say it's done", "told", NOW)
    ways.keep("quiet", "nobody has spoken to me", "I don't message first", "habit", NOW)
    ways.known[0]["strength"] = 0.8
    shown = ways.section()
    assert shown.startswith("## YOUR WAYS")
    habits, lately = shown.split("Habits of yours")[1].split("What you took on lately")
    assert "When I finish a piece of code: I run it before I say it's done" in habits
    assert "When nobody has spoken to me: I don't message first" in lately
    assert ways.drop("Quiet") and not ways.drop("quiet")
    assert [w["name"] for w in Ways(ways.to_dict()).listed()] == ["test_first"]  # kept and loaded again


@pytest.mark.mind  # her mind lives in this one
def test_her_ways_are_in_every_chat_and_in_her_thoughts(brain):
    mind = brain.brain.mind
    mind.keep_way("sign_off", "I answer the user", "I end with a milk glass", "told")
    for session in ("a", "b"):
        brain.provider.replies += ["Hi."]
        turn(brain, "cli", "hello", session=session)
        system = brain.provider.sent[-1]["messages"][0]["content"]
        assert "## YOUR WAYS" in system and "When I answer the user: I end with a milk glass" in system
    taken = brain.store.session("cli", "a")["state"]["snapshot"]["at"]
    brain.provider.replies += ["Again."]
    turn(brain, "cli", "and again", session="a")  # nothing changed: the chat's cached prompt holds
    assert brain.store.session("cli", "a")["state"]["snapshot"]["at"] == taken
    mind.keep_way("short", "the user asks a quick thing", "I answer in a line", "told")
    assert "snapshot" not in brain.store.session("cli", "a")["state"]  # her ways changed: taken again
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Quiet day.", "want": "nothing"})]
    mind._think("wonder", None)
    asked = [r["messages"][1]["content"] for r in brain.provider.mind_requests
             if r["messages"][0]["content"].startswith("[mind:think]")][-1]
    assert "How they do things: When I answer the user: I end with a milk glass" in asked
    assert [w["name"] for w in mind.state()["ways"]] == ["sign_off", "short"]
    assert mind.drop_way("SHORT") and not mind.drop_way("short")


def test_told_how_to_do_things_from_now_on_she_keeps_it_as_a_way(brain):
    profile = brain.brain.profile("bare", "main")
    assert {"ways_keep", "ways_drop"} <= set(brain.brain.toolset(profile, "turn").by_name)  # a part of her, every app
    keep = {"name": "sign_off", "when": "I answer the user", "then": "I end with a milk glass"}
    brain.provider.replies += [tool_call("ways_keep", keep), "From now on."]
    result = turn(brain, "cli", "from now on, end every message with a milk glass")
    ended = [e for e in result["events"] if e["type"] == "tool.end"]
    assert ended[0]["result"] == "Your way from now on, in every chat: when I answer the user, I end with a milk glass."
    way = brain.brain.mind.ways.find("sign_off")
    assert way["source"] == "told" and way["strength"] == 0.5
    brain.provider.replies += [tool_call("ways_drop", {"name": "nope"}), tool_call("ways_drop", {"name": "sign_off"}),
                               "Okay."]
    result = turn(brain, "cli", "stop that")
    assert [e["result"] for e in result["events"] if e["type"] == "tool.end"] == [
        "You have no way called nope.", "You no longer do this: when I answer the user, I end with a milk glass."]
    assert brain.brain.mind.ways.known == []


@pytest.mark.mind
def test_sleep_tells_which_ways_she_kept_and_what_she_fell_into(brain):
    mind = brain.brain.mind
    mind.keep_way("sign_off", "I answer the user", "I end with a milk glass", "told")
    mind.keep_way("tabs", "I write code", "I indent with tabs", "decided")
    mind.self["slept"] = time.time() - 60
    brain.provider.replies += [tool_call("memory_save", {"key": "server", "value": "staging"}),
                               tool_call("memory_save", {"key": "port", "value": "8080"}, "c2"), "Saved. 🥛"]
    turn(brain, "cli", "use the staging server on 8080")
    brain.provider.mind_replies["ways"] = [json.dumps({
        "kept": ["sign_off"], "broken": ["nothing_like_it"], "dropped": ["tabs"],
        "new": [{"name": "Read Back", "when": "I save something", "then": "I read it back", "from": "habit"},
                {"name": "sign_off", "when": "never", "then": "a twin"}]})]
    mind._consolidate()
    asked = [r for r in brain.provider.mind_requests if r["messages"][0]["content"].startswith("[mind:ways]")][-1]
    day = asked["messages"][1]["content"]
    assert "use the staging server on 8080" in day and "memory_save x2" in day and "Saved. 🥛" in day
    assert "sign_off: when I answer the user, I end with a milk glass" in day
    shown = {w["name"]: (w["source"], w["strength"], w["then"]) for w in mind.state()["ways"]}
    assert shown == {"sign_off": ("told", 0.625, "I end with a milk glass")}
    brain.provider.mind_replies["ways"] = ["not json at all"]
    mind.self["slept"] = time.time() - 60
    mind._consolidate()  # a night whose answer says nothing changes nothing
    assert {w["name"]: w["strength"] for w in mind.state()["ways"]} == {"sign_off": 0.625}
