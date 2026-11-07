"""GitHub through its REST API (https://docs.github.com/rest).

Reading asks nothing: search, repositories and their files, issues and pull requests (with comments, reviews,
checks and diffs), Actions runs with the log of what failed, and any other GET (``github_get``). Changes ask
the user first: issues, comments, pull requests (open, review, merge), and any other call (``github_api``).
Writes match rules by repository, so ``github_comment(me/*)`` can be allowed for one's own.

The token is the plugin's setting, else GITHUB_TOKEN or GH_TOKEN, else the gh CLI's login. Without one, only
public data can be read, 60 requests an hour. It is only ever sent to the configured API host.
"""

import base64
import json
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests

from sentientmilk_framework.toolkits import ToolContext, ToolError, Toolkit, cap, tool

PLUGIN = "github"
API = "https://api.github.com"
API_VERSION = "2022-11-28"
TIMEOUT = 30
GH_RETRY = 300  # s before asking the gh CLI again after it had no token
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
LOG_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ", re.MULTILINE)
SEARCH_KINDS = ("repositories", "issues", "code", "commits", "users")
REVIEW_EVENTS = ("APPROVE", "REQUEST_CHANGES", "COMMENT")
MERGE_METHODS = ("merge", "squash", "rebase")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

_gh_tokens: Dict[str, tuple] = {}  # host -> (token, when asked)
_gh_lock = threading.Lock()


# ============== Talking to GitHub ==============

def _settings(ctx: ToolContext) -> dict:
    return ctx.brain.plugins.settings(PLUGIN)


def _api(ctx: ToolContext) -> str:
    return (_settings(ctx).get("api_url") or API).rstrip("/")


