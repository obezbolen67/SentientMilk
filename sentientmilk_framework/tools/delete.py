from pathlib import Path
import shutil

DESCRIPTION = """
Delete file or folder permanently.
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
}

def run(file):
    path = Path(file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError("File not found.")
    
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        ValueError("Specified object is not a folder or file.")
    return True