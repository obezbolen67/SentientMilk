import shutil
from pathlib import Path

DESCRIPTION = """
Delete file or folder permanently.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
}

def run(file):
    path = Path(file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        raise ValueError("Specified object is not a folder or file.")
    return True
