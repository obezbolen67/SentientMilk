"""evals.py: a task's check commands run on Python, even in an installed SentientMilk."""

import sys

from sentientmilk_framework import evals


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