def _gh_token(host: str) -> str:
    """The gh CLI's token for ``host``; asked again after a while when it had none (the user may log in)."""
    with _gh_lock:
        token, asked = _gh_tokens.get(host, ("", 0.0))
        if token or time.monotonic() - asked < GH_RETRY and host in _gh_tokens:
            return token
    try:
        done = subprocess.run(["gh", "auth", "token", "--hostname", host], capture_output=True, text=True,
                              timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        token = done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        token = ""
    with _gh_lock:
        _gh_tokens[host] = (token, time.monotonic())
    return token


def _token(ctx: ToolContext) -> str:
    token = _settings(ctx).get("token", "")
    if token:
        return token
    host = urlparse(_api(ctx)).hostname or "github.com"
    return _gh_token("github.com" if host == "api.github.com" else host)


def _request(ctx: ToolContext, method: str, path: str, params: Optional[dict] = None, body: Any = None,
             accept: str = "application/vnd.github+json", raw: bool = False) -> Any:
    api = _api(ctx)
    url = path if re.match(r"^https?://", path) else f"{api}/{path.lstrip('/')}"
    if urlparse(url).netloc != urlparse(api).netloc:
        raise ToolError(f"Only GitHub's API at {api} is reached here (the token goes with each call). "
                        "Give a path such as /repos/owner/name/releases.")
    headers = {"Accept": accept, "X-GitHub-Api-Version": API_VERSION, "User-Agent": "SentientMilk"}
    token = _token(ctx)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:  # a redirect to another host (job logs) drops the Authorization header: requests does that
        response = requests.request(method, url, params=params, json=body, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ToolError(f"GitHub could not be reached: {exc}")
    if response.status_code >= 400:
        raise ToolError(_failure(response, method, path, bool(token)))
    if raw:
        return response.text
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text


def _failure(response, method: str, path: str, authed: bool) -> str:
    try:
        data = response.json()
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    message = data.get("message") or response.text[:300]
    status, where = response.status_code, f"{method} {path}"
    if status == 401:
        return ("GitHub refused the token (401, bad credentials). Set a working one in SentientMilk's control "
                "panel (Plugins: github, Settings), or log in again with: gh auth login")
    if status in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(response.headers.get("X-RateLimit-Reset") or 0)
        when = time.strftime("%H:%M", time.localtime(reset)) if reset else "a while"
        hint = "" if authed else (" Without a token it is 60 requests an hour: set one in SentientMilk's control "
                                  "panel (Plugins: github) or log in with gh auth login.")
        return f"GitHub's rate limit is used up until {when}.{hint}"
    if status == 404:
        reach = "the token may not reach it" if authed else "a private one needs a token"
        return f"Not found: {where}. Check the owner/name, number or path; if the repository is private, {reach}."
    if status == 403:
        return f"GitHub refused {where} (403): {message}. The token may lack the permission for it."
    if status == 422:
        details = "; ".join(_rejected(e) for e in data.get("errors", []))
        return f"GitHub could not do {where} (422): {message}" + (f" ({details})" if details else "")
    return f"GitHub answered {status} to {where}: {message}"


def _rejected(error) -> str:
    """One of a 422's errors: its message, else which field was wrong and how ("assignees invalid: x")."""
    if not isinstance(error, dict):
        return str(error)
    if error.get("message"):
        return str(error["message"])
    what = " ".join(str(error[key]) for key in ("field", "code") if error.get(key)) or str(error)
    return f"{what}: {error['value']}" if error.get("value") not in (None, "") else what


# ============== Showing it ==============

def _repo(repo: str) -> str:
    """owner/name, also from a URL or with .git."""
    value = (repo or "").strip().rstrip("/")
    found = re.search(r"github\.[^/:]+[/:]([^/]+/[^/#?]+)", value)
    value = (found.group(1) if found else value).removesuffix(".git")
    if not REPO.fullmatch(value):
        raise ToolError(f"repo must be owner/name, such as octocat/Hello-World (got {repo!r})")
    return value


def _when(stamp: Optional[str]) -> str:
    return (stamp or "")[:16].replace("T", " ")


def _user(item: Optional[dict]) -> str:
    return "@" + ((item or {}).get("login") or "ghost")


def _labels(item: dict) -> str:
    names = [label["name"] for label in item.get("labels", []) if isinstance(label, dict)]
    return f" [{', '.join(names)}]" if names else ""


def _body(text: Optional[str], limit: int = 6000) -> str:
    text = (text or "").strip() or "(no description)"
    return text if len(text) <= limit else f"{text[:limit]}\n[... {len(text) - limit:,} more characters]"


def _repo_of(item: dict) -> str:
    return (item.get("repository_url") or "").split("/repos/")[-1]


def _search_line(kind: str, item: dict) -> str:
    if kind == "repositories":
        return (f"{item['full_name']} ★{item.get('stargazers_count', 0):,} · {item.get('language') or '-'} · "
                f"pushed {_when(item.get('pushed_at'))[:10]} — {item.get('description') or ''}").rstrip(" —")
    if kind == "issues":
        what = "PR" if "pull_request" in item else "issue"
        return (f"{_repo_of(item)}#{item['number']} [{what}, {item['state']}] {item['title']} — {_user(item.get('user'))}, "
                f"{item.get('comments', 0)} comments, updated {_when(item.get('updated_at'))[:10]}")
    if kind == "code":
        return f"{item['repository']['full_name']}:{item['path']}"
    if kind == "commits":
        commit = item.get("commit", {})
        return (f"{item['repository']['full_name']}@{item['sha'][:7]} {commit.get('author', {}).get('date', '')[:10]} "
                f"{_user(item.get('author'))} — {(commit.get('message') or '').splitlines()[0] if commit.get('message') else ''}")
    return f"{item['login']} ({item.get('type', 'User')}) {item.get('html_url', '')}"


# ============== Reading ==============

@tool(readonly=True, args={
    "query": "GitHub search syntax: 'agents language:python stars:>100', 'repo:owner/name is:pr is:open', "
             "'user:octocat', 'filename:pyproject.toml repo:owner/name'.",
    "kind": "repositories, issues (issues and pull requests), code, commits or users.",
    "limit": "How many, at most 50."})
def github_search(ctx: ToolContext, query: str, kind: str = "repositories", limit: int = 10):
    """Search GitHub: repositories, issues and pull requests, code, commits or users. Code search needs a
    token. For one repository's issues, github_issues lists them without a query."""
    if kind not in SEARCH_KINDS:
        raise ToolError(f"kind must be one of {', '.join(SEARCH_KINDS)}")
    data = _request(ctx, "GET", f"/search/{kind}", params={"q": query, "per_page": max(1, min(int(limit), 50))})
    items = data.get("items", [])
    head = f"{data.get('total_count', len(items)):,} found" + (f", the first {len(items)}:" if items else ".")
    return "\n".join([head] + [_search_line(kind, item) for item in items])


@tool(readonly=True, args={"repo": "owner/name, or its URL."})
def github_repo(ctx: ToolContext, repo: str):
    """A repository at a glance: description, stars, default branch, license, latest release and the files at
    its top. Read files with github_files, issues with github_issues."""
    repo = _repo(repo)
    data = _request(ctx, "GET", f"/repos/{repo}")
    flags = [word for word, on in (("private", data.get("private")), ("archived", data.get("archived")),
                                   ("template", data.get("is_template"))) if on]
    if data.get("fork") and data.get("parent"):
        flags.append(f"fork of {data['parent']['full_name']}")
    lines = [data["full_name"] + (f" ({', '.join(flags)})" if flags else ""), data.get("description") or "",
             f"★{data.get('stargazers_count', 0):,} · {data.get('forks_count', 0):,} forks · "
             f"{data.get('open_issues_count', 0):,} open issues and PRs · {data.get('language') or '-'}",
             f"Default branch {data.get('default_branch')} · pushed {_when(data.get('pushed_at'))} · "
             f"license {(data.get('license') or {}).get('spdx_id') or 'none'}"]
    if data.get("topics"):
        lines.append("Topics: " + ", ".join(data["topics"]))
    lines.append(" · ".join(filter(None, [data.get("homepage"), data.get("html_url")])))
    try:
        release = _request(ctx, "GET", f"/repos/{repo}/releases/latest")
        lines.append(f"Latest release: {release.get('tag_name')} ({_when(release.get('published_at'))[:10]}) "
                     f"{release.get('name') or ''}".rstrip())
    except ToolError:
        pass  # none
    try:
        top = _request(ctx, "GET", f"/repos/{repo}/contents")
        if isinstance(top, list):
            names = sorted(top, key=lambda e: (e.get("type") != "dir", e.get("name", "").lower()))
            lines.append("Top: " + "  ".join(e["name"] + ("/" if e.get("type") == "dir" else "") for e in names))
    except ToolError:
        pass  # an empty repository
    return "\n".join(line for line in lines if line)


@tool(readonly=True, args={
    "repo": "owner/name.", "path": "A folder or file in it; empty: the top.",
    "ref": "A branch, tag or commit; empty: the default branch.",
    "offset": "The first line of a file to show (1-based).", "limit": "How many lines of a file."})
def github_files(ctx: ToolContext, repo: str, path: str = "", ref: str = "", offset: int = 1, limit: int = 400):
    """List a folder of a repository, or read a file in it with numbered lines, without cloning. Read a long
    file on with offset. To change files, clone the repository and use the shell, or github_api."""
    repo, path = _repo(repo), path.strip("/")
    data = _request(ctx, "GET", f"/repos/{repo}/contents/{quote(path)}", params={"ref": ref} if ref else None)
    where = f"{repo}/{path}" + (f" at {ref}" if ref else "")
    if isinstance(data, list):
        entries = sorted(data, key=lambda e: (e.get("type") != "dir", e.get("name", "").lower()))
        lines = [f"{where}: {len(entries)} entries"]
        lines += [e["name"] + "/" if e.get("type") == "dir" else f"{e['name']}  {e.get('size', 0):,} B"
                  if e.get("type") == "file" else f"{e['name']}  ({e.get('type')})" for e in entries]
        return "\n".join(lines)
    if data.get("type") != "file":
        return f"{where} is a {data.get('type')}" + (f" pointing at {data['target']}" if data.get("target") else "")
    if data.get("encoding") == "base64" and data.get("content") is not None:
        content = base64.b64decode(data["content"])
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return f"{where} is a binary file of {data.get('size', len(content)):,} bytes."
    else:  # over 1 MB: the contents API leaves it out
        text = _request(ctx, "GET", f"/repos/{repo}/contents/{quote(path)}", params={"ref": ref} if ref else None,
                        accept="application/vnd.github.raw", raw=True)
    lines = text.splitlines()
    start = max(1, int(offset))
    shown = lines[start - 1:start - 1 + max(1, int(limit))]
    end = start + len(shown) - 1
    body = "\n".join(f"{number:>6}\t{line[:2000]}" for number, line in enumerate(shown, start))
    footer = f"[{where}: lines {start}-{end} of {len(lines)}" + (f"; read on with offset={end + 1}]" if end < len(lines) else "]")
    return cap(ctx, f"{body}\n{footer}", "github")


@tool(readonly=True, args={
    "repo": "owner/name.", "state": "open, closed or all.", "kind": "issues, prs or all.",
    "labels": "Comma-separated label names, all of which an item must have.", "limit": "How many, at most 100.",
    "page": "The page, from 1, for more."})
def github_issues(ctx: ToolContext, repo: str, state: str = "open", kind: str = "all", labels: str = "",
                  limit: int = 20, page: int = 1):
    """A repository's issues and pull requests, recently updated first. Read one with github_issue; search
    across repositories with github_search (kind issues)."""
    repo = _repo(repo)
    if state not in ("open", "closed", "all") or kind not in ("issues", "prs", "all"):
        raise ToolError("state must be open, closed or all; kind issues, prs or all")
    per_page = max(1, min(int(limit), 100))
    params = {"state": state, "per_page": per_page, "page": max(1, int(page)), "sort": "updated"}
    if labels:
        params["labels"] = labels
    data = _request(ctx, "GET", f"/repos/{repo}/issues", params=params)
    items = [i for i in data if kind == "all" or ("pull_request" in i) == (kind == "prs")]
    lines = [f"#{i['number']} [{'PR' if 'pull_request' in i else 'issue'}{', draft' if i.get('draft') else ''}"
             f"{', closed' if i['state'] == 'closed' else ''}] {i['title']}{_labels(i)} — {_user(i.get('user'))} · "
             f"{i.get('comments', 0)} comments · updated {_when(i.get('updated_at'))[:10]}" for i in items]
    if not lines:
        lines = [f"No {state if state != 'all' else ''} {'pull requests' if kind == 'prs' else 'issues'} here.".replace("  ", " ")]
    if len(data) == per_page:
        lines.append(f"[more: page={int(page) + 1}]")
    return "\n".join(lines)


@tool(readonly=True, args={"repo": "owner/name.", "number": "The issue or pull request number.",
                           "comments": "How many of the latest comments to show."})
def github_issue(ctx: ToolContext, repo: str, number: int, comments: int = 20):
    """One issue or pull request in full: its text, labels and latest comments; for a pull request also its
    branches, size, mergeability, reviews and checks. Its diff: github_diff."""
    repo, number = _repo(repo), int(number)
    issue = _request(ctx, "GET", f"/repos/{repo}/issues/{number}")
    pull = "pull_request" in issue
    lines = [f"{repo}#{number} {'pull request' if pull else 'issue'}: {issue['title']}",
             f"{issue['state']} · by {_user(issue.get('user'))} · opened {_when(issue.get('created_at'))} · "
             f"updated {_when(issue.get('updated_at'))} · {issue.get('comments', 0)} comments"]
    extras = [("Labels", ", ".join(label["name"] for label in issue.get("labels", []))),
              ("Assignees", ", ".join(_user(user) for user in issue.get("assignees", []))),
              ("Milestone", (issue.get("milestone") or {}).get("title", ""))]
    lines += [f"{name}: {value}" for name, value in extras if value]
    if pull:
        pr = _request(ctx, "GET", f"/repos/{repo}/pulls/{number}")
        merge = "merged" if pr.get("merged") else {True: "mergeable", False: "has conflicts"}.get(
            pr.get("mergeable"), "mergeability not known yet")
        lines.append(f"{pr['head']['label']} → {pr['base']['ref']} · {'draft · ' if pr.get('draft') else ''}{merge}"
                     f" ({pr.get('mergeable_state', '?')}) · {pr.get('commits', 0)} commits, "
                     f"{pr.get('changed_files', 0)} files, +{pr.get('additions', 0)} −{pr.get('deletions', 0)}")
        reviews: Dict[str, str] = {}
        for review in _request(ctx, "GET", f"/repos/{repo}/pulls/{number}/reviews", params={"per_page": 100}):
            if review.get("state") != "COMMENTED" or _user(review.get("user")) not in reviews:
                reviews[_user(review.get("user"))] = review.get("state", "").lower().replace("_", " ")
        if reviews:
            lines.append("Reviews: " + ", ".join(f"{who} {state}" for who, state in reviews.items()))
        checks = _request(ctx, "GET", f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs",
                          params={"per_page": 100}).get("check_runs", [])
        if checks:
            counts: Dict[str, int] = {}
            for check in checks:
                result = check.get("conclusion") or check.get("status") or "?"
                counts[result] = counts.get(result, 0) + 1
            failed = [c["name"] for c in checks if c.get("conclusion") in ("failure", "timed_out", "cancelled")]
            lines.append("Checks: " + ", ".join(f"{n} {result}" for result, n in counts.items()) +
                         (f" (failed: {', '.join(failed)}; see github_runs)" if failed else ""))
    lines += [issue.get("html_url", ""), "", _body(issue.get("body"))]
    if issue.get("comments") and comments > 0:
        listed = _request(ctx, "GET", f"/repos/{repo}/issues/{number}/comments", params={"per_page": 100})
        shown = listed[-int(comments):]
        if len(listed) > len(shown):
            lines.append(f"\n[{len(listed) - len(shown)} earlier comments left out]")
        for comment in shown:
            lines += ["", f"--- {_user(comment.get('user'))} {_when(comment.get('created_at'))}",
                      _body(comment.get("body"), 3000)]
    return cap(ctx, "\n".join(lines), "github")


@tool(readonly=True, args={"repo": "owner/name.", "number": "A pull request's number.",
                           "base": "Or compare two refs: the base (branch, tag or commit)...",
                           "head": "...and the head."})
def github_diff(ctx: ToolContext, repo: str, number: int = 0, base: str = "", head: str = ""):
    """The unified diff of a pull request, or between two branches, tags or commits. Long diffs are saved to a
    file you can search or page."""
    repo = _repo(repo)
    if number:
        text = _request(ctx, "GET", f"/repos/{repo}/pulls/{int(number)}", accept="application/vnd.github.diff", raw=True)
    elif base and head:
        text = _request(ctx, "GET", f"/repos/{repo}/compare/{quote(base)}...{quote(head)}",
                        accept="application/vnd.github.diff", raw=True)
    else:
        raise ToolError("Give a pull request number, or base and head to compare.")
    return cap(ctx, text or "(no changes)", "github-diff")


@tool(readonly=True, args={"repo": "owner/name.", "branch": "Only this branch's runs.",
                           "status": "Only runs in this state: failure, success, in_progress, queued...",
                           "limit": "How many, at most 50."})
def github_runs(ctx: ToolContext, repo: str, branch: str = "", status: str = "", limit: int = 10):
    """GitHub Actions runs of a repository, newest first, with their ids. Why one failed: github_run."""
    repo = _repo(repo)
    params = {"per_page": max(1, min(int(limit), 50)), **({"branch": branch} if branch else {}),
              **({"status": status} if status else {})}
    runs = _request(ctx, "GET", f"/repos/{repo}/actions/runs", params=params).get("workflow_runs", [])
    if not runs:
        return "No runs found."
    return "\n".join(f"{r['id']} · {r.get('name')} · {r.get('head_branch')} · {r.get('event')} · "
                     f"{r.get('conclusion') or r.get('status')} · {_when(r.get('created_at'))} · "
                     f"{(r.get('head_sha') or '')[:7]} — {r.get('display_title', '')}" for r in runs)


@tool(readonly=True, args={"repo": "owner/name.", "run_id": "The run's id, from github_runs.",
                           "log_lines": "How many of the last log lines of each failed job to show."})
def github_run(ctx: ToolContext, repo: str, run_id: int, log_lines: int = 60):
    """One Actions run: its jobs and steps, and for each failed job the end of its log, where the error
    usually is. Re-run or cancel with github_api (POST .../actions/runs/ID/rerun-failed-jobs or cancel)."""
    repo, run_id = _repo(repo), int(run_id)
    run = _request(ctx, "GET", f"/repos/{repo}/actions/runs/{run_id}")
    jobs = _request(ctx, "GET", f"/repos/{repo}/actions/runs/{run_id}/jobs", params={"per_page": 100}).get("jobs", [])
    lines = [f"Run {run_id} {run.get('name')} on {run.get('head_branch')} ({run.get('event')}): "
             f"{run.get('conclusion') or run.get('status')} · {_when(run.get('created_at'))} · {run.get('html_url', '')}"]
    failed = []
    for job in jobs:
        lines.append(f"{job.get('name')}: {job.get('conclusion') or job.get('status')}")
        for step in job.get("steps", []):
            if step.get("conclusion") in ("failure", "timed_out", "cancelled"):
                lines.append(f"  ✕ step {step.get('number')}: {step.get('name')} ({step.get('conclusion')})")
        if job.get("conclusion") in ("failure", "timed_out"):
            failed.append(job)
    for job in failed:
        try:
            log = _request(ctx, "GET", f"/repos/{repo}/actions/jobs/{job['id']}/logs", accept="*/*", raw=True)
        except ToolError as exc:
            lines += ["", f"--- {job.get('name')}: its log could not be read ({exc})"]
            continue
        tail = LOG_STAMP.sub("", log).splitlines()[-max(1, int(log_lines)):]
        lines += ["", f"--- the last {len(tail)} log lines of {job.get('name')}:", *tail]
    return cap(ctx, "\n".join(lines), "github")


@tool(readonly=True, args={
    "path": "The REST path, such as /repos/owner/name/releases, /user, /notifications, /orgs/NAME/repos.",
    "params": {"type": "object", "description": "Query parameters, such as {\"per_page\": 50, \"state\": \"all\"}."}})
def github_get(ctx: ToolContext, path: str, params: Optional[dict] = None):
    """Any GET of GitHub's REST API, for what the other tools do not cover: releases, branches, tags,
    commits, contributors, gists, notifications, the user, organizations... Returns its JSON."""
    data = _request(ctx, "GET", path, params=params or None)
    return cap(ctx, data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":")),
               "github")


