"""Evaluation tasks: realistic work with an outcome a script can check, run against the configured model.

Each task gets a throw-away brain home and work folder and runs through the real HTTP API.
Kinds: "task" (a background task; check its files, a command or its report) and "chat" (turns in a
session; check replies, signals, schedules, what was remembered and each session's own memory). Tasks marked "holdout" catch rules that only fit the rest.

    sentientmilk eval                 every task
    sentientmilk eval fix-failing-test --report results.json
    sentientmilk eval context-continuity --context-pair --report continuity.json
"""

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from .client import BrainClient, default_home
from .config import BrainConfig

TASKS_DIR = Path(__file__).parent / "eval_tasks"
COPIED_SETTINGS = ("api_key", "base_url", "model", "light_model", "web_search_key", "thinking_mode",
                   "thinking_tokens", "context_window", "vision", "request_budget")
DEFAULT_TOOLKITS = ["files", "shell", "web", "todo", "agents", "schedule"]  # and memory, as every app


def load(names: Optional[List[str]] = None) -> List[dict]:
    specs = [json.loads(path.read_text(encoding="utf-8")) | {"name": path.stem}
             for path in sorted(TASKS_DIR.glob("*.json"))]
    if names:
        missing = set(names) - {spec["name"] for spec in specs}
        if missing:
            raise SystemExit(f"No eval tasks named {sorted(missing)}. Known: {[s['name'] for s in specs]}")
        specs = [spec for spec in specs if spec["name"] in names]
    return specs


def _write(folder: Path, files: dict) -> None:
    for name, content in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")  # as given: Windows would turn \n into \r\n


