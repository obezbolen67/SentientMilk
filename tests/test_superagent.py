"""Super agents: agents Claude does through the user's Claude Code (superagent.py), here a stand-in that speaks
its stream-json protocol. To the lead they are agents: approvals, reports, messages and stopping work the same."""

import json
import sys
import textwrap

import pytest
from conftest import turn, wait_for

from sentientmilk_framework import BrainError
from sentientmilk_framework.toolkits.agents import agent_start

# Claude Code's headless protocol, as far as SentientMilk uses it. What the prompt says decides what it does.
FAKE = textwrap.dedent('''
    import json, os, sys, time
    args = sys.argv[1:]
    mcp = json.load(open(args[args.index("--mcp-config") + 1])) if "--mcp-config" in args else None
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"args": args, "cwd": os.getcwd(), "mcp": mcp}) + "\\n")
    resumed = args[args.index("--resume") + 1] if "--resume" in args else None
    session = resumed or "claude-session-1"

    def out(event):
        sys.stdout.write(json.dumps(event) + "\\n")
        sys.stdout.flush()

    def said(text):
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})

    def result(text):
        out({"type": "result", "subtype": "success", "is_error": False, "result": text, "num_turns": 2,
             "session_id": session, "total_cost_usd": 0.01,
             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100,
                       "output_tokens": 7}})

    def message():
        for line in sys.stdin:
            event = json.loads(line)
            if event["type"] == "user":
                return event["message"]["content"]
            if event["type"] == "control_response":
                return event["response"]["response"]
        sys.exit(0)

    out({"type": "system", "subtype": "init", "session_id": session})
    while True:
        text = message()
        if "crash" in text:
            sys.stderr.write("boom\\n")
            sys.exit(3)
        if "write" in text:
            path = os.path.join(os.getcwd(), "out.txt")
            out({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {"file_path": path, "content": "made"}}]}})
            out({"type": "control_request", "request_id": "r1", "request": {
                "subtype": "can_use_tool", "tool_name": "Write", "tool_use_id": "toolu_1",
                "input": {"file_path": path, "content": "made"}}})
            answer = message()
            if answer["behavior"] == "allow":
                open(path, "w").write(answer["updatedInput"]["content"])
                out({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "File created"}]}})
                said("Wrote out.txt.")
                result("Wrote out.txt.")
            else:
                out({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": answer["message"], "is_error": True}]}})
                result("Could not write: " + answer["message"])
        elif "slow" in text:
            time.sleep(60)
        elif "wait" in text:
            said("Waiting for the lead.")
            result("got: " + message())
        else:
            result(("resumed " if resumed else "") + "echo: " + text.splitlines()[-1])
''')


def calls(*items) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        for name, arguments, call_id in items]}


@pytest.fixture
def claude(brain, tmp_path, monkeypatch):
    """The stand-in Claude Code; ``claude.started()`` lists how each process was started."""
    script, log = tmp_path / "fake_claude.py", tmp_path / "claude.log"
    script.write_text(FAKE, encoding="utf-8")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setattr(brain.brain.superagents, "argv", lambda: [sys.executable, str(script)])
    started = lambda: [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]  # noqa: E731
    return type("Claude", (), {"started": staticmethod(started)})


def start_super(brain, task, name="coder"):
    """A turn of the lead that starts one super agent."""
    def route(payload):
        if payload["messages"][-1]["role"] != "tool":
            return calls(("agent_start", {"name": name, "task": task, "super_agent": True}, "s"))
        return "Started."
    brain.provider.replies += [route] * 2
    turn(brain, "cli", "do it")
    return brain.store.runs(kind="agent")[0]


def ended(brain, run_id):
    """The run once it ended (a stopped agent's runs are deleted with it: then a stand-in)."""
    def check():
        run = brain.store.run(run_id)
        return run is None and {"status": "deleted"} or run["status"] in ("completed", "failed", "cancelled") and run
    return wait_for(check)


def test_the_lead_is_told_it_has_super_agents_and_how_to_start_one(brain, claude):
    brain.provider.replies += ["hi"]
    turn(brain, "cli", "hello")
    system = brain.provider.sent[-1]["messages"][0]["content"]
    assert "Super agents: Opus 5.5" in system and "super_agent=true" in system
    assert agent_start.parameters["properties"]["super_agent"]["type"] == "boolean"

    brain.client.update_config(super_model="")  # turned off: no rule
    brain.provider.replies += ["hi"]
    turn(brain, "cli", "hello")
    assert "Super agents:" not in brain.provider.sent[-1]["messages"][0]["content"]
    with pytest.raises(Exception, match="turned super agents off"):
        brain.brain.agents.start(brain.store.runs(kind="turn")[0], "x", "Do.", super_agent=True)


def test_a_super_agent_writes_with_the_users_approval_and_reports_to_the_lead(brain, claude):
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"no_push": "Never push."}})
    run = start_super(brain, "Please write out.txt.")
    asked = wait_for(lambda: [n for n in brain.store.notifications("cli") if n["type"] == "agent.input_required"])
    assert asked[0]["data"]["name"] == "coder"
    waiting = wait_for(lambda: brain.client.run(run["id"])["waiting"])
    assert [w["name"] for w in waiting] == ["Write"] and waiting[0]["call_id"] == "toolu_1"
    assert brain.client.agents("cli", "main")[0]["status"] == "waiting"
    brain.client.answer(run["id"], call_id="toolu_1", decision="allow")
    done = ended(brain, run["id"])
    assert done["status"] == "completed" and done["result"]["reply"] == "Wrote out.txt."
    assert (brain.work / "out.txt").read_text() == "made"
    args = claude.started()[0]["args"]
    assert args[args.index("--model") + 1] == "claude-opus-5-5" and args[args.index("--effort") + 1] == "high"
    assert "--restricted" in args and "--permission-prompt-tool" in args
    assert "## THE CHAT'S MEMORY" in args[args.index("--append-system-prompt") + 1]  # the chat's rules hold for it
    assert "- no_push: Never push." in args[args.index("--append-system-prompt") + 1]
    assert claude.started()[0]["cwd"] == str(brain.work)
    steps = brain.client.agent(run["id"])["steps"]
    assert [(s["name"], s["status"]) for s in steps] == [("Write", "ok")]
    usage = done["usage"]
    assert usage["prompt_tokens"] == 115 and usage["cached_tokens"] == 100 and usage["cost_usd"] == 0.01
    agent = brain.client.agents("cli", "main", all=True)[0]
    assert agent["super"] == "Opus 5.5" and agent["report"] == "Wrote out.txt."


