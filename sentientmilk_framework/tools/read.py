from pathlib import Path

DESCRIPTION = """
Read file with upper offset, and characters limit. Set values to 0 to read all content..
"""

ARGS_DESCRIPTION = {
    "file": "Path to a file. Could be either full path or from CWD.",
    "offset": "Upper offset by lines.",
    "limit": "lines limit"
}

def run(file, offset=0, limit=0):
    line_count = 1
    lines = []
    content = ""
    with open(file, "r") as f:
        lines = f.readlines()
    
    f.close()

    if len(lines) >= offset:
        for line in lines:
            if line_count >= offset:
                content+=f"[Ln {line_count}] {line}"

            if line_count == limit:
                break
            line_count += 1
        
        print(content)
        return content
    else:
        raise Exception("Offset is bigger than total lines in file")