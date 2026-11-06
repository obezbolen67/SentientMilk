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
    assert "mcp__test__add" in tools