# ============== Changing things: these ask the user first ==============

@tool(rule_arg="repo", args={"repo": "owner/name.", "title": "The issue's title.", "body": "Its text, in Markdown.",
                             "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names."},
                             "assignees": {"type": "array", "items": {"type": "string"}, "description": "Logins."}})
def github_issue_create(ctx: ToolContext, repo: str, title: str, body: str = "", labels: Optional[List[str]] = None,
                        assignees: Optional[List[str]] = None):
    """Open an issue."""
    repo = _repo(repo)
    payload = {"title": title, "body": body, **({"labels": labels} if labels else {}),
               **({"assignees": assignees} if assignees else {})}
    created = _request(ctx, "POST", f"/repos/{repo}/issues", body=payload)
    return f"Opened {repo}#{created['number']}: {created.get('html_url', '')}"


@tool(rule_arg="repo", args={"repo": "owner/name.", "number": "The issue or pull request number.",
                             "body": "The comment, in Markdown."})
def github_comment(ctx: ToolContext, repo: str, number: int, body: str):
    """Comment on an issue or pull request."""
    repo = _repo(repo)
    if not body.strip():
        raise ToolError("body is empty: write the comment.")
    made = _request(ctx, "POST", f"/repos/{repo}/issues/{int(number)}/comments", body={"body": body})
    return f"Commented on {repo}#{int(number)}: {made.get('html_url', '')}"


