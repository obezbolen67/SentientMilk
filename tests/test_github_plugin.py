"""The built-in GitHub plugin against a fake GitHub: what each tool asks of the API and how it shows the
answer, where its token comes from, which tools ask the user first, and errors that say what to do."""

import base64
import json
from types import SimpleNamespace

import pytest

from sentientmilk_framework.plugins.github import tools as github
from sentientmilk_framework.toolkits import ToolError

API = "https://api.github.com"


class Response:
    def __init__(self, status=200, data=None, text=None, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.text = text if text is not None else json.dumps(data if data is not None else {})
        self.content = self.text.encode()
        self._data = data

    def json(self):
        if self._data is None and self.text and not self.text.startswith(("{", "[")):
            raise ValueError("not JSON")
        return self._data if self._data is not None else json.loads(self.text or "null")


class FakeGitHub:
    """Answers by (method, path); keeps every request."""

    def __init__(self, monkeypatch, routes, gh_token=""):
        self.routes, self.calls = routes, []
        monkeypatch.setattr(github.requests, "request", self.request)
        monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0 if gh_token else 1, stdout=gh_token + "\n"))
        github._gh_tokens.clear()

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        path = url.removeprefix(API)
        self.calls.append(SimpleNamespace(method=method, path=path, params=params, body=json, headers=headers))
        answer = self.routes.get((method, path), Response(404, {"message": "Not Found"}))
        return answer(params) if callable(answer) else answer


class Context:
    def __init__(self, tmp_path, **settings):
        values = {"token": "", "api_url": API, **settings}
        self.brain = SimpleNamespace(plugins=SimpleNamespace(settings=lambda name: values))
        self.saved = tmp_path

    def save_output(self, text, stem="out"):
        path = self.saved / f"{stem}.txt"
        path.write_text(text, encoding="utf-8")
        return path


def test_the_token_comes_from_the_setting_then_the_gh_login_and_goes_only_to_github(monkeypatch, tmp_path):
    fake = FakeGitHub(monkeypatch, {("GET", "/user"): Response(200, {"login": "me"})}, gh_token="gho_cli")
    github.github_get.func(Context(tmp_path, token="ghp_set"), "/user")
    assert fake.calls[-1].headers["Authorization"] == "Bearer ghp_set"
    github.github_get.func(Context(tmp_path), "/user")  # none set: the gh CLI's login
    assert fake.calls[-1].headers["Authorization"] == "Bearer gho_cli"
    fake = FakeGitHub(monkeypatch, {("GET", "/user"): Response(200, {"login": "me"})})
    github.github_get.func(Context(tmp_path), "/user")
    assert "Authorization" not in fake.calls[-1].headers  # public data only
    with pytest.raises(ToolError, match="Only GitHub's API"):
        github.github_get.func(Context(tmp_path, token="ghp_set"), "https://evil.example/steal")


def test_reading_asks_nothing_and_changing_asks_first_by_repository():
    tools = {t.name: t for t in github.TOOLKIT.tools}
    reads = {"github_search", "github_repo", "github_files", "github_issues", "github_issue", "github_diff",
             "github_runs", "github_run", "github_get"}
    assert all(tools[name].readonly and tools[name].policy == "auto" for name in reads)
    writes = set(tools) - reads
    assert writes and all(not tools[name].readonly and tools[name].policy == "ask" for name in writes)
    assert all(tools[name].rule_arg == "repo" for name in writes - {"github_api"})
    assert tools["github_api"].rule_arg == "path"


def test_a_repository_at_a_glance(monkeypatch, tmp_path):
    FakeGitHub(monkeypatch, {
        ("GET", "/repos/octo/milk"): Response(200, {
            "full_name": "octo/milk", "description": "A brain.", "stargazers_count": 1234, "forks_count": 5,
            "open_issues_count": 7, "language": "Python", "default_branch": "main", "pushed_at": "2026-11-07T10:20:30Z",
            "license": {"spdx_id": "MIT"}, "topics": ["ai"], "html_url": "https://github.com/octo/milk"}),
        ("GET", "/repos/octo/milk/releases/latest"): Response(200, {"tag_name": "v1.2", "published_at": "2026-11-01T00:00:00Z"}),
        ("GET", "/repos/octo/milk/contents"): Response(200, [{"name": "src", "type": "dir"}, {"name": "README.md", "type": "file"}]),
    })
    shown = github.github_repo.func(Context(tmp_path), "https://github.com/octo/milk.git")  # a URL is fine
    assert "octo/milk" in shown and "★1,234" in shown and "Default branch main" in shown and "license MIT" in shown
    assert "Latest release: v1.2 (2026-11-01)" in shown and "Top: src/  README.md" in shown


