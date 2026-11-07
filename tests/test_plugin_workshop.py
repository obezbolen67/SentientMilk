"""The model makes plugins itself (the plugins toolkit). Installing or reloading one always asks the user,
whatever the rules or the app's bypass, and the tools of a plugin the user has not trusted ask every time,
however they are marked. Trust belongs to a plugin's exact files: a change takes it away."""

import json

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.client import BrainError
from sentientmilk_framework.testing import tool_call

MANIFEST = {"name": "moon", "version": "0.1.0", "description": "The moon.", "toolkits": ["tools.py"]}
TOOLS = '''
from sentientmilk_framework.toolkits import Toolkit, tool


@tool(readonly=True)
def moon_phase(ctx):
    """Today's moon phase."""
    return "WAXING"


TOOLKIT = Toolkit("moon", "The moon.", [moon_phase])
'''


@pytest.fixture
def workshop(brain):
    brain.client.declare_app("cli", name="CLI", environment="A terminal.",
                             toolkits=["files", "shell", "todo", "plugins"])
    folder = brain.work / "moon"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (folder / "tools.py").write_text(TOOLS, encoding="utf-8")
    return folder


def approvals_of(result):
    return [e for e in result["events"] if e["type"] == "approval.requested"]


def install(brain, decision="allow", folder="moon"):
    brain.provider.replies += [tool_call("plugin_install", {"folder": folder}, "i1"), "installed"]
    return turn(brain, "cli", "make yourself a moon tool", on_approval=lambda event: decision)


def results(brain):
    return {m["tool_call_id"]: m["content"] for p in brain.provider.sent for m in p["messages"] if m["role"] == "tool"}


def test_she_installs_her_plugin_after_asking_and_its_tools_ask_until_trusted(brain, workshop):
    asked = approvals_of(install(brain))
    assert [(e["name"], e["always_ask"]) for e in asked] == [("plugin_install", True)]
    said = results(brain)["i1"]
    assert "moon_phase" in said and "ask the user every time" in said
    plugin = next(p for p in brain.client.plugins() if p["name"] == "moon")
    assert plugin["enabled"] and not plugin["trusted"] and plugin["source"] == str(workshop)

    brain.provider.replies += [tool_call("moon_phase", {}, "m1"), "it waxes"]
    asked = approvals_of(turn(brain, "cli", "moon?", on_approval=lambda event: "allow"))
    assert [(e["name"], e["always_ask"]) for e in asked] == [("moon_phase", True)]  # marked read-only, all the same
    assert results(brain)["m1"] == "WAXING"

    brain.client.update_plugin("moon", trusted=True)
    brain.provider.replies += [tool_call("moon_phase", {}, "m2"), "it waxes"]
    assert approvals_of(turn(brain, "cli", "moon again?")) == []  # trusted: its own policy

    (workshop / "tools.py").write_text(TOOLS.replace("WAXING", "FULL"), encoding="utf-8")
    brain.provider.replies += [tool_call("plugin_reload", {"name": "moon"}, "r1"), tool_call("moon_phase", {}, "m3"),
                               "full now"]
    asked = approvals_of(turn(brain, "cli", "fix it", on_approval=lambda event: "allow"))
    assert [e["name"] for e in asked] == ["plugin_reload", "moon_phase"]  # new files: not trusted any more
    assert results(brain)["m3"] == "FULL"


def test_nothing_skips_asking_to_install(brain, workshop):
    brain.client.update_app("cli", rules={"allow": ["plugin_install", "plugin_*"]})
    assert approvals_of(install(brain, decision="always"))
    brain.client.remove_plugin("moon")
    assert approvals_of(install(brain))  # "always" was this once: no rule was saved
    brain.client.remove_plugin("moon")
    brain.client.update_app("cli", rules={"deny": ["plugin_install(*)"]})
    assert approvals_of(install(brain)) == [] and "not allowed" in results(brain)["i1"]  # deny still wins
    assert not any(p["name"] == "moon" for p in brain.client.plugins())


def test_a_denied_install_installs_nothing(brain, workshop):
    install(brain, decision="deny")
    assert "did not allow" in results(brain)["i1"]
    assert not (brain.home / "plugins" / "moon").exists()


def test_she_installs_only_from_folders_open_to_her_and_never_over_a_built_in(brain, workshop, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    install(brain, folder=str(outside))
    assert "outside the folders open to you" in results(brain)["i1"]
    (workshop / "plugin.json").write_text(json.dumps({**MANIFEST, "name": "github"}), encoding="utf-8")
    install(brain)
    assert "built in" in results(brain)["i1"]


def test_a_task_waiting_to_install_says_it_must_ask(brain, workshop):
    brain.provider.replies += [tool_call("plugin_install", {"folder": "moon"}, "t1"), "done"]
    task = brain.client.start_task("cli", "install the moon plugin", session="main")
    wait_for(lambda: brain.client.run(task["id"])["status"] == "input_required")
    assert [(w["name"], w["always_ask"]) for w in brain.client.run(task["id"])["waiting"]] == [("plugin_install", True)]


def test_trust_belongs_to_the_files(brain, workshop):
    installed = brain.client.install_plugin(str(workshop))  # the user installs it: trusted
    assert installed["trusted"]
    copy = brain.home / "plugins" / "moon" / "tools.py"
    copy.write_text(copy.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    brain.brain.plugins.load()  # as at the next start
    assert not next(p for p in brain.client.plugins() if p["name"] == "moon")["trusted"]
    assert brain.brain.plugins.toolkits()["moon"].tools[0].policy == "always"
    assert next(p for p in brain.client.plugins() if p["name"] == "github")["trusted"]  # built in
    with pytest.raises(BrainError, match="built in"):
        brain.client.reload_plugin("github")


def test_the_list_says_what_she_has_and_how_to_make_one(brain, workshop):
    brain.provider.replies += [tool_call("plugin_list", {}, "l1"), "listed"]
    assert approvals_of(turn(brain, "cli", "what plugins?")) == []
    listed = results(brain)["l1"]
    assert "github" in listed and "trusted" in listed
    from sentientmilk_framework.toolkits import builtin

    guide = {t.name: t.description for t in builtin()["plugins"].tools}["plugin_install"]
    assert "plugin.json" in guide and "TOOLKIT" in guide and "ctx.brain.plugins.settings" in guide