@tool(rule_arg="repo", args={
    "repo": "owner/name.", "number": "The issue or pull request number.", "state": "open or closed; empty: as is.",
    "title": "A new title; empty: as is.", "body": "A new text; empty: as is.",
    "labels": {"type": "array", "items": {"type": "string"}, "description": "All its labels from now on."},
    "assignees": {"type": "array", "items": {"type": "string"}, "description": "All its assignees from now on."}})
def github_issue_update(ctx: ToolContext, repo: str, number: int, state: str = "", title: str = "", body: str = "",
                        labels: Optional[List[str]] = None, assignees: Optional[List[str]] = None):
    """Close or reopen an issue or pull request, or change its title, text, labels or assignees."""
    repo = _repo(repo)
    if state not in ("", "open", "closed"):
        raise ToolError("state must be open or closed")
    changes = {key: value for key, value in (("state", state), ("title", title), ("body", body)) if value}
    changes.update({key: value for key, value in (("labels", labels), ("assignees", assignees)) if value is not None})
    if not changes:
        raise ToolError("Nothing to change: give state, title, body, labels or assignees.")
    updated = _request(ctx, "PATCH", f"/repos/{repo}/issues/{int(number)}", body=changes)
    return f"Updated {repo}#{int(number)} ({', '.join(changes)}): now {updated.get('state')}, \"{updated.get('title')}\""


