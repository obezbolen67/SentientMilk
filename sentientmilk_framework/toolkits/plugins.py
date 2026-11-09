"""Plugins the model makes for itself: written with the files toolkit, installed and fixed here.

Installing or reloading runs the plugin's code inside the brain, so it always asks the user (policy
``always``: no rule, "always allow" or app bypass skips it; a deny rule still refuses it). A plugin
installed here is not trusted: its tools ask the user every time until the user trusts it (see
``sentientmilk_framework.plugins``).
"""

from . import ToolContext, ToolError, Toolkit, tool
from .files import resolve

UNTRUSTED = ("It is not trusted yet: each of its tools will ask the user every time it is called, until they "
             "trust the plugin in SentientMilk's control panel (Plugins).")


def _tools_of(ctx: ToolContext, info: dict) -> list:
    kits = ctx.brain.plugins.toolkits()
    return [item.name for kit in info["toolkits"] for item in getattr(kits.get(kit), "tools", [])]


def _report(ctx: ToolContext, info: dict, done: str) -> str:
    if info["error"]:
        return (f"{done} {info['name']}, but it did not load: {info['error']}\n"
                f"Fix its files and call plugin_reload(name={info['name']!r}).")
    names = _tools_of(ctx, info)
    lines = [f"{done} {info['name']} {info['version']}: " +
             (f"{len(names)} tools ({', '.join(names)}). Load them with tools_load and call them by name."
              if names else "no tools.")]
    if info["mcp"]:
        lines.append(f"Its MCP servers ({', '.join(info['mcp'])}) run once the user trusts it.")
    if not info["trusted"]:
        lines.append(UNTRUSTED)
    return "\n".join(lines)


def _plugin_error(exc: ValueError) -> ToolError:
    return ToolError(str(exc))


@tool(readonly=True)
def plugin_list(ctx: ToolContext):
    """The plugins SentientMilk has: each one's state, whether the user trusts it, its tools, and what is
    wrong with a broken one. To make one, see plugin_install."""
    lines = []
    for info in ctx.brain.plugins.public():
        state = "broken" if info["error"] else "on" if info["enabled"] else "off"
        trust = "trusted" if info["trusted"] else "not trusted (its tools ask every time)"
        origin = "built in" if info["builtin"] else f"from {info['source'] or info['path']}"
        lines.append(f"{info['name']} {info['version']} · {state} · {trust} · {info['tools']} tools · {origin}")
        if info["error"]:
            lines.append(f"    {info['error']}")
    return "\n".join(lines) or "No plugins."


@tool(policy="always", rule_arg="folder", args={"folder": "The plugin's folder, with its plugin.json."})
def plugin_install(ctx: ToolContext, folder: str):
    """Install a plugin you wrote, so its tools are yours (and every app's) from your next step. It runs
    the plugin's code inside SentientMilk, so the user is always asked first. Until they trust it in
    SentientMilk's control panel, each of its tools asks them every time it is called.

    A plugin is a folder (write it with files_write, in a folder open to you):
      plugin.json  {"name": "moon", "version": "0.1.0", "description": "What it is for.",
                    "toolkits": ["tools.py"],
                    "settings": {"key": {"label": "API key", "secret": true, "env": ["MOON_KEY"]}}}
      tools.py     from sentientmilk_framework.toolkits import Toolkit, ToolError, tool

                   @tool(readonly=True, args={"city": "The city."})
                   def moon_phase(ctx, city: str = ""):
                       '''Today's moon phase. This docstring is what you read when you load the tool.'''
                       key = ctx.brain.plugins.settings("moon")["key"]  # the user sets it in the panel
                       if not key:
                           raise ToolError("No API key: ask the user to set it in SentientMilk (Plugins: moon).")
                       return "waxing"

                   TOOLKIT = Toolkit("moon", "The moon.", [moon_phase])

    Rules: the plugin's name is 1-32 of a-z, 0-9, _ and -. Tools are named <toolkit>_<verb>, and the
    toolkit's name must be new (not files, shell, web, github...). Type hints give the parameters. Return
    text; raise ToolError with what to do instead. readonly=True for tools that change nothing; the others
    ask the user. Code may import the standard library, requests and the plugin's own files (from . import
    helpers). For anything else, run an MCP server: "mcp": {"servers": {"moon": {"command": "npx", "args":
    ["-y", "some-server"]}}} in plugin.json; it runs once the user trusts the plugin. After changing the
    files, call plugin_reload."""
    path = resolve(ctx, folder)
    if not (path / "plugin.json").is_file():
        raise ToolError(f"{path} has no plugin.json: write the plugin's files there first (see this tool's description).")
    try:
        info = ctx.brain.install_plugin(str(path), trusted=False)
    except ValueError as exc:
        raise _plugin_error(exc)
    return _report(ctx, info, "Installed")


@tool(policy="always", rule_arg="name", args={"name": "The plugin's name, as plugin_list gives it."})
def plugin_reload(ctx: ToolContext, name: str):
    """Bring in your changes to a plugin: copies its folder again and imports it (the user is always asked).
    If its files changed, the user's trust in it ends until they trust it again."""
    try:
        info = ctx.brain.reload_plugin(name)
    except ValueError as exc:
        raise _plugin_error(exc)
    return _report(ctx, info, "Reloaded")


TOOLKIT = Toolkit("plugins", "Make your own tools: write a plugin, install it, fix it (asks the user).",
                  [plugin_list, plugin_install, plugin_reload], part=True)
