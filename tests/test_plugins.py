"""Plugins: folders with a plugin.json that bring toolkits, MCP servers and settings to every app."""

import json
import shutil
import subprocess

import pytest

from sentientmilk_framework.client import BrainError

PLUGIN = {
    "name": "notes", "version": "1.2.0", "description": "Notes kept in a folder.",
    "toolkits": ["tools.py"],
    "settings": {"token": {"label": "Token", "secret": True, "env": ["NOTES_TOKEN"], "help": "Any word."},
                 "folder": {"label": "Folder", "default": "D:/notes"}},
}
TOOLS = '''
from sentientmilk_framework.toolkits import Toolkit, tool
from . import helpers


@tool(readonly=True)
def notes_token(ctx):
    """The token the plugin got."""
    return helpers.show(ctx.brain.plugins.settings("notes"))


TOOLKIT = Toolkit("notes", "Notes kept in a folder.", [notes_token])
'''
HELPERS = '''
def show(settings):
    return f"token={settings['token']} folder={settings['folder']}"
'''


def make_plugin(folder, manifest=None, tools=TOOLS):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps(manifest or PLUGIN), encoding="utf-8")
    (folder / "tools.py").write_text(tools, encoding="utf-8")
    (folder / "helpers.py").write_text(HELPERS, encoding="utf-8")
    return folder


def by_name(client, name):
    return next(plugin for plugin in client.plugins() if plugin["name"] == name)


def test_github_is_built_in_and_offered_to_every_app(brain):
    github = by_name(brain.client, "github")
    assert github["builtin"] and github["enabled"] and not github["error"] and github["tools"] >= 12
    assert "github" in brain.client.toolkits()["toolkits"]
    assert "github" in brain.client.toolkits("milk")["enabled"]  # milk does not declare it: plugins are for all
    brain.client.update_app("milk", disabled_toolkits=["github"])
    assert "github" not in brain.client.toolkits("milk")["enabled"]  # an app can still switch it off


def test_a_plugin_folder_brings_its_tools_and_settings(brain, monkeypatch):
    make_plugin(brain.home / "plugins" / "notes")
    monkeypatch.setenv("NOTES_TOKEN", "from-env")
    brain.brain.plugins.load()
    notes = by_name(brain.client, "notes")
    assert notes["version"] == "1.2.0" and notes["enabled"] and notes["toolkits"] == ["notes"]
    assert notes["settings"]["token"] == {"label": "Token", "secret": True, "help": "Any word.", "set": True}
    assert notes["settings"]["folder"]["value"] == "D:/notes"
    assert "notes" in brain.client.toolkits("milk")["enabled"]
    kit = brain.brain.plugins.toolkits()["notes"]
    assert kit.tools[0].func(_ctx(brain)) == "token=from-env folder=D:/notes"
    updated = brain.client.update_plugin("notes", settings={"token": "s3cret", "folder": "E:/n"})
    assert updated["settings"]["token"]["set"] and "s3cret" not in json.dumps(brain.client.plugins())
    brain.client.update_plugin("notes", settings={"token": "<set>"})  # read back hidden, sent again: kept
    assert kit.tools[0].func(_ctx(brain)) == "token=s3cret folder=E:/n"
    brain.client.update_plugin("notes", enabled=False)
    assert "notes" not in brain.client.toolkits()["toolkits"] and not by_name(brain.client, "notes")["enabled"]


def _ctx(brain):
    from types import SimpleNamespace

    return SimpleNamespace(brain=brain.brain)


def test_a_broken_plugin_is_listed_with_its_error_and_the_brain_goes_on(brain):
    make_plugin(brain.home / "plugins" / "broken", {**PLUGIN, "name": "broken"}, tools="def oops(:\n")
    make_plugin(brain.home / "plugins" / "nameless", {"version": "1"})
    make_plugin(brain.home / "plugins" / "taken", {**PLUGIN, "name": "taken"},
                tools=TOOLS.replace('Toolkit("notes"', 'Toolkit("files"'))
    brain.brain.plugins.load()
    assert "SyntaxError" in by_name(brain.client, "broken")["error"]
    assert "name" in by_name(brain.client, "nameless")["error"]
    assert "files" in by_name(brain.client, "taken")["error"]  # a built-in toolkit's name
    assert "files" in brain.client.toolkits()["toolkits"] and "broken" not in brain.client.toolkits()["toolkits"]


