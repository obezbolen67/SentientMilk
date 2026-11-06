import base64
import io
import json
import socket
import sys

import pytest
import requests
from conftest import turn, wait_for
from PIL import Image

from sentientmilk_framework import BrainClient, BrainError, connect
from sentientmilk_framework import signals as signal_format
from sentientmilk_framework.client import launch_command, own_command, record_launch
from sentientmilk_framework.server import AlreadyRunning, start
from sentientmilk_framework.testing import PROVIDER_URL


def png(size=(64, 36)):
    output = io.BytesIO()
    Image.effect_noise(size, 60).convert("RGB").save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def user_text(message):
    content = message["content"]
    return content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content)


def test_every_request_needs_the_token(brain):
    assert requests.get(f"{brain.server.url}/v1/health").status_code == 401
    wrong = requests.get(f"{brain.server.url}/v1/config", headers={"Authorization": "Bearer guess"})
    assert wrong.status_code == 401
    assert brain.client.health()["api"] == 2


def test_settings_hide_secrets_and_reject_bad_values_whole(brain):
    public = brain.client.config()
    assert public["api_key_set"] is True and "api_key" not in public
    assert "sk-test-secret" not in json.dumps(public)
    for bad in ({"base_url": "ftp://x"}, {"vision": "yes"}, {"colour": "red"}, {"shell": "fish"},
                {"thinking_mode": "tokens", "thinking_tokens": 0}, {"request_budget": 10},
                {"rules": {"allow": [""]}}, {"context_window": 10}):
        with pytest.raises(BrainError) as caught:
            brain.client.update_config(model="changed", **bad)
        assert caught.value.type == "bad_request"
    assert brain.client.config()["model"] == ""
    assert json.loads((brain.home / "config.json").read_text())["api_key"] == "sk-test-secret"


def test_a_turn_streams_the_reply_and_returns_valid_signals(brain):
    brain.provider.replies.append('{"expression": "arms_down/smile"}\nHello there!')
    result = turn(brain, "milk", "Hi!", context={"user": "Tester"})
    assert result["reply"] == "Hello there!" and result["signals"] == {"expression": "arms_down/smile"}
    deltas = "".join(e["text"] for e in result["events"] if e["type"] == "text.delta")
    assert deltas == "Hello there!"  # the signals line never shows as text
    assert any(e["type"] == "signals" for e in result["events"])
    system = brain.provider.sent[0]["messages"][0]["content"]
    who = system.partition("## ENVIRONMENT")[0].strip()
    assert who.startswith("## WHO YOU ARE\nIn this app you are called Milk.") and who.endswith("You are Milk.")
    assert "not a role you play" in who and "first person" in who  # she thinks as herself, not about a character
    assert "A desktop character." in system and "Name:" not in system
    assert "brain" not in system.lower() and "As an AI" not in system  # nothing calls her something else
    assert system.rstrip().endswith("only the final reply has this form.")  # the format rule closes the prompt
    assert "arms_down: neutral, smile" in system
    newest = user_text(brain.provider.sent[0]["messages"][-1])
    assert "user: Tester" in newest and newest.endswith(f"[{signal_format.FORMAT_REMINDER}]")
    assert brain.client.history("milk", "main") == [
        {"role": "user", "text": "Hi!", "time": pytest.approx(0, abs=1e10)},
        {"role": "assistant", "text": "Hello there!", "signals": {"expression": "arms_down/smile"},
         "time": pytest.approx(0, abs=1e10)}]


def test_history_can_include_tool_calls(brain):
    from sentientmilk_framework.testing import tool_call

    brain.client.declare_app("milk", name="Milk", toolkits=["memory"])
    brain.provider.replies += [tool_call("memory_list", {}, "m1"), "Nothing yet."]
    turn(brain, "milk", "What do you remember?")
    shown = brain.client.history("milk", "main", tools=True)
    assert [entry["role"] for entry in shown] == ["user", "tool", "assistant"]
    tool = shown[1]
    assert tool["name"] == "memory_list" and tool["call_id"] == "m1" and tool["arguments"] == {}
    assert tool["status"] == "ok" and tool["text"] and tool["seconds"] >= 0
    assert [entry["role"] for entry in brain.client.history("milk", "main")] == ["user", "assistant"]


