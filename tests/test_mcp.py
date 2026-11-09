import sys

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mcp_host import public, tool_name, validate
from sentientmilk_framework.testing import tool_call

SERVER = '''
from mcp.server import MCPServer

app = MCPServer("test")


@app.tool()
def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


@app.tool()
async def slow(seconds: float) -> str:
    """Answer after a while."""
    import asyncio
    await asyncio.sleep(seconds)
    return "woke"


@app.tool()
def fail() -> str:
    """Always fails."""
    raise RuntimeError("broken on purpose")


if __name__ == "__main__":
    app.run()
'''


def test_settings_are_checked_and_secrets_hidden():
    config = validate({"servers": {"gh": {"url": "https://x.invalid/mcp", "headers": {
        "Authorization": "Bearer ${GH_TOKEN}", "X-Key": "literal-secret"}}}})
    shown = public(config)["servers"]["gh"]["headers"]
    assert shown == {"Authorization": "Bearer ${GH_TOKEN}", "X-Key": "<set>"}
    for bad in ({"servers": {"x": {}}}, {"servers": {"bad name": {"command": "a"}}},
                {"servers": {"x": {"command": "a", "url": "b"}}}):
        with pytest.raises(ValueError):
            validate(bad)
    assert tool_name("my.server", "do thing") == "mcp__my_server__do_thing"


def test_changing_servers_keeps_the_hidden_secrets_of_the_others(brain):
    brain.client.set_mcp({"gh": {"url": "https://x.invalid/mcp", "headers": {"X-Key": "literal-secret"},
                                 "enabled": False}})
    servers = brain.client.mcp()["servers"]  # what the CLI and the panel read: the key shows as <set>
    servers["other"] = {"url": "https://y.invalid/mcp", "enabled": False}
    brain.client.set_mcp(servers)
    assert brain.brain.mcp.config()["servers"]["gh"]["headers"] == {"X-Key": "literal-secret"}


def test_mcp_servers_are_toolkits_the_model_can_use(brain, tmp_path):
    pytest.importorskip("mcp")
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    brain.client.set_mcp({"test": {"command": sys.executable, "args": [str(script)]}})
    wait_for(lambda: brain.client.mcp()["status"]["test"]["state"] == "connected", 60)
    assert "mcp:test" in brain.client.toolkits()["toolkits"]
    brain.client.update_app("cli", rules={"allow": ["mcp__test__*"]})
    brain.provider.replies += [tool_call("mcp__test__add", {"a": 2, "b": 40}, "m1"),
                               tool_call("mcp__test__fail", {}, "m2"), "2 + 40 = 42"]
    brain.client.declare_app("cli", name="CLI", toolkits=["files", "mcp:*"])
    assert turn(brain, "cli", "add 2 and 40")["reply"] == "2 + 40 = 42"
    results = {m["tool_call_id"]: m["content"] for m in brain.provider.sent[2]["messages"] if m["role"] == "tool"}
    assert results["m1"] == "42" and results["m2"].startswith("Error:") and "fail" in results["m2"]
    tools = [t["function"]["name"] for t in brain.provider.sent[0]["tools"]]
    assert "mcp__test__add" not in tools  # listed, and called by name
    assert "mcp__test__add" in brain.provider.sent[0]["messages"][0]["content"].split("## YOUR TOOLS")[1]


def test_a_long_mcp_call_goes_on_as_a_job_and_a_stop_frees_the_server(brain, tmp_path, monkeypatch):
    """No time limit on a call: one still running after WAIT s goes on as a job, as a command does; her
    note brings its result, and stopping it lets the server take the next call."""
    pytest.importorskip("mcp")
    from sentientmilk_framework import mcp_host

    monkeypatch.setattr(mcp_host, "WAIT", 1)
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    brain.client.set_mcp({"test": {"command": sys.executable, "args": [str(script)]}})
    wait_for(lambda: brain.client.mcp()["status"]["test"]["state"] == "connected", 60)
    brain.client.update_app("cli", rules={"allow": ["mcp__test__*"]})
    brain.client.declare_app("cli", name="CLI", toolkits=["shell", "mcp:*"])
    brain.provider.replies += [tool_call("mcp__test__slow", {"seconds": 3}, "s1"), "It runs."]
    turn(brain, "cli", "be slow")
    said = next(m["content"] for m in brain.provider.sent[-1]["messages"] if m.get("tool_call_id") == "s1")
    assert "Still running after 1 s" in said and "background job" in said
    job = brain.store.jobs("cli", 0)[0]
    wait_for(lambda: brain.store.job(job["id"])["status"] == "finished", 30)
    assert open(job["log"], encoding="utf-8").read() == "woke"
    wait_for(lambda: any("woke" in e["text"] for e in brain.store.events("cli", "main", types=("note",))), 30)

    brain.provider.replies += [tool_call("mcp__test__slow", {"seconds": 600}, "s2"), "Stuck."]
    turn(brain, "cli", "hang")
    stuck = brain.store.jobs("cli", 0)[0]
    assert stuck["status"] == "running" and stuck["id"] != job["id"]
    brain.provider.replies += [tool_call("shell_stop", {"job": stuck["id"]}, "x1"),
                               tool_call("mcp__test__add", {"a": 1, "b": 1}, "a1"), "2."]
    turn(brain, "cli", "stop it and add")
    results = {m["tool_call_id"]: m["content"] for m in brain.provider.sent[-1]["messages"] if m["role"] == "tool"}
    assert results["x1"] == f"Stopped job {stuck['id']}." and results["a1"] == "2"
    wait_for(lambda: brain.store.job(stuck["id"])["status"] == "stopped", 30)
