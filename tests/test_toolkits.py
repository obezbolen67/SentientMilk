import sys
import time
from types import SimpleNamespace

import pytest
import requests
from conftest import wait_for

from sentientmilk_framework import BrainError, permissions, toolkits
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


@pytest.mark.skipif(shell.shell_name("") != "powershell", reason="Windows PowerShell's own quirk")
def test_a_program_keeps_its_exit_code_when_its_warnings_are_redirected(brain, ctx):
    """Windows PowerShell makes `2>&1` lines of a program errors: $? turns false although the program
    exited 0. The exit code is the program's own."""
    (brain.work / "warn.py").write_text("import sys\nsys.stderr.write('a warning\\n')\nprint('done')\n"
                                        "sys.exit(int(sys.argv[1]))\n", encoding="utf-8")
    program = f'& "{sys.executable}" warn.py'
    assert shell.shell_run.func(ctx, f"{program} 0 2>&1 | Select-Object -Last 5").startswith("[exit code 0]")
    assert shell.shell_run.func(ctx, f"{program} 3 | Out-String").startswith("[exit code 3]")
    assert shell.shell_run.func(ctx, "Get-Item no-such-file").startswith("[exit code 1]")  # a cmdlet that failed
    assert shell.shell_run.func(ctx, "echo fine  # a comment at the end").startswith("[exit code 0]")


def test_a_folder_that_cannot_be_followed_is_left_out_of_searches(brain, ctx, monkeypatch):
    """Windows refuses some links (WinError 448, an untrusted mount point) or access: the search goes on."""
    for folder in ("blocked", "open"):
        (brain.work / folder).mkdir()
        (brain.work / folder / "notes.txt").write_text("the needle", encoding="utf-8")
    real = files.Path.resolve

    def resolve(path, *args, **kwargs):
        if "blocked" in path.parts:
            raise OSError(22, "The path cannot be traversed because it contains an untrusted mount point")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(files.Path, "resolve", resolve)
    monkeypatch.setattr(files.shutil, "which", lambda name: None)  # the search that walks in Python
    found = files.files_search.func(ctx, "needle", ".")
    assert "open" in found and "blocked" not in found
    found = files.files_find.func(ctx, "**/notes.txt", ".")
    assert "open" in found and "blocked" not in found


def test_shell_runs_with_exit_codes_and_slow_commands_go_on_as_jobs(brain, ctx):
    assert shell.shell_run.func(ctx, "echo hello").startswith("[exit code 0]\nhello")
    assert "[exit code 3]" in shell.shell_run.func(ctx, "exit 3")
    assert not list(ctx.run_dir().glob("job-*.log"))  # finished commands leave no log behind
    slow = ("Write-Output begun; Start-Sleep -Seconds 4; Write-Output ended" if shell.shell_name("") == "powershell"
            else "echo begun; sleep 4; echo ended")
    started = time.time()
    result = shell.shell_run.func(ctx, slow, timeout=1)
    assert time.time() - started < 4  # the model gets control back; nothing is stopped
    assert "goes on as background job" in result and "called back" not in result  # the CLI calls nobody back
    job = int(result.split("background job ", 1)[1].split(".", 1)[0])
    assert "is running" in shell.shell_output.func(ctx, job)
    waited = shell.shell_output.func(ctx, job, wait=30)  # returns when the job ends, not after 30 s
    assert "begun" in waited and "ended" in waited and "finished, exit code 0" in waited
    assert time.time() - started < 15
    notes = brain.store.events("cli", "main", types=("note",))
    assert f"Background job {job} finished with exit code 0" in notes[-1]["text"]


def test_an_app_that_calls_back_has_her_end_her_turn_instead_of_waiting_for_a_job(brain, monkeypatch):
    brain.client.declare_app("calls", name="Calls", toolkits=["shell"], callbacks=True)
    brain.client.update_session("calls", "main", cwd=str(brain.work), roots=[str(brain.work)])
    monkeypatch.setattr(toolkits, "CALLBACK_WAIT", 1)
    run_id = brain.store.add_run("calls", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run_id), brain.brain.profile("calls", "main"), "call-1")
    slow = "Start-Sleep -Seconds 30" if shell.shell_name("") == "powershell" else "sleep 30"
    started = shell.shell_run.func(ctx, "echo working", background=True)
    assert "called back when it ends" in started and "End your turn" in started
    result = shell.shell_run.func(ctx, slow, timeout=1)
    assert "called back when it ends" in result and "End your turn" in result
    job = int(result.split("background job ", 1)[1].split(" ", 1)[0].rstrip(".,"))
    started = time.time()
    waited = shell.shell_output.func(ctx, job, wait=600)
    assert time.time() - started < 5 and f"job {job} is running" in waited and "called back" in waited
    task = ToolContext(brain.brain, {**ctx.run, "kind": "task"}, ctx.profile, "call-2")  # nobody calls a task back
    started = time.time()
    shell.shell_output.func(task, job, wait=3)
    assert time.time() - started >= 2.5
    shell.shell_stop.func(ctx, job)


