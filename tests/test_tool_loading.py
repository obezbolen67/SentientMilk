"""Tools on demand: requests carry the core tools and two meta-tools; the rest are listed in the system prompt,
loaded into the conversation with tools_load and called by name."""

import pytest
from conftest import turn

from sentientmilk_framework import BrainError
from sentientmilk_framework.testing import tool_call
from sentientmilk_framework.toolkits import Tool, Toolkit


def sent_names(payload):
    return [t["function"]["name"] for t in payload.get("tools") or []]


def tool_results(payload):
    return {m["tool_call_id"]: m["content"] for m in payload["messages"] if m["role"] == "tool"}


def system(payload):
    return payload["messages"][0]["content"]


def test_requests_carry_the_core_tools_and_list_the_rest(brain):
    brain.provider.replies += [tool_call("files_find", {"pattern": "*.txt"}, "f"), "none", "hi"]
    turn(brain, "cli", "find text files")
    turn(brain, "cli", "and now?")
    first, *others = brain.provider.sent
    assert set(sent_names(first)) == {"memory_save", "todo_write", "files_read", "files_search", "shell_run",
                                      "shell_output", "web_search", "web_fetch", "tools_search", "tools_load",
                                      'history_read', 'history_search', 'context_compact'}
    assert all(other["tools"] == first["tools"] for other in others)  # one tool list: the cache keeps hitting
    listed = system(first).split("## YOUR TOOLS", 1)[1]
    assert 'schedule_create(when, text, timezone?, title?)' in listed
    assert 'schedule_update(id, when?, text?, timezone?, title?, enabled?)' in listed
    assert "files_edit(path, old, new, all?)" in listed  # called right before it is loaded
    # one map of all it can do: the tools sent by name, the others to load with their parameters
    assert "- files (Read, search and change files in the folders opened to you.): files_read, files_search; " \
        "load: files_find(pattern, path?)" in listed
    assert "agent_start(name, task, super_agent?)" in listed


def test_a_listed_tool_is_loaded_then_called_by_name(brain):
    (brain.work / "notes.txt").write_text("x", encoding="utf-8")
    brain.provider.replies += [tool_call("tools_load", {"names": ["files_find"]}, "l"),
                               tool_call("files_find", {"pattern": "*.txt"}, "f"), "found notes.txt"]
    assert turn(brain, "cli", "which text files are there?")["reply"] == "found notes.txt"
    loaded = tool_results(brain.provider.sent[1])["l"]
    assert '"name":"files_find"' in loaded.replace(" ", "") and '"pattern"' in loaded and "by name" in loaded
    assert "notes.txt" in tool_results(brain.provider.sent[2])["f"]
    assert brain.provider.sent[2]["tools"] == brain.provider.sent[0]["tools"]


def test_wrong_arguments_and_unknown_names_say_how_to_call(brain):
    broken = tool_call("files_find", {}, "j")
    broken["tool_calls"][0]["function"]["arguments"] = '{"pattern": "say "hi"\n"}'  # a long text, unescaped
    listed = tool_call("files_find", {}, "l")
    listed["tool_calls"][0]["function"]["arguments"] = '["*.txt"]'
    lines = tool_call("files_find", {}, "b")
    lines["tool_calls"][0]["function"]["arguments"] = '{"pattern": "*.txt\n"}'  # a raw line break is accepted
    brain.provider.replies += [tool_call("files_find", {"glob": "*.txt"}, "w"), tool_call("files_findd", {}, "u"),
                               tool_call("tools_load", {"names": ["nope"]}, "n"), broken, listed, lines, "ok"]
    turn(brain, "cli", "find")
    results = tool_results(brain.provider.sent[-1])
    assert results["w"].startswith("Error:") and '"pattern"' in results["w"]  # its parameters
    for broken_id in "jl":  # broken JSON names the tool and shows how to call it, as wrong keys do
        assert results[broken_id].startswith("Error: The arguments for files_find") and '"pattern"' in results[broken_id]
    assert "not valid JSON" in results["j"] and "escaped" in results["j"]
    assert not results["b"].startswith("Error")
    assert "There is no tool 'files_findd'" in results["u"] and "files_find" in results["u"] \
        and "tools_search" in results["u"]
    assert results["n"].startswith("Error:") and "tools_search" in results["n"]