def test_single_file_toolkits_load_as_plugins(brain):
    (brain.home / "toolkits").mkdir()
    (brain.home / "toolkits" / "dice.py").write_text(
        'from sentientmilk_framework.toolkits import Toolkit, tool\n\n\n@tool(readonly=True)\n'
        'def dice_roll(ctx):\n    """Roll."""\n    return "4"\n\n\nTOOLKIT = Toolkit("dice", "Dice.", [dice_roll])\n',
        encoding="utf-8")
    brain.brain.plugins.load()
    assert by_name(brain.client, "dice")["toolkits"] == ["dice"] and "dice" in brain.client.toolkits()["toolkits"]


def test_plugins_install_from_a_folder_or_git_and_remove(brain, tmp_path):
    source = make_plugin(tmp_path / "source" / "anything")
    installed = brain.client.install_plugin(str(source))
    assert installed["name"] == "notes" and installed["enabled"] and (brain.home / "plugins" / "notes").is_dir()
    with pytest.raises(BrainError, match="already installed"):
        brain.client.install_plugin(str(source))
    brain.client.remove_plugin("notes")
    assert not (brain.home / "plugins" / "notes").exists() and "notes" not in brain.client.toolkits()["toolkits"]
    with pytest.raises(BrainError, match="built in"):
        brain.client.remove_plugin("github")
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
                       check=True)
        cloned = brain.client.install_plugin(source.as_uri())  # a git URL
        assert cloned["name"] == "notes" and not (brain.home / "plugins" / "notes" / ".git").exists()


def test_a_plugins_mcp_servers_take_its_settings(brain):
    manifest = {**PLUGIN, "toolkits": [],
                "mcp": {"servers": {"notes": {"command": "notes-server", "env": {"TOKEN": "${token}",
                                                                                  "HOME_DIR": "${HOME}"}},
                                    "search": {"url": "https://notes.invalid/mcp",
                                               "headers": {"Authorization": "Bearer ${token}"}}}}}
    make_plugin(brain.home / "plugins" / "notes", manifest)
    brain.brain.plugins.load()
    brain.client.update_plugin("notes", settings={"token": "t0k"})
    servers = brain.brain.plugins.mcp_servers()
    assert servers["notes"]["env"] == {"TOKEN": "t0k", "HOME_DIR": "${HOME}"}  # the environment fills the rest
    assert servers["notes-search"]["headers"] == {"Authorization": "Bearer t0k"}
    assert {"mcp:notes", "mcp:notes-search"} <= set(brain.client.toolkits()["toolkits"])
    assert set(brain.client.toolkits()["mcp"]) >= {"notes", "notes-search"}


def test_the_command_line_lists_sets_and_switches_plugins(brain, capsys, monkeypatch):
    from argparse import Namespace

    from sentientmilk_framework import cli

    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "typed-secret")
    cli._plugins(brain.client, Namespace(action="set", name="github", values=["token", "api_url=https://x/api/v3"]))
    assert brain.brain.plugins.settings("github") == {"token": "typed-secret", "api_url": "https://x/api/v3"}
    shown = capsys.readouterr().out
    assert "token = set" in shown and "'https://x/api/v3'" in shown and "typed-secret" not in shown
    cli._plugins(brain.client, Namespace(action="off", name="github", values=[]))
    assert "github" in capsys.readouterr().out and not brain.brain.plugins.enabled("github")
    with pytest.raises(SystemExit, match="has no setting"):
        cli._plugins(brain.client, Namespace(action="set", name="github", values=["colour=red"]))
