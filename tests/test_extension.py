"""The extension's side of the brain without a browser: its port, and its version."""

import json
import socket
import time
from types import SimpleNamespace

from sentientmilk_framework import __version__, extension


def test_the_extension_is_sentientmilk_s_version():  # it reloads itself when SentientMilk is newer than it
    assert json.loads((extension.FOLDER / "manifest.json").read_text(encoding="utf-8"))["version"] == __version__


def test_a_taken_port_is_tried_again_until_it_is_free(tmp_path, monkeypatch):
    monkeypatch.setattr(extension, "RETRY", 0.2)
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    bridge = extension.Bridge(SimpleNamespace(folder=tmp_path), port)
    try:
        bridge.start()
        assert "is taken by another program" in bridge.error and bridge.code() == ""
        holder.close()
        deadline = time.monotonic() + 10
        while bridge.port is None:
            assert time.monotonic() < deadline, "it never listened"
            time.sleep(0.05)
        assert bridge.port == port and not bridge.error and bridge.code().startswith(f"{port}-")
        assert json.loads((tmp_path / "extension.json").read_text(encoding="utf-8"))["token"] == bridge.token
    finally:
        bridge.close()
        holder.close()
