from pathlib import Path

DESCRIPTION = """
Edit file with upper line offset.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
    "content": "Content to write.",
    "offset1": "Upper line offset"
}

def run(file, content, offset1):
    path = Path(file)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    buffer = []
    with open(file, "r") as f:
        buffer = f.readlines()
    f.close()

    if offset1 > len(buffer):
        raise Exception("Upper line offset out of bound. Re-read file.")
    content_lines = content.split("\n")

    current_line = offset1-1
    for line in buffer[(offset1-1):]:
        if len(content_lines) == 0:
            break
        buffer[current_line] = content_lines[0]
        content_lines.pop(0)
        current_line += 1
    with open(file, "w") as f:
        f.writelines(buffer)
    f.close()

    return "Done."