def test_files_are_listed_and_read_in_numbered_windows(monkeypatch, tmp_path):
    text = "\n".join(f"line {n}" for n in range(1, 11))
    FakeGitHub(monkeypatch, {
        ("GET", "/repos/octo/milk/contents/"): Response(200, [{"name": "b.py", "type": "file", "size": 1200},
                                                              {"name": "a", "type": "dir"}]),
        ("GET", "/repos/octo/milk/contents/src/b.py"): Response(200, {
            "type": "file", "encoding": "base64", "size": len(text), "content": base64.b64encode(text.encode()).decode()}),
    })
    listing = github.github_files.func(Context(tmp_path), "octo/milk")
    assert listing.splitlines()[1:] == ["a/", "b.py  1,200 B"]
    window = github.github_files.func(Context(tmp_path), "octo/milk", "src/b.py", offset=3, limit=2)
    assert "     3\tline 3\n     4\tline 4" in window and "lines 3-4 of 10; read on with offset=5" in window


def test_a_pull_request_in_full(monkeypatch, tmp_path):
    FakeGitHub(monkeypatch, {
        ("GET", "/repos/octo/milk/issues/12"): Response(200, {
            "title": "Plugins", "state": "open", "user": {"login": "ann"}, "comments": 3, "pull_request": {},
            "labels": [{"name": "feature"}], "assignees": [], "body": "Adds plugins.", "html_url": "https://x/12"}),
        ("GET", "/repos/octo/milk/pulls/12"): Response(200, {
            "head": {"label": "ann:plugins", "sha": "abc123"}, "base": {"ref": "main"}, "mergeable": True,
            "mergeable_state": "clean", "commits": 4, "changed_files": 9, "additions": 300, "deletions": 20}),
        ("GET", "/repos/octo/milk/pulls/12/reviews"): Response(200, [
            {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED"}, {"user": {"login": "bob"}, "state": "APPROVED"}]),
        ("GET", "/repos/octo/milk/commits/abc123/check-runs"): Response(200, {"check_runs": [
            {"name": "tests", "conclusion": "success"}, {"name": "lint", "conclusion": "failure"}]}),
        ("GET", "/repos/octo/milk/issues/12/comments"): Response(200, [
            {"user": {"login": f"u{n}"}, "body": f"comment {n}", "created_at": "2026-11-07T00:00:00Z"} for n in range(3)]),
    })
    shown = github.github_issue.func(Context(tmp_path), "octo/milk", 12, comments=2)
    assert "octo/milk#12 pull request: Plugins" in shown and "Labels: feature" in shown
    assert "ann:plugins → main · mergeable (clean) · 4 commits, 9 files, +300 −20" in shown
    assert "Reviews: @bob approved" in shown and "1 success, 1 failure (failed: lint" in shown
    assert "[1 earlier comments left out]" in shown and "comment 2" in shown and "comment 0" not in shown


def test_a_failed_run_shows_its_failed_steps_and_the_end_of_their_log(monkeypatch, tmp_path):
    log = "\n".join(f"2026-11-07T10:00:{n:02d}.1234567Z step output {n}" for n in range(100))
    fake = FakeGitHub(monkeypatch, {
        ("GET", "/repos/octo/milk/actions/runs/77"): Response(200, {"name": "CI", "head_branch": "main", "event": "push",
                                                                    "conclusion": "failure"}),
        ("GET", "/repos/octo/milk/actions/runs/77/jobs"): Response(200, {"jobs": [
            {"id": 5, "name": "test", "conclusion": "failure",
             "steps": [{"number": 1, "name": "checkout", "conclusion": "success"},
                       {"number": 2, "name": "pytest", "conclusion": "failure"}]},
            {"id": 6, "name": "lint", "conclusion": "success", "steps": []}]}),
        ("GET", "/repos/octo/milk/actions/jobs/5/logs"): Response(200, text=log),
    })
    shown = github.github_run.func(Context(tmp_path), "octo/milk", 77, log_lines=3)
    assert "Run 77 CI on main (push): failure" in shown and "✕ step 2: pytest (failure)" in shown
    assert shown.endswith("step output 97\nstep output 98\nstep output 99")  # timestamps cut
    assert not any(call.path.endswith("/jobs/6/logs") for call in fake.calls)  # only failed jobs' logs


def test_search_lines(monkeypatch, tmp_path):
    FakeGitHub(monkeypatch, {("GET", "/search/issues"): Response(200, {"total_count": 41, "items": [
        {"repository_url": f"{API}/repos/octo/milk", "number": 3, "state": "open", "title": "Crash", "comments": 2,
         "user": {"login": "ann"}, "updated_at": "2026-11-06T00:00:00Z", "pull_request": {}}]})})
    shown = github.github_search.func(Context(tmp_path), "repo:octo/milk crash", kind="issues")
    assert shown == "41 found, the first 1:\nocto/milk#3 [PR, open] Crash — @ann, 2 comments, updated 2026-11-06"


def test_changes_send_what_they_say(monkeypatch, tmp_path):
    fake = FakeGitHub(monkeypatch, {
        ("POST", "/repos/octo/milk/issues"): Response(201, {"number": 13, "html_url": "https://x/13"}),
        ("POST", "/repos/octo/milk/issues/13/comments"): Response(201, {"html_url": "https://x/13#c"}),
        ("PUT", "/repos/octo/milk/pulls/12/merge"): Response(200, {"sha": "deadbeef1", "message": "Merged"}),
        ("GET", "/repos/octo/milk"): Response(200, {"default_branch": "trunk"}),
        ("POST", "/repos/octo/milk/pulls"): Response(201, {"number": 14, "html_url": "https://x/14"}),
        ("DELETE", "/repos/octo/milk/git/refs/heads/old"): Response(204, text=""),
    })
    ctx = Context(tmp_path, token="t")
    assert github.github_issue_create.func(ctx, "octo/milk", "Bug", "It broke", labels=["bug"]) == \
        "Opened octo/milk#13: https://x/13"
    assert fake.calls[-1].body == {"title": "Bug", "body": "It broke", "labels": ["bug"]}
    github.github_comment.func(ctx, "octo/milk", 13, "On it.")
    assert fake.calls[-1].body == {"body": "On it."}
    assert "Merged octo/milk#12 (squash): deadbee" in github.github_pr_merge.func(ctx, "octo/milk", 12, "squash")
    assert fake.calls[-1].body == {"merge_method": "squash"}
    assert "(feature → trunk)" in github.github_pr_create.func(ctx, "octo/milk", "feature", "Feature")  # the default branch
    assert github.github_api.func(ctx, "delete", "/repos/octo/milk/git/refs/heads/old") == "Done."
    with pytest.raises(ToolError, match="github_get"):
        github.github_api.func(ctx, "GET", "/user")
    with pytest.raises(ToolError, match="needs a body"):
        github.github_pr_review.func(ctx, "octo/milk", 12, "request_changes")


def test_errors_say_what_to_do(monkeypatch, tmp_path):
    FakeGitHub(monkeypatch, {
        ("GET", "/user"): Response(401, {"message": "Bad credentials"}),
        ("GET", "/rate"): Response(403, {"message": "API rate limit exceeded"},
                                   headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"}),
        ("POST", "/repos/octo/milk/issues"): Response(422, {"message": "Validation Failed",
                                                            "errors": [{"message": "title is too long"}]}),
    })
    with pytest.raises(ToolError, match="refused the token.*gh auth login"):
        github.github_get.func(Context(tmp_path, token="bad"), "/user")
    with pytest.raises(ToolError, match="rate limit is used up.*60 requests an hour"):
        github.github_get.func(Context(tmp_path), "/rate")
    with pytest.raises(ToolError, match="Not found: GET /repos/octo/gone.*private one needs a token"):
        github.github_repo.func(Context(tmp_path), "octo/gone")
    with pytest.raises(ToolError, match="422.*title is too long"):
        github.github_issue_create.func(Context(tmp_path, token="t"), "octo/milk", "x" * 300)
    with pytest.raises(ToolError, match="owner/name"):
        github.github_repo.func(Context(tmp_path), "just-a-name")
