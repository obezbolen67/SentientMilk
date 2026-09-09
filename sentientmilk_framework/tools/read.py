DESCRIPTION = """
Read UTF-8 text without truncation. Offset is 1-based; zero limit reads to EOF.
Default output has one metadata header and exact text; numbered=True labels each line.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
    "offset": "Upper offset by lines.",
    "limit": "lines limit",
    "numbered": "Add per-line labels (more tokens); default false preserves raw text."
}

def run(file: str, offset: int = 0, limit: int = 0, numbered: bool = False):
    offset = int(offset or 0)
    limit = int(limit or 0)
    with open(file, "r", encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    start = max(offset, 1) - 1
    if start >= len(lines) and (lines or start):
        raise ValueError("Offset is bigger than total lines in file")
    selected = lines[start:] if limit <= 0 else lines[start:start + limit]
    if numbered:
        return "".join(f"[Ln {start + index + 1}] {line}" for index, line in enumerate(selected))
    return f"File: {file} | start_line: {start + 1} | lines: {len(selected)}\n" + "".join(selected)
