DESCRIPTION = "Replace one exact, unique text block in a UTF-8 file. Preserves newline bytes. Fails without changing the file if the match is absent or ambiguous."
ARGS_DESCRIPTION = {"file": "File path", "old": "Exact nonempty text to match once", "new": "Replacement text"}


def run(file: str, old: str, new: str):
    with open(file, encoding="utf-8", newline="") as handle:
        text = handle.read()
    if not old or text.count(old) != 1:
        raise ValueError("Expected exactly one nonempty match; read current content and include more context")
    with open(file, "w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace(old, new, 1))
    return {"file": file, "replacements": 1}
