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