def _screenshot() -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1280, 720), "white")
    ImageDraw.Draw(image).text((40, 40), "def main():\n    print('hello world')", fill="black")
    output = io.BytesIO()
    image.save(output, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()


def _command(command: str, folder: Path) -> tuple:
    bundled = Path(sys.executable).parent / "runtime" / "python.exe"  # SentientMilk.exe runs Python from there
    command = command.replace("{python}", f'"{bundled if bundled.exists() else sys.executable}"')
    done = subprocess.run(command, shell=True, cwd=folder, capture_output=True, text=True, timeout=300)
    return done.returncode == 0, (done.stdout + done.stderr)[-1500:]


def check(spec: dict, folder: Path, replies: List[str], extra: dict) -> tuple:
    """(passed, why) for a task's ``check``: every given condition must hold."""
    rule = spec["check"]
    if rule.get("checker_files"):
        _write(folder, rule["checker_files"])
    if "command" in rule:
        ok, output = _command(rule["command"], folder)
        if not ok:
            return False, f"command failed: {output}"
    if "file" in rule:
        path = folder / rule["file"]
        if not path.exists():
            return False, f"{rule['file']} was not written"
        import re

        if "matches" in rule and not re.search(rule["matches"], path.read_text(encoding="utf-8")):
            return False, f"{rule['file']} does not match {rule['matches']}"
    memory = extra.get("memory", "").lower()  # everything the app remembered, as JSON
    for text in rule.get("memory_has", []):
        if text.lower() not in memory:
            return False, f"nothing remembered mentions {text!r}: {memory[:300]}"
    for text in rule.get("memory_lacks", []):
        if text.lower() in memory:
            return False, f"a memory mentions {text!r}, which is not worth keeping: {memory[:300]}"
    kept = extra.get("session_memory", {})  # each session's own memory, as JSON
    for session, texts in rule.get("session_memory_has", {}).items():
        for text in texts:
            if text.lower() not in kept.get(session, "").lower():
                return False, f"the memory of {session} does not mention {text!r}: {kept.get(session, '')[:300]}"
    for text in rule.get("reply_contains", []):
        if text.lower() not in (replies[-1] if replies else "").lower():
            return False, f"the last reply does not mention {text!r}"
    if "signals_ok" in rule and extra.get("signals_ok", 0) < rule["signals_ok"]:
        return False, f"signals were valid in {extra.get('signals_ok', 0)} of {len(replies)} replies"
    if "schedules" in rule and extra.get("schedules", 0) != rule["schedules"]:
        return False, f"{extra.get('schedules', 0)} schedules instead of {rule['schedules']}"
    return True, "ok"


def run_one(spec: dict, settings: dict, *, compact_between_turns: bool = False) -> dict:
    from .server import start

    root = Path(tempfile.mkdtemp(prefix=f"sm-eval-{spec['name']}-"))
    work = root / "work"
    work.mkdir()
    _write(work, spec.get("files", {}))
    server = start(root / "home")
    client = BrainClient(server.url, server.token)
    started = time.time()
    replies: List[str] = []
    extra: dict = {}
    error = None
    try:
        client.update_config(**settings)
        client.declare_app("eval", name="SentientMilk", environment=spec.get(
            "environment", "You work on the user's computer, in the working folder named below."),
            toolkits=spec.get("toolkits", DEFAULT_TOOLKITS), **({"signals": spec["signals"]} if spec.get("signals") else {}))
        client.update_session("eval", "main", cwd=str(work), roots=[str(work)])
        client.update_app("eval", rules={"allow": ["*"]})  # a throw-away folder: no approvals needed
        if spec.get("kind", "task") == "task":
            task = client.start_task("eval", spec["prompt"], session="main", max_steps=spec.get("max_steps", 80))
            deadline = started + spec.get("timeout", 1200)
            while client.run(task["id"])["status"] not in ("completed", "failed", "cancelled"):
                if time.time() > deadline:
                    client.cancel(task["id"])
                    raise TimeoutError("the task ran out of time")
                time.sleep(2)
            run = client.run(task["id"])
            replies.append((run["result"] or {}).get("reply", ""))
            if run["status"] != "completed":
                error = (run["error"] or {}).get("message", run["status"])
            runs = [run]
        else:
            runs = []
            screenshot = _screenshot() if spec.get("screenshot") else None
            for index, prompt in enumerate(spec["turns"]):
                session = spec.get("sessions", ["main"] * len(spec["turns"]))[index]
                result = client.turn("eval", session, prompt, image=screenshot, context={"user": "Tester"},
                                     max_steps=spec.get("max_steps"))
                replies.append(result["reply"])
                extra["signals_ok"] = extra.get("signals_ok", 0) + bool(result["signals"])
                runs.append(client.run(result["run"]))
                if compact_between_turns and index < len(spec["turns"]) - 1:
                    client.compact_session("eval", session)
            extra["schedules"] = len(client.schedules("eval"))
            extra["memory"] = json.dumps(server.brain.store.memories(), ensure_ascii=False)
            extra["session_memory"] = {session: json.dumps(server.brain.session_info("eval", session)["session_memory"],
                                                           ensure_ascii=False)
                                       for session in set(spec.get("sessions", ["main"]))}
        passed, why = (False, error) if error else check(spec, work, replies, extra)
    except Exception as exc:
        passed, why, runs = False, f"{type(exc).__name__}: {exc}", []
    events = [e for r in runs for e in server.brain.store.run_events(r["id"])]
    usage = {key: sum((r.get("usage") or {}).get(key) or 0 for r in runs)
             for key in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens")}
    tools = server.brain.toolset(server.brain.profile("eval", "main"), spec.get("kind", "task")).by_name
    readonly = {name for name, item in tools.items() if item.readonly}
    compactions = sum(e["type"] == "compaction" for session in {r["session"] for r in runs}
                      for e in server.brain.store.events("eval", session))
    result = {"name": spec["name"], "holdout": spec.get("holdout", False), "passed": passed, "why": why,
              "mode": "forced_compaction" if compact_between_turns else "baseline", "compactions": compactions,
              "seconds": round(time.time() - started, 1), "steps": usage["calls"],
              "tool_calls": sum(e["type"] == "tool" for e in events),
              "mutating_tool_calls": sum(e["type"] == "tool" and e.get("name") not in readonly for e in events),
              "tool_errors": sum(e["type"] == "tool" and e.get("status") == "error" for e in events),
              "prompt_tokens": usage["prompt_tokens"], "cached_tokens": usage["cached_tokens"],
              "completion_tokens": usage["completion_tokens"], "folder": str(root)}
    server.close()
    if passed:
        shutil.rmtree(root, ignore_errors=True)
    return result


def main(names: Optional[List[str]] = None, model: str = "", report: str = "", *, context_pair: bool = False) -> None:
    values = BrainConfig(default_home() / "config.json").values()
    if not values["api_key"]:
        raise SystemExit("Set the provider key first: sentientmilk config api_key")
    settings = {key: values[key] for key in COPIED_SETTINGS}
    if model:
        settings["model"] = model
    results = []
    print(f"{'task':<26} {'mode':<17} {'result':<6} {'time':>6} {'steps':>5} {'tools':>5} "
          f"{'errors':>6} {'cache':>6}  why")
    for spec in load(names):
        paired = context_pair and spec.get("kind", "task") == "chat"
        for compact in (False, True) if paired else (False,):
            result = run_one(spec, settings, compact_between_turns=compact)
            results.append(result)
            cache = f"{result['cached_tokens'] / result['prompt_tokens']:.0%}" if result["prompt_tokens"] else "-"
            print(f"{result['name'] + (' (holdout)' if result['holdout'] else ''):<26} {result['mode']:<17} "
                  f"{'PASS' if result['passed'] else 'FAIL':<6} {result['seconds']:>5}s {result['steps']:>5} "
                  f"{result['tool_calls']:>5} {result['tool_errors']:>6} {cache:>6}  "
                  f"{'' if result['passed'] else result['why'][:300] + ' (kept in ' + result['folder'] + ')'}",
                  flush=True)
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    if report:
        Path(report).write_text(json.dumps(results, indent=2), encoding="utf-8")
