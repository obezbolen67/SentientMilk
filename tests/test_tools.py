from pathlib import Path

from sentientmilk_framework import LLM, Settings
from sentientmilk_framework.tools import delete, edit, read


def make_llm(tmp_path: Path) -> LLM:
    return LLM(
        api_key="test",
        base_url="https://example.invalid/v1",
        model="test-model",
        settings=Settings(custom_tools_path=tmp_path / "missing"),
    )


def test_tool_schema_preserves_numeric_and_boolean_types(tmp_path):
    schemas = {
        tool["function"]["name"]: tool["function"]["parameters"]
        for tool in make_llm(tmp_path).get_all_tools()
    }

    assert schemas["read"]["properties"]["offset"]["type"] == "integer"
    assert schemas["exec"]["properties"]["timeout"]["type"] == "integer"
    assert schemas["exec"]["properties"]["settle_time"]["type"] == "number"
    assert schemas["web_search"]["properties"]["summary"]["type"] == "boolean"


def test_file_tools_accept_model_supplied_string_offsets(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"one\ntwo\nthree\n")

    assert read.run(str(path), offset="2", limit="1", numbered=True) == "[Ln 2] two\n"
    assert edit.run(str(path), "changed\n", offset1="2") == "Done."
    assert path.read_text(encoding="utf-8") == "one\nchanged\nthree\n"


def test_delete_reports_a_missing_target(tmp_path):
    missing = tmp_path / "does-not-exist"

    try:
        delete.run(str(missing))
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing delete target was reported as successful")
