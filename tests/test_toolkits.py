import time
from types import SimpleNamespace

import pytest
import requests
from conftest import wait_for

from sentientmilk_framework import permissions
from sentientmilk_framework.toolkits import RESULT_CAP, ToolContext, ToolError, cap, files, shell, todo, web
from sentientmilk_framework.toolkits import memory as memory_kit


@pytest.fixture
def ctx(brain):
    run_id = brain.store.add_run("cli", "main", "turn", {}, status="working")
    profile = brain.brain.profile("cli", "main")
    return ToolContext(brain.brain, brain.store.run(run_id), profile, "call-1")


def test_reading_comes_in_numbered_windows(brain, ctx):
    (brain.work / "long.txt").write_text("\n".join(f"line {n}" for n in range(1, 1201)), encoding="utf-8")
    first = files.files_read.func(ctx, "long.txt")
    assert first.startswith("     1\tline 1") and "[Lines 1-500 of 1200. Continue with offset=501.]" in first
    later = files.files_read.func(ctx, "long.txt", offset=1190, limit=50)
    assert later.splitlines()[0] == "  1190\tline 1190" and later.endswith("[Lines 1190-1200 of 1200.]")
    assert "a" in files.files_read.func(ctx, ".")


def test_edits_need_a_fresh_read_and_a_unique_match(brain, ctx):
    path = brain.work / "app.py"
    path.write_text("x = 1\ny = 1\n", encoding="utf-8")
    with pytest.raises(ToolError, match="Read"):
        files.files_edit.func(ctx, "app.py", "x = 1", "x = 2")
    files.files_read.func(ctx, "app.py")
    with pytest.raises(ToolError, match="2 times"):
        files.files_edit.func(ctx, "app.py", "= 1", "= 2")
    result = files.files_edit.func(ctx, "app.py", "x = 1", "x = 2")
    assert "     1\tx = 2" in result and path.read_text() == "x = 2\ny = 1\n"
    path.write_text("changed elsewhere\n", encoding="utf-8")
    import os
    os.utime(path, ns=(1, 1))
    with pytest.raises(ToolError, match="changed since"):
        files.files_edit.func(ctx, "app.py", "changed", "again")


def test_edits_that_break_syntax_are_refused_and_nothing_changes(brain, ctx):
    path = brain.work / "ok.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    files.files_read.func(ctx, "ok.py")
    with pytest.raises(ToolError, match="invalid") as caught:
        files.files_edit.func(ctx, "ok.py", "return 1", "return (1")
    assert "line" in str(caught.value) and path.read_text() == "def f():\n    return 1\n"
    with pytest.raises(ToolError, match="invalid"):
        files.files_write.func(ctx, "new.json", "{not json")
    assert not (brain.work / "new.json").exists()
    assert "Wrote" in files.files_write.func(ctx, "new.json", '{"a": 1}')