def test_tools_search_ranks_by_what_tools_do(brain):
    brain.provider.replies += [tool_call("tools_search", {"query": "reminders"}, "s"),
                               tool_call("tools_search", {"query": "I want to be reminded of a thing"}, "q"),
                               tool_call("tools_search", {"query": ""}, "all"), "ok"]
    turn(brain, "cli", "search")
    results = tool_results(brain.provider.sent[-1])
    first = results["s"].splitlines()[0]
    assert first.startswith("schedule_") and "load it" in first
    assert results["q"].splitlines()[0].startswith("schedule_")  # short words ("I", "a", "of") match nothing
    catalog = results["all"]
    assert "files_read" in catalog and "ready" in catalog and "schedule_delete" in catalog


def test_many_mcp_tools_are_listed_by_toolkit_and_found_by_search(brain, monkeypatch):
    calls = []
    many = [Tool(name=f"mcp__big__t{i}", description=f"Tool number {i} of the big server.", toolkit="mcp:big",
                 parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
                 func=lambda ctx, x=0, i=i: calls.append((i, x)) or f"t{i} got {x}", policy="auto")
            for i in range(80)]
    monkeypatch.setattr(brain.brain.mcp, "toolkits", lambda: {"mcp:big": Toolkit("mcp:big", "A big server.", many)})
    monkeypatch.setattr(brain.brain.mcp, "servers", lambda: ["big"])
    brain.client.declare_app("big", toolkits=["memory", "mcp:*"])
    brain.provider.replies += [tool_call("tools_search", {"query": "number 7", "limit": 3}, "s"),
                               tool_call("mcp__big__t7", {"x": 3}, "c"), "done"]
    turn(brain, "big", "use t7")
    assert not any(name.startswith("mcp__") for name in sent_names(brain.provider.sent[0]))
    listed = system(brain.provider.sent[0]).split("## YOUR TOOLS", 1)[1]
    # every tool of a server is listed with what it is for, however many: a count hid what it could do
    assert "- mcp:big [from an MCP server the user added] (A big server.): load:\n" in listed
    assert "  - mcp__big__t79(x?): Tool number 79 of the big server.\n" in listed
    assert tool_results(brain.provider.sent[1])["s"].splitlines()[0].startswith("mcp__big__t7 ")
    assert calls == [(7, 3)] and tool_results(brain.provider.sent[2])["c"] == "t7 got 3"


def test_an_mcp_servers_tools_are_listed_with_what_each_is_for(brain, monkeypatch):
    # names alone hid that a game editor's server had its docs, play input and walking (2026-11-09)
    tools = [Tool(name="mcp__studio__list_skills", toolkit="mcp:studio", policy="auto", func=lambda ctx: "",
                  description="Lists every available skill with its source. Call this before starting a task.",
                  parameters={"type": "object", "properties": {"studio_id": {"type": "string"}},
                              "required": ["studio_id"]}),
             Tool(name="mcp__studio__character_navigation", toolkit="mcp:studio", policy="auto", func=lambda ctx: "",
                  description="Navigate the character to the given position, or instance.\nMore text.",
                  parameters={"type": "object", "properties": {"x": {"type": "number"}}})]
    monkeypatch.setattr(brain.brain.mcp, "toolkits", lambda: {"mcp:studio": Toolkit("mcp:studio", "Studio.", tools)})
    monkeypatch.setattr(brain.brain.mcp, "servers", lambda: ["studio"])
    brain.client.declare_app("game", toolkits=["mcp:*"])
    brain.provider.replies += ["ok"]
    turn(brain, "game", "hi")
    listed = system(brain.provider.sent[0]).split("## YOUR TOOLS", 1)[1]
    assert "  - mcp__studio__list_skills(studio_id): Lists every available skill with its source.\n" in listed
    assert "  - mcp__studio__character_navigation(x?): Navigate the character to the given position, or " \
           "instance.\n" in listed


def test_an_app_marks_the_actions_it_wants_sent(brain):
    brain.client.declare_app("acts", toolkits=["web"], actions=[
        {"name": "look", "description": "Look at the screen.", "core": True},
        {"name": "act", "description": "Use the mouse."}])
    brain.provider.replies += ["hi"]
    turn(brain, "acts", "hello")
    names = sent_names(brain.provider.sent[0])
    assert "look" in names and "act" not in names and "tools_load" in names
    assert "- this app's own: look; load: act()" in system(brain.provider.sent[0])
    with pytest.raises(BrainError) as caught:
        brain.client.declare_app("acts", actions=[{"name": "look", "core": "yes"}])
    assert caught.value.type == "bad_request"