def test_a_super_agent_has_the_leads_mcp_servers(brain, claude, monkeypatch):
    # code in an app the user connected (a game editor) is Claude's too, checked there (2026-11-09)
    from sentientmilk_framework.mcp_host import _Server

    host = brain.brain.mcp
    studio = _Server("studio", {"command": "cmd.exe", "args": ["/c", "mcp.bat"], "env": {"KEY": "k"}})
    studio.state = "connected"
    broken = _Server("broken", {"url": "http://x"})  # failed: the lead does not have it either
    monkeypatch.setattr(host, "_servers", {"studio": studio, "broken": broken})
    assert host.for_claude(["mcp:studio", "mcp:broken"]) == {
        "studio": {"type": "stdio", "command": "cmd.exe", "args": ["/c", "mcp.bat"], "env": {"KEY": "k"}}}
    assert host.for_claude(["files"]) == {}  # turned off for the app

    monkeypatch.setattr(host, "for_claude", lambda kits: {"studio": {"type": "stdio", "command": "x", "args": []}})
    run = start_super(brain, "Say done.")
    assert ended(brain, run["id"])["status"] == "completed"
    started = claude.started()[0]
    assert started["mcp"] == {"mcpServers": {"studio": {"type": "stdio", "command": "x", "args": []}}}
    assert "--strict-mcp-config" in started["args"]
    assert not list(brain.brain.home.glob("super-mcp-*.json"))  # its keys do not stay on disk


def test_the_brains_rules_decide_for_claudes_tools(brain, claude):
    brain.client.update_app("cli", rules={"deny": ["files_write(*)"]})
    run = start_super(brain, "Please write out.txt.")
    done = ended(brain, run["id"])
    assert "not allowed" in done["result"]["reply"] and not (brain.work / "out.txt").exists()
    assert not brain.store.notifications("cli") or not [
        n for n in brain.store.notifications("cli") if n["type"] == "agent.input_required"]
    brain.client.update_app("cli", rules={"allow": ["files_write(*)"]})  # allowed: nobody is asked
    run = start_super(brain, "Please write out.txt.", name="second")
    assert ended(brain, run["id"])["result"]["reply"] == "Wrote out.txt."


def test_a_message_resumes_a_finished_super_agent_and_steers_a_working_one(brain, claude):
    run = start_super(brain, "Say hello.")
    assert ended(brain, run["id"])["result"]["reply"] == "echo: Say hello."
    lead = brain.store.runs(kind="turn")[0]
    brain.brain.agents.message(lead, "coder", "And now?")
    second = wait_for(lambda: [r for r in brain.store.runs(kind="agent") if r["id"] != run["id"]])[0]
    assert ended(brain, second["id"])["result"]["reply"] == "resumed echo: And now?"
    args = claude.started()[-1]["args"]
    assert args[args.index("--resume") + 1] == "claude-session-1"

    working = start_super(brain, "Please wait for me.", name="waiter")
    wait_for(lambda: brain.client.agents("cli", "main")[0]["step"] >= 1)  # it said it waits
    brain.brain.agents.message(lead, "waiter", "Here it is.")
    assert "Here it is." in ended(brain, working["id"])["result"]["reply"]


def test_stopping_a_super_agent_ends_its_claude_code(brain, claude):
    run = start_super(brain, "Be slow.")
    work = wait_for(lambda: brain.brain.superagents._live.get(run["id"]))
    wait_for(lambda: work.process is not None)
    brain.client.stop_agent(run["id"])
    assert ended(brain, run["id"])["status"] in ("cancelled", "deleted")
    wait_for(lambda: work.process.poll() is not None)
    wait_for(lambda: not brain.brain.superagents._live)


def test_a_claude_code_that_dies_fails_the_agent_with_what_it_said(brain, claude):
    run = start_super(brain, "Please crash.")
    done = ended(brain, run["id"])
    assert done["status"] == "failed" and "stopped before it finished" in done["error"]["message"]
    assert "boom" in done["error"]["details"]


def test_without_claude_code_a_super_agent_is_refused_with_why(brain, monkeypatch):
    monkeypatch.setattr(brain.brain.superagents, "argv", lambda: [])
    with pytest.raises(Exception, match="Claude Code is not installed"):
        brain.brain.agents.start({"app": "cli", "session": "main", "id": 0, "options": {}}, "x", "Do.",
                                 super_agent=True)
    assert brain.brain.profile("cli", "main")["super"] == ""


def test_every_effort_can_be_set_and_nothing_else(brain):
    for effort in ("low", "medium", "high", "xhigh", "max"):
        assert brain.client.update_config(super_effort=effort)["super_effort"] == effort
    with pytest.raises(BrainError):
        brain.client.update_config(super_effort="turbo")
    status = brain.client.config()["super"]
    assert status["efforts"] == ["low", "medium", "high", "xhigh", "max"] and status["label"] == "Opus 5.5"
