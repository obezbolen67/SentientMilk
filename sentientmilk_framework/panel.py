"""The SentientMilk control panel: the one place to see and set up the brain. Run ``sentientmilk``.

Apps have no settings for the brain. The provider, personas, toolkits, permissions and MCP servers
are changed here, through the brain's own API, and every app uses them from its next message.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    SelectionList,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from . import __version__, autostart
from .claudecode import EFFORT_NAMES
from .client import BrainClient, connect, start_command
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, SHELLS
from .exceptions import BrainError
from .thinking import THINKING_MODES

OK, WARN, BAD, MUTED, ACCENT = "#7bd88f", "#f2c35b", "#ff6b7a", "#8b8fa3", "#b3a4ff"
PROVIDERS = (("An API service: the key, URL and model below", "api"),
             ("Claude Code: Claude on your own Claude plan", "claude_code"))
OFF = ("Off: no super agents", "")


def claude_line(claude: dict) -> str:
    """The user's Claude Code as it says about itself (the brain's /claude_code)."""
    if not claude:
        return f"[{MUTED}]asking Claude Code…[/]"
    if not claude["command"]:
        return f"[{BAD}]✗ not found: install Claude Code and sign in to it, or set where it is[/]"
    name = escape(" ".join(f"Claude Code {claude['version']}".split()))
    if claude["error"] == "not signed in":
        return f"[{BAD}]✗ {name} is not signed in: run claude in a terminal and sign in with /login[/]"
    if claude["error"]:
        return f"[{BAD}]✗ {name}: {escape(claude['error'])}[/]"
    account = claude["account"]
    who = " · ".join(escape(part) for part in (account.get("plan"), account.get("email")) if part)
    return f"[{OK}]✓ {name}[/]" + (f" · {who}" if who else "")


def super_line(status: dict, claude: dict) -> str:
    """The super model and its effort (the brain's ``super`` status), and whether Claude Code can run it."""
    if not status:
        return f"[{MUTED}]unknown (an older brain)[/]"
    if not status["model"]:
        return f"[{MUTED}]off: apps have no super agents[/]"
    effort, starts = status["effort"], status.get("starts_with", status["effort"])
    head = escape(status["label"]) + (f" · {EFFORT_NAMES[starts]} effort" if starts else "")
    if starts and starts != effort:
        head += f" [{MUTED}](the most it takes of {EFFORT_NAMES[effort]})[/]"
    if not claude:
        return head
    ready = claude["command"] and not claude["error"]
    return head + (f" · [{OK}]✓ ready[/]" if ready else f" · [{BAD}]✗ Claude Code is not ready[/]")


def model_options(claude: dict, *chosen: str) -> List[Tuple[str, str]]:
    """Claude Code's models for a Select ("Opus 5.5 · For complex work"), and any chosen one it does not list."""
    options = [(m["label"] + (f" · {m['about']}" if m["about"] and m["value"] != "default" else ""), m["value"])
               for m in (claude or {}).get("models", [])]
    return options + [(value, value) for value in chosen if value and value not in {v for _, v in options}]


THEME = Theme(name="sentientmilk", primary=ACCENT, secondary="#7fd1c7", accent="#ffd59e", foreground="#e9e6f2",
              background="#0d0f15", surface="#141720", panel="#1b1f2c", success=OK, warning=WARN, error=BAD)
FlatButton = partial(Button, flat=True)  # muted until hovered: calmer than solid blocks
TABS = ("overview", "provider", "apps", "work", "journal", "tools", "plugins", "skills", "logs")
SHELL_NAMES = {"": "Automatic (Windows PowerShell on Windows, bash elsewhere)", "powershell": "Windows PowerShell 5.1",
               "pwsh": "PowerShell 7", "bash": "bash", "sh": "sh", "cmd": "cmd.exe"}
STATUS_COLORS = {"working": ACCENT, "queued": MUTED, "input_required": WARN, "completed": OK, "failed": BAD,
                 "cancelled": MUTED}
Rows = List[Tuple[str, tuple]]
AUTOSTART = "SentientMilk"  # its name in Windows' Startup apps


def ago(at: Optional[float]) -> str:
    if not at:
        return "never"
    seconds = max(0, time.time() - at)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds >= size:
            return f"{int(seconds // size)} {unit} ago"
    return "just now"


def uptime(at: Optional[float]) -> str:
    return ago(at).replace(" ago", "")


def when(at: Optional[float]) -> str:
    return datetime.fromtimestamp(at).strftime("%a %d %b %H:%M") if at else "-"


def items(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def number(field: Input, what: str) -> int:
    try:
        return int(field.value.strip())
    except ValueError:
        raise ValueError(f"{what} must be a whole number") from None


def cut(text: str, size: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[:size - 1] + "…"


def fill(table: DataTable, rows: Rows) -> None:
    """Show these rows, keeping the selected one; an unchanged table is left alone (no flicker)."""
    if getattr(table, "shown_rows", None) == rows:
        return
    selected = selected_key(table)
    table.clear()
    for key, cells in rows:
        table.add_row(*cells, key=key)
    table.shown_rows = rows
    keys = [key for key, _ in rows]
    if selected in keys:
        table.move_cursor(row=keys.index(selected))


def open_folder(folder: Path) -> None:
    """In the file manager, beside the panel."""
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 (a folder of ours)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])


def selected_key(table: DataTable) -> Optional[str]:
    if not table.row_count:
        return None
    return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value


class Confirm(ModalScreen[bool]):
    """Asks before anything that cannot be undone."""

    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, question: str, action: str):
        super().__init__()
        self.question, self.action = question, action

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(self.question, classes="question")
            with Horizontal(classes="buttons"):
                yield FlatButton(self.action, variant="error", id="yes")
                yield FlatButton("Cancel", id="no")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        event.stop()  # the panel's own button handler must not see it
        self.dismiss(event.button.id == "yes")


class AddServer(ModalScreen[Optional[Tuple[str, dict]]]):
    """An MCP server: a command SentientMilk starts, or the URL of one that already runs."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("[b]Add an MCP server[/b]\nIts tools appear as the toolkit mcp:<name>.", classes="question")
            with Grid(classes="form"):
                yield Label("Name")
                yield Input(placeholder="github", id="m-name")
                yield Label("Command or URL")
                yield Input(placeholder="npx -y @modelcontextprotocol/server-everything", id="m-target")
                yield Label("Environment / headers")
                yield Input(placeholder="TOKEN=${GITHUB_TOKEN}, comma-separated", id="m-extra")
            with Horizontal(classes="buttons"):
                yield FlatButton("Add", variant="primary", id="add")
                yield FlatButton("Cancel", id="cancel")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id != "add":
            return self.dismiss(None)
        name = self.query_one("#m-name", Input).value.strip()
        target = self.query_one("#m-target", Input).value.strip()
        pairs = [item.partition("=") for item in items(self.query_one("#m-extra", Input).value)]
        if not name or not target or any(not sep for _, sep, _ in pairs):
            return self.app.notify("Give a name, a command or URL, and extras as NAME=VALUE.", severity="error")
        extra = {key.strip(): value.strip() for key, _, value in pairs}
        if target.startswith(("http://", "https://")):
            spec = {"url": target, **({"headers": extra} if extra else {})}
        else:
            parts = [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
                     for part in shlex.split(target, posix=False)]  # posix=False keeps Windows backslashes
            command, *args = parts
            spec = {"command": command, "args": args, **({"env": extra} if extra else {})}
        self.dismiss((name, spec))


class InstallPlugin(ModalScreen[Optional[str]]):
    """Where a plugin comes from: a folder with a plugin.json, or a git URL."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("[b]Install a plugin[/b]\nIt runs as you, inside the brain: install only plugins you trust.",
                         classes="question")
            yield Input(placeholder="C:/plugins/weather  or  https://github.com/owner/plugin.git", id="source")
            with Horizontal(classes="buttons"):
                yield FlatButton("Install", variant="primary", id="install")
                yield FlatButton("Cancel", id="cancel")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        event.stop()
        source = self.query_one("#source", Input).value.strip()
        if event.button.id == "install" and not source:
            return self.app.notify("Give a folder or a git URL.", severity="error")
        self.dismiss(source if event.button.id == "install" else None)


