"""Plugins: what extends the brain for every app, installed once in SentientMilk.

A plugin is a folder with a ``plugin.json``:

    {"name": "github", "version": "1.0.0",
     "description": "GitHub: repositories, code, issues, pull requests and Actions.",
     "toolkits": ["tools.py"],
     "mcp": {"servers": {"search": {"command": "search-server", "env": {"TOKEN": "${token}"}}}},
     "settings": {"token": {"label": "Token", "secret": true, "env": ["GITHUB_TOKEN"], "help": "..."}}}

- ``toolkits``: Python files of the folder, each defining ``TOOLKIT`` (a ``Toolkit``) or ``TOOLKITS`` (a list),
  under the toolkit contract (``toolkits/__init__.py``). The folder is a package: files import each other with
  ``from . import helpers``. A tool reads its plugin's settings with ``ctx.brain.plugins.settings(name)``.
- ``mcp``: MCP servers the plugin runs, as in mcp.json. ``${key}`` takes the plugin's setting; other
  ``${NAME}`` are environment variables, as in mcp.json. A server is toolkit ``mcp:<plugin>`` when it is named
  like the plugin, otherwise ``mcp:<plugin>-<server>``; the user's mcp.json wins a name both use.
- ``settings``: what the user sets in the control panel (Plugins). A secret is only ever shown as set or not.
  ``env`` lists environment variables to fall back on, ``default`` the value when none is set.

Built-in plugins ship in this package; the user's live in ``<home>/plugins/<name>/``, installed from a folder
or a git URL. Single-file toolkits in ``<home>/toolkits/*.py`` load as plugins too. Plugins are on until the
user turns one off (``<home>/plugins.json`` keeps that and the settings). An enabled plugin's toolkits are
offered to every app, which can switch them off like any toolkit.

A plugin runs as the user, inside the brain: install only plugins you trust. A broken one is listed with its
error and never stops the brain.

Trust belongs to a plugin's exact files. Built-in plugins are trusted; one the user installs (panel, command
line, API) is trusted as it is then; one a model installs (the plugins toolkit) is not, and neither is one that
appears on disk or changes after it was trusted. The tools of an untrusted plugin ask the user every time,
whatever they declare and whatever the rules or an app's bypass say (policy ``always``), and its MCP servers
do not run, until the user trusts it.
"""

import copy
import dataclasses
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..toolkits import Toolkit, builtin

logger = logging.getLogger(__name__)

MANIFEST = "plugin.json"
STATE = "plugins.json"
BUILT_IN = Path(__file__).parent
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
HIDDEN = "<set>"
SETTING_FIELDS = {"label": str, "secret": bool, "env": list, "help": str, "default": str}
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_IGNORED = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")


@dataclass
class Plugin:
    name: str
    path: Path
    builtin: bool
    manifest: dict = field(default_factory=dict)
    toolkits: Dict[str, Toolkit] = field(default_factory=dict)
    error: str = ""
    single_file: bool = False  # an old <home>/toolkits/*.py
    fingerprint: str = ""  # of its files: what the user trusted

    @property
    def settings_spec(self) -> dict:
        return self.manifest.get("settings", {})

    @property
    def servers(self) -> dict:
        return self.manifest.get("mcp", {}).get("servers", {})


def read_manifest(folder: Path) -> dict:
    """The folder's plugin.json, checked: what is wrong in it says how to put it right."""
    from ..mcp_host import validate as validate_mcp

    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{MANIFEST} is unreadable: {exc}")
    if not isinstance(manifest, dict):
        raise ValueError(f"{MANIFEST} must hold an object")
    if not NAME.fullmatch(str(manifest.get("name", ""))):
        raise ValueError(f"{MANIFEST} needs a name: 1-32 lowercase letters, digits, '_' or '-'")
    for key in ("version", "description"):
        if not isinstance(manifest.get(key, ""), str):
            raise ValueError(f"{MANIFEST}: {key} must be a string")
    files = manifest.get("toolkits", [])
    if not isinstance(files, list) or not all(isinstance(name, str) and _inside(folder, name) and name.endswith(".py")
                                              for name in files):
        raise ValueError(f"{MANIFEST}: toolkits must list .py files inside the plugin's folder")
    if "mcp" in manifest:
        manifest["mcp"] = validate_mcp(manifest["mcp"])
    settings = manifest.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError(f"{MANIFEST}: settings must map names to {{label, secret, env, help, default}}")
    for key, spec in settings.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", key) or not isinstance(spec, dict) or \
                set(spec) - set(SETTING_FIELDS) or \
                any(not isinstance(spec[item], kind) for item, kind in SETTING_FIELDS.items() if item in spec):
            raise ValueError(f"{MANIFEST}: setting {key!r} must be {{label, secret, env, help, default}}")
    return manifest


