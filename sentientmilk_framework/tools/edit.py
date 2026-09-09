from pathlib import Path

DESCRIPTION = """
Edit file with upper line offset.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
    "content": "Content to write.",
    "offset1": "Upper line offset"
}

def run(file: str, content: str, offset1: int):
    offset1 = int(offset1)
    path = Path(file)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file, "r", encoding="utf-8") as f:
        buffer = f.readlines()

    if offset1 > len(buffer):
        raise Exception("Upper line offset out of bound. Re-read file.")
    content_lines = content.splitlines(keepends=True)
    if content and not content_lines:
        content_lines = [content]
    start = max(offset1, 1) - 1
    end = min(start + len(content_lines), len(buffer))
    buffer[start:end] = content_lines[: end - start]
    with open(file, "w", encoding="utf-8") as f:
        f.writelines(buffer)

    return "Done."