class PluginSettings(ModalScreen[Optional[dict]]):
    """A plugin's settings. Secrets are never shown: left empty they stay as they are."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, plugin: dict):
        super().__init__()
        self.plugin = plugin

    def compose(self) -> ComposeResult:
        settings = self.plugin["settings"]
        with Vertical(classes="dialog"):
            yield Static(f"[b]{escape(self.plugin['name'])}[/b]  [{MUTED}]{escape(self.plugin['version'])}[/]\n"
                         f"{escape(self.plugin['description'])}", classes="question")
            if not settings:
                yield Static(f"[{MUTED}]It has nothing to set.[/]", classes="subtitle")
            with Grid(classes="form"):
                for key, setting in settings.items():
                    yield Label(setting["label"])
                    if setting["secret"]:
                        yield Input(password=True, id=f"s-{key}",
                                    placeholder="set: type to replace it" if setting["set"] else "not set")
                    else:
                        yield Input(setting["value"], id=f"s-{key}")
            for setting in settings.values():
                if setting["help"]:
                    yield Static(f"[{MUTED}]{escape(setting['label'])}: {escape(setting['help'])}[/]",
                                 classes="subtitle")
            with Horizontal(classes="buttons"):
                yield FlatButton("Save", variant="primary", id="save")
                if any(s["secret"] and s["set"] for s in settings.values()):
                    yield FlatButton("Forget secrets", variant="error", id="forget")
                yield FlatButton("Cancel", id="cancel")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        event.stop()
        settings = self.plugin["settings"]
        if event.button.id == "forget":
            return self.dismiss({key: "" for key, setting in settings.items() if setting["secret"]})
        if event.button.id != "save":
            return self.dismiss(None)
        values = {key: self.query_one(f"#s-{key}", Input).value.strip() for key in settings}
        self.dismiss({key: (value or "<set>") if settings[key]["secret"] else value for key, value in values.items()})


class Panel(App):
    TITLE = "SentientMilk"
    CSS = """
    Screen { background: $background; }
    #topbar { dock: top; height: 3; padding: 0 2; background: $panel; }
    #brand { width: auto; height: 3; content-align: left middle; }
    #state { width: 1fr; height: 3; content-align: right middle; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2 0 2; }
    .hint { color: $text-muted; height: auto; margin: 0 0 1 0; }
    .card { height: auto; border: round $primary 40%; border-title-color: $primary; border-title-style: bold;
            padding: 0 1; margin: 0 0 1 0; background: $surface; }
    .row { height: auto; }
    .row > .card { width: 1fr; }
    .row > .card:first-of-type { margin-right: 2; }
    .form { grid-size: 2; grid-columns: 26 1fr; grid-rows: 3; grid-gutter: 0 2; height: auto; margin: 1 0 0 0; }
    .form > Label { width: 100%; height: 3; content-align: right middle; color: $text-muted; }
    .field { height: 3; }
    .field > Input { width: 1fr; }
    .field > Button { margin-left: 1; }
    .buttons { height: auto; margin: 1 0 0 0; }
    .buttons > Button { margin-right: 1; }
    .toggle { height: auto; margin: 1 0 0 0; }
    .toggle-label { width: 1fr; height: 3; content-align: left middle; padding-left: 1; }
    Button:disabled { opacity: 45%; }
    #usage-empty { margin: 1 0 0 0; }
    .subtitle { margin: 1 0 0 0; color: $text-muted; }
    DataTable { height: auto; max-height: 14; margin: 1 0 0 0; }
    SelectionList { height: auto; max-height: 12; margin: 1 0 0 0; border: none; background: $surface; }
    #models { height: auto; max-height: 10; display: none; }
    #persona { height: 14; margin: 1 0 0 0; }
    #apps-pane { width: 30; height: 1fr; }
    #app-list { height: 1fr; border: none; background: $surface; }
    #app-detail { width: 1fr; padding-left: 2; }
    #task-detail { height: auto; margin: 1 0 0 0; color: $text-muted; }
    #log { height: 1fr; border: round $primary 40%; background: $surface; }
    Confirm, AddServer, InstallPlugin, PluginSettings { align: center middle; }
    #plugin-detail { height: auto; margin: 1 0 0 0; color: $text-muted; }
    .dialog { width: 84; height: auto; padding: 1 2; border: thick $primary; background: $panel; }
    .question { height: auto; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "start", "Start brain"),
        Binding("x", "stop", "Stop brain"),
        Binding("ctrl+s", "save", "Save"),
        *[Binding(str(n), f"tab('{tab}')", tab.title(), show=False) for n, tab in enumerate(TABS, 1)],
    ]

    def __init__(self, home: Path):
        super().__init__()
        self.home = Path(home)
        self.client: Optional[BrainClient] = None
        self.state = "stopped"
        self.health: dict = {}
        self.settings: dict = {}
        self.claude: dict = {}  # what the user's Claude Code said about itself, through the brain
        self.app_id: Optional[str] = None
        self.app_record: dict = {}
        self.log_offset = 0
        self.plugins: dict = {}
        self.skills: dict = {}

    @property
    def main(self) -> Screen:
        """The panel's own screen: App.query_one would search an open dialog instead."""
        return self.screen_stack[0]

    # ============== Layout ==============

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(f"[b {ACCENT}]◆ SentientMilk[/]  [{MUTED}]control panel · {__version__}[/]", id="brand")
            yield Static("", id="state")
        with TabbedContent(id="tabs"):
            with TabPane("Overview", id="overview"):
                yield from self.compose_overview()
            with TabPane("Provider", id="provider"):
                yield from self.compose_provider()
            with TabPane("Apps", id="apps"):
                yield from self.compose_apps()
            with TabPane("Work", id="work"):
                yield from self.compose_work()
            with TabPane("Memory", id="journal"):
                yield from self.compose_journal()
            with TabPane("Tools", id="tools"):
                yield from self.compose_tools()
            with TabPane("Plugins", id="plugins"):
                yield from self.compose_plugins()
            with TabPane("Skills", id="skills"):
                yield from self.compose_skills()
            with TabPane("Logs", id="logs"):
                yield Static("The brain's own log, live.", classes="hint")
                yield RichLog(id="log", wrap=True, highlight=True, max_lines=2000)
        yield Footer()

    def compose_overview(self) -> ComposeResult:
        yield Static("SentientMilk is the brain every app thinks with. Apps only connect to it: "
                     "everything about it is set up here.", classes="hint")
        with Horizontal(classes="row"):
            with Vertical(classes="card", id="brain-card"):
                yield Static(id="brain-info")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Start", id="brain-start", variant="success")
                    yield FlatButton("Restart", id="brain-restart")
                    yield FlatButton("Stop", id="brain-stop", variant="error")
                if autostart.AVAILABLE:
                    with Horizontal(classes="toggle"):
                        yield Switch(value=autostart.enabled(AUTOSTART), id="autostart")
                        yield Static("Start with Windows: the brain starts in the background when you sign in, "
                                     "with only its tray icon", classes="toggle-label")
            with Vertical(classes="card", id="provider-card"):
                yield Static(id="provider-info")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Set up provider", id="goto-provider", variant="primary")
        with Vertical(classes="card", id="usage-card"):
            yield DataTable(id="usage", cursor_type="row", zebra_stripes=True)
            yield Static("No model calls yet.", id="usage-empty", classes="hint")
        with Vertical(classes="card", id="activity-card"):
            yield Static(id="activity")

    def compose_provider(self) -> ComposeResult:
        yield Static("What SentientMilk thinks with. Keys are write-only: the brain never shows them again; leave "
                     "a key field empty to keep the saved one.", classes="hint")
        with VerticalScroll():
            with Vertical(classes="card", id="engine-card"):
                with Grid(classes="form"):
                    yield Label("She thinks with")
                    yield Select(PROVIDERS, allow_blank=False, id="p-provider")
            with Vertical(classes="card", id="claude-card"):
                yield Static("Your own Claude Code, signed in as you: Claude through it, on your plan. Super agents "
                             "always use it; she does too when she thinks with Claude Code.", classes="hint")
                yield Static(id="p-claude-status")
                with Grid(classes="form"):
                    yield Label("Where it is")
                    with Horizontal(classes="field"):
                        yield Input(placeholder="found by itself (default) · or the path of claude",
                                    id="p-claude-command")
                        yield FlatButton("Check again", id="p-claude-refresh")
                with Grid(classes="form", id="claude-models"):
                    yield Label("Model")
                    yield Select([("Default", "default")], allow_blank=False, id="p-claude-model")
                    yield Label("Model for helpers")
                    yield Select([("Haiku", "haiku")], allow_blank=False, id="p-claude-light")
                    yield Label("Thinking effort")
                    yield Select([(name, effort) for effort, name in EFFORT_NAMES.items()], allow_blank=False,
                                 id="p-claude-effort")
            with Vertical(classes="card", id="service-card"):
                with Grid(classes="form"):
                    yield Label("API key")
                    yield Input(password=True, id="p-key")
                    yield Label("Service URL")
                    yield Input(placeholder=f"{DEFAULT_BASE_URL}  (default)", id="p-base-url")
                    yield Label("Model")
                    with Horizontal(classes="field"):
                        yield Input(placeholder=f"{DEFAULT_MODEL}  (default)", id="p-model")
                        yield FlatButton("Test & list models", id="p-models")
                    yield Label("Model for helpers")
                    yield Input(placeholder="the same model (compaction, titles, journal notes, reviewers)", id="p-light")
                yield OptionList(id="models")
                # the API service's own: shown with Claude Code, they changed the service's under the user
                with Grid(classes="form"):
                    yield Label("Thinking")
                    yield Select([(label, value) for label, value in THINKING_MODES], allow_blank=False,
                                 id="p-thinking")
                    yield Label("Thinking tokens")
                    yield Input(type="integer", id="p-thinking-tokens")
                    yield Label("Context window (tokens)")
                    yield Input(type="integer", id="p-context")
                    yield Label("Send images")
                    yield Switch(id="p-vision")
                    yield Label("Stream replies")
                    yield Switch(id="p-stream")
                    yield Label("Request size limit (KiB)")
                    yield Input(type="integer", id="p-budget")
            with Vertical(classes="card", id="thinking-card"):
                with Grid(classes="form"):
                    yield Label("Picture size the model sees (thousand pixels; 0: as sent)")
                    yield Input(type="integer", id="p-pixels")
                    yield Label("Brave search key")
                    yield Input(password=True, id="p-web-key")
            with Vertical(classes="card", id="super-card"):
                yield Static("Super agents do the apps' code and hard thinking: Claude, through your Claude Code "
                             "(above). Off: her own agents do it.", classes="hint")
                with Grid(classes="form"):
                    yield Label("Super model")
                    yield Select([("Opus", "opus"), OFF], allow_blank=False, id="p-super-model")
                    yield Label("Thinking effort")
                    yield Select([(name, effort) for effort, name in EFFORT_NAMES.items()], allow_blank=False,
                                 id="p-super-effort")
                yield Static(id="p-super-status")
            with Horizontal(classes="buttons"):
                yield FlatButton("Save", id="p-save", variant="primary")
                yield FlatButton("Remove API key", id="p-remove-key", variant="error")

    def compose_apps(self) -> ComposeResult:
        yield Static("Each app that connected to SentientMilk. Personas, models and toolkits set here win "
                     "over what the app asked for.", classes="hint")
        with Horizontal():
            with Vertical(classes="card", id="apps-pane"):
                yield OptionList(id="app-list")
            with VerticalScroll(id="app-detail"):
                yield Static(id="app-header")
                with Vertical(classes="card", id="persona-card"):
                    yield Static(id="persona-note", classes="subtitle")
                    yield TextArea(id="persona", soft_wrap=True)
                    with Horizontal(classes="buttons"):
                        yield FlatButton("Save persona", id="persona-save", variant="primary")
                        yield FlatButton("Use the app's default", id="persona-reset")
                with Vertical(classes="card", id="app-settings-card"):
                    with Grid(classes="form"):
                        yield Label("Model")
                        yield Input(placeholder="the brain's model", id="app-model")
                        yield Label("Folders it may use")
                        yield Input(placeholder="comma-separated paths", id="app-roots")
                        yield Label("Reads the journal")
                        yield Switch(id="app-journal-read")
                        yield Label("Writes the journal")
                        yield Switch(id="app-journal-write")
                    yield Static("Toolkits this app may use", classes="subtitle")
                    yield SelectionList(id="app-toolkits")
                    with Horizontal(classes="buttons"):
                        yield FlatButton("Save app settings", id="app-save", variant="primary")
                with Vertical(classes="card", id="sessions-card"):
                    yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
                    with Horizontal(classes="buttons"):
                        yield FlatButton("Clear this conversation", id="session-clear", variant="error")

    def compose_work(self) -> ComposeResult:
        yield Static("Background tasks and agents run on their own and report back to the app or chat that "
                     "started them. Schedules run once or repeat, each in a conversation of its own.", classes="hint")
        with VerticalScroll():
            with Vertical(classes="card", id="tasks-card"):
                yield DataTable(id="tasks", cursor_type="row", zebra_stripes=True)
                yield Static(id="task-detail")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Cancel task", id="task-cancel", variant="error")
            with Vertical(classes="card", id="schedules-card"):
                yield DataTable(id="schedules", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield FlatButton("Pause / resume", id="schedule-toggle")
                    yield FlatButton("Delete", id="schedule-delete", variant="error")

    def compose_journal(self) -> ComposeResult:
        yield Static("What the brain remembers, shared by every app and always in its context (From: the app "
                     "that saved it; each conversation's own memory is in its app), then the journal: short dated "
                     "notes about conversations in every app, the 20 newest kept.", classes="hint")
        with VerticalScroll():
            with Vertical(classes="card", id="memory-card"):
                with Horizontal(classes="toggle"):
                    yield Switch(id="summaries")
                    yield Static("Go over each conversation as it ends and keep what matters (her own model, "
                                 "with memory_save)", classes="toggle-label")
                yield DataTable(id="memory", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield FlatButton("Forget", id="memory-forget", variant="error")
            yield Input(placeholder="Search notes…", id="journal-search")
            with Vertical(classes="card", id="journal-card"):
                yield DataTable(id="notes", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield FlatButton("Delete note", id="note-delete", variant="error")

    def compose_tools(self) -> ComposeResult:
        yield Static("What the brain may do on this computer. A toolkit switched off here is off for every app.",
                     classes="hint")
        with VerticalScroll():
            with Horizontal(classes="row"):
                with Vertical(classes="card", id="toolkits-card"):
                    yield SelectionList(id="toolkits")
                with Vertical(classes="card", id="runtime-card"):
                    with Grid(classes="form"):
                        yield Label("Shell")
                        yield Select([(label, value) for value, label in SHELL_NAMES.items() if value in SHELLS],
                                     allow_blank=False, id="t-shell")
                        yield Label("Background workers")
                        yield Input(type="integer", id="t-workers")
                        yield Label("Always refuse")
                        yield Input(placeholder="shell_run(rm *), …", id="t-deny")
                        yield Label("Always ask first")
                        yield Input(placeholder="files_write, …", id="t-ask")
                        yield Label("Always allow")
                        yield Input(placeholder="shell_run(git status*), …", id="t-allow")
            with Vertical(classes="card", id="browser-card"):
                yield Static("Her browser is your own Chrome, signed in as you are: she works in tabs of her own "
                             "there (a purple SentientMilk group), and opens Chrome when it is not running. Add the "
                             "extension once (chrome://extensions > Developer mode > Load unpacked > the folder "
                             "below), then press Connect (or paste the code into the extension). Cancel on Chrome's "
                             "bar stops her there, and the extension's Disconnect until you connect again. Rules name "
                             "sites: browser_act(github.com), browser_*(*.bank.com).", classes="hint")
                with Grid(classes="form"):
                    yield Label("Chrome")
                    yield Input(placeholder="found by itself (Chrome, else Edge) · or its path", id="t-browser")
                    yield Label("Extension folder")
                    yield Input(id="t-chrome-folder")
                    yield Label("Code")
                    yield Input(id="t-chrome-code")
                yield Static(id="t-chrome-status")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Connect my Chrome", id="chrome-connect")
            with Horizontal(classes="buttons"):
                yield FlatButton("Save", id="t-save", variant="primary")
            with Vertical(classes="card", id="mcp-card"):
                yield DataTable(id="mcp", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield FlatButton("Add server", id="mcp-add", variant="primary")
                    yield FlatButton("Reconnect", id="mcp-reconnect")
                    yield FlatButton("Turn on / off", id="mcp-toggle")
                    yield FlatButton("Remove", id="mcp-remove", variant="error")

    def compose_plugins(self) -> ComposeResult:
        yield Static("Plugins extend the brain for every app: their tools are offered to all of them, and an app can "
                     "still switch one off. A plugin runs as you, inside the brain: install only plugins you trust.",
                     classes="hint")
        with VerticalScroll():
            with Vertical(classes="card", id="plugins-card"):
                yield DataTable(id="plugin-table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="plugin-detail")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Install…", id="plugin-install", variant="primary")
                    yield FlatButton("Settings…", id="plugin-settings")
                    yield FlatButton("Turn on / off", id="plugin-toggle")
                    yield FlatButton("Trust / distrust", id="plugin-trust")
                    yield FlatButton("Reload", id="plugin-reload")
                    yield FlatButton("Remove", id="plugin-remove", variant="error")

    def compose_skills(self) -> ComposeResult:
        yield Static("Skills are instructions she loads when a task needs them, in every app; you start one with "
                     "/name. Ask her to make one, or put a skill's folder (with its SKILL.md) in her skills folder.",
                     classes="hint")
        with VerticalScroll():
            with Vertical(classes="card", id="skills-card"):
                yield DataTable(id="skill-table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="skill-detail")
                with Horizontal(classes="buttons"):
                    yield FlatButton("Open folder", id="skill-open", variant="primary")
                    yield FlatButton("Remove", id="skill-remove", variant="error")

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = "sentientmilk"
        for card, title in (("brain-card", "Brain"), ("provider-card", "Provider"), ("usage-card", "Usage by app"),
                            ("activity-card", "Activity"), ("engine-card", "Thinks with"),
                            ("claude-card", "Claude Code"), ("service-card", "API service"),
                            ("thinking-card", "Pictures and web search"), ("super-card", "Super model"),
                            ("apps-pane", "Apps"),
                            ("persona-card", "Persona"), ("app-settings-card", "Settings"),
                            ("sessions-card", "Conversations"), ("memory-card", "Memory, every app's"),
                            ("tasks-card", "Background tasks and agents"), ("schedules-card", "Schedules"),
                            ("journal-card", "Journal"), ("toolkits-card", "Toolkits"),
                            ("runtime-card", "Runtime and permissions"), ("browser-card", "Her browser"),
                            ("mcp-card", "MCP servers"),
                            ("plugins-card", "Plugins")):
            self.main.query_one(f"#{card}").border_title = title
        columns = {
            "usage": ("App", "Runs", "Model calls", "Prompt tokens", "Cached", "Cache hits", "Reply tokens"),
            "sessions": ("Conversation", "Started", "Last active"),
            "memory": ("Category", "Key", "Value", "From"),
            "tasks": ("#", "App", "Status", "Goal", "Started", "Tokens"),
            "schedules": ("#", "App", "When", "Next", "Name", "Instructions", "State"),
            "notes": ("When", "App", "Note"),
            "mcp": ("Server", "State", "Tools", "Runs", "Problem"),
            "plugin-table": ("Plugin", "Version", "State", "Tools", "From"),
            "skill-table": ("Skill", "Started by", "State", "Description"),
        }
        for table, names in columns.items():
            self.main.query_one(f"#{table}", DataTable).add_columns(*names)
        self.show_state()
        self.start_brain()
        self.set_interval(2.5, self.refresh_live)
        self.set_interval(1.0, self.tail_log)

    # ============== Talking to the brain ==============

    def api(self) -> Optional[BrainClient]:
        if self.client is None and self.state != "starting":
            self.client = BrainClient.discover(self.home)  # no home: a stopped brain stays stopped
            self.state = "running" if self.client else "stopped"
        return self.client

    def call(self, request: Callable[[BrainClient], Any], done: str = "", quiet: bool = False) -> Any:
        """One request to the brain; a problem becomes a notification and the result None
        (requests that answer nothing give True, so callers can tell success from failure)."""
        client = self.api()
        if client is None:
            if not quiet:
                self.notify("The brain is not running. Press s to start it.", severity="warning")
            return None
        try:
            result = request(client)
        except BrainError as exc:
            if exc.type == "brain_unreachable":
                self.client, self.state = None, "stopped"
                self.show_state()
            if not quiet:
                self.notify(exc.message + (f"\n{exc.details}" if exc.details else ""), title="SentientMilk",
                            severity="error", timeout=8)
            return None
        if done:
            self.notify(done)
        return True if result is None else result

    @work(thread=True, exclusive=True, group="brain")
    def start_brain(self, after_stop: bool = False) -> None:
        if after_stop:  # the old process lets go of the home first
            deadline = time.time() + 15
            while BrainClient.discover(self.home) and time.time() < deadline:
                time.sleep(0.3)
        self.state = "starting"
        self.call_from_thread(self.show_state)
        try:
            client = connect(self.home)
        except BrainError as exc:
            self.client, self.state = None, "stopped"
            self.call_from_thread(self.notify, exc.message + (f"\n{exc.details}" if exc.details else ""),
                                  severity="error", timeout=10)
            self.call_from_thread(self.show_state)
            return
        client.home = None  # a brain the user stops here is not started again behind their back
        self.client, self.state = client, "running"
        self.call_from_thread(self.load_all)

    @work(thread=True, exclusive=True, group="chrome")
    def connect_chrome(self) -> None:
        """Connect my Chrome: the brain waits up to 15 s for that Chrome to connect, so off the panel's thread."""
        client = self.api()
        if client is None:
            return self.call_from_thread(self.notify, "The brain is not running. Press s to start it.",
                                         severity="warning")
        try:
            status = client.connect_chrome()
        except BrainError as exc:
            return self.call_from_thread(self.notify, exc.message, severity="error", timeout=10)
        self.call_from_thread(self.load_browser, status)
        chrome = status["chrome"]
        if chrome["took"]:
            self.call_from_thread(self.notify, f"Connected: she can use {chrome['browser']} when you ask her to.")
        else:
            self.call_from_thread(self.notify, "Your Chrome opened the extension's page but did not connect. Add "
                                  "the extension to the Chrome profile you use (Load unpacked, the folder above), "
                                  "then press Connect again.", severity="warning", timeout=12)

    def load_all(self) -> None:
        if not self.is_running:
            return
        self.show_state()
        self.load_provider()
        self.load_apps()
        self.load_tools()
        self.load_plugins()
        self.load_skills()
        self.refresh_live()

    def refresh_live(self) -> None:
        if not self.is_running:  # a timer or worker that fires while the panel closes
            return
        self.show_state()
        live = {"overview": self.load_overview, "apps": self.load_app_tables, "work": self.load_work,
                "journal": self.load_memory, "tools": self.load_mcp, "plugins": self.load_plugins}
        active = self.main.query_one(TabbedContent).active
        live.get(active, lambda: None)()
        if active in ("overview", "provider") and self.state == "running":  # signed in or out meanwhile
            self.load_claude()

    # ============== Overview ==============

    def show_state(self) -> None:
        client = self.api()
        if client:
            self.health = self.call(lambda c: c.health(), quiet=True) or {}
            self.settings = self.call(lambda c: c.config(), quiet=True) or self.settings
        state = self.state if client or self.state == "starting" else "stopped"
        if self.settings.get("provider") == "claude_code":
            model = "Claude Code · " + self.model_label(self.settings["claude_model"])
            ready = self.claude and self.claude["command"] and not self.claude["error"]
            key = f"[{OK}]✓[/]" if ready else f"[{BAD}]not ready ✗[/]" if self.claude else ""
        else:
            model = self.settings.get("model") or DEFAULT_MODEL
            key = f"[{OK}]key ✓[/]" if self.settings.get("api_key_set") else f"[{BAD}]no API key ✗[/]"
        if state == "running" and self.health:
            text = (f"[{OK}]● running[/]  [{MUTED}]pid {self.health.get('pid')} · {client.url.split('//')[-1]} · "
                    f"up {uptime(self.health.get('started'))}[/]   {escape(model)}  {key}")
        elif state == "starting":
            text = f"[{WARN}]◌ starting…[/]"
        else:
            text = f"[{BAD}]○ stopped[/]  [{MUTED}]press s to start[/]"
        self.main.query_one("#state", Static).update(text)
        self.main.query_one("#brain-start", Button).disabled = state != "stopped"
        self.main.query_one("#brain-stop", Button).disabled = self.main.query_one("#brain-restart", Button).disabled = \
            state != "running"

    def load_overview(self) -> None:
        health, settings = self.health, self.settings
        running = self.state == "running" and health
        rows = [("State", f"[{OK}]● running[/]" if running else f"[{BAD}]○ stopped[/]")]
        if running:
            rows += [("Address", self.client.url), ("Process", f"{health['pid']} · up {uptime(health['started'])}"),
                     ("Version", f"{health.get('version', '?')} · API {health['api']}")]
        rows += [("Home", str(self.home)),
                 ("Runs", "in the background until stopped here or from its tray icon; closing this "
                          "window leaves it running")]
        self.main.query_one("#brain-info", Static).update(self.lines(rows))
        self.show_autostart()
        thinking = dict((v, k) for k, v in THINKING_MODES).get(settings.get("thinking_mode"), "?")
        if settings.get("provider") == "claude_code":
            provider = [
                ("Service", claude_line(self.claude)),
                ("Model", escape(self.model_label(settings["claude_model"]))
                 + f" · {EFFORT_NAMES[settings['claude_effort']]} effort"),
                ("Helpers", escape(self.model_label(settings["claude_light_model"]))),
            ]
        else:
            provider = [
                ("Service", escape(settings.get("base_url") or f"{DEFAULT_BASE_URL} (default)")),
                ("Model", escape(settings.get("model") or f"{DEFAULT_MODEL} (default)")),
                ("Helpers", escape(settings.get("light_model") or "same model")),
                ("API key", f"[{OK}]✓ saved[/]" if settings.get("api_key_set")
                 else f"[{BAD}]✗ missing: apps cannot think until you add one[/]"),
                ("Thinking", f"{thinking} · images {'on' if settings.get('vision', True) else 'off'}"),
            ]
        provider += [
            ("Web search", f"[{OK}]✓ Brave key saved[/]" if settings.get("web_search_key_set")
             else f"[{MUTED}]no Brave key (pages can still be read)[/]"),
            ("Super model", super_line(settings.get("super") or {}, self.claude)),
        ]
        self.main.query_one("#provider-info", Static).update(self.lines(provider))
        stats = self.call(lambda c: c.stats(), quiet=True) or {"apps": {}}
        fill(self.main.query_one("#usage", DataTable), [
            (app, (app, s["runs"], s["calls"], f"{s['prompt_tokens']:,}", f"{s['cached_tokens']:,}",
                   f"{s['cache_hit_rate']:.0%}" if s["cache_hit_rate"] is not None else "-",
                   f"{s['completion_tokens']:,}"))
            for app, s in sorted(stats["apps"].items())])
        self.main.query_one("#usage-empty").display = not stats["apps"]
        tasks = self.call(lambda c: c.tasks(status="working,queued,input_required"), quiet=True) or []
        schedules = self.call(lambda c: c.schedules(), quiet=True) or []
        mcp = (self.call(lambda c: c.mcp(), quiet=True) or {}).get("status", {})
        apps = self.call(lambda c: c.apps(), quiet=True) or []
        connected = sum(1 for s in mcp.values() if s.get("state") == "connected")
        self.main.query_one("#activity", Static).update(self.lines([
            ("Apps", ", ".join(apps) or f"[{MUTED}]none has connected yet[/]"),
            ("Tasks", f"{sum(t['status'] == 'working' for t in tasks)} working · "
                      f"{sum(t['status'] == 'queued' for t in tasks)} queued · "
                      f"{sum(t['status'] == 'input_required' for t in tasks)} waiting for an answer"),
            ("Schedules", f"{sum(1 for s in schedules if s['enabled'])} on · "
                          f"{sum(1 for s in schedules if not s['enabled'])} paused"),
            ("MCP servers", f"{connected} of {len(mcp)} connected" if mcp else f"[{MUTED}]none[/]"),
        ]))

    @staticmethod
    def lines(rows) -> str:
        return "\n".join(f"[{MUTED}]{label:<11}[/] {value}" for label, value in rows)

    # ============== Provider ==============

    def load_provider(self, settings: Optional[dict] = None) -> None:
        settings = settings or self.call(lambda c: c.config(), quiet=True)
        if not settings:
            return
        self.settings = settings
        self.main.query_one("#p-key", Input).placeholder = (
            "saved · type a new key to replace it" if settings["api_key_set"] else "paste your provider's API key")
        self.main.query_one("#p-web-key", Input).placeholder = (
            "saved · type a new key to replace it" if settings["web_search_key_set"]
            else "optional: enables web search")
        for field, key in (("#p-base-url", "base_url"), ("#p-model", "model"), ("#p-light", "light_model")):
            self.main.query_one(field, Input).value = settings[key]
        self.main.query_one("#p-thinking", Select).value = settings["thinking_mode"]
        self.main.query_one("#p-thinking-tokens", Input).value = str(settings["thinking_tokens"])
        self.main.query_one("#p-context", Input).value = str(settings["context_window"])
        self.main.query_one("#p-vision", Switch).value = settings["vision"]
        self.main.query_one("#p-pixels", Input).value = str(settings["image_pixels"] // 1000)
        self.main.query_one("#p-stream", Switch).value = settings["stream"]
        self.main.query_one("#p-budget", Input).value = str(settings["request_budget"] // 1024)
        self.main.query_one("#p-provider", Select).value = settings["provider"]
        self.main.query_one("#p-claude-command", Input).value = settings["claude_command"]
        self.main.query_one("#p-claude-effort", Select).value = settings["claude_effort"]
        self.main.query_one("#p-super-effort", Select).value = settings["super_effort"]
        for field, key in (("#p-claude-model", "claude_model"), ("#p-claude-light", "claude_light_model"),
                           ("#p-super-model", "super_model")):
            self.choose(field, settings[key])
        self.show_kind(settings["provider"])
        self.show_claude(self.claude)
        self.load_claude()

    def choose(self, field: str, value: str) -> None:
        """A model select set to ``value``, with Claude Code's models (and ``value``, if it lists no such one)."""
        select = self.main.query_one(field, Select)
        select.set_options(model_options(self.claude, value) + ([OFF] if field == "#p-super-model" else []))
        select.value = value
        select._watch_value(value)  # Textual 8 keeps the old option's words when the value stays the same

    def model_label(self, value: str) -> str:
        return next((m["label"] for m in self.claude.get("models", []) if m["value"] == value), value)

    def show_kind(self, kind: str) -> None:
        """The API service's card for an API service, Claude Code's models for Claude Code."""
        self.main.query_one("#service-card").display = kind != "claude_code"
        self.main.query_one("#claude-models").display = kind == "claude_code"

    @on(Select.Changed, "#p-provider")
    def kind_chosen(self, event: Select.Changed) -> None:
        self.show_kind(str(event.value))

    @work(thread=True, exclusive=True, group="claude")
    def load_claude(self, refresh: bool = False) -> None:
        """What the user's Claude Code says about itself, off the panel's thread (asking it takes a second)."""
        client = self.client
        if client is None:
            return
        try:
            claude = client.claude_code(refresh)
        except BrainError as exc:
            if refresh:
                self.call_from_thread(self.notify, exc.message, severity="error")
            return
        self.call_from_thread(self.show_claude, claude, refresh)

    def show_claude(self, claude: dict, told: bool = False) -> None:
        if not self.is_running:  # Claude Code answered as the panel closed
            return
        if claude.get("models") != self.claude.get("models"):  # the choices change, the chosen ones stay
            self.claude = claude
            for field in ("#p-claude-model", "#p-claude-light", "#p-super-model"):
                self.choose(field, self.main.query_one(field, Select).value)
        self.claude = claude
        where = f"\n[{MUTED}]{escape(claude['command'])}[/]" if claude.get("command") else ""
        self.main.query_one("#p-claude-status", Static).update(claude_line(claude) + where)
        self.main.query_one("#p-super-status", Static).update(super_line(self.settings.get("super") or {}, claude))
        if told:
            self.notify("Claude Code checked." if claude and not claude["error"] and claude["command"]
                        else "Claude Code is not ready: see its card.", severity="information")

    def save_provider(self) -> None:
        try:
            changes = {
                "provider": self.main.query_one("#p-provider", Select).value,
                "claude_command": self.main.query_one("#p-claude-command", Input).value.strip(),
                "claude_model": self.main.query_one("#p-claude-model", Select).value,
                "claude_light_model": self.main.query_one("#p-claude-light", Select).value,
                "claude_effort": self.main.query_one("#p-claude-effort", Select).value,
                "base_url": self.main.query_one("#p-base-url", Input).value.strip(),
                "model": self.main.query_one("#p-model", Input).value.strip(),
                "light_model": self.main.query_one("#p-light", Input).value.strip(),
                "thinking_mode": self.main.query_one("#p-thinking", Select).value,
                "thinking_tokens": number(self.main.query_one("#p-thinking-tokens", Input), "Thinking tokens"),
                "context_window": number(self.main.query_one("#p-context", Input), "Context window"),
                "vision": self.main.query_one("#p-vision", Switch).value,
                "image_pixels": number(self.main.query_one("#p-pixels", Input), "Picture size") * 1000,
                "stream": self.main.query_one("#p-stream", Switch).value,
                "request_budget": number(self.main.query_one("#p-budget", Input), "Request size limit") * 1024,
                "super_model": self.main.query_one("#p-super-model", Select).value,
                "super_effort": self.main.query_one("#p-super-effort", Select).value,
            }
        except ValueError as exc:
            return self.notify(str(exc), severity="error")
        for key, field in (("api_key", "#p-key"), ("web_search_key", "#p-web-key")):
            if self.main.query_one(field, Input).value.strip():
                changes[key] = self.main.query_one(field, Input).value.strip()
        saved = self.call(lambda c: c.update_config(**changes),
                          done="Provider saved. Every app uses it from its next message.")
        if saved is not None:
            self.main.query_one("#p-key", Input).value = self.main.query_one("#p-web-key", Input).value = ""
            self.load_provider(saved)
            self.show_state()

    @work(thread=True, exclusive=True, group="models")
    def list_models(self, base_url: str, api_key: str) -> None:
        client = self.client
        if client is None:
            return self.call_from_thread(self.notify, "The brain is not running. Press s to start it.",
                                         severity="warning")
        self.call_from_thread(self.notify, "Asking the service for its models…")
        try:  # here, not through call(): a slow service must not freeze the panel
            models = client.models(base_url or None, api_key or None)
        except BrainError as exc:
            return self.call_from_thread(self.notify, exc.message + (f"\n{exc.details}" if exc.details else ""),
                                         severity="error", timeout=10)
        self.call_from_thread(self.show_models, models)

    def show_models(self, models: List[str]) -> None:
        listing = self.main.query_one("#models", OptionList)
        listing.set_options(models)
        listing.display = bool(models)
        self.notify(f"Connected: {len(models)} models. Pick one to use it." if models
                    else "Connected, but the service lists no models; type the model name.")

    @on(OptionList.OptionSelected, "#models")
    def pick_model(self, event: OptionList.OptionSelected) -> None:
        self.main.query_one("#p-model", Input).value = str(event.option.prompt)

    # ============== Apps ==============

    def load_apps(self) -> None:
        apps = self.call(lambda c: c.apps(), quiet=True)
        if apps is None:
            return
        listing = self.main.query_one("#app-list", OptionList)
        if [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)] != apps:
            listing.set_options(apps)
        if apps and self.app_id not in apps:
            listing.highlighted = 0
            self.show_app(apps[0])
        elif not apps:
            self.main.query_one("#app-header", Static).update(
                f"[{MUTED}]No app has connected yet. Start MilkChan or run sentientmilk chat.[/]")

    @on(OptionList.OptionHighlighted, "#app-list")
    def app_chosen(self, event: OptionList.OptionHighlighted) -> None:
        if str(event.option.prompt) != self.app_id:
            self.show_app(str(event.option.prompt))

    def show_app(self, app: str) -> None:
        record = self.call(lambda c: c.app(app))
        kits = self.call(lambda c: c.toolkits(app), quiet=True)
        if record is None or kits is None:
            return
        self.app_id, self.app_record = app, record
        declaration, settings = record["declaration"], record["settings"]
        name = declaration.get("name") or app
        environment = cut(declaration.get("environment", ""), 140)
        self.main.query_one("#app-header", Static).update(
            f"[b]{escape(name)}[/]  [{MUTED}]app id {app}[/]\n[{MUTED}]{escape(environment)}[/]")
        self.main.query_one("#persona-note", Static).update(
            f"[{OK}]Your persona for {escape(name)}[/]" if record["persona_custom"]
            else f"[{MUTED}]The persona {escape(name)} brings with it. Edit and save to make it yours.[/]")
        self.main.query_one("#persona", TextArea).text = record["persona"]
        self.main.query_one("#app-model", Input).value = settings.get("model", "")
        self.main.query_one("#app-roots", Input).value = ", ".join(settings.get("roots", []))
        journal = {"read": True, "write": True, **declaration.get("journal", {}), **settings.get("journal", {})}
        self.main.query_one("#app-journal-read", Switch).value = journal["read"]
        self.main.query_one("#app-journal-write", Switch).value = journal["write"]
        declared = []
        for kit in ["memory"] + declaration.get("toolkits", []):  # every app has memory, listed or not
            declared += [k for k in kits["toolkits"] if k.startswith("mcp:")] if kit == "mcp:*" else [kit]
        off_everywhere = set(self.settings.get("disabled_toolkits", []))
        off_here = set(settings.get("disabled_toolkits", []))
        self.main.query_one("#app-toolkits", SelectionList).set_options([
            (kit + ("  (off for every app in Tools)" if kit in off_everywhere else ""), kit, kit not in off_here)
            for kit in dict.fromkeys(declared)])
        self.load_app_tables()

    def load_app_tables(self) -> None:
        app = self.app_id
        if not app:
            return
        sessions = self.call(lambda c: c.sessions(app), quiet=True)
        if sessions is None:
            return
        fill(self.main.query_one("#sessions", DataTable),
             [(s["id"], (s["id"], when(s["created"]), ago(s["last_active"]))) for s in sessions])

    def save_app(self) -> None:
        app = self.app_id
        if not app:
            return
        chosen = set(self.main.query_one("#app-toolkits", SelectionList).selected)
        listed = [str(option.value) for option in self.main.query_one("#app-toolkits", SelectionList).options]
        changes = {"model": self.main.query_one("#app-model", Input).value.strip(),
                   "roots": items(self.main.query_one("#app-roots", Input).value),
                   "journal": {"read": self.main.query_one("#app-journal-read", Switch).value,
                               "write": self.main.query_one("#app-journal-write", Switch).value},
                   "disabled_toolkits": [kit for kit in listed if kit not in chosen]}
        if self.call(lambda c: c.update_app(app, **changes), done=f"Saved. {app} uses it from its next message."):
            self.show_app(app)

    def save_persona(self, text: str) -> None:
        app = self.app_id
        if app and self.call(lambda c: c.update_app(app, persona=text),
                             done="Persona saved." if text else "Back to the app's own persona."):
            self.show_app(app)

    # ============== Work and journal ==============

    def load_work(self) -> None:
        tasks = self.call(lambda c: sorted(c.tasks() + c.tasks(kind="agent"), key=lambda t: -t["id"]), quiet=True)
        schedules = self.call(lambda c: c.schedules(), quiet=True)
        if tasks is None or schedules is None:
            return
        fill(self.main.query_one("#tasks", DataTable), [
            (str(t["id"]), (t["id"], t["app"], f"[{STATUS_COLORS.get(t['status'], MUTED)}]{t['status']}[/]",
                            cut(t["options"].get("goal", ""), 60), ago(t["created"]),
                            f"{(t['usage'] or {}).get('prompt_tokens', 0):,}"))
            for t in tasks])
        fill(self.main.query_one("#schedules", DataTable), [
            (str(s["id"]), (s["id"], s["app"], f"{s['kind']} {s['spec']}", when(s["next_at"]), cut(s["payload"]["title"], 30),
                            cut(s["payload"]["text"], 50),
                            f"[{OK}]on[/]" if s["enabled"] else f"[{MUTED}]paused[/]"))
            for s in schedules])
        self.show_task()

    @on(DataTable.RowHighlighted, "#tasks")
    def show_task(self) -> None:
        if not self.screen_stack:
            return  # the panel closed with this row highlight still queued
        key = selected_key(self.main.query_one("#tasks", DataTable))
        task = self.call(lambda c: c.run(int(key)), quiet=True) if key else None
        if not task:
            return self.main.query_one("#task-detail", Static).update(f"[{MUTED}]No background tasks yet.[/]")
        result, error = task["result"] or {}, task["error"] or {}
        outcome = (f"[{BAD}]{escape(error.get('message', ''))}[/]" if error
                   else escape(cut(result.get("reply", ""), 600)) or f"[{MUTED}]still working…[/]")
        self.main.query_one("#task-detail", Static).update(
            f"[b]#{task['id']}[/] {escape(task['options'].get('goal', ''))}\n{outcome}")

    def load_memory(self) -> None:
        """Memory (From: the app that saved an entry), then the journal."""
        settings = self.call(lambda c: c.config(), quiet=True)
        if settings is not None:
            switch = self.main.query_one("#summaries", Switch)
            with switch.prevent(Switch.Changed):
                switch.value = settings["session_summaries"]
        memory = self.call(lambda c: c.memory_entries(), quiet=True)
        if memory is not None:
            fill(self.main.query_one("#memory", DataTable),
                 [(f"{e['category']}\n{e['key']}", (e["category"], e["key"], cut(e["value"], 90), e["app"]))
                  for e in memory])
        self.load_notes()

    def load_notes(self) -> None:
        query = self.main.query_one("#journal-search", Input).value.strip()
        notes = self.call(lambda c: c.journal(query), quiet=True)
        if notes is not None:
            fill(self.main.query_one("#notes", DataTable),
                 [(str(n["id"]), (when(n["at"]), n["app"], cut(n["note"], 110))) for n in notes])

    @on(Input.Changed, "#journal-search")
    def search_notes(self) -> None:
        self.load_notes()

    # ============== Tools ==============

    def load_tools(self) -> None:
        kits = self.call(lambda c: c.toolkits(), quiet=True)
        settings = self.call(lambda c: c.config(), quiet=True)
        if kits is None or settings is None:
            return
        off = set(settings["disabled_toolkits"])
        self.main.query_one("#toolkits", SelectionList).set_options(
            [(kit, kit, kit not in off) for kit in kits["toolkits"]])
        self.main.query_one("#t-shell", Select).value = settings["shell"]
        self.main.query_one("#t-workers", Input).value = str(settings["task_workers"])
        for kind in ("deny", "ask", "allow"):
            self.main.query_one(f"#t-{kind}", Input).value = ", ".join(settings["rules"].get(kind, []))
        self.main.query_one("#t-browser", Input).value = settings["browser_command"]
        self.load_browser()
        self.load_mcp()

    def load_browser(self, status: Optional[dict] = None) -> None:
        status = status or self.call(lambda c: c.browser(), quiet=True)
        if status is None:
            return
        chrome = status["chrome"]
        self.main.query_one("#t-chrome-folder", Input).value = chrome["folder"]
        self.main.query_one("#t-chrome-code", Input).value = chrome["code"]
        if chrome["error"]:
            words = f"[{WARN}]{escape(chrome['error'])}[/]"
        elif chrome["connected"]:
            words = (f"[{OK}]connected ({escape(chrome['browser'])}, extension {escape(chrome['extension'])})[/] · "
                     f"{chrome['tabs']} tab{'s' if chrome['tabs'] != 1 else ''} of hers")
        elif chrome["disconnected"]:
            words = f"[{MUTED}]you disconnected it in Chrome: Connect there, or here, brings her back[/]"
        else:
            words = "not connected (she opens it when she needs it)"
        if not status["command"]:
            words += f" · [{WARN}]no Chrome or Edge found: install one, or give its path[/]"
        else:
            words += " · " + escape(f"{Path(status['command']).name} {status['version']}".strip())
        self.main.query_one("#t-chrome-status", Static).update("Your Chrome: " + words)

    def save_tools(self) -> None:
        listed = [str(option.value) for option in self.main.query_one("#toolkits", SelectionList).options]
        chosen = set(self.main.query_one("#toolkits", SelectionList).selected)
        try:
            changes = {"disabled_toolkits": [kit for kit in listed if kit not in chosen],
                       "shell": self.main.query_one("#t-shell", Select).value,
                       "task_workers": number(self.main.query_one("#t-workers", Input), "Background workers"),
                       "browser_command": self.main.query_one("#t-browser", Input).value.strip(),
                       "rules": {kind: items(self.main.query_one(f"#t-{kind}", Input).value)
                                 for kind in ("deny", "ask", "allow")}}
        except ValueError as exc:
            return self.notify(str(exc), severity="error")
        if self.call(lambda c: c.update_config(**changes),
                     done="Saved. Workers and the shell change at the next brain start."):
            self.load_tools()

    def load_mcp(self) -> None:
        mcp = self.call(lambda c: c.mcp(), quiet=True)
        if mcp is None:
            return
        rows = []
        for name, spec in mcp["servers"].items():
            status = mcp["status"].get(name, {})
            state = status.get("state", "?")
            color = OK if state == "connected" else MUTED if state == "disabled" else WARN
            target = spec.get("url") or " ".join([spec.get("command", "")] + spec.get("args", []))
            rows.append((name, (name, f"[{color}]{state}[/]", status.get("tools", "-"), cut(target, 50),
                                cut(status.get("error") or "", 60))))
        fill(self.main.query_one("#mcp", DataTable), rows)

    def change_mcp(self, change: Callable[[dict], None], done: str) -> None:
        mcp = self.call(lambda c: c.mcp())
        if mcp is None:
            return
        servers = mcp["servers"]  # hidden secrets read back as <set>, which keeps them
        change(servers)
        if self.call(lambda c: c.set_mcp(servers), done=done) is not None:
            self.load_mcp()

    # ============== Plugins ==============

    def load_plugins(self) -> None:
        plugins = self.call(lambda c: c.plugins(), quiet=True)
        if plugins is None:
            return
        self.plugins = {plugin["name"]: plugin for plugin in plugins}
        rows = []
        for plugin in plugins:
            state = f"[{BAD}]broken[/]" if plugin["error"] else f"[{OK}]on[/]" if plugin["enabled"] else f"[{MUTED}]off[/]"
            if not plugin["trusted"]:
                state += f" [{WARN}]untrusted[/]"
            source = "built in" if plugin["builtin"] else plugin["source"] or plugin["path"]
            rows.append((plugin["name"], (plugin["name"], plugin["version"], state, plugin["tools"], cut(source, 60))))
        fill(self.main.query_one("#plugin-table", DataTable), rows)
        self.show_plugin()

    @on(DataTable.RowHighlighted, "#plugin-table")
    def show_plugin(self) -> None:
        if not self.screen_stack:
            return  # the panel closed with this row highlight still queued
        plugin = self.plugins.get(selected_key(self.main.query_one("#plugin-table", DataTable)) or "")
        if not plugin:
            return self.main.query_one("#plugin-detail", Static).update("")
        lines = [escape(plugin["description"])]
        if plugin["error"]:
            lines.append(f"[{BAD}]{escape(plugin['error'])}[/]")
        if not plugin["trusted"]:
            lines.append(f"[{WARN}]Not trusted: its tools ask every time, whatever they say and even in an app "
                         "that allows everything, and its MCP servers do not run. Trust it once you know its code: "
                         f"{escape(plugin['path'])}[/]")
        if plugin["toolkits"] or plugin["mcp"]:
            lines.append("Toolkits: " + ", ".join(plugin["toolkits"] + [f"mcp:{name}" for name in plugin["mcp"]]))
        for setting in plugin["settings"].values():
            shown = ("✓ set" if setting["set"] else "not set") if setting["secret"] else setting["value"] or "-"
            lines.append(f"{escape(setting['label'])}: {escape(str(shown))}")
        self.main.query_one("#plugin-detail", Static).update("\n".join(lines))

    def plugin_button(self, button: str) -> None:
        if button == "plugin-install":
            return self.push_screen(InstallPlugin(), self.install_plugin)
        name = selected_key(self.main.query_one("#plugin-table", DataTable))
        plugin = self.plugins.get(name or "")
        if not plugin:
            return
        if button == "plugin-toggle":
            enabled = not plugin["enabled"]
            if self.call(lambda c: c.update_plugin(name, enabled=enabled),
                         done=f"{name} turned {'on' if enabled else 'off'}."):
                self.load_plugins()
        elif button == "plugin-settings":
            self.push_screen(PluginSettings(plugin), lambda settings: settings is not None and self.call(
                lambda c: c.update_plugin(name, settings=settings), done=f"{name} saved.") and self.load_plugins())
        elif button == "plugin-trust":
            if plugin["builtin"]:
                return self.notify(f"{name} is built in: it is always trusted.")
            if plugin["trusted"]:
                if self.call(lambda c: c.update_plugin(name, trusted=False), done=f"{name}'s tools ask every time again."):
                    self.load_plugins()
                return
            self.push_screen(Confirm(f"Trust {name} as its files are now? Its tools then run as they declare, "
                                     f"without asking when they say they change nothing, and its MCP servers run. "
                                     f"Its code is in {plugin['path']}. A change to it takes the trust away.", "Trust"),
                             lambda yes: yes and self.call(lambda c: c.update_plugin(name, trusted=True),
                                                           done=f"{name} is trusted.") and self.load_plugins())
        elif button == "plugin-reload":
            if self.call(lambda c: c.reload_plugin(name), done=f"{name} reloaded."):
                self.load_plugins()
        elif button == "plugin-remove":
            if plugin["builtin"]:
                return self.notify(f"{name} is built in: turn it off instead.", severity="warning")
            self.push_screen(Confirm(f"Remove the plugin {name}? Its folder is deleted: {plugin['path']}", "Remove"),
                             lambda yes: yes and self.call(lambda c: c.remove_plugin(name), done=f"{name} removed.")
                             and self.load_plugins())

    @work(thread=True, group="plugins")
    def install_plugin(self, source: Optional[str]) -> None:
        if not source:
            return
        self.call_from_thread(self.notify, f"Installing {source}…")
        installed = self.call(lambda c: c.install_plugin(source))  # a git clone can take a while
        if installed:
            self.call_from_thread(self.notify, f"{installed['name']} {installed['version']} installed and on.")
            self.call_from_thread(self.load_plugins)

    # ============== Skills ==============

    def load_skills(self) -> None:
        skills = self.call(lambda c: c.skills(), quiet=True)
        if skills is None:
            return
        self.skills = {skill["name"]: skill for skill in skills}
        rows = []
        for skill in skills:
            who = "nobody" if skill["error"] else "you and her" if skill["model_invocable"] and \
                skill["user_invocable"] else "her" if skill["model_invocable"] else "you" if skill["user_invocable"] \
                else "nobody"
            state = f"[{BAD}]broken[/]" if skill["error"] else f"[{MUTED}]built in[/]" if skill["builtin"] else \
                f"[{OK}]ready[/]"
            rows.append((skill["name"], (skill["name"], who, state, cut(skill["description"], 70))))
        fill(self.main.query_one("#skill-table", DataTable), rows)
        self.show_skill()

    @on(DataTable.RowHighlighted, "#skill-table")
    def show_skill(self) -> None:
        if not self.screen_stack:
            return  # the panel closed with this row highlight still queued
        skill = self.skills.get(selected_key(self.main.query_one("#skill-table", DataTable)) or "")
        if not skill:
            return self.main.query_one("#skill-detail", Static).update("")
        lines = [escape(skill["description"])]
        if skill["error"]:
            lines.append(f"[{BAD}]{escape(skill['error'])}[/]")
        if skill["user_invocable"]:
            lines.append(escape(f"Start it: /{skill['name']} {skill['argument_hint']}".rstrip()))
        lines.append(f"[{MUTED}]{escape(skill['path'])}[/]")
        self.main.query_one("#skill-detail", Static).update("\n".join(lines))

    def skill_button(self, button: str) -> None:
        name = selected_key(self.main.query_one("#skill-table", DataTable))
        skill = self.skills.get(name or "")
        if button == "skill-open":
            folder = Path(skill["path"]) if skill and not skill["builtin"] else self.home / "skills"
            folder.mkdir(parents=True, exist_ok=True)
            return open_folder(folder)
        if not skill:
            return
        if skill["builtin"]:
            return self.notify(f"{name} comes with SentientMilk. A skill of the same name in your skills folder "
                               "replaces it.", severity="warning")
        self.push_screen(Confirm(f"Remove the skill {name}? Its folder is deleted: {skill['path']}", "Remove"),
                         lambda yes: yes and self.call(lambda c: c.remove_skill(name), done=f"{name} removed.")
                         and self.load_skills())

    # ============== Logs ==============

    def tail_log(self) -> None:
        if self.main.query_one(TabbedContent).active != "logs":
            return
        path = self.home / "brain.log"
        try:
            size = path.stat().st_size
            if size < self.log_offset:
                self.log_offset = 0  # the log was rotated
            with open(path, encoding="utf-8", errors="replace") as log:
                log.seek(self.log_offset)
                text = log.read()
                self.log_offset = log.tell()
        except OSError:
            return
        view = self.main.query_one("#log", RichLog)
        for line in text.splitlines():
            view.write(line)

    # ============== Actions ==============

    def action_tab(self, tab: str) -> None:
        self.main.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        self.load_all()
        self.notify("Refreshed.")

    def action_start(self) -> None:
        if self.state == "stopped" and not self.api():
            self.start_brain()

    def action_stop(self) -> None:
        if self.state != "running":
            return
        self.push_screen(Confirm("Stop the brain? Running tasks pause and apps lose their connection "
                                 "until it starts again.", "Stop"), self.stop_brain)

    def stop_brain(self, confirmed: bool) -> None:
        if confirmed and self.call(lambda c: c.shutdown(), done="Brain stopped.") is not None:
            self.client, self.state = None, "stopped"
            self.show_state()
            self.load_overview()

    def action_save(self) -> None:
        tab = self.main.query_one(TabbedContent).active
        {"provider": self.save_provider, "apps": self.save_app, "tools": self.save_tools}.get(tab, lambda: None)()

    @on(TabbedContent.TabActivated)
    def tab_shown(self) -> None:
        self.refresh_live()
        self.tail_log()

    @on(Switch.Changed, "#summaries")
    def summaries_changed(self, event: Switch.Changed) -> None:
        self.call(lambda c: c.update_config(session_summaries=event.value),
                  done="She goes over each conversation as it ends." if event.value
                  else "She no longer goes over conversations as they end.")

    @on(Switch.Changed, "#autostart")
    def autostart_changed(self, event: Switch.Changed) -> None:
        try:
            autostart.set_enabled(AUTOSTART, start_command(self.home) if event.value else None)
        except OSError as exc:
            self.notify(f"Windows did not take it: {exc}", severity="error")
        else:
            self.notify("SentientMilk starts with Windows from now on." if event.value
                        else "SentientMilk no longer starts with Windows.")
        self.show_autostart()

    def show_autostart(self) -> None:
        """As Windows has it: Task Manager may turn it off too."""
        if autostart.AVAILABLE:
            switch = self.main.query_one("#autostart", Switch)
            with switch.prevent(Switch.Changed):
                switch.value = autostart.enabled(AUTOSTART)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "brain-start":
            self.action_start()
        elif button == "brain-stop":
            self.action_stop()
        elif button == "brain-restart":
            if self.call(lambda c: c.shutdown(), done="Restarting the brain…") is not None:
                self.client, self.state = None, "starting"
                self.start_brain(after_stop=True)
        elif button == "goto-provider":
            self.action_tab("provider")
        elif button == "p-save":
            self.save_provider()
        elif button == "p-claude-refresh":
            self.notify("Asking Claude Code…")
            self.load_claude(refresh=True)
        elif button == "p-models":
            self.list_models(self.main.query_one("#p-base-url", Input).value.strip(),
                             self.main.query_one("#p-key", Input).value.strip())
        elif button == "p-remove-key":
            self.push_screen(Confirm("Remove the saved API key? No app can think until a new one is set.",
                                     "Remove key"),
                             lambda yes: yes and self.call(lambda c: c.update_config(api_key=""), done="Key removed.")
                             and self.load_provider())
        elif button == "persona-save":
            self.save_persona(self.main.query_one("#persona", TextArea).text.strip())
        elif button == "persona-reset":
            self.save_persona("")
        elif button == "app-save":
            self.save_app()
        elif button == "session-clear":
            self.clear_session()
        elif button == "memory-forget":
            self.forget_memory()
        elif button == "task-cancel":
            key = selected_key(self.main.query_one("#tasks", DataTable))
            if key:
                self.call(lambda c: c.cancel(int(key)), done=f"Task {key} cancelled.")
        elif button == "schedule-toggle":
            self.toggle_schedule()
        elif button == "schedule-delete":
            key = selected_key(self.main.query_one("#schedules", DataTable))
            if key:
                self.push_screen(Confirm(f"Delete schedule {key}?", "Delete"),
                                 lambda yes: yes and self.call(lambda c: c.delete_schedule(int(key)),
                                                               done="Schedule deleted."))
        elif button == "note-delete":
            key = selected_key(self.main.query_one("#notes", DataTable))
            if key:
                self.push_screen(Confirm("Delete this journal note?", "Delete"),
                                 lambda yes: yes and self.call(lambda c: c.delete_note(int(key)), done="Note deleted."))
        elif button == "t-save":
            self.save_tools()
        elif button == "chrome-connect":
            self.notify("Opening SentientMilk's extension in your Chrome…")
            self.connect_chrome()
        elif button == "mcp-add":
            self.push_screen(AddServer(), self.add_server)
        elif button in ("mcp-reconnect", "mcp-toggle", "mcp-remove"):
            self.mcp_button(button)
        elif button and button.startswith("plugin-"):
            self.plugin_button(button)
        elif button and button.startswith("skill-"):
            self.skill_button(button)

    def clear_session(self) -> None:
        app, session = self.app_id, selected_key(self.main.query_one("#sessions", DataTable))
        if app and session:
            self.push_screen(Confirm(f"Clear the conversation {session} of {app}? Its history and its own "
                                     "memory are deleted; memory of every app and the journal stay.", "Clear"),
                             lambda yes: yes and self.call(lambda c: c.clear_history(app, session),
                                                           done="Conversation cleared."))

    def forget_memory(self) -> None:
        key = selected_key(self.main.query_one("#memory", DataTable))
        if key:
            category, _, name = key.partition("\n")
            self.push_screen(Confirm(f"Forget {category} / {name}? Every app forgets it.", "Forget"),
                             lambda yes: yes and self.call(lambda c: c.forget(category, name),
                                                           done="Forgotten.") and self.load_memory())

    def toggle_schedule(self) -> None:
        key = selected_key(self.main.query_one("#schedules", DataTable))
        schedules = {str(s["id"]): s for s in self.call(lambda c: c.schedules(), quiet=True) or []}
        if key in schedules:
            enabled = not schedules[key]["enabled"]
            self.call(lambda c: c.enable_schedule(int(key), enabled),
                      done=f"Schedule {key} {'resumed' if enabled else 'paused'}.")
            self.load_work()

    def add_server(self, server: Optional[Tuple[str, dict]]) -> None:
        if server:
            name, spec = server
            self.change_mcp(lambda servers: servers.__setitem__(name, spec), f"MCP server {name} added.")

    def mcp_button(self, button: Optional[str]) -> None:
        name = selected_key(self.main.query_one("#mcp", DataTable))
        if not name:
            return
        if button == "mcp-reconnect":
            self.call(lambda c: c.reconnect_mcp(name), done=f"Reconnecting {name}…")
        elif button == "mcp-toggle":
            self.change_mcp(lambda servers: servers[name].__setitem__("enabled", not servers[name].get("enabled", True)),
                            f"{name} switched.")
        elif button == "mcp-remove":
            self.push_screen(Confirm(f"Remove the MCP server {name}?", "Remove"),
                             lambda yes: yes and self.change_mcp(lambda servers: servers.pop(name),
                                                                 f"{name} removed."))


def run(home: Path) -> None:
    Panel(home).run()
