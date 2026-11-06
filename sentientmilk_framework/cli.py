"""The ``sentientmilk`` command.

    sentientmilk                             the control panel: status, provider, apps, work, tools
    sentientmilk serve [--port N] [--log]   run the brain (apps start it on their own when needed)
    sentientmilk config [KEY=VALUE...]       show or change settings; a bare api_key or web_search_key
                                             asks for the secret without echoing it
    sentientmilk chat [--session ID]         talk to the brain here, with this folder open to it
    sentientmilk tasks [show|cancel ID]      background tasks
    sentientmilk schedules [delete ID]       schedules
    sentientmilk journal [QUERY] [--delete ID]
    sentientmilk mcp [add NAME --url URL | add NAME -- COMMAND ARGS... | remove NAME]
    sentientmilk stats                       tokens and cache hits per app
    sentientmilk eval [NAME...]              run the evaluation tasks against the configured model
"""

import argparse
import getpass
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .client import connect, default_home, record_launch
from .config import DEFAULTS, SECRETS
from .exceptions import BrainError

CLI_APP = "cli"
CLI_DECLARATION = {
    "name": "SentientMilk",
    "environment": "You are talking with the user in a text terminal on their computer. Format replies as short "
                   "Markdown; show commands and code in fenced blocks.",
    "toolkits": ["files", "shell", "web", "todo", "memory", "journal", "agents", "tasks", "schedule", "mcp:*"],
}


def _parse_change(item: str):
    key, has_value, raw = item.partition("=")
    if key not in DEFAULTS:
        raise SystemExit(f"Unknown setting {key!r}. Settings: {', '.join(DEFAULTS)}")
    if not has_value:
        if key not in SECRETS:
            raise SystemExit(f"Give a value: {key}=...")
        return key, getpass.getpass(f"{key}: ")
    return key, raw if isinstance(DEFAULTS[key], str) else json.loads(raw)


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


class _ChatView:
    """Prints a turn as it streams: text, tools, approvals."""

    def __init__(self):
        self.streamed, self.run = False, None

    def event(self, event: dict) -> None:
        kind = event["type"]
        self.run = event.get("run", self.run)
        if kind == "text.delta":
            if not self.streamed:
                print()
            self.streamed = True
            print(event["text"], end="", flush=True)
        elif kind == "tool.start":
            arguments = json.dumps(event.get("arguments"), ensure_ascii=False)
            print(f"\n  -> {event['name']} {arguments[:160]}", flush=True)
            self.streamed = False
        elif kind == "tool.end" and event["status"] == "error":
            print(f"  !! {event['result'][:300]}", flush=True)
        elif kind == "retry":
            print(f"\n  .. provider problem ({event['error']['type']}), retrying in {event['wait']} s", flush=True)
        elif kind == "question.requested":
            print(f"\n  ?? {event.get('source')}: {event.get('message')}", flush=True)

    @staticmethod
    def approve(event: dict):
        arguments = json.dumps(event.get("arguments"), ensure_ascii=False, indent=1)
        print(f"\n  The brain wants to run {event['name']}:\n{arguments[:2000]}")
        while True:
            choice = input("  Allow? [y]es / [a]lways / [n]o: ").strip().lower()
            if choice in ("y", "yes"):
                return "allow"
            if choice in ("a", "always"):
                return "always"
            if choice in ("n", "no"):
                return "deny", input("  Why not (optional): ").strip()


def _notifications(client, app: str) -> None:
    after = -1  # only what happens from now on
    while True:
        try:
            for notification in client.events(app, after):
                after = notification["id"]
                if notification["type"] in ("task.completed", "task.failed", "task.input_required", "schedule.fired",
                                            "job.finished"):
                    data = notification["data"]
                    detail = data.get("text") or data.get("goal") or data.get("command") or ""
                    print(f"\n[{notification['type']}] {detail[:200]}", flush=True)
        except BrainError:
            time.sleep(5)


