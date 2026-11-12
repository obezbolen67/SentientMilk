import asyncio
import time

from conftest import wait_for
from textual.widgets import Button, DataTable, Input, OptionList, Select, SelectionList, Switch, TextArea

from sentientmilk_framework.panel import Panel


def run(brain, scenario):
    """Drive the panel headless against the test brain."""
    async def main():
        panel = Panel(brain.home)
        async with panel.run_test(size=(170, 55)) as pilot:
            await until(pilot, lambda: "running" in str(panel.query_one("#state").render()))
            await scenario(panel, pilot)
    asyncio.run(main())


async def until(pilot, check, timeout=8.0):
    deadline = time.time() + timeout
    while not check():
        assert time.time() < deadline, "timed out"
        await pilot.pause(0.05)


async def press(pilot, panel, button):
    panel.screen.query_one(f"#{button}", Button).press()
    await pilot.pause(0.1)


def test_the_panel_shows_the_brain_and_saves_the_provider(brain):
    async def scenario(panel, pilot):
        assert "running" in str(panel.query_one("#state").render())
        panel.action_tab("overview")
        await pilot.pause(0.1)
        assert "✓ saved" in str(panel.query_one("#provider-info").render())
        panel.action_tab("provider")
        await pilot.pause()
        assert panel.query_one("#p-key", Input).value == ""  # keys are never shown
        panel.query_one("#p-model", Input).value = "another-model"
        panel.query_one("#p-key", Input).value = "sk-replaced"
        panel.query_one("#p-budget", Input).value = "abc"
        await press(pilot, panel, "p-save")
        assert brain.brain.config.values()["model"] != "another-model"  # nothing saved with a bad field
        panel.query_one("#p-budget", Input).value = "512"
        assert panel.query_one("#p-pixels", Input).value == "1600"  # thousand pixels: what the model sees
        panel.query_one("#p-pixels", Input).value = "0"
        await until(pilot, lambda: panel.claude.get("models"))  # Claude Code's own list, asked off the UI thread
        assert panel.query_one("#p-super-model", Select).value == "opus"  # the default: its newest Opus, high
        panel.query_one("#p-super-model", Select).value = "sonnet"
        panel.query_one("#p-super-effort", Select).value = "max"
        await press(pilot, panel, "p-save")
        assert panel.query_one("#p-key", Input).value == ""
        status = str(panel.query_one("#p-super-status").render())
        assert "Sonnet 9 · High effort" in status and "the most it takes of Max" in status and "✓ ready" in status
        assert "✓ Claude Code 9.9.9" in str(panel.query_one("#p-claude-status").render())
    run(brain, scenario)
    values = brain.brain.config.values()
    assert (values["model"], values["api_key"], values["request_budget"]) == ("another-model", "sk-replaced", 512 * 1024)
    assert (values["super_model"], values["super_effort"]) == ("sonnet", "max")
    assert values["image_pixels"] == 0  # pictures go as the apps send them


def test_she_can_think_with_claude_code_chosen_in_the_panel(brain):
    brain.client.update_config(model="my-model", thinking_mode="high", context_window=256000, stream=False)
    service = {k: v for k, v in brain.client.config().items() if k not in ("provider", "claude_model", "claude_effort")}

    async def scenario(panel, pilot):
        panel.action_tab("provider")
        await until(pilot, lambda: panel.claude.get("models"))
        assert panel.query_one("#service-card").display and not panel.query_one("#claude-models").display
        panel.query_one("#p-provider", Select).value = "claude_code"
        await pilot.pause(0.1)
        assert not panel.query_one("#service-card").display and panel.query_one("#claude-models").display
        # the API service's thinking, window and requests go with its card: set on Claude Code, they changed it
        for field in ("p-thinking", "p-thinking-tokens", "p-context", "p-vision", "p-stream", "p-budget"):
            assert panel.query_one(f"#service-card #{field}")
        assert panel.query_one("#thinking-card #p-pixels") and panel.query_one("#thinking-card").display
        model = panel.query_one("#p-claude-model", Select)
        assert ("Default (Opus 9)", "default") in [(str(p), v) for p, v in model._options]  # its names
        model.value = "sonnet"
        panel.query_one("#p-claude-effort", Select).value = "high"
        await press(pilot, panel, "p-save")
        await until(pilot, lambda: "Claude Code · Sonnet 9" in str(panel.query_one("#state").render()))
        panel.action_tab("overview")
        await until(pilot, lambda: "Sonnet 9" in str(panel.query_one("#provider-info").render()))
        assert "Claude Max" in str(panel.query_one("#provider-info").render())
        values = brain.brain.config.values()
        assert (values["provider"], values["claude_model"], values["claude_effort"]) == ("claude_code", "sonnet", "high")
        assert values["model"] == "sonnet"  # what she thinks with now
        panel.action_tab("provider")
        panel.query_one("#p-provider", Select).value = "api"  # and back: the API service as it was
        await press(pilot, panel, "p-save")
        await until(pilot, lambda: "my-model" in str(panel.query_one("#state").render()))
    run(brain, scenario)
    assert {k: v for k, v in brain.client.config().items() if k in service} == service