def test_with_nothing_to_load_there_are_no_meta_tools(brain):
    brain.client.declare_app("small", toolkits=["web"])
    brain.client.update_app("small", disabled_toolkits=["github"])  # plugins come to every app unless switched off
    brain.provider.replies += ["hi"]
    turn(brain, "small", "hello")
    assert set(sent_names(brain.provider.sent[0])) == {'history_read', 'history_search', 'context_compact',
                                                     'web_search', 'web_fetch'}
    assert "- web (Search the web and read pages.): web_search, web_fetch" in system(brain.provider.sent[0])
    assert "tools_load" not in system(brain.provider.sent[0]) and 'memory_save' not in system(brain.provider.sent[0])


def test_rules_come_only_with_the_tools_they_name(brain):
    brain.client.declare_app("small", toolkits=["web"])
    brain.provider.replies += ["hi", "hi"]
    turn(brain, "cli", "hello")
    turn(brain, "small", "hello")
    full, small = system(brain.provider.sent[0]), system(brain.provider.sent[1])
    assert "memory_save right away" in full and "todo_write" in full and "give the parts to agents" in full
    assert "memory_save" not in small and "todo_write" not in small and "agent_start" not in small


def test_calls_run_in_the_order_the_model_wrote_them(brain):
    """A read after a write that waits for the user's approval runs after the write, not before it."""
    message = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "files_write", "arguments": '{"path": "b.txt", "content": "new"}'}},
        {"id": "r", "type": "function", "function": {"name": "files_read", "arguments": '{"path": "b.txt"}'}}]}
    brain.provider.replies += [message, "done"]
    brain.client.turn("cli", "main", "write it, then read it", on_approval=lambda request: "allow")
    assert "new" in tool_results(brain.provider.sent[-1])["r"]


def test_an_app_action_waits_for_the_calls_before_it(brain):
    """The app runs an action as soon as it is asked: asking it while an earlier call still waited for
    approval ran it first."""
    brain.client.declare_app("acts", toolkits=["files"], actions=[{"name": "act", "description": "Use it.", "core": True}])
    brain.client.update_session("acts", "main", cwd=str(brain.work), roots=[str(brain.work)])
    message = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "files_write", "arguments": '{"path": "c.txt", "content": "x"}'}},
        {"id": "a", "type": "function", "function": {"name": "act", "arguments": "{}"}}]}
    brain.provider.replies += [message, "done"]
    seen = []
    brain.client.turn("acts", "main", "write, then act", on_approval=lambda request: "allow",
                      on_action=lambda request: seen.append((brain.work / "c.txt").exists()) or "acted")
    assert seen == [True]


def test_one_map_of_all_it_can_do_marks_the_parts_of_it(brain):
    brain.provider.replies += ["hi"]
    turn(brain, "cli", "hello")
    listed = system(brain.provider.sent[0]).split("## YOUR TOOLS", 1)[1]
    flat = " ".join(listed.split())
    assert "never by looking for it on the screen or in files" in flat and "is the whole truth about it" in flat
    assert "whatever they say they made, installed or set up for you is here" in flat
    assert "- memory [part of you] (What you remember about the user" in listed
    assert "- agents [part of you]" in listed and "- web (Search the web" in listed  # the world is not a part
    # a tool's guide comes under its toolkit, with the tool
    assert listed.index("save it with memory_save right away") > listed.index("- memory [part of you]")


def test_the_first_turn_after_its_tools_changed_hears_what_changed(brain, tmp_path, monkeypatch):
    import sys

    from test_plugins import make_plugin

    monkeypatch.setattr(brain.brain.superagents, "argv", lambda: [sys.executable])  # super agents can start
    brain.provider.replies += ["hi"] * 4
    turn(brain, "cli", "hello")
    assert "Your tools changed" not in str(brain.provider.sent[-1]["messages"])  # an app's first turn: nothing
    brain.client.install_plugin(str(make_plugin(tmp_path / "notes")))
    brain.client.update_config(super_model="")
    turn(brain, "cli", "I installed something for you, and turned the super model off")
    said = brain.provider.sent[-1]["messages"][-1]["content"]
    assert said.index("Your tools changed") < said.index("I installed something")  # before what the user says
    assert "- new: notes: notes_token" in said and "- agents, no longer: Super agents: Opus 5.5" in said
    # where it came from: the user may say "I installed it for you"
    assert "- notes [from the plugin notes, which the user installed]" in system(brain.provider.sent[-1])
    turn(brain, "cli", "and now?")
    assert "Your tools changed" not in brain.provider.sent[-1]["messages"][-1]["content"]  # said once
