from pathlib import Path

DESCRIPTION = """
Write a new file by specified path. Also allows to create empty files.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
    "content": "Optional argument to write content to a file."
}

def run(file, content=""):
    path = Path(file)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(file, "w") as f:
        f.write(content)
    f.close()
    return "Success."