def test_apps_get_their_persona_and_toolkits_and_memory_is_forgotten_in_its_tab(brain):
    brain.store.remember("milk", "user facts", "favourite colour", "green")

    async def scenario(panel, pilot):
        panel.action_tab("apps")
        await until(pilot, lambda: panel.app_id is not None)
        panel.query_one("#app-list", OptionList).highlighted = 1  # cli, milk
        await until(pilot, lambda: panel.app_id == "milk")
        panel.query_one("#persona", TextArea).text = "You are a calm milk carton."
        await press(pilot, panel, "persona-save")
        panel.query_one("#app-toolkits", SelectionList).deselect("web")
        await press(pilot, panel, "app-save")
        panel.action_tab("journal")  # memory is every app's: it has its own tab, with the journal
        await until(pilot, lambda: panel.query_one("#memory", DataTable).row_count == 1)
        assert panel.query_one("#summaries", Switch).value  # she goes over conversations as they end
        panel.query_one("#summaries", Switch).value = False
        await until(pilot, lambda: not brain.client.config()["session_summaries"])
        await press(pilot, panel, "memory-forget")
        await press(pilot, panel, "yes")
    run(brain, scenario)
    milk = brain.client.app("milk")
    assert milk["persona"] == "You are a calm milk carton." and milk["persona_custom"]
    assert "web" not in milk["toolkits"] and "memory" in milk["toolkits"]
    assert brain.store.memories() == {}


def test_schedules_are_paused_and_deleted_after_asking(brain):
    brain.client.create_schedule("milk", "every 1h", "stretch")

    async def scenario(panel, pilot):
        panel.action_tab("work")
        await until(pilot, lambda: panel.query_one("#schedules", DataTable).row_count == 1)
        await press(pilot, panel, "schedule-toggle")
        assert not brain.store.schedules("milk")[0]["enabled"]
        await press(pilot, panel, "schedule-delete")
        await press(pilot, panel, "no")
        assert brain.store.schedules("milk")
        await press(pilot, panel, "schedule-delete")
        await press(pilot, panel, "yes")
    run(brain, scenario)
    assert brain.store.schedules("milk") == []


def test_stopping_the_brain_from_the_panel(brain):
    async def scenario(panel, pilot):
        panel.action_stop()
        await pilot.pause(0.1)
        await press(pilot, panel, "yes")
        await until(pilot, lambda: panel.state == "stopped")
        await until(pilot, lambda: "stopped" in str(panel.query_one("#state").render()))
        assert not panel.query_one("#brain-start", Button).disabled
    run(brain, scenario)
    wait_for(lambda: not (brain.home / "server.json").exists(), 30)  # it answers first, then closes


def test_plugins_are_turned_off_and_set_up_here_without_showing_secrets(brain):
    async def scenario(panel, pilot):
        panel.action_tab("plugins")
        table = panel.query_one("#plugin-table", DataTable)
        await until(pilot, lambda: table.row_count)
        assert "github" in str(table.get_row("github"))
        table.move_cursor(row=table.get_row_index("github"))
        await press(pilot, panel, "plugin-toggle")
        assert not brain.brain.plugins.enabled("github")
        await press(pilot, panel, "plugin-settings")
        dialog = panel.screen
        token = dialog.query_one("#s-token", Input)
        assert token.password and token.value == ""
        token.value = "ghp_from_panel"
        dialog.query_one("#s-api_url", Input).value = "https://ghe.example/api/v3"
        await press(pilot, panel, "save")
        assert brain.brain.plugins.settings("github") == {"token": "ghp_from_panel",
                                                          "api_url": "https://ghe.example/api/v3"}
        await press(pilot, panel, "plugin-settings")
        await press(pilot, panel, "save")  # nothing typed: the token stays
        assert brain.brain.plugins.settings("github")["token"] == "ghp_from_panel"
        assert "ghp_from_panel" not in str(table.get_row("github"))
        await press(pilot, panel, "plugin-remove")
        assert panel.screen is panel.main  # built in: nothing to ask, it can only be turned off
        assert any(p["name"] == "github" for p in brain.client.plugins())
    run(brain, scenario)


