from sentientmilk_framework.tools import read

DESCRIPTION = "Read multiple independent UTF-8 files in one call. Returns full content or an error for each path, in input order."
ARGS_DESCRIPTION = {"files": "Paths to read completely. For line ranges use read."}


def run(files: list[str]):
    results = []
    for file in files:
        try:
            results.append({"file": file, "content": read.run(file)})
        except Exception as error:
            results.append({"file": file, "error": str(error), "type": type(error).__name__})
    return results
