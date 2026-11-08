import asyncio
import time

from conftest import wait_for
from textual.widgets import Button, DataTable, Input, OptionList, SelectionList, TextArea

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
        await press(pilot, panel, "p-save")
        assert panel.query_one("#p-key", Input).value == ""
    run(brain, scenario)
    values = brain.brain.config.values()
    assert (values["model"], values["api_key"], values["request_budget"]) == ("another-model", "sk-replaced", 512 * 1024)


def test_apps_get_their_persona_toolkits_and_memory_managed_here(brain):
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
        await until(pilot, lambda: panel.query_one("#memory", DataTable).row_count == 1)
        await press(pilot, panel, "memory-forget")
        await press(pilot, panel, "yes")
    run(brain, scenario)
    milk = brain.client.app("milk")
    assert milk["persona"] == "You are a calm milk carton." and milk["persona_custom"]
    assert "web" not in milk["toolkits"] and "memory" in milk["toolkits"]
    assert brain.store.memories("milk") == {}


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


def test_a_table_message_that_lands_while_the_panel_closes_is_dropped(brain):
    panel = Panel(brain.home)  # no screens: as while it closes, with a row highlight still queued
    panel.show_plugin()
    panel.show_skill()
    panel.show_task()
