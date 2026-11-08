"""Files: read, search, find, edit and write, inside the folders the app opened to the brain."""

import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from . import ToolContext, ToolError, Toolkit, ToolResult, cap, tool

READ_LINES = 500
LINE_CUT = 2000
SEARCH_LIMIT = 200
FIND_LIMIT = 300
SKIPPED_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
                ".pytest_cache", ".ruff_cache", ".tox"}
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".webp": "image/webp", ".bmp": "image/bmp"}


def roots(ctx: ToolContext) -> List[Path]:
    return [Path(root).resolve() for root in ctx.profile.get("roots", [])]


def cwd(ctx: ToolContext) -> Path:
    if ctx.profile.get("cwd"):
        return Path(ctx.profile["cwd"])
    found = roots(ctx)
    return found[0] if found else ctx.run_dir()


def _inside(path: Path, root: Path) -> bool:
    path_text, root_text = os.path.normcase(str(path)), os.path.normcase(str(root)).rstrip("\\/")
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def closed(home, path: Path) -> bool:
    """Inside SentientMilk's own folder (its settings and keys, plugin trust, the server's token), which no
    file tool opens nor a mention shows; the saved outputs in its runs folder are the exception."""
    home = Path(home).resolve()
    return _inside(path, home) and not _inside(path, home / "runs")


def private(ctx: ToolContext, path: Path) -> bool:
    return closed(ctx.brain.home, path)


def _hidden(ctx: ToolContext, path: Path) -> bool:
    """Left out of a search: SentientMilk's own folder, and a link Windows will not follow (an untrusted mount
    point) or a folder it will not open, which cannot be checked for being SentientMilk's own."""
    try:
        return private(ctx, path.resolve())
    except OSError:
        return True


def resolve(ctx: ToolContext, path: str, write: bool = False) -> Path:
    if not path or not isinstance(path, str):
        raise ToolError("path is required, e.g. path='src/app.py'")
    target = (cwd(ctx) / Path(path).expanduser()).resolve()
    if private(ctx, target):
        raise ToolError(f"{target} is in SentientMilk's own folder (its settings, keys and plugins): the file tools "
                        "cannot open it. Write plugins in a folder of your own and install them with plugin_install.")
    allowed = roots(ctx) + [ctx.run_dir()]
    if not write:
        allowed.append(ctx.brain.home / "runs")  # saved tool outputs
    if not any(_inside(target, root) for root in allowed):
        opened = ", ".join(str(root) for root in roots(ctx)) or "none"
        raise ToolError(f"{target} is outside the folders open to you here (opened: {opened}).")
    return target


def _remember_read(ctx: ToolContext, path: Path) -> None:
    mtime = path.stat().st_mtime_ns

    def change(state):
        state.setdefault("read", {})[path.as_posix()] = mtime
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)


def _check_fresh(ctx: ToolContext, path: Path) -> None:
    """Edits need a current read: the model must have seen what it changes."""
    seen = ctx.store.session(ctx.app, ctx.session)["state"].get("read", {}).get(path.as_posix())
    if seen is None:
        raise ToolError(f"Read {path} with files_read before changing it.")
    if seen != path.stat().st_mtime_ns:
        raise ToolError(f"{path} changed since you read it. Read it again, then retry.")


