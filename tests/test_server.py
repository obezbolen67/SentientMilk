import base64
import io
import json
import socket
import sys
import threading

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
                {"rules": {"allow": [""]}}, {"context_window": 10}, {"image_pixels": 5}):
        with pytest.raises(BrainError) as caught:
            brain.client.update_config(model="changed", **bad)
        assert caught.value.type == "bad_request"
    assert brain.client.config()["model"] == ""
    assert json.loads((brain.home / "config.json").read_text())["api_key"] == "sk-test-secret"


def test_the_old_default_request_budget_gives_way_to_the_new_one(tmp_path):
    from sentientmilk_framework.config import BrainConfig
    from sentientmilk_framework.transport import DEFAULT_BUDGET

    (tmp_path / "config.json").write_text(json.dumps({"request_budget": 800 * 1024, "image_pixels": 0}))
    values = BrainConfig(tmp_path / "config.json").values()
    assert values["request_budget"] == DEFAULT_BUDGET == 8 * 1024 * 1024 and values["image_pixels"] == 0
    (tmp_path / "config.json").write_text(json.dumps({"request_budget": 512 * 1024}))
    assert BrainConfig(tmp_path / "config.json").values()["request_budget"] == 512 * 1024  # a choice stays


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
    said, replied = brain.client.history("milk", "main")
    assert said["id"] < replied["id"]  # a message's id is where a return to it goes
    assert said == {"id": said["id"], "role": "user", "text": "Hi!", "time": pytest.approx(0, abs=1e10)}
    assert replied == {"id": replied["id"], "role": "assistant", "text": "Hello there!",
                       "signals": {"expression": "arms_down/smile"}, "time": pytest.approx(0, abs=1e10)}


def test_history_can_include_tool_calls(brain):
    from sentientmilk_framework.testing import tool_call

    brain.client.declare_app("milk", name="Milk", toolkits=["journal"])
    brain.provider.replies += [tool_call("journal_search", {}, "m1"), "Nothing yet."]
    turn(brain, "milk", "What do you remember?")
    shown = brain.client.history("milk", "main", tools=True)
    assert [entry["role"] for entry in shown] == ["user", "tool", "assistant"]
    tool = shown[1]
    assert tool["name"] == "journal_search" and tool["call_id"] == "m1" and tool["arguments"] == {}
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
    turn(brain, "milk", "look", image=png((2560, 1600)))
    blocks = brain.provider.sent[0]["messages"][-1]["content"]
    image = next(b for b in blocks if b["type"] == "image_url")["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[1]))) as picture:
        assert picture.size == (1600, 1000)  # what the default model sees, no more
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


def test_imported_history_fills_only_an_empty_session_and_memory_is_shared(brain):
    messages = [{"role": "user", "content": "I am Tester"},
                {"role": "assistant", "content": '{"expression": "arms_down/smile"}\nHi Tester!'}]
    brain.client.import_history("milk", "main", messages, {"user": {"name": "Tester"}})
    assert [e["text"] for e in brain.client.history("milk", "main")] == ["I am Tester", "Hi Tester!"]
    with pytest.raises(BrainError) as caught:
        brain.client.import_history("milk", "main", messages, {})
    assert caught.value.type == "bad_request"
    assert brain.client.memory() == {"user": {"name": "Tester"}}  # every app's
    assert brain.client.memory_entries()[0]["app"] == "milk"
    brain.client.import_history("milk", "old", messages, {}, transcript=[{"role": "user", "text": "I am Tester"}])
    assert brain.client.history("milk", "old") == [  # what the app showed is no place to return to: no id
        {"role": "user", "text": "I am Tester", "time": pytest.approx(0, abs=1e10)}]


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
    monkeypatch.setattr(sys, "executable", str(runtime.parent / "MilkChan.exe"))  # its own program, beside it
    with pytest.raises(BrainError):
        launch_command(home)


def test_the_installer_registers_sentientmilk_without_starting_it(tmp_path):
    from sentientmilk_framework.cli import main

    home = tmp_path / "home"
    main(["--home", str(home), "setup"])
    assert json.loads((home / "launch.json").read_text())["command"] == own_command(home.resolve())
    assert not (home / "server.json").exists()  # no brain was started


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


def test_a_session_tells_how_full_its_context_is(brain):
    brain.provider.usage = {"prompt_tokens": 4321, "completion_tokens": 10, "prompt_cache_hit_tokens": 0}
    brain.provider.replies.append('{"expression": "arms_down/smile"}\nHi.')
    turn(brain, "milk", "hi")
    window = brain.client.config()["context_window"]
    assert brain.client.session("milk", "main")["context"] == {"used": 4331, "window": window,
        "clear_at": 0.5, "compact_at": 0.75, 'source': 'provider', 'input_tokens': 4321, 'output_tokens': 10}
    brain.client.clear_history("milk", "main")
    assert brain.client.session("milk", "main")["context"]["used"] == 0  # a new conversation holds nothing yet


def test_the_discovery_file_goes_and_comes_while_an_app_reads_it(tmp_path):
    """Windows refuses to delete or replace a file another process has open at that instant."""
    home = tmp_path / "home"
    first = start(home)
    reading = open(home / "server.json", encoding="utf-8")  # an app discovering the brain right now
    closing_brain = first.brain.close
    first.brain.close = lambda: (closing_brain(), threading.Timer(0.3, reading.close).start())  # open at the delete
    first.close()
    assert not (home / "server.json").exists()
    (home / "server.json").write_text('{"url": "http://127.0.0.1:9", "token": "old"}', encoding="utf-8")  # left over
    reading = open(home / "server.json", encoding="utf-8")
    threading.Timer(0.3, reading.close).start()
    second = start(home)
    try:
        assert json.loads((home / "server.json").read_text(encoding="utf-8"))["token"] == second.token
    finally:
        second.close()