def test_requests_only_grow_at_the_end_so_the_prefix_cache_holds(brain):
    brain.provider.replies += ['{"expression": "arms_down/smile"}\nOne', '{"expression": "one_arm/neutral"}\nTwo']
    turn(brain, "milk", "first")
    turn(brain, "milk", "second")
    first, second = brain.provider.sent[0]["messages"], brain.provider.sent[1]["messages"]
    assert second[:len(first)] == first  # the stored reminder repeats exactly
    assert second[len(first)]["role"] == "assistant"


def test_a_bad_signal_is_dropped_and_the_model_hears_about_it(brain):
    brain.provider.replies += ['{"expression": "dance/wild"}\nWheee', "plain words, no header"]
    assert turn(brain, "milk", "go")["signals"] == {}
    result = turn(brain, "milk", "again")
    assert result["reply"] == "plain words, no header" and result["signals"] == {}
    assert "is not one of the listed options" in user_text(brain.provider.sent[1]["messages"][-1])


def test_optional_replies_may_stay_silent(brain):
    brain.provider.replies.append('{"expression": "arms_down/neutral"}\n[silent]')
    result = turn(brain, "milk", None, items=[{"type": "event", "name": "idle", "text": "The user is quiet."}],
                  reply="optional")
    assert result["silent"] is True and result["reply"] == ""
    sent = user_text(brain.provider.sent[0]["messages"][-1])
    assert "[Event: idle] The user is quiet." in sent and signal_format.SILENT in sent
    assert brain.client.history("milk", "main") == []  # events and silence are not shown