def _chat(client, session: str) -> None:
    client.declare_app(CLI_APP, **CLI_DECLARATION)
    folder = os.getcwd()
    client.update_session(CLI_APP, session, cwd=folder, roots=[folder])
    threading.Thread(target=_notifications, args=(client, CLI_APP), daemon=True).start()
    print(f"Talking to the brain in {folder}. /clear forgets this conversation, /tasks lists tasks, /exit leaves.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text in ("/exit", "/quit"):
            return
        if text == "/clear":
            client.clear_history(CLI_APP, session)
            print("Conversation cleared.")
            continue
        if text == "/tasks":
            for task in client.tasks(CLI_APP):
                print(f"  {task['id']} {task['status']}: {task['options'].get('goal', '')[:100]}")
            continue
        if not text:
            continue
        view = _ChatView()
        try:
            result = client.turn(CLI_APP, session, text, context={"user": getpass.getuser()},
                                 on_event=view.event, on_approval=view.approve)
            if not view.streamed:
                print("\n" + result["reply"])
            else:
                print()
        except KeyboardInterrupt:
            if view.run:
                client.cancel(view.run)
            print("\n(interrupted: the brain stops after its current step)")
        except BrainError as exc:
            print(f"\n[{exc.type}] {exc.message}" + (f"\n{exc.details}" if exc.details else ""))


def _tasks(client, args) -> None:
    if args.action == "show":
        _print(client.run(args.id))
    elif args.action == "cancel":
        client.cancel(args.id)
        print(f"Task {args.id} stops after its current step.")
    else:
        for task in client.tasks():
            print(f"{task['id']:>5} {task['app']:<12} {task['status']:<15} {task['options'].get('goal', '')[:80]}")


def _mcp(client, args) -> None:
    servers = client.mcp()["servers"]
    if args.action == "add":
        if args.url:
            spec = {"url": args.url, **({"headers": dict(h.split("=", 1) for h in args.header)} if args.header else {})}
        elif args.server_command:
            spec = {"command": args.server_command[0], "args": args.server_command[1:]}
        else:
            raise SystemExit("Give --url URL or -- COMMAND ARGS...")
        if args.env:
            spec["env"] = dict(e.split("=", 1) for e in args.env)
        servers[args.name] = spec
        client.set_mcp(servers)
    elif args.action == "remove":
        servers.pop(args.name, None)
        client.set_mcp(servers)
    time.sleep(1 if args.action != "list" else 0)
    _print(client.mcp())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="sentientmilk", description="SentientMilk: the brain your apps use. "
                                     "Without a command it opens the control panel.")
    parser.add_argument("--home", help="the brain's home folder (default: SENTIENTMILK_HOME or ~/.sentientmilk)")
    parser.add_argument("--version", action="version", version=f"SentientMilk {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("panel", help="the control panel (the default)")
    serve = commands.add_parser("serve", help="run the brain server")
    serve.add_argument("--port", type=int, default=0, help="fixed port (default: any free port)")
    serve.add_argument("--log", action="store_true", help="log to brain.log in the home folder")
    config = commands.add_parser("config", help="show or change the brain's settings")
    config.add_argument("changes", nargs="*", metavar="KEY=VALUE")
    chat = commands.add_parser("chat", help="talk to the brain in this terminal")
    chat.add_argument("--session", default="main")
    tasks = commands.add_parser("tasks", help="background tasks")
    tasks.add_argument("action", nargs="?", choices=("list", "show", "cancel"), default="list")
    tasks.add_argument("id", nargs="?", type=int)
    schedules = commands.add_parser("schedules", help="schedules")
    schedules.add_argument("action", nargs="?", choices=("list", "delete"), default="list")
    schedules.add_argument("id", nargs="?", type=int)
    journal = commands.add_parser("journal", help="the brain's notes about sessions")
    journal.add_argument("query", nargs="?", default="")
    journal.add_argument("--delete", type=int, metavar="ID")
    mcp = commands.add_parser("mcp", help="MCP servers")
    mcp.add_argument("action", nargs="?", choices=("list", "add", "remove"), default="list")
    mcp.add_argument("name", nargs="?")
    mcp.add_argument("--url")
    mcp.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    mcp.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    mcp.add_argument("server_command", nargs=argparse.REMAINDER, metavar="-- COMMAND ARGS")
    commands.add_parser("stats", help="tokens and cache hits per app")
    evaluate = commands.add_parser("eval", help="run evaluation tasks against the configured model")
    evaluate.add_argument("names", nargs="*")
    evaluate.add_argument("--model", default="")
    evaluate.add_argument("--report", default="", help="write the results as JSON here")
    args = parser.parse_args(argv)
    home = Path(args.home or default_home()).expanduser().resolve()
    record_launch(home)

    logging.basicConfig(level=logging.WARNING if args.command != "serve" else logging.INFO,
                        format="%(asctime)s [SentientMilk] %(message)s")
    if args.command == "serve":
        from .server import serve as run

        return run(home, port=args.port, log_file=args.log)
    if args.command in (None, "panel"):
        from .panel import run as run_panel

        return run_panel(home)
    if args.command == "eval":
        from .evals import main as run_evals

        return run_evals(args.names, model=args.model, report=args.report)
    client = connect(home)
    if args.command == "config":
        if args.changes:
            client.update_config(**dict(_parse_change(item) for item in args.changes))
        _print(client.config())
    elif args.command == "chat":
        _chat(client, args.session)
    elif args.command == "tasks":
        _tasks(client, args)
    elif args.command == "schedules":
        if args.action == "delete":
            client.delete_schedule(args.id)
        for schedule in client.schedules():
            print(f"{schedule['id']:>4} {schedule['app']:<10} {schedule['kind']:<6} {schedule['spec']:<18} "
                  f"{schedule['payload']['mode']:<5} {schedule['payload']['text'][:60]}")
    elif args.command == "journal":
        if args.delete:
            client.delete_note(args.delete)
        for note in client.journal(args.query):
            print(f"{note['id']:>4} {time.strftime('%Y-%m-%d %H:%M', time.localtime(note['at']))} "
                  f"[{note['app']}] {note['note']}")
    elif args.command == "mcp":
        if args.server_command[:1] == ["--"]:
            args.server_command = args.server_command[1:]
        _mcp(client, args)
    elif args.command == "stats":
        _print(client.stats())


if __name__ == "__main__":
    main(sys.argv[1:])
