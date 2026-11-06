"""Signals: structured values an app wants next to each reply, such as a character's expression.

The model starts its final reply with one line holding only a JSON object of signals,
then writes the reply as plain text. Measured on the default model: 4/4 fresh, 4/4 after
plain-text history with a screenshot, 2/2 with a code answer; the reminder in the newest
user message is what keeps it reliable (see FORMAT_REMINDER).
"""

import json
from typing import Callable, Dict, List, Optional, Tuple

SILENT = "[silent]"
FORMAT_REMINDER = "Start your final reply with the signals JSON line described in OUTPUT FORMAT."
OPTIONAL_REPLY = (f"A reply is optional this time: if you have nothing worth saying, answer with only {SILENT}"
                  " (after the signals line, if you use one).")


def validate(declared) -> Dict[str, dict]:
    """``{name: {"description"?, "options": [..] or {group: [..]}}}``; grouped options become group/option."""
    if not isinstance(declared, dict):
        raise ValueError("signals must be an object")
    result = {}
    for name, spec in declared.items():
        if not isinstance(spec, dict) or "options" not in spec:
            raise ValueError(f"signals.{name} needs options")
        options = spec["options"]
        if isinstance(options, dict):
            if not all(isinstance(v, list) and v and all(isinstance(o, str) and o for o in v)
                       for v in options.values()):
                raise ValueError(f"signals.{name}.options groups must be non-empty lists of names")
            flat = [f"{group}/{option}" for group, values in options.items() for option in values]
        elif isinstance(options, list) and options and all(isinstance(o, str) and o for o in options):
            flat = list(options)
        else:
            raise ValueError(f"signals.{name}.options must be a non-empty list or {{group: [options]}}")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"signals.{name}.description must be a string")
        result[name] = {"description": description, "options": flat,
                        "groups": options if isinstance(options, dict) else None}
    return result


def prompt_section(signals: Dict[str, dict]) -> str:
    example = json.dumps({name: f"<{name}>" for name in signals})
    lines = ["## OUTPUT FORMAT (every final reply)",
             "Start your final reply with one line that holds only a JSON object with your signals, then",
             "write what you say as normal text on the next lines:", example, "<what you say>", ""]
    for name, spec in signals.items():
        lines.append(f"{name}: {spec['description']}".rstrip(": ") if spec["description"] else f"{name}:")
        if spec["groups"]:
            lines.append("  Values are <group>/<option>. Options per group:")
            lines += [f"  {group}: {', '.join(options)}" for group, options in spec["groups"].items()]
        else:
            lines.append(f"  One of: {', '.join(spec['options'])}")
    lines += ["", "Pick values that match what you say. When you need tools, call them first as usual;",
              "only the final reply has this form."]
    return "\n".join(lines)


def split(text: str) -> Tuple[Optional[dict], str]:
    """The signals header (if the reply starts with one) and the reply without it."""
    stripped = text.lstrip()
    if stripped.startswith("```"):  # a fenced header: ```json\n{...}\n```\nreply
        fence_end = stripped.find("```", 3)
        inner = stripped[3:fence_end].strip() if fence_end > 0 else ""
        inner = inner[4:].strip() if inner.startswith("json") else inner
        header = _object(inner)
        if header is not None:
            return header, stripped[fence_end + 3:].strip()
    first, _, rest = stripped.partition("\n")
    header = _object(first.strip())
    if header is None:
        return None, text.strip()
    return header, rest.strip()


def _object(text: str) -> Optional[dict]:
    if not text.startswith("{"):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def check(header: Optional[dict], signals: Dict[str, dict]) -> Tuple[Dict[str, str], List[str]]:
    """Valid values, and what was wrong (told to the model on its next turn)."""
    if header is None:
        return {}, ["Your last reply did not start with the signals JSON line."]
    values, problems = {}, []
    for name, spec in signals.items():
        value = header.get(name)
        if value in spec["options"]:
            values[name] = value
        elif value is None:
            problems.append(f"Signal '{name}' was missing.")
        else:
            problems.append(f"Signal {name}={value!r} is not one of the listed options.")
    return values, problems


def is_silent(reply: str) -> bool:
    return reply.strip() in ("", SILENT)


class HeaderStream:
    """Splits streamed text: the header line goes to ``on_signals``, the rest to ``on_text``."""

    def __init__(self, on_signals: Callable[[dict], None], on_text: Callable[[str], None]):
        self.on_signals, self.on_text = on_signals, on_text
        self.buffer, self.decided = "", False

    def feed(self, delta: str) -> None:
        if self.decided:
            self.on_text(delta)
            return
        self.buffer += delta
        head = self.buffer.lstrip()
        if not head:
            return
        if not head.startswith(("{", "`")):
            self._release(self.buffer)
        elif "\n" in head and not head.startswith("`"):
            line, _, rest = head.partition("\n")
            header = _object(line.strip())
            if header is None:
                self._release(self.buffer)
            else:
                self.on_signals(header)
                self._release(rest.lstrip("\n"))
        elif head.startswith("```") and head.count("```") >= 2 and "\n" in head[head.rfind("```"):]:
            header, rest = split(head)
            if header is not None:
                self.on_signals(header)
            self._release(rest if header is not None else self.buffer)

    def _release(self, text: str) -> None:
        self.decided = True
        if text:
            self.on_text(text)

    def reset(self) -> None:
        """A new model message starts (the previous one ended in tool calls)."""
        self.buffer, self.decided = "", False