@tool(rule_arg="repo", args={
    "repo": "owner/name.", "head": "The branch with the changes (owner:branch for a fork's).",
    "title": "The pull request's title.", "base": "The branch to merge into; empty: the default branch.",
    "body": "Its description, in Markdown.", "draft": "Open it as a draft."})
def github_pr_create(ctx: ToolContext, repo: str, head: str, title: str, base: str = "", body: str = "",
                     draft: bool = False):
    """Open a pull request from a pushed branch."""
    repo = _repo(repo)
    base = base or _request(ctx, "GET", f"/repos/{repo}").get("default_branch", "main")
    made = _request(ctx, "POST", f"/repos/{repo}/pulls",
                    body={"title": title, "head": head, "base": base, "body": body, "draft": bool(draft)})
    return f"Opened {repo}#{made['number']} ({head} → {base}): {made.get('html_url', '')}"


@tool(rule_arg="repo", args={"repo": "owner/name.", "number": "The pull request number.",
                             "event": "APPROVE, REQUEST_CHANGES or COMMENT.",
                             "body": "The review's text (needed for REQUEST_CHANGES and COMMENT)."})
def github_pr_review(ctx: ToolContext, repo: str, number: int, event: str = "COMMENT", body: str = ""):
    """Review a pull request: approve it, request changes, or comment."""
    repo, event = _repo(repo), event.upper()
    if event not in REVIEW_EVENTS:
        raise ToolError(f"event must be one of {', '.join(REVIEW_EVENTS)}")
    if event != "APPROVE" and not body.strip():
        raise ToolError(f"A {event} review needs a body.")
    made = _request(ctx, "POST", f"/repos/{repo}/pulls/{int(number)}/reviews",
                    body={"event": event, **({"body": body} if body else {})})
    return f"Reviewed {repo}#{int(number)}: {made.get('state', event).lower().replace('_', ' ')}"


