"""evals.py: a task's check commands run on Python, even in an installed SentientMilk."""

import json
import sys

from sentientmilk_framework import evals
from sentientmilk_framework.config import BrainConfig
from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider, tool_call


def test_checks_run_on_python_when_sentientmilk_runs_from_its_own_program(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SentientMilk.exe"))  # scripts/bundle.py's program
    ran = []
    monkeypatch.setattr(evals.subprocess, "run", lambda command, **_: ran.append(command) or
                        type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    evals._command("{python} check.py", tmp_path)
    assert ran == [f'"{runtime / "python.exe"}" check.py']


def test_a_task_checks_what_was_remembered_and_what_was_left_out(tmp_path):
    spec = {"check": {"memory_has": ["nurse"], "memory_lacks": ["dark mode"]}}
    kept = '{"user": {"job": "Works night shifts as a Nurse"}}'
    assert evals.check(spec, tmp_path, ["hi"], {"memory": kept}) == (True, "ok")
    trivia = '{"user": {"job": "nurse"}, "events": {"phone": "Turned on Dark Mode tonight"}}'
    assert evals.check(spec, tmp_path, ["hi"], {"memory": trivia})[0] is False
    assert evals.check(spec, tmp_path, ["hi"], {"memory": "{}"})[0] is False


def test_context_pair_runs_identical_coding_work_and_checks_files_after_two_compactions(tmp_path, monkeypatch):
    provider = FakeProvider().install(monkeypatch)
    original = '"""Tiny calculator: continuity-keep-7."""\n\ndef add(a, b):\n    return a + b\n'
    addition = "    return a + b\n"
    extended = addition + "\ndef subtract(a, b):\n    return a - b\n"
    turns = ["Create add and keep the marker.", "Add subtract without changing add.", "Verify without rewriting."]
    spec = {"name": "paired-code", "kind": "chat", "toolkits": ["files"], "turns": turns,
            "files": {"contract.txt": "keep-me\n"}, "check": {"file": "calculator.py", "checker_files": {
                "check_calc.py": "from pathlib import Path\nfrom calculator import add, subtract\n"
                "assert add(-2, 5) == 3\nassert subtract(0, -2) == 2\n"
                "assert Path('contract.txt').read_text() == 'keep-me\\n'\n"},
                "command": "{python} check_calc.py", "reply_contains": ["verified"]}}
    for compact in (False, True):
        provider.replies += [tool_call("files_write", {"path": "calculator.py", "content": original}), "Created."]
        if compact:
            provider.replies.append("You created add; preserve the marker and contract file.")
        provider.replies += [tool_call("files_edit", {"path": "calculator.py", "old": addition, "new": extended}),
                             "Added subtract."]
        if compact:
            provider.replies.append("You created both functions; only verification remains.")
        provider.replies.append("Verified.")
    source = tmp_path / "source"
    BrainConfig(source / "config.json").update({"api_key": "test", "base_url": PROVIDER_URL})
    monkeypatch.setattr(evals, "default_home", lambda: source)
    monkeypatch.setattr(evals, "load", lambda names: [spec])
    checked_files = []
    check = evals.check

    def inspect_files(specification, folder, replies, extra):
        checked_files.append((folder / "calculator.py").read_bytes())
        return check(specification, folder, replies, extra)

    monkeypatch.setattr(evals, "check", inspect_files)
    report = tmp_path / "paired.json"
    evals.main(["paired-code"], report=str(report), context_pair=True)
    results = json.loads(report.read_text(encoding="utf-8"))

    assert [result["name"] for result in results] == ["paired-code", "paired-code"]
    assert [result["mode"] for result in results] == ["baseline", "forced_compaction"]
    assert [result["compactions"] for result in results] == [0, 2]
    assert all(result["passed"] for result in results), results
    assert [result["mutating_tool_calls"] for result in results] == [2, 2]
    assert checked_files == [original.replace(addition, extended).encode()] * 2
    assert provider.replies == []


def test_cli_accepts_the_context_pair_flag(tmp_path, monkeypatch):
    from sentientmilk_framework import cli

    monkeypatch.setattr(evals, "main", lambda names, **kwargs: (names, kwargs))
    report = str(tmp_path / "paired.json")
    assert cli.main(["--home", str(tmp_path), "eval", "context-continuity", "--context-pair", "--report", report]) == (
        ["context-continuity"], {"model": "", "report": report, "context_pair": True})


def test_context_continuity_task_checker_enforces_original_contract_and_arithmetic(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")  # same-size edits must not reuse cached imports
    assert (evals.TASKS_DIR / "context-continuity.json").is_file(), "The continuity coding eval is missing"
    spec = evals.load(["context-continuity"])[0]
    evals._write(tmp_path, spec["files"])
    correct = '"""Tiny calculator: continuity-keep-7."""\n\ndef add(a, b):\n    return a + b\n' \
        '\ndef subtract(a, b):\n    return a - b\n'
    evals._write(tmp_path, {"calculator.py": correct})
    assert evals.check(spec, tmp_path, ["continuity-keep-7 verified"], {}) == (True, "ok")
    evals._write(tmp_path, {"calculator.py": correct.replace("return a - b", "return a + b")})
    assert evals.check(spec, tmp_path, ["continuity-keep-7 verified"], {})[0] is False
    evals._write(tmp_path, {"calculator.py": correct.replace("continuity-keep-7", "forgotten")})
    assert evals.check(spec, tmp_path, ["continuity-keep-7 verified"], {})[0] is False
    evals._write(tmp_path, {"calculator.py": correct, "contract.txt": "rewritten contract\n"})
    assert evals.check(spec, tmp_path, ["continuity-keep-7 verified"], {})[0] is False