def _inside(folder: Path, name: str) -> bool:
    return (folder / name).resolve().is_relative_to(folder.resolve())


def _delete(path: Path) -> None:
    """A folder and all in it, read-only files too (git's objects are, on Windows)."""
    def writable(function, name, _info):
        os.chmod(name, stat.S_IWRITE)
        function(name)
    shutil.rmtree(path, **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))


def fingerprint(path: Path) -> str:
    """Of a plugin's files (not Python's caches): any change makes another."""
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(
        item for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc")
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode() if item != path else b"")
        digest.update(b"\0" + item.read_bytes() + b"\0")
    return digest.hexdigest()


def _asking(kit: Toolkit) -> Toolkit:
    """The toolkit of an untrusted plugin: each tool asks the user, and is never re-run after a crash."""
    return Toolkit(kit.name, kit.description, [dataclasses.replace(item, policy="always", readonly=False)
                                               for item in kit.tools])


def _toolkits_of(module) -> List[Toolkit]:
    kits = getattr(module, "TOOLKITS", None) or [getattr(module, "TOOLKIT", None)]
    if not kits or not all(isinstance(kit, Toolkit) for kit in kits):
        raise TypeError(f"{module.__name__} must define TOOLKIT (a Toolkit) or TOOLKITS (a list of them)")
    return kits


