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
    if resumed == "gone-session":  # Claude Code deleted it (it keeps them 30 days)
        sys.stderr.write("No conversation found with session ID: gone-session\\n")
        sys.stdout.write(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                     "num_turns": 0, "session_id": resumed}) + "\\n")
        sys.exit(1)

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
            if event["type"] == "user":  # taken in: it says so (--replay-user-messages)
                out({"type": "user", "isReplay": True, "message": event["message"]})
                return event["message"]["content"]
            if event["type"] == "control_response":
                return event["response"]["response"]
        sys.exit(0)

    out({"type": "system", "subtype": "init", "session_id": session})
    while True:
        text = message()
        if "brain restarted" in text:  # it goes on where it was: in these tests, the write
            text = "write"
        if "is gone" in text:
            result("anew: " + " | ".join(text.splitlines()))
            continue
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
        elif "mcp" in text:
            out({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_2", "name": "mcp__editor__save", "input": {"scene": "main"}}]}})
            out({"type": "control_request", "request_id": "r2", "request": {
                "subtype": "can_use_tool", "tool_name": "mcp__editor__save", "tool_use_id": "toolu_2",
                "input": {"scene": "main"}}})
            answer = message()
            result("saved" if answer["behavior"] == "allow" else "refused")
        elif "race" in text:  # it finishes only once the test has sent it a message
            said("Part A.")
            while not os.path.exists(os.environ["FAKE_GO"]):
                time.sleep(0.02)
            result("Did A.")
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


def test_a_super_agent_writes_with_the_users_approval_and_reports_to_the_lead(brain, claude, monkeypatch):
    brain.store.update_session("cli", "main", "state", lambda s: {**s, "session_memory": {"no_push": "Never push."}})
    brain.store.remember("milk", "preferences", "tests", "Always run the tests before saying done.")
    run = start_super(brain, "Please write out.txt.")
    asked = wait_for(lambda: [n for n in brain.store.notifications("cli") if n["type"] == "agent.input_required"])
    assert asked[0]["data"]["name"] == "coder"
    waiting = wait_for(lambda: brain.client.run(run["id"])["waiting"])
    assert [w["name"] for w in waiting] == ["Write"] and waiting[0]["call_id"] == "toolu_1"
    assert brain.client.agents("cli", "main")[0]["status"] == "waiting"
    spawned, spawn = [], brain.brain.runs.spawn
    monkeypatch.setattr(brain.brain.runs, "spawn", lambda run_id: (spawned.append(run_id), spawn(run_id)))
    brain.client.answer(run["id"], call_id="toolu_1", decision="allow")
    done = ended(brain, run["id"])
    assert run["id"] not in spawned  # the answer woke it where it waits: no thread started to find it busy
    assert done["status"] == "completed" and done["result"]["reply"] == "Wrote out.txt."
    assert (brain.work / "out.txt").read_text() == "made"
    args = claude.started()[0]["args"]
    assert args[args.index("--model") + 1] == "claude-opus-5-5" and args[args.index("--effort") + 1] == "high"
    assert "--restricted" in args and "--permission-prompt-tool" in args
    assert "## THE CHAT'S MEMORY" in args[args.index("--append-system-prompt") + 1]  # the chat's rules hold for it
    assert "- no_push: Never push." in args[args.index("--append-system-prompt") + 1]
    assert "- tests: Always run the tests before saying done. [milk]" in args[args.index("--append-system-prompt") + 1]
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


def test_always_allowing_a_tool_the_brain_has_no_name_for_saves_a_rule(brain, claude):
    """Only Claude's Bash, Write, Edit... had rules: an MCP tool allowed always was asked again each time."""
    run = start_super(brain, "Please use mcp.")
    waiting = wait_for(lambda: brain.client.run(run["id"])["waiting"])
    assert [w["name"] for w in waiting] == ["mcp__editor__save"]
    brain.client.answer(run["id"], call_id="toolu_2", decision="always")
    assert ended(brain, run["id"])["result"]["reply"] == "saved"
    assert "mcp__editor__save" in brain.store.app("cli")["settings"]["rules"]["allow"]
    again = start_super(brain, "Please use mcp.", name="again")
    assert ended(brain, again["id"])["result"]["reply"] == "saved"  # nobody was asked
    assert not brain.client.run(again["id"])["waiting"]


def test_a_super_agent_whose_claude_code_session_is_gone_starts_anew_with_what_it_knew(brain, claude):
    """Claude Code deletes old sessions: a message to an agent of a month ago failed then, and every one after."""
    run = start_super(brain, "Say hello.")
    assert ended(brain, run["id"])["result"]["reply"] == "echo: Say hello."
    brain.store.update_session("cli", run["session"], "state", lambda s: {**s, "claude_session": "gone-session"})
    brain.brain.agents.message(brain.store.runs(kind="turn")[0], "coder", "And now?")
    second = wait_for(lambda: [r for r in brain.store.runs(kind="agent") if r["id"] != run["id"]])[0]
    done = ended(brain, second["id"])
    reply = done["result"]["reply"]
    assert done["status"] == "completed" and reply.startswith("anew: [The Claude Code session you worked in is gone")
    assert "Your task: | Say hello." in reply and "Your last report: | echo: Say hello." in reply
    assert "| Now: |" in reply and reply.endswith("[A message from the lead] | And now?")
    resumed, fresh = claude.started()[-2:]
    assert resumed["args"][resumed["args"].index("--resume") + 1] == "gone-session" and "--resume" not in fresh["args"]
    assert brain.store.session("cli", run["session"])["state"]["claude_session"] == "claude-session-1"


def test_a_message_that_comes_as_a_super_agent_finishes_is_its_next_turn(brain, claude, tmp_path, monkeypatch):
    """Sent to Claude Code as it wrote its last words, the message was its next turn: the run ended before it."""
    go = tmp_path / "go"
    monkeypatch.setenv("FAKE_GO", str(go))
    run = start_super(brain, "Please race.")
    wait_for(lambda: brain.client.agents("cli", "main")[0]["step"] >= 1)  # it said Part A. and finishes on go
    brain.brain.agents.message(brain.store.runs(kind="turn")[0], "coder", "Also B.")
    wait_for(lambda: any(e["type"] == "input" and "Also B." in str(e["content"])
                         for e in brain.store.run_events(run["id"])))  # sent on to Claude Code
    go.write_text("", encoding="utf-8")
    done = ended(brain, run["id"])
    assert done["status"] == "completed" and done["result"]["reply"] == "echo: Also B."


def test_a_super_agent_waiting_for_the_user_when_the_brain_restarts_asks_again(brain, claude):
    """Its Claude Code went with the brain: the old question had nobody to answer it, and the run waited on."""
    run = brain.store.add_run("cli", "agent-90", "agent", {"input": None, "agent": 90, "parent_session": "main",
                                                           "super": True, "profile": {"from_session": "main"}},
                              status="input_required")
    brain.store.update_session("cli", "agent-90", "settings", lambda s: {"title": "coder", "agent": {
        "name": "coder", "parent": "main", "task": "Please write out.txt.", "created": 0, "super": "Opus 5.5"}})
    brain.store.update_session("cli", "agent-90", "state",
                               lambda s: {"claude_session": "claude-session-1", "claude_run": run})
    brain.store.add_event("cli", "agent-90", run, "input", {"content": "Please write out.txt.", "display": "x"})
    brain.store.add_event("cli", "agent-90", run, "approval_request",
                          {"call_id": "toolu_old", "name": "Write", "arguments": {"file_path": "out.txt"}})
    brain.brain.runs.recover()
    asked = wait_for(lambda: brain.client.run(run)["waiting"])
    assert [w["call_id"] for w in asked] == ["toolu_1"]  # its new Claude Code asks again; the old one is closed
    assert "--resume" in claude.started()[0]["args"]
    brain.client.answer(run, call_id="toolu_1", decision="allow")
    assert ended(brain, run)["status"] == "completed"
    closed = [e for e in brain.store.run_events(run) if e["type"] == "tool" and e["call_id"] == "toolu_old"]
    assert len(closed) == 1 and "restarted" in closed[0]["content"]


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