@tool(rule_arg="repo", args={"repo": "owner/name.", "number": "The pull request number.",
                             "method": "merge, squash or rebase (as the repository allows).",
                             "title": "The merge commit's title; empty: GitHub's.",
                             "message": "The merge commit's message; empty: GitHub's."})
def github_pr_merge(ctx: ToolContext, repo: str, number: int, method: str = "merge", title: str = "", message: str = ""):
    """Merge a pull request."""
    repo = _repo(repo)
    if method not in MERGE_METHODS:
        raise ToolError(f"method must be one of {', '.join(MERGE_METHODS)}")
    pull = _request(ctx, "GET", f"/repos/{repo}/pulls/{int(number)}")
    if pull.get("merged"):  # GitHub answers a second merge with success all the same
        return (f"{repo}#{int(number)} was already merged by {_user(pull.get('merged_by'))} on "
                f"{_when(pull.get('merged_at'))} ({(pull.get('merge_commit_sha') or '')[:7]}).")
    payload = {"merge_method": method, **({"commit_title": title} if title else {}),
               **({"commit_message": message} if message else {})}
    merged = _request(ctx, "PUT", f"/repos/{repo}/pulls/{int(number)}/merge", body=payload)
    return f"Merged {repo}#{int(number)} ({method}): {(merged.get('sha') or '')[:7]} {merged.get('message', '')}".rstrip()