class Plugins:
    def __init__(self, home: Path, built_in: Path = BUILT_IN):
        self.home, self.built_in = Path(home), Path(built_in)
        self.folder = self.home / "plugins"
        self.state_path = self.home / STATE
        self._lock = threading.RLock()
        self._plugins: Dict[str, Plugin] = {}
        self.version = 0  # one more at each load: runs then take the tools as they are now
        self._state = self._read_state()
        self.load()

    # ============== Loading ==============

    def load(self) -> None:
        """Find and import every plugin again: after installing or removing one."""
        found: Dict[str, Plugin] = {}
        taken = set(builtin())
        candidates = [(folder, True) for folder in sorted(self.built_in.iterdir()) if (folder / MANIFEST).is_file()]
        if self.folder.is_dir():
            candidates += [(folder, False) for folder in sorted(self.folder.iterdir()) if (folder / MANIFEST).is_file()]
        for folder, shipped in candidates:
            plugin = Plugin(folder.name, folder, shipped, fingerprint="" if shipped else fingerprint(folder))
            try:
                plugin.manifest = read_manifest(folder)
                plugin.name = plugin.manifest["name"]
                if plugin.name in found:
                    raise ValueError(f"a plugin named {plugin.name} is loaded already")
                plugin.toolkits = self._import(plugin, taken)
            except Exception as exc:
                plugin.error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)
                logger.error("Plugin %s was skipped: %s", folder, plugin.error)
            found.setdefault(plugin.name, plugin)
            taken |= set(plugin.toolkits)
        for path in sorted((self.home / "toolkits").glob("*.py")) if (self.home / "toolkits").is_dir() else []:
            plugin = Plugin(path.stem, path, False, {"name": path.stem, "description": ""}, single_file=True,
                            fingerprint=fingerprint(path))
            try:
                plugin.toolkits = self._import(plugin, taken)
                plugin.manifest["description"] = next(iter(plugin.toolkits.values())).description
            except Exception as exc:
                plugin.error = f"{type(exc).__name__}: {exc}"
                logger.error("Toolkit %s was skipped: %s", path, plugin.error)
            if plugin.name not in found:
                found[plugin.name] = plugin
                taken |= set(plugin.toolkits)
        with self._lock:
            self._plugins = found
            self.version += 1

    def _import(self, plugin: Plugin, taken: set) -> Dict[str, Toolkit]:
        if plugin.single_file:
            spec = importlib.util.spec_from_file_location(f"sentientmilk_plugin_{plugin.name}", plugin.path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules = [module]
        else:
            package = f"{__name__}.{plugin.path.name}" if plugin.builtin else f"sentientmilk_plugins.{plugin.name}"
            if not plugin.builtin:  # the user's folder as a package of its own, freshly imported
                for loaded in [name for name in sys.modules if name == package or name.startswith(package + ".")]:
                    del sys.modules[loaded]
                sys.modules.setdefault("sentientmilk_plugins", importlib.util.module_from_spec(
                    importlib.machinery.ModuleSpec("sentientmilk_plugins", None, is_package=True)))
                spec = importlib.machinery.ModuleSpec(package, None, is_package=True)
                spec.submodule_search_locations = [str(plugin.path)]
                sys.modules[package] = importlib.util.module_from_spec(spec)
            modules = [importlib.import_module(f"{package}.{Path(name).with_suffix('').as_posix().replace('/', '.')}")
                       for name in plugin.manifest.get("toolkits", [])]
        kits = {}
        for module in modules:
            for kit in _toolkits_of(module):
                if kit.name in taken or kit.name in kits or kit.name.startswith("mcp:"):
                    raise ValueError(f"toolkit name {kit.name!r} is taken: give the toolkit another name")
                kits[kit.name] = kit
        return kits

    # ============== What the brain uses ==============

    def enabled(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
            return bool(plugin) and not plugin.error and self._state.get(name, {}).get(
                "enabled", plugin.manifest.get("enabled", True))

    def trusted(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
            return bool(plugin) and (plugin.builtin or self._state.get(name, {}).get("trusted") == plugin.fingerprint)

    def toolkits(self) -> Dict[str, Toolkit]:
        """The toolkits of the plugins that are on; an untrusted plugin's tools all ask the user."""
        with self._lock:
            plugins = list(self._plugins.values())
        return {name: kit if self.trusted(plugin.name) else _asking(kit)
                for plugin in plugins if self.enabled(plugin.name) for name, kit in plugin.toolkits.items()}

    def installed(self) -> Dict[str, str]:
        """Toolkit name -> the plugin the user installed that brings it (built-in plugins are not "installed")."""
        with self._lock:
            plugins = list(self._plugins.values())
        return {name: plugin.name for plugin in plugins if not plugin.builtin and self.enabled(plugin.name)
                for name in plugin.toolkits}

    def offered(self) -> List[str]:
        """Toolkit names every app gets: the plugins' own and their MCP servers'."""
        return list(self.toolkits()) + [f"mcp:{name}" for name in self.mcp_servers()]

    def settings(self, name: str) -> dict:
        """A plugin's settings for its code: what the user set, else the environment, else the default."""
        with self._lock:
            plugin = self._plugins.get(name)
            stored = dict(self._state.get(name, {}).get("settings", {}))
        if plugin is None:
            raise KeyError(f"No plugin named {name}")
        values = {}
        for key, spec in plugin.settings_spec.items():
            value = stored.get(key) or next((os.environ[var] for var in spec.get("env", []) if os.environ.get(var)), "")
            values[key] = value or spec.get("default", "")
        return values

    def mcp_servers(self) -> Dict[str, dict]:
        """The MCP servers of the trusted plugins that are on, with their settings filled in."""
        with self._lock:
            plugins = list(self._plugins.values())
        servers = {}
        for plugin in plugins:
            if not plugin.servers or not self.enabled(plugin.name) or not self.trusted(plugin.name):
                continue
            values = self.settings(plugin.name)

            def fill(text: str) -> str:
                return _PLACEHOLDER.sub(lambda m: values.get(m.group(1)) or m.group(0), text)
            for server, spec in plugin.servers.items():
                filled = copy.deepcopy(spec)
                for key in ("env", "headers"):
                    if key in filled:
                        filled[key] = {item: fill(value) for item, value in filled[key].items()}
                filled["args"] = [fill(arg) for arg in filled.get("args", [])]
                servers[plugin.name if server == plugin.name else f"{plugin.name}-{server}"] = filled
        return servers

    def has_servers(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
        return bool(plugin and plugin.servers)

    # ============== What the user sees and changes ==============

    def public(self) -> List[dict]:
        with self._lock:
            plugins, state = list(self._plugins.values()), copy.deepcopy(self._state)
        listed = []
        for plugin in plugins:
            stored = state.get(plugin.name, {}).get("settings", {})
            values = self.settings(plugin.name) if not plugin.error else {}
            settings = {}
            for key, spec in plugin.settings_spec.items():
                shown = {"label": spec.get("label", key), "secret": bool(spec.get("secret")), "help": spec.get("help", "")}
                if spec.get("secret"):
                    shown["set"] = bool(values.get(key))
                else:
                    shown.update({"value": values.get(key, ""), "stored": key in stored})
                settings[key] = shown
            listed.append({"name": plugin.name, "version": plugin.manifest.get("version", ""),
                           "description": plugin.manifest.get("description", ""), "builtin": plugin.builtin,
                           "path": str(plugin.path), "enabled": self.enabled(plugin.name), "error": plugin.error,
                           "trusted": self.trusted(plugin.name), "source": state.get(plugin.name, {}).get("source", ""),
                           "toolkits": list(plugin.toolkits), "tools": sum(len(k.tools) for k in plugin.toolkits.values()),
                           "mcp": sorted(plugin.servers), "settings": settings})
        return listed

    def info(self, name: str) -> dict:
        found = next((plugin for plugin in self.public() if plugin["name"] == name), None)
        if found is None:
            raise ValueError(f"No plugin named {name}")
        return found

    def update(self, name: str, enabled: Optional[bool] = None, settings: Optional[dict] = None,
               trusted: Optional[bool] = None) -> dict:
        """Turn a plugin on or off, change its settings (``<set>`` keeps a secret, "" clears one), and trust
        it as its files are now, or no more."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                raise ValueError(f"No plugin named {name}")
            entry = copy.deepcopy(self._state.get(name, {}))
            if trusted is not None:
                if not isinstance(trusted, bool):
                    raise ValueError("trusted must be true or false")
                if plugin.builtin:
                    raise ValueError(f"{name} is built in: it is always trusted")
                if trusted:
                    entry["trusted"] = plugin.fingerprint
                else:
                    entry.pop("trusted", None)
            if enabled is not None:
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be true or false")
                entry["enabled"] = enabled
            if settings is not None:
                if not isinstance(settings, dict):
                    raise ValueError("settings must map names to strings")
                unknown = set(settings) - set(plugin.settings_spec)
                if unknown:
                    raise ValueError(f"{name} has no settings {sorted(unknown)}; it has {sorted(plugin.settings_spec)}")
                stored = entry.setdefault("settings", {})
                for key, value in settings.items():
                    if not isinstance(value, str):
                        raise ValueError(f"setting {key} must be a string")
                    if value == HIDDEN:
                        continue
                    if value.strip():
                        stored[key] = value.strip()
                    else:
                        stored.pop(key, None)
            state = {**self._state, name: entry}
            self._save(state)
            self._state = state
        return self.info(name)

    def install(self, source: str, trusted: bool = True, replace: Optional[str] = None) -> str:
        """Copy a plugin in from a folder, or clone it from a git URL; it is on at once, and ``trusted`` as
        it is. ``replace``: the installed plugin of that name, copied in again from its source."""
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a folder or a git URL")
        source = source.strip()
        self.folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.folder, prefix=".install-") as temporary:
            staged = Path(temporary) / "plugin"
            if re.match(r"^(https?|ssh|git|file)://|^git@", source):
                done = subprocess.run(["git", "clone", "--depth", "1", "--quiet", source, str(staged)],
                                      capture_output=True, text=True, timeout=300,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if done.returncode:
                    raise ValueError(f"git clone failed: {(done.stderr or done.stdout).strip()[:500]}")
                _delete(staged / ".git")
            else:
                folder = Path(source).expanduser().resolve()
                if not (folder / MANIFEST).is_file():
                    raise ValueError(f"{folder} has no {MANIFEST}: it is not a plugin")
                shutil.copytree(folder, staged, ignore=_IGNORED)
                source = str(folder)
            name = read_manifest(staged)["name"]
            with self._lock:
                existing = self._plugins.get(name)
            if replace and name != replace:
                raise ValueError(f"{source} now holds the plugin {name}, not {replace}")
            if existing and existing.builtin:
                raise ValueError(f"{name} is built in: give your plugin another name")
            if existing and not replace:
                raise ValueError(f"A plugin named {name} is already installed; reload it to bring in changes, "
                                 "or remove it first")
            if existing:
                os.replace(existing.path, Path(temporary) / "replaced")  # the folder must be free to take its place
            os.replace(staged, self.folder / name)
        self.load()
        with self._lock:
            state = {**self._state, name: {**self._state.get(name, {}), "source": source}}
            self._save(state)
            self._state = state
        self.update(name, **({} if replace else {"enabled": True}), **({"trusted": True} if trusted else {}))
        return name

    def reload(self, name: str) -> str:
        """Bring in a plugin's changes: copied again from where it was installed from, or, edited in place
        (a single-file toolkit, or one without a source), imported again. Trust stays only if nothing changed."""
        with self._lock:
            plugin = self._plugins.get(name)
            source = self._state.get(name, {}).get("source")
        if plugin is None:
            raise ValueError(f"No plugin named {name}")
        if plugin.builtin:
            raise ValueError(f"{name} is built in: it changes with SentientMilk")
        if source and not plugin.single_file:
            return self.install(source, trusted=False, replace=name)
        self.load()
        return name

    def remove(self, name: str) -> None:
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                raise ValueError(f"No plugin named {name}")
            if plugin.builtin:
                raise ValueError(f"{name} is built in: turn it off instead")
            state = {key: value for key, value in self._state.items() if key != name}
            self._save(state)
            self._state = state
        if plugin.single_file:
            plugin.path.unlink()
        else:
            _delete(plugin.path)
        self.load()

    # ============== State ==============

    def _read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("top level is not an object")
            return state
        except (OSError, ValueError) as exc:
            # kept aside: the next save must not destroy the tokens in it
            kept = self.state_path.with_name(self.state_path.name + ".invalid")
            logger.error("Plugin settings %s are unreadable (%s); kept as %s", self.state_path, exc, kept)
            try:
                os.replace(self.state_path, kept)
            except OSError:
                pass
            return {}

    def _save(self, state: dict) -> None:
        """Atomic and private to the user: settings may hold tokens."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".plugins-", suffix=".json", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state, output, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.state_path)
        except BaseException:
            os.unlink(temporary)
            raise
