"""Whether a tool call runs on its own, needs the user's approval, or is refused.

Rules come from the brain, the app and the session, and are checked like Claude
Code's: deny, then ask, then allow; the first match decides, otherwise the tool's
own default does. A rule is ``tool_glob`` or ``tool_glob(argument_glob)``, e.g.
``shell_run(git status*)``, ``files_edit(C:/work/**)``, ``mcp__github__*``.
Command patterns are a convenience, not a security boundary: path confinement is.
"""

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DECISIONS = (("deny", "off"), ("ask", "ask"), ("allow", "auto"))


def parse(rule: str) -> Tuple[str, Optional[str]]:
    rule = rule.strip()
    if rule.endswith(")") and "(" in rule:
        name, _, argument = rule[:-1].partition("(")
        return name.strip(), argument
    return rule, None


def merge(*levels: Optional[dict]) -> Dict[str, List[str]]:
    merged: Dict[str, List[str]] = {"allow": [], "ask": [], "deny": []}
    for level in levels:
        for kind in merged:
            merged[kind] += list((level or {}).get(kind, []))
    return merged


def argument_value(tool, arguments: dict, cwd: Optional[str]) -> str:
    if not tool.rule_arg:
        return ""
    value = str(arguments.get(tool.rule_arg, "") or "")
    if tool.rule_arg == "path":  # rules name absolute folders; the model may pass relative paths
        base = Path(cwd) if cwd else Path.cwd()
        value = (base / value).resolve().as_posix()
    return value


def decide(tool, arguments: dict, rules: Dict[str, List[str]], cwd: Optional[str] = None) -> str:
    value = argument_value(tool, arguments, cwd)
    for kind, decision in DECISIONS:
        for rule in rules.get(kind, []):
            name, pattern = parse(rule)
            if fnmatchcase(tool.name, name) and (pattern is None or fnmatchcase(value, pattern.replace("\\", "/"))):
                return decision
    return tool.policy


def removed(tool_name: str, rules: Dict[str, List[str]]) -> bool:
    """A bare deny rule takes the tool out of the model's tool list altogether."""
    return any(fnmatchcase(tool_name, name) for name, pattern in map(parse, rules.get("deny", []))
               if pattern is None)


def always_rule(tool, arguments: dict, cwd: Optional[str]) -> str:
    """The rule saved by "allow always": this tool with this exact argument, or the whole tool."""
    value = argument_value(tool, arguments, cwd)
    return f"{tool.name}({value})" if value else tool.name


def strictest(values: Iterable[str]) -> str:
    order = {"off": 0, "ask": 1, "auto": 2}
    return min(values, key=order.__getitem__, default="auto")