def test_paths_outside_the_open_folders_are_refused(brain, ctx, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("no", encoding="utf-8")
    for call in (lambda: files.files_read.func(ctx, str(secret)), lambda: files.files_read.func(ctx, "../secret.txt"),
                 lambda: files.files_write.func(ctx, "../evil.txt", "x")):
        with pytest.raises(ToolError, match="outside the folders"):
            call()


def test_search_lists_every_match_and_find_globs(brain, ctx, monkeypatch):
    (brain.work / "src").mkdir()
    (brain.work / "src" / "a.py").write_text("import os\nTODO: fix\n", encoding="utf-8")
    (brain.work / "src" / "b.py").write_text("todo later\n", encoding="utf-8")
    (brain.work / ".git").mkdir()
    (brain.work / ".git" / "x").write_text("TODO hidden", encoding="utf-8")
    monkeypatch.setattr(files.shutil, "which", lambda name: None)  # the pure Python search
    found = files.files_search.func(ctx, "todo", ignore_case=True)
    assert found.splitlines() == ["src\\a.py:2: TODO: fix" if "\\" in found else "src/a.py:2: TODO: fix",
                                  "src\\b.py:1: todo later" if "\\" in found else "src/b.py:1: todo later"]
    assert "a.py" in files.files_find.func(ctx, "**/*.py")
    with pytest.raises(ToolError, match="Bad regular expression"):
        files.files_search.func(ctx, "foo(")


def test_big_results_are_saved_and_both_ends_kept(brain, ctx):
    text = "start " + "x" * (RESULT_CAP * 2) + " end"
    shown = cap(ctx, text)
    assert shown.startswith("start ") and shown.endswith(" end") and len(shown) < RESULT_CAP
    saved = shown.split("is saved in ", 1)[1].split(". ", 1)[0]
    assert open(saved, encoding="utf-8").read() == text
    assert "start" in files.files_read.func(ctx, saved, limit=1)  # saved outputs stay readable


def test_a_search_without_ripgrep_stops_in_time_and_says_so(brain, ctx, monkeypatch):
    for index in range(3):
        (brain.work / f"note{index}.txt").write_text("needle here\n", encoding="utf-8")
    monkeypatch.setattr(files.shutil, "which", lambda name: None)
    assert files.files_search.func(ctx, "needle").count("needle here") == 3
    monkeypatch.setattr(files, "SEARCH_SECONDS", -1)  # out of time at once
    assert "Stopped after -1 s and 0 files" in files.files_search.func(ctx, "needle")


def test_shell_runs_with_exit_codes_and_slow_commands_go_on_as_jobs(brain, ctx):
    assert shell.shell_run.func(ctx, "echo hello").startswith("[exit code 0]\nhello")
    assert "[exit code 3]" in shell.shell_run.func(ctx, "exit 3")
    assert not list(ctx.run_dir().glob("job-*.log"))  # finished commands leave no log behind
    slow = ("Write-Output begun; Start-Sleep -Seconds 4; Write-Output ended" if shell.shell_name("") == "powershell"
            else "echo begun; sleep 4; echo ended")
    started = time.time()
    result = shell.shell_run.func(ctx, slow, timeout=1)
    assert time.time() - started < 4  # the model gets control back; nothing is stopped
    assert "goes on as background job" in result
    job = int(result.split("background job ", 1)[1].split(".", 1)[0])
    assert "is running" in shell.shell_output.func(ctx, job)
    waited = shell.shell_output.func(ctx, job, wait=30)  # returns when the job ends, not after 30 s
    assert "begun" in waited and "ended" in waited and "finished, exit code 0" in waited
    assert time.time() - started < 15
    notes = brain.store.events("cli", "main", types=("note",))
    assert f"Background job {job} finished with exit code 0" in notes[-1]["text"]


def test_background_jobs_report_when_they_end(brain, ctx):
    started = shell.shell_run.func(ctx, "echo working", background=True)
    job = int(started.split()[2].rstrip("."))
    wait_for(lambda: brain.store.job(job)["status"] == "finished", 30)
    assert "working" in shell.shell_output.func(ctx, job)
    # the job is marked finished first, then noted and announced
    assert wait_for(lambda: brain.store.notifications("cli"))[-1]["type"] == "job.finished"
    notes = brain.store.events("cli", "main", types=("note",))
    assert f"Background job {job} finished with exit code 0" in notes[-1]["text"]


def test_web_pages_become_text_and_search_needs_a_key(brain, ctx, monkeypatch):
    html = (b"<html><head><title>Hi</title><script>var x=1</script></head>"
            b"<body><h1>Title</h1><p>First &amp; second</p></body></html>")

    def get(url, **kwargs):
        raw = SimpleNamespace(read=lambda n, decode_content=True: html)
        return SimpleNamespace(raw=raw, status_code=200, headers={"Content-Type": "text/html"}, encoding="utf-8",
                               url=url, close=lambda: None)

    monkeypatch.setattr(requests, "get", get)
    page = web.web_fetch.func(ctx, "https://example.com/")
    assert page.startswith("Hi\nhttps://example.com/") and "First & second" in page and "var x" not in page
    with pytest.raises(ToolError, match="web_search_key"):
        web.web_search.func(ctx, "news")


def test_todo_and_memory_belong_to_their_session_and_app(brain, ctx):
    shown = todo.todo_write.func(ctx, [{"text": "plan", "status": "done"}, {"text": "build", "status": "doing"}])
    assert shown == "1. [x] plan\n2. [>] build"
    assert brain.store.session("cli", "main")["state"]["todo"][1] == {"text": "build", "status": "doing"}
    memory_kit.memory_save.func(ctx, "user", "name", "Tester")
    assert memory_kit.memory_get.func(ctx, "user", "name") == "Tester"
    assert brain.store.memories("milk") == {}


def test_permission_rules_deny_then_ask_then_allow():
    tool = SimpleNamespace(name="shell_run", rule_arg="command", policy="ask")
    rules = permissions.merge({"allow": ["shell_run(git *)"]}, {"deny": ["shell_run(git push*)"]})
    assert permissions.decide(tool, {"command": "git status"}, rules) == "auto"
    assert permissions.decide(tool, {"command": "git push origin"}, rules) == "off"
    assert permissions.decide(tool, {"command": "rm -rf /"}, rules) == "ask"
    edit = SimpleNamespace(name="files_edit", rule_arg="path", policy="ask")
    assert permissions.decide(edit, {"path": "src/a.py"}, {"allow": ["files_edit(C:/work/**)"]}, cwd="C:/work") == "auto"
    assert permissions.removed("mcp__github__push", {"deny": ["mcp__github__*"]})
    assert not permissions.removed("shell_run", {"deny": ["shell_run(rm *)"]})
