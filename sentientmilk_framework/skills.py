"""Skills, as Claude has them: instructions for a kind of task, loaded only when a task needs them.

A skill is a folder with a SKILL.md, YAML frontmatter and then the instructions, plus any files they point to
(references, scripts, templates). Her prompt lists each skill's name and description (``prompt``); when a task
matches one she loads its instructions with skill_use, and reads or runs its other files only when they say to.
The user starts one with /name and arguments (a ``skill`` input item, see ``expand``).

Skills live in SentientMilk's ``skills`` folder, for every app; the ones shipped in ``assets/skills`` count
unless a skill of the user's has the same name. Folders are read again when they change, so a skill she writes
(with her file tools), edits or deletes counts from her next step.

Frontmatter, as Claude Code reads it: ``name`` (the folder's name: lowercase letters, numbers and hyphens, at
most 64), ``description`` (what it does and when to use it, at most 1024 characters; without one, the first
line of the instructions), ``argument-hint`` (shown with /name), ``disable-model-invocation`` (true: only the
user starts it), ``user-invocable`` (false: only she does). Other fields are allowed and ignored.
"""

import json
import re
import shlex
import shutil
import textwrap
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
NAME_CHARS, DESCRIPTION_CHARS = 64, 1024
LISTING_CHARS = 8_000  # descriptions past this are left out of her prompt; the names stay
ARGUMENT_CHARS = 10_000
BUILT_IN = Path(__file__).parent / "assets" / "skills"
TRUE, FALSE = {"true", "yes", "on", "1"}, {"false", "no", "off", "0"}
PLACEHOLDER = re.compile(r"\\\$|\$ARGUMENTS\[(\d+)\]|\$ARGUMENTS\b|\$(\d+)|\$\{(?:CLAUDE_)?SKILL_DIR\}")
XML_TAG = re.compile(r"<[^<>]+>")
PROMPT = """## SKILLS
Skills are your instructions for kinds of tasks. When a task matches a skill below, load it with skill_use before
you start, and follow it. Each is a folder with a SKILL.md: read its files with your file tools, and make or
change one by writing its SKILL.md (load skill-creator first). Your skills folder: {folder}
"""


@dataclass
class Skill:
    name: str
    folder: Path
    builtin: bool
    description: str = ""
    body: str = ""
    argument_hint: str = ""
    model: bool = True  # she may load it (disable-model-invocation is not true)
    user: bool = True  # the user may start it with /name (user-invocable is not false)
    error: str = ""

    def public(self) -> dict:
        return {"name": self.name, "description": self.description, "argument_hint": self.argument_hint,
                "model_invocable": self.model, "user_invocable": self.user, "builtin": self.builtin,
                "path": str(self.folder), "error": self.error}


# ============== Reading ==============

def frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """(fields, the instructions) of a SKILL.md: the YAML between a first line --- and the next one, as far as
    skills use it (key: value, plain or quoted, | and > blocks; nested values are kept as their text).
    Without a first line --- there are no fields."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        raise ValueError("its frontmatter has no closing --- line")
    block, fields, index = lines[1:end], {}, 0
    while index < len(block):
        line = block[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, colon, value = line.partition(":")
        if not colon or line[0] in " \t-":
            raise ValueError(f"its frontmatter line {line.strip()!r} is not key: value")
        nested = []
        while index < len(block) and (not block[index].strip() or block[index][0] in " \t-"):  # its nested lines
            nested.append(block[index])
            index += 1
        fields[key.strip()] = _value(value.strip(), nested)
    return fields, "\n".join(lines[end + 1:])


def _value(value: str, nested: List[str]) -> str:
    if value[:1] in ("|", ">"):
        if value[0] == "|":
            return textwrap.dedent("\n".join(nested)).strip()
        texts = [line.strip() for line in nested]
        return re.sub(r"[ ]*\n[ ]*", "\n", " ".join(t or "\n" for t in texts)).strip()
    if value.startswith('"'):
        try:
            return str(json.loads(value))
        except ValueError:
            return value.strip('"')
    if value.startswith("'") and value.endswith("'") and len(value) > 1:
        return value[1:-1].replace("''", "'")
    if not value:
        return "\n".join(nested).strip()
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _flag(fields: Dict[str, str], key: str, default: bool) -> bool:
    value = fields.get(key, "").strip().lower()
    if not value:
        return default
    if value not in TRUE | FALSE:
        raise ValueError(f"its {key} must be true or false, not {fields[key]!r}")
    return value in TRUE


def read(folder: Path, builtin: bool = False) -> Skill:
    """The skill in ``folder``; ``error`` says what is wrong with a broken one."""
    skill = Skill(folder.name, folder, builtin)
    try:
        fields, body = frontmatter((folder / "SKILL.md").read_text(encoding="utf-8-sig"))
        skill.model = not _flag(fields, "disable-model-invocation", False)
        skill.user = _flag(fields, "user-invocable", True)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        skill.error = f"SKILL.md does not read: {exc}"
        return skill
    skill.body = body.strip()
    first = next((line.lstrip("# ").strip() for line in skill.body.splitlines() if line.strip()), "")
    skill.description = " ".join(fields.get("description", "").split()) or first
    skill.argument_hint = " ".join(fields.get("argument-hint", "").split())
    skill.error = _problem(folder.name, fields.get("name", ""), skill)
    return skill


def _problem(folder: str, name: str, skill: Skill) -> str:
    if len(folder) > NAME_CHARS or not NAME.fullmatch(folder):
        return (f"its folder's name {folder!r} is its name: use 1-{NAME_CHARS} lowercase letters, numbers and "
                "hyphens, such as writing-reports")
    if name and name.strip() != folder:
        return f"its name {name.strip()!r} is not its folder's ({folder!r}): they must be the same"
    if not skill.description:
        return "it has no description: say what it does and when to use it"
    if len(skill.description) > DESCRIPTION_CHARS:
        return f"its description has {len(skill.description)} characters (at most {DESCRIPTION_CHARS})"
    if XML_TAG.search(skill.description):
        return "its description cannot hold XML tags (<...>)"
    if not skill.body:
        return "it has no instructions after its frontmatter"
    return ""


# ============== Using ==============

def render(skill: Skill, arguments: str = "") -> str:
    """The instructions with what the user or she passed: $ARGUMENTS (all of it), $0 or $ARGUMENTS[0] (the
    first word, "quoted words" as one), ${SKILL_DIR} (its folder; ${CLAUDE_SKILL_DIR} too, as skills written
    for Claude say), \\$ for a $. Arguments no placeholder took are added at the end."""
    arguments = arguments.strip()
    try:
        words = shlex.split(arguments)
    except ValueError:
        words = arguments.split()
    used = False

    def fill(match: re.Match) -> str:
        nonlocal used
        whole = match.group(0)
        if whole == "\\$":
            return "$"
        if whole.startswith("${"):
            return skill.folder.as_posix()
        number = match.group(1) or match.group(2)
        if number is None:
            used = True
            return arguments
        if int(number) < len(words):
            used = True
            return words[int(number)]
        return whole  # no such argument: as written
    text = PLACEHOLDER.sub(fill, skill.body)
    return text + (f"\n\nARGUMENTS: {arguments}" if arguments and not used else "")


def loaded(skill: Skill, arguments: str = "") -> str:
    """What the model reads when a skill starts: where its files are, then its instructions."""
    return f"Base directory for this skill: {skill.folder.as_posix()}\n\n{render(skill, arguments)}"


class Skills:
    """The skills folder (``folder``) and the shipped skills, read again as their SKILL.md files change."""

    def __init__(self, folder: Path, built_in: Path = BUILT_IN):
        self.folder, self.built_in = Path(folder), Path(built_in)
        self._read: Dict[Path, Tuple[tuple, Skill]] = {}
        self._lock = threading.Lock()

    def all(self) -> List[Skill]:
        """Every skill by name: the user's, and the shipped ones none of theirs replaces."""
        found: Dict[str, Skill] = {}
        for root, builtin in ((self.folder, False), (self.built_in, True)):
            try:
                folders = sorted(root.iterdir()) if root.is_dir() else []
            except OSError:
                continue
            for folder in folders:
                if folder.name not in found and (folder / "SKILL.md").is_file():
                    found[folder.name] = self._skill(folder, builtin)
        return sorted(found.values(), key=lambda skill: skill.name)

    def _skill(self, folder: Path, builtin: bool) -> Skill:
        try:
            stat = (folder / "SKILL.md").stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        with self._lock:
            cached = self._read.get(folder)
            if cached and stamp is not None and cached[0] == stamp:
                return cached[1]
        skill = read(folder, builtin)
        with self._lock:
            self._read[folder] = (stamp, skill)
        return skill

    def get(self, name: str) -> Optional[Skill]:
        return next((skill for skill in self.all() if skill.name == name), None)

    def public(self) -> List[dict]:
        return [skill.public() for skill in self.all()]

    def prompt(self) -> str:
        """Her prompt's SKILLS section: the skills she may load, each with its description while they fit."""
        lines, room = [], LISTING_CHARS
        for skill in self.all():
            if skill.error or not skill.model:
                continue
            line = f"- {skill.name}: {skill.description}"
            room -= len(line)
            lines.append(line if room >= 0 else f"- {skill.name}")  # shortcut: names only past the budget
        return PROMPT.format(folder=self.folder) + "\n".join(lines)

    def expand(self, items: List[dict]) -> List[dict]:
        """Turn input with each skill the user started (``skill`` items) as the text the model reads."""
        result = []
        for item in items:
            if item["type"] != "skill" or "text" in item:
                result.append(item)
                continue
            name, arguments = item["name"], item.get("arguments", "")
            skill = self.get(name)
            started = f"[The user started the skill /{name}" + (f" with: {arguments}]" if arguments else "]")
            if skill is None:
                text = f"{started}\nThere is no such skill (any more): tell the user."
            elif skill.error:
                text = f"{started}\nIt is broken ({skill.error}): tell the user, or fix {skill.folder / 'SKILL.md'}."
            else:
                text = f"{started}\n{loaded(skill, arguments)}"
            result.append({**item, "text": text})
        return result

    def status(self, path: Path) -> str:
        """After a file in the skills folder changed: how that skill reads now ('' for a file elsewhere)."""
        try:
            relative = Path(path).resolve().relative_to(self.folder.resolve())
        except (OSError, ValueError):
            return ""
        if len(relative.parts) < 2:
            return "A skill is a folder in the skills folder, with its SKILL.md: a file right in it is no skill."
        folder = self.folder / relative.parts[0]
        if not (folder / "SKILL.md").is_file():
            return f"The skill {relative.parts[0]} has no SKILL.md yet: it counts once it has one."
        skill = self._skill(folder, False)
        if skill.error:
            return f"The skill {skill.name} is broken: {skill.error}. Fix its SKILL.md."
        who = "only the user starts it" if not skill.model else "listed in SKILLS from your next step"
        return f"The skill {skill.name} reads well ({who})."

    def remove(self, name: str) -> None:
        """Delete one of the user's skills, its whole folder."""
        skill = self.get(name)
        if skill is None:
            raise ValueError(f"There is no skill {name}")
        if skill.builtin:
            raise ValueError(f"{name} comes with SentientMilk: it cannot be removed. A skill of the same name in "
                             f"{self.folder} replaces it.")
        shutil.rmtree(skill.folder)