def test_screenshots_are_sent_stored_small_and_switchable(brain):
    brain.provider.replies += ['{"expression": "arms_down/smile"}\nI see red', '{"expression": "arms_down/smile"}\nok']
    turn(brain, "milk", "look", image=png((1600, 900)))
    blocks = brain.provider.sent[0]["messages"][-1]["content"]
    image = next(b for b in blocks if b["type"] == "image_url")["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[1]))) as picture:
        assert max(picture.size) == 768
    brain.client.update_config(vision=False)
    turn(brain, "milk", "and now?")
    assert "image_url" not in json.dumps(brain.provider.sent[1]["messages"])
    with pytest.raises(BrainError) as caught:
        brain.client.turn("milk", "main", "x", image="data:image/png;base64,bm9wZQ==")
    assert caught.value.type == "bad_request"


def test_provider_failures_become_errors_and_busy_providers_are_retried(brain):
    brain.provider.replies += [503, '{"expression": "arms_down/smile"}\nback']
    assert turn(brain, "milk", "hi")["reply"] == "back"
    brain.provider.replies += [401]
    with pytest.raises(BrainError) as caught:
        brain.client.turn("milk", "main", "hi")
    assert caught.value.type == "auth_error"
    brain.client.update_config(api_key="")
    with pytest.raises(BrainError) as caught:
        brain.client.turn("milk", "main", "hi")
    assert caught.value.type == "config_missing"


def test_app_settings_override_the_declared_persona(brain):
    info = brain.client.update_app("milk", persona="You are grumpy Milk.")
    assert info["persona"] == "You are grumpy Milk." and info["persona_custom"]
    brain.provider.replies.append('{"expression": "arms_down/smile"}\nhm')
    turn(brain, "milk", "hi")
    assert "You are grumpy Milk." in brain.provider.sent[0]["messages"][0]["content"]
    assert brain.client.update_app("milk", persona="")["persona"] == "You are Milk."
    with pytest.raises(BrainError):
        brain.client.update_app("milk", colour="red")
    with pytest.raises(BrainError):
        brain.client.declare_app("bad", signals={"expression": {"options": []}})


def test_imported_history_fills_only_an_empty_session_and_memory_is_per_app(brain):
    messages = [{"role": "user", "content": "I am Tester"},
                {"role": "assistant", "content": '{"expression": "arms_down/smile"}\nHi Tester!'}]
    brain.client.import_history("milk", "main", messages, {"user": {"name": "Tester"}})
    assert [e["text"] for e in brain.client.history("milk", "main")] == ["I am Tester", "Hi Tester!"]
    with pytest.raises(BrainError) as caught:
        brain.client.import_history("milk", "main", messages, {})
    assert caught.value.type == "bad_request"
    assert brain.store.memories("milk") == {"user": {"name": "Tester"}}
    assert brain.store.memories("cli") == {}


def test_models_never_send_the_stored_key_elsewhere(brain, monkeypatch):
    seen = []

    def get(url, headers=None, timeout=None):
        seen.append((url, headers))
        return type("R", (), {"raise_for_status": lambda self: None,
                              "json": lambda self: {"data": [{"id": "b"}, {"id": "a"}]}})()

    monkeypatch.setattr(requests, "get", get)
    assert brain.client.models() == ["a", "b"]
    assert seen[-1] == (f"{PROVIDER_URL}/models", {"Authorization": "Bearer sk-test-secret"})
    brain.client.models(base_url="https://other.invalid/v1")
    assert seen[-1] == ("https://other.invalid/v1/models", {})


def test_one_brain_per_home_and_the_discovery_file(brain, tmp_path):
    with pytest.raises(AlreadyRunning):
        start(brain.home)
    found = BrainClient.discover(brain.home)
    assert found and found.url == brain.server.url
    other = start(tmp_path / "other")
    other.close()
    assert not (tmp_path / "other" / "server.json").exists()
    assert BrainClient.discover(tmp_path / "other") is None


def test_idle_exit_waits_for_work_streams_and_requests(brain):
    server = brain.server
    server.last_request -= 3600
    assert server.idle(30)
    brain.client.create_schedule("milk", "every 1d", "drink water")
    server.last_request -= 3600
    assert not server.idle(30)  # a schedule keeps the brain alive
    assert not server.idle(0)


def test_connect_starts_the_brain_as_its_own_process(tmp_path):
    import os
    import signal

    home = tmp_path / "spawned"
    client = connect(home)
    try:
        assert client.health()["pid"] != os.getpid()
        assert (home / "brain.lock").exists()
        assert json.loads((home / "launch.json").read_text())["command"] == own_command(home.resolve())
    finally:
        pid = client.health()["pid"]
        os.kill(pid, signal.SIGTERM)
    wait_for(lambda: not _alive(client), 15)
    # a vanished brain is started again on the next call
    assert client.health()["pid"] != pid
    client.home = None  # stopped on purpose: no new start
    client.shutdown()
    wait_for(lambda: not (home / "server.json").exists(), 15)
    assert not _alive(client)


def test_apps_start_the_brain_the_way_sentientmilk_recorded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    record_launch(home)
    assert launch_command(home) == own_command(home)
    (home / "launch.json").write_text(json.dumps({"command": [str(tmp_path / "moved.exe"), "serve"]}))
    assert launch_command(home) == own_command(home)  # a moved install: this Python can still run it
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(BrainError) as error:  # a packaged app has no brain of its own to run
        launch_command(home)
    assert "open it once" in error.value.details
    monkeypatch.setattr(sys, "frozen", False)
    runtime = tmp_path / "MilkChan" / "runtime"  # a folder made by scripts/bundle.py is packaged too
    runtime.mkdir(parents=True)
    (runtime / "bundle.json").write_text("{}")
    monkeypatch.setattr(sys, "executable", str(runtime / "pythonw.exe"))
    with pytest.raises(BrainError):
        launch_command(home)


def _alive(client):
    try:
        requests.get(f"{client.url}/v1/health", timeout=1)
        return True
    except requests.RequestException:
        return False


def test_the_server_only_listens_locally(brain):
    host, port = brain.server.server_address[:2]
    assert host == "127.0.0.1"
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