def test_a_plugin_she_made_is_trusted_here(brain):
    folder = brain.work / "moon"
    folder.mkdir()
    (folder / "plugin.json").write_text('{"name": "moon", "toolkits": ["tools.py"]}', encoding="utf-8")
    (folder / "tools.py").write_text(
        'from sentientmilk_framework.toolkits import Toolkit, tool\n\n\n@tool(readonly=True)\n'
        'def moon_phase(ctx):\n    """Phase."""\n    return "x"\n\n\nTOOLKIT = Toolkit("moon", "Moon.", [moon_phase])\n',
        encoding="utf-8")
    brain.brain.install_plugin(str(folder), trusted=False)  # as her plugin_install does

    async def scenario(panel, pilot):
        panel.action_tab("plugins")
        table = panel.query_one("#plugin-table", DataTable)
        await until(pilot, lambda: table.row_count > 1)
        assert "untrusted" in str(table.get_row("moon"))
        table.move_cursor(row=table.get_row_index("moon"))
        await pilot.pause(0.1)
        assert "ask every time" in str(panel.query_one("#plugin-detail").render())
        await press(pilot, panel, "plugin-trust")
        await press(pilot, panel, "yes")
        assert brain.brain.plugins.trusted("moon")
        (folder / "tools.py").write_text((folder / "tools.py").read_text(encoding="utf-8") + "\n", encoding="utf-8")
        await press(pilot, panel, "plugin-reload")
        assert not brain.brain.plugins.trusted("moon")  # changed files: asked again
        await until(pilot, lambda: "untrusted" in str(table.get_row("moon")))
    run(brain, scenario)


def test_skills_show_here_and_hers_are_removed_after_asking(brain, monkeypatch):
    folder = brain.home / "skills" / "packing-lists"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\ndescription: Makes packing lists. Use for trips.\nargument-hint: '[trip]'\n"
                                     "---\nList by bag.\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("sentientmilk_framework.panel.open_folder", opened.append)

    async def scenario(panel, pilot):
        panel.action_tab("skills")
        table = panel.query_one("#skill-table", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        assert [str(cell) for cell in table.get_row("packing-lists")][:2] == ["packing-lists", "you and her"]
        table.move_cursor(row=table.get_row_index("packing-lists"))
        await pilot.pause(0.1)
        detail = str(panel.query_one("#skill-detail").render())
        assert "Start it: /packing-lists [trip]" in detail and "packing-lists" in detail
        await press(pilot, panel, "skill-open")
        assert opened == [folder]
        table.move_cursor(row=table.get_row_index("skill-creator"))
        await press(pilot, panel, "skill-remove")
        assert panel.screen is panel.main  # built in: nothing to ask
        table.move_cursor(row=table.get_row_index("packing-lists"))
        await press(pilot, panel, "skill-remove")
        await press(pilot, panel, "yes")
        await until(pilot, lambda: table.row_count == 1)
    run(brain, scenario)
    assert not folder.exists()


def test_her_browser_is_set_in_the_tools_tab(brain, tmp_path):
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"")  # a Chrome where the user says it is (it is never started here)

    async def scenario(panel, pilot):
        panel.action_tab("tools")
        await pilot.pause(0.2)
        assert panel.query_one("#t-browser", Input).value == ""  # found by itself
        panel.query_one("#t-browser", Input).value = str(chrome)
        await press(pilot, panel, "t-save")
        await until(pilot, lambda: "chrome.exe · closed · 0 tabs" in str(panel.query_one("#t-browser-status").render()))
        if tmp_path.exists():
            panel.save_screenshot(str(tmp_path / "tools.svg"))
    run(brain, scenario)
    assert brain.brain.config.values()["browser_command"] == str(chrome)


def test_a_table_message_that_lands_while_the_panel_closes_is_dropped(brain):
    panel = Panel(brain.home)  # no screens: as while it closes, with a row highlight still queued
    panel.show_plugin()
    panel.show_skill()
    panel.show_task()
