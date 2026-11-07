"""Toolkits: named groups of tools the brain offers to the model.

A tool is a Python function whose first argument is the ToolContext; its schema
comes from the type hints and its description from the docstring. Plugins in
``<home>/toolkits/*.py`` define ``TOOLKIT = Toolkit(...)`` the same way.
"""

import importlib.util
import inspect
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, get_args, get_origin, get_type_hints

logger = logging.getLogger(__name__)

# About Claude Code's shell output cap; bigger results go to a file the model can search or page.
RESULT_CAP = 30_000
HEAD, TAIL = 20_000, 8_000


class ToolError(Exception):
    """A failure the model should read: say what was wrong and how to call the tool correctly."""


@dataclass
class ToolResult:
    text: str
    images: List[str] = field(default_factory=list)  # data URLs, shown to the model after the result


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    readonly: bool = False
    policy: str = "ask"  # used when no rule matches
    rule_arg: Optional[str] = None  # the argument rules match, as in shell_run(git *)
    only_in: Optional[tuple] = None  # run kinds the tool exists in
    toolkit: str = ""
    action: bool = False  # run by the app, not the brain
    core: bool = False  # sent with every request; the others are listed and loaded on demand (tools_load)

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class Toolkit:
    name: str
    description: str
    tools: List[Tool]

    def __post_init__(self):
        for item in self.tools:
            item.toolkit = self.name


STOPPED_BY_USER = "The user stopped you."
MESSAGE_FROM_USER = "The user sent you a message."


class Attention:
    """What a run must notice at once: the user stopped it, or sent a message while it works. Waits inside
    tools end early on either (``ToolContext.pause``); the loop stops waiting for anything on a stop."""

    def __init__(self):
        self.stopped = threading.Event()
        self.woken = threading.Event()  # a stop or a message

    def stop(self) -> None:
        self.stopped.set()
        self.woken.set()

    def message(self) -> None:
        self.woken.set()

    def settle(self) -> None:
        """The loop took the messages: waits go on until the next one."""
        if not self.stopped.is_set():
            self.woken.clear()


@dataclass
class ToolContext:
    brain: Any
    run: dict
    profile: dict  # the effective app profile with this session's settings
    call_id: str = ""
    emit: Callable[[dict], None] = lambda event: None
    attention: Attention = field(default_factory=Attention)

    def pause(self, seconds: float) -> bool:
        """Wait up to ``seconds``; True as soon as the user stops the run or sends a message: end the wait
        then, with what there is, and say why (``interruption()``)."""
        return self.attention.woken.wait(max(0.0, float(seconds)))

    def interruption(self) -> str:
        if self.attention.stopped.is_set():
            return STOPPED_BY_USER
        return MESSAGE_FROM_USER if self.attention.woken.is_set() else ""

    @property
    def app(self) -> str:
        return self.run["app"]

    @property
    def session(self) -> str:
        return self.run["session"]

    @property
    def store(self):
        return self.brain.store

    def run_dir(self) -> Path:
        path = self.brain.home / "runs" / str(self.run["id"])
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_output(self, text: str, stem: str = "out") -> Path:
        directory = self.run_dir()
        path = directory / f"{stem}-{len(list(directory.glob(stem + '-*.txt'))) + 1}.txt"
        path.write_text(text, encoding="utf-8")
        return path


def _schema(annotation: Any) -> dict:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is list:
        return {"type": "array", "items": _schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object"}
    if origin is not None and args:  # Optional[X], Union
        return _schema(next((arg for arg in args if arg is not type(None)), str))
    return {"type": {int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}
            .get(annotation, "string")}


def tool(readonly: bool = False, policy: Optional[str] = None, rule_arg: Optional[str] = None,
         args: Optional[Dict[str, Any]] = None, only_in: Optional[tuple] = None, name: Optional[str] = None,
         core: bool = False):
    """Make a Tool from ``func(ctx, ...)``. ``args`` maps an argument to its description, or to a full
    JSON schema dict for arguments plain type hints cannot describe."""
    def wrap(func: Callable) -> Tool:
        hints = get_type_hints(func)
        properties, required = {}, []
        for index, (arg, parameter) in enumerate(inspect.signature(func).parameters.items()):
            if index == 0:
                continue  # the ToolContext
            described = (args or {}).get(arg, "")
            schema = dict(described) if isinstance(described, dict) else {
                **_schema(hints.get(arg, str)), **({"description": described} if described else {})}
            properties[arg] = schema
            if parameter.default is inspect.Parameter.empty:
                required.append(arg)
        parameters = {"type": "object", "properties": properties, **({"required": required} if required else {})}
        return Tool(name=name or func.__name__, description=inspect.getdoc(func) or "", parameters=parameters,
                    func=func, readonly=readonly, policy=policy or ("auto" if readonly else "ask"),
                    rule_arg=rule_arg, only_in=only_in, core=core)
    return wrap


def format_result(result: Any) -> ToolResult:
    if isinstance(result, ToolResult):
        return result
    if isinstance(result, (dict, list)):
        return ToolResult(json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str))
    return ToolResult("" if result is None else str(result))


def cap(ctx: ToolContext, text: str, stem: str = "out") -> str:
    """Keep results small: above RESULT_CAP the full text goes to a file and the model gets both ends."""
    if len(text) <= RESULT_CAP:
        return text
    path = ctx.save_output(text, stem)
    return (f"{text[:HEAD]}\n\n[... {len(text) - HEAD - TAIL:,} characters left out. The full output "
            f"({len(text):,} characters) is saved in {path}. Search it with files_search or read parts "
            f"of it with files_read and offset.]\n\n{text[-TAIL:]}")


def builtin() -> Dict[str, Toolkit]:
    from . import agents, files, journal, memory, schedule, shell, todo, web

    return {kit.TOOLKIT.name: kit.TOOLKIT for kit in (files, shell, web, todo, memory, journal, agents, schedule)}


def load_plugins(directory: Path) -> Dict[str, Toolkit]:
    """User toolkits; a broken plugin is logged and skipped, never fatal."""
    found = {}
    for path in sorted(Path(directory).glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"sentientmilk_plugin_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            kit = getattr(module, "TOOLKIT")
            if not isinstance(kit, Toolkit):
                raise TypeError("TOOLKIT must be a sentientmilk_framework.toolkits.Toolkit")
            found[kit.name] = kit
        except Exception as exc:
            logger.error("Plugin toolkit %s was skipped: %s", path, exc)
    return found