def started_job(text):
    return int(text.split()[2].rstrip(".;"))


def job_news(brain, job):
    return [n for n in brain.store.notifications("cli") if n["type"] == "job.finished" and n["data"]["job"] == job]


def test_background_jobs_report_when_they_end(brain, ctx):
    started = shell.shell_run.func(ctx, "echo working", background=True)
    job = started_job(started)
    wait_for(lambda: brain.store.job(job)["status"] == "finished", 30)
    assert "working" in shell.shell_output.func(ctx, job)
    # the job is marked finished first, then noted; her turn still works, so it reads the note itself
    notes = wait_for(lambda: [n for n in brain.store.events("cli", "main", types=("note",)) if f"job {job}" in n["text"]])
    assert f"Background job {job} finished with exit code 0" in notes[-1]["text"]
    time.sleep(1)
    assert not job_news(brain, job)
    brain.store.update_run(ctx.run["id"], status="completed")  # the turn ended without a step after the note
    assert wait_for(lambda: job_news(brain, job))  # so the app calls her back


def test_a_job_she_saw_end_in_her_turn_does_not_call_her_back(brain, ctx):
    job = started_job(shell.shell_run.func(ctx, "echo working", background=True))
    wait_for(lambda: [n for n in brain.store.events("cli", "main", types=("note",)) if f"job {job}" in n["text"]])
    brain.store.add_event("cli", "main", ctx.run["id"], "assistant",  # her next step read the note
                          {"message": {"role": "assistant", "content": "The command finished."}})
    brain.store.update_run(ctx.run["id"], status="completed")
    time.sleep(1.5)
    assert not job_news(brain, job)


def test_a_job_that_ends_while_she_is_idle_calls_her_back_at_once(brain, ctx):
    brain.store.update_run(ctx.run["id"], status="completed")
    job = started_job(shell.shell_run.func(ctx, "echo working", background=True))
    assert wait_for(lambda: job_news(brain, job))


def test_an_app_lists_its_jobs_and_stops_one(brain, ctx):
    wait = "Start-Sleep -Seconds 30" if shell.shell_name("") == "powershell" else "sleep 30"
    started = shell.shell_run.func(ctx, f"echo first; echo 'second line'; {wait}", background=True)
    job = int(started.split()[2].rstrip("."))
    old = brain.store.add_job(None, "cli", "main", "echo old", str(brain.work), str(brain.work / "old.log"))
    brain.store.update_job(old, status="finished", exit_code=0, ended=time.time() - 3600)
    brain.store.add_job(None, "milk", "main", "echo theirs", str(brain.work), str(brain.work / "theirs.log"))
    recent = time.time() - 600
    [listed] = wait_for(lambda: [j for j in brain.client.jobs("cli", since=recent) if j["last"] == "second line"])
    assert [j["id"] for j in brain.client.jobs("cli", since=recent)] == [job]  # not the old one, not another app's
    assert (listed["session"], listed["status"]) == ("main", "running")
    assert "echo first" in listed["command"] and "log" not in listed
    assert brain.client.stop_job(job)["message"] == f"Stopped job {job}."
    wait_for(lambda: brain.store.job(job)["status"] == "stopped", 30)
    assert brain.client.jobs("cli", since=recent)[0]["status"] == "stopped"  # it ended just now: still listed
    assert "is not running (stopped)" in brain.client.stop_job(job)["message"]
    with pytest.raises(BrainError):
        brain.client.stop_job(9999)


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


def test_sentientmilks_own_folder_is_closed_to_the_file_tools(brain, tmp_path, monkeypatch):
    brain.client.update_session("cli", "main", roots=[str(tmp_path)], cwd=str(tmp_path))  # holds the brain's home
    run_id = brain.store.add_run("cli", "main", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run_id), brain.brain.profile("cli", "main"), "call-1")
    (brain.work / "notes.txt").write_text("sk-test-secret is not here", encoding="utf-8")
    for call in (lambda: files.files_read.func(ctx, str(brain.home / "config.json")),
                 lambda: files.files_write.func(ctx, str(brain.home / "plugins.json"), "{}"),
                 lambda: files.files_find.func(ctx, "*", str(brain.home))):
        with pytest.raises(ToolError, match="SentientMilk's own folder"):
            call()
    monkeypatch.setattr(files.shutil, "which", lambda name: None)  # the search without ripgrep walks every folder
    found = files.files_search.func(ctx, "sk-test-secret", ".")
    assert "notes.txt" in found and "config.json" not in found  # the key in its config stays out
    assert "config.json" not in files.files_find.func(ctx, "**/*.json", ".")
    saved = ctx.save_output("a long output", "out")
    assert "a long output" in files.files_read.func(ctx, str(saved))  # its saved outputs stay readable