@tool(rule_arg="path", args={
    "method": "POST, PUT, PATCH or DELETE (reading is github_get).",
    "path": "The REST path, such as /repos/owner/name/releases or /repos/owner/name/actions/runs/ID/rerun.",
    "body": {"type": "object", "description": "The JSON body, as GitHub's REST docs give it."},
    "params": {"type": "object", "description": "Query parameters."}})
def github_api(ctx: ToolContext, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None):
    """Any other change through GitHub's REST API: releases, labels, branches, files (PUT contents), forks,
    repositories, gists, workflow runs (rerun, cancel, dispatch)... Returns GitHub's answer."""
    method = method.upper()
    if method not in WRITE_METHODS:
        raise ToolError(f"method must be one of {', '.join(WRITE_METHODS)}; to read, use github_get")
    data = _request(ctx, method, path, params=params or None, body=body)
    if not data:
        return "Done."
    return cap(ctx, data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":")),
               "github")


TOOLKIT = Toolkit(
    "github", "GitHub: search; repositories, files, issues and pull requests with diffs, reviews and checks; "
    "Actions runs and failed logs; open, comment, review, merge; any REST call (github_get, github_api).",
    [github_search, github_repo, github_files, github_issues, github_issue, github_diff, github_runs, github_run,
     github_get, github_issue_create, github_comment, github_issue_update, github_pr_create, github_pr_review,
     github_pr_merge, github_api])