def syntax_problem(path: Path, text: str) -> Optional[str]:
    """Why ``text`` is not valid for the file's type, or None; unknown types always pass."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".py":
            compile(text, str(path), "exec", dont_inherit=True)
        elif suffix == ".json":
            json.loads(text)
        elif suffix == ".toml":
            import tomllib

            tomllib.loads(text)
    except SyntaxError as exc:
        lines = text.splitlines()
        line = exc.lineno or 1
        around = "\n".join(f"{n:>6}\t{lines[n - 1]}" for n in range(max(1, line - 3), min(len(lines), line + 3) + 1))
        return f"{exc.msg} at line {line}:\n{around}"
    except ImportError:
        return None  # tomllib needs Python 3.11
    except ValueError as exc:
        return str(exc)
    return None


def _keep_version(ctx: ToolContext, path: Path) -> None:
    """The file as it is before its first change since the session's latest message: returning to a message
    (rewind.py) brings it back. An agent's or a task's versions belong to the chat they work for."""
    chat = (ctx.run["options"].get("profile") or {}).get("from_session") or ctx.session
    ctx.store.keep_version(ctx.app, chat, ctx.session, ctx.run["id"], ctx.run["created"], str(path),
                           lambda: path.read_bytes() if path.is_file() else None)


def _write_checked(path: Path, text: str, old: Optional[str]) -> None:
    """Refuse content that breaks a file which parsed before (or a new file that does not parse)."""
    problem = syntax_problem(path, text)
    if problem and (old is None or syntax_problem(path, old) is None):
        raise ToolError(f"Not saved: the change would make {path.name} invalid. {problem}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as output:
        output.write(text)


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as source:
        return source.read()


def _snippet(text: str, index: int, length: int) -> str:
    lines = text.splitlines()
    first = text.count("\n", 0, index) + 1
    last = first + text.count("\n", index, index + length)
    return "\n".join(f"{n:>6}\t{lines[n - 1][:LINE_CUT]}"
                     for n in range(max(1, first - 3), min(len(lines), last + 3) + 1))


@tool(core=True, readonly=True, rule_arg="path", args={
    "path": "File or folder, absolute or relative to the working folder.",
    "offset": "First line to show, from 1.", "limit": f"Lines to show (default {READ_LINES})."})
def files_read(ctx: ToolContext, path: str, offset: int = 1, limit: int = READ_LINES):
    """Read a text file with line numbers, a window at a time; a folder lists its entries; an image is shown
    to you. Use offset and limit to page through long files. Always read a file before you edit it."""
    target = resolve(ctx, path)
    if target.is_dir():
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        listed = [entry.name + ("/" if entry.is_dir() else "") for entry in entries[:FIND_LIMIT]]
        more = f"\n[{len(entries) - FIND_LIMIT} more entries]" if len(entries) > FIND_LIMIT else ""
        return f"{target}:\n" + "\n".join(listed) + more
    if not target.exists():
        raise ToolError(f"{target} does not exist. Find files with files_find.")
    if target.suffix.lower() in IMAGES:
        from .. import transport

        data = base64.b64encode(target.read_bytes()).decode("ascii")
        url = transport.encode_image(f"data:{IMAGES[target.suffix.lower()]};base64,{data}", transport.IMAGE)
        _remember_read(ctx, target)
        return ToolResult(f"{target} is an image; it is attached below.", [url])
    with open(target, "rb") as source:
        if b"\0" in source.read(8192):
            return f"{target} is a binary file ({target.stat().st_size:,} bytes); it cannot be shown as text."
    lines = _read_text(target).splitlines()
    start = max(1, int(offset or 1))
    end = min(len(lines), start + max(1, int(limit or READ_LINES)) - 1)
    shown = [f"{n:>6}\t{line[:LINE_CUT]}{' [line cut]' if len(line) > LINE_CUT else ''}"
             for n, line in zip(range(start, end + 1), lines[start - 1:end])]
    _remember_read(ctx, target)
    if not lines:
        return f"{target} is empty."
    footer = "" if start == 1 and end == len(lines) else \
        f"\n[Lines {start}-{end} of {len(lines)}." + (f" Continue with offset={end + 1}.]" if end < len(lines) else "]")
    return cap(ctx, "\n".join(shown) + footer)


SEARCH_SECONDS = 30  # without ripgrep a search walks in Python; a whole home folder would take many minutes


def _walk(ctx: ToolContext, base: Path):
    for folder, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS and not _hidden(ctx, Path(folder, d)))
        for name in sorted(names):
            yield Path(folder) / name


@tool(core=True, readonly=True, rule_arg="path", args={
    "pattern": "Regular expression (Python/ripgrep syntax).", "path": "Folder or file to search (default: working folder).",
    "glob": "Only files matching this glob, e.g. '*.py'.", "ignore_case": "Match case-insensitively."})
def files_search(ctx: ToolContext, pattern: str, path: str = ".", glob: str = "", ignore_case: bool = False):
    """Search file contents for a regular expression. Returns every match as path:line: text (up to 200),
    so you can go straight to files_read with an offset. Skips .git, virtualenvs and caches."""
    base = resolve(ctx, path)
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ToolError(f"Bad regular expression: {exc}. Escape special characters, e.g. 'foo\\(' for 'foo('.")
    matches: List[str] = []
    total, searched, stopped = 0, 0, False
    rg = shutil.which("rg")
    if rg:
        command = [rg, "--line-number", "--no-heading", "--color", "never", "--max-columns", "300"]
        command += (["-i"] if ignore_case else []) + (["--glob", glob] if glob else []) + ["-e", pattern, str(base)]
        output = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=60).stdout.splitlines()
        home = os.path.normcase(str(Path(ctx.brain.home).resolve()))  # ripgrep skips hidden folders, not others
        output = [line for line in output if not os.path.normcase(line).startswith(home)]
        total = len(output)
        matches = [_relative(ctx, line) for line in output[:SEARCH_LIMIT]]
    else:
        files = [base] if base.is_file() else _walk(ctx, base)
        deadline = time.monotonic() + SEARCH_SECONDS
        for file in files:
            if time.monotonic() > deadline:
                stopped = True
                break
            if glob and not file.match(glob):
                continue
            searched += 1
            try:
                if file.stat().st_size > 2_000_000:
                    continue
                with open(file, "rb") as source:
                    if b"\0" in source.read(8192):
                        continue
                text = _read_text(file)
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    total += 1
                    if len(matches) < SEARCH_LIMIT:
                        matches.append(f"{_relative(ctx, str(file))}:{number}: {line.strip()[:300]}")
    partial = (f"\n[Stopped after {SEARCH_SECONDS} s and {searched} files; narrow the path or glob to search "
               "the rest.]") if stopped else ""
    if not matches:
        return f"No matches for {pattern!r} in {base}." + partial
    more = f"\n[Showing {SEARCH_LIMIT} of {total} matches; narrow the pattern, path or glob.]" \
        if total > SEARCH_LIMIT else ""
    return cap(ctx, "\n".join(matches) + more + partial)


def _relative(ctx: ToolContext, text: str) -> str:
    base = str(cwd(ctx))
    return text[len(base):].lstrip("\\/") if os.path.normcase(text).startswith(os.path.normcase(base)) else text


@tool(readonly=True, rule_arg="path", args={
    "pattern": "Glob such as '**/*.py' or 'src/*.json'.", "path": "Folder to search from (default: working folder)."})
def files_find(ctx: ToolContext, pattern: str, path: str = "."):
    """Find files by name with a glob pattern. Newest first, up to 300."""
    base = resolve(ctx, path)
    found = [p for p in base.glob(pattern) if p.is_file() and not SKIPPED_DIRS.intersection(p.relative_to(base).parts)
             and not _hidden(ctx, p)]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not found:
        return f"No files match {pattern!r} under {base}."
    more = f"\n[{len(found) - FIND_LIMIT} more; use a narrower pattern.]" if len(found) > FIND_LIMIT else ""
    return "\n".join(_relative(ctx, str(p)) for p in found[:FIND_LIMIT]) + more


@tool(rule_arg="path", args={
    "path": "The file to change.", "old": "Exact text to replace, including indentation; must be unique unless all=true.",
    "new": "The replacement text.", "all": "Replace every occurrence instead of exactly one."})
def files_edit(ctx: ToolContext, path: str, old: str, new: str, all: bool = False):
    """Replace exact text in a file you have read. Include enough surrounding lines in old to make it unique.
    Edits that would break the syntax of a .py, .json or .toml file are refused and nothing changes."""
    target = resolve(ctx, path, write=True)
    if not target.is_file():
        raise ToolError(f"{target} does not exist; create it with files_write.")
    _check_fresh(ctx, target)
    if old == new:
        raise ToolError("old and new are the same; nothing to change.")
    text = _read_text(target)
    count = text.count(old) if old else 0
    if count == 0:
        raise ToolError("old was not found. Copy it exactly from files_read output, without the line numbers.")
    if count > 1 and not all:
        raise ToolError(f"old occurs {count} times. Add surrounding lines to make it unique, or set all=true.")
    index = text.index(old)
    updated = text.replace(old, new) if all else text.replace(old, new, 1)
    _keep_version(ctx, target)
    _write_checked(target, updated, text)
    _remember_read(ctx, target)
    return f"Edited {target} ({count if all else 1} replacement{'s' if all and count > 1 else ''}):\n" + \
        _snippet(updated, index, len(new))


@tool(rule_arg="path", args={"path": "The file to create or overwrite.", "content": "The complete new content."})
def files_write(ctx: ToolContext, path: str, content: str):
    """Create a file, or overwrite one you have read. Prefer files_edit for changes to existing files."""
    target = resolve(ctx, path, write=True)
    old = None
    if target.exists():
        if target.is_dir():
            raise ToolError(f"{target} is a folder.")
        _check_fresh(ctx, target)
        old = _read_text(target)
    _keep_version(ctx, target)
    _write_checked(target, content, old)
    _remember_read(ctx, target)
    return f"Wrote {target} ({content.count(chr(10)) + (1 if content and not content.endswith(chr(10)) else 0)} lines)."


TOOLKIT = Toolkit("files", "Read, search and change files in the folders opened to you.",
                  [files_read, files_search, files_find, files_edit, files_write])
