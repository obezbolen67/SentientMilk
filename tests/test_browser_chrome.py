"""Her browser's connection to the user's own Chrome, through SentientMilk's extension: the stand-in Edge of
test_browser.py (the brain opens it as it would the user's Chrome), whose debugging port lets the tests use the
extension's own page as the user would; fake extensions (a WebSocket with the extension's origin) try the rest."""

import contextlib
import json
import re
import shutil
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from test_browser import EDGE, PAGES, Site, brain_with_chrome, ids, until
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from sentientmilk_framework import BrainClient, __version__, browser, desktops, extension
from sentientmilk_framework.extension import EXTENSION_ID, FOLDER
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import browser as kit

ORIGIN = f"chrome-extension://{EXTENSION_ID}"

pytestmark = pytest.mark.skipif(not desktops.WINDOWS or not EDGE,
                                reason="needs Windows and Edge (the user's Chrome's stand-in)")


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def chrome(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    home, work = tmp_path_factory.mktemp("home"), tmp_path_factory.mktemp("work")
    server, stand = brain_with_chrome(home, tmp_path_factory.mktemp("chrome"), patch)
    client = BrainClient(server.url, server.token)
    client.declare_app("cli", name="CLI", environment="A terminal.", toolkits=["browser", "files"])
    client.update_session("cli", "main", cwd=str(work), roots=[str(work)])
    # the panel's Connect, to a Chrome that was not running: it starts with the extension's page, given the code
    # (Chrome blocks that page while the extension loads; the extension picks it up)
    assert client.connect_chrome()["chrome"]["took"]
    yield SimpleNamespace(server=server, brain=server.brain, client=client, work=work, stand=stand, port=stand.port)
    server.close()
    for process in stand.processes:
        desktops.stop(process, 5)
    patch.undo()
    shutil.rmtree(stand.folder, ignore_errors=True)


@contextlib.contextmanager
def extension_page(chrome, hash=""):
    """The extension's page in a tab of the stand-in Edge: ``run(js)`` gives what the expression comes to."""
    url = requests.get(f"http://127.0.0.1:{chrome.port}/json/version", timeout=5).json()["webSocketDebuggerUrl"]
    wire = browser.Wire(url, lambda *_: None)
    target = wire.call("Target.createTarget", {"url": f"{ORIGIN}/popup.html{hash}"})["targetId"]
    session = wire.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]

    def run(expression):
        return wire.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True},
                         session)["result"].get("value")

    try:
        until(lambda: run("document.readyState") == "complete")
        yield run
    finally:
        with contextlib.suppress(Exception):
            wire.call("Target.closeTarget", {"targetId": target})
        wire.close()


def says(run):
    return run("document.getElementById('line').textContent")


def fake(chrome):
    """A WebSocket as the extension's, from its origin."""
    return connect(f"ws://127.0.0.1:{chrome.brain.browser.bridge.port}/extension", origin=ORIGIN)


def hello(chrome, socket, token=None, **more):
    greeting = json.loads(socket.recv(timeout=5))["sentientmilk"]
    proof = extension.proof(token or chrome.brain.browser.bridge.token, greeting["nonce"])
    socket.send(json.dumps({"hello": {"protocol": extension.PROTOCOL, "proof": proof, "instance": "fake",
                                      "name": "Fake 1", "version": "9.9.9", **more}}))
    return greeting


def refused(socket):
    with pytest.raises(ConnectionClosed):
        socket.recv(timeout=5)
    return socket.close_code, socket.close_reason


def context(chrome, session="main", kind="turn"):
    if session != "main":
        chrome.client.update_session("cli", session, cwd=str(chrome.work), roots=[str(chrome.work)])
    run_id = chrome.brain.store.add_run("cli", session, kind, {}, status="working")
    return ToolContext(chrome.brain, chrome.brain.store.run(run_id), chrome.brain.profile("cli", session), "call-1")


def test_the_panel_s_code_connects_the_extension_and_says_so(chrome):
    status = chrome.client.browser()["chrome"]
    assert status["connected"] and re.fullmatch(r"Edge \d+", status["browser"]) and status["extension"] == __version__
    assert status["folder"] == str(FOLDER) and re.fullmatch(r"\d+-\S+", status["code"]) and not status["error"]
    with extension_page(chrome) as run:  # the popup's page says so too, in its colours
        until(lambda: says(run) == f"✓ Connected to SentientMilk {__version__}")
        assert run("document.getElementById('legend').textContent") == "This Edge"
        assert run("document.getElementById('code-card').hidden") is True
    browser_, before = chrome.brain.browser, len(chrome.stand.opened)
    link = browser_.link
    status = chrome.client.connect_chrome()  # Connect, while it is connected already: it says the page opened
    assert chrome.stand.opened[before:] == [([browser_.command(), browser_.bridge.connect_url()], None)]  # their screen
    assert status["chrome"]["took"] and browser_.link is link  # nothing let go of
    until(lambda: not [t for t in requests.get(f"http://127.0.0.1:{chrome.port}/json/list", timeout=5).json()
                       if "popup.html#code" in t["url"]])  # and the page closed itself


def test_her_tabs_there_wear_sentientmilk_s_colour(chrome, site):
    ctx = context(chrome, "popups")
    page = kit.browser_open.func(ctx, site + "/popups")
    opened = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Form in a new tab"')}])
    assert "It opened a new tab, t2" in opened
    with extension_page(chrome) as run:  # the toolbar button counts them
        assert set(run("chrome.tabGroups.query({title: 'SentientMilk'}).then(gs => gs.map(g => g.color))")) == {"purple"}
        grouped = run("chrome.tabs.query({}).then(ts => ts.filter(t => t.groupId !== -1).length)")
        assert grouped >= 2 and run("chrome.action.getBadgeText({})") == str(grouped)  # the popup t2 joined it too


def test_a_lost_connection_lets_go_and_her_tab_is_taken_up_again(chrome, site):
    ctx = context(chrome, "again")
    kit.browser_open.func(ctx, site + "/terms")
    tab = chrome.brain.browser.owners["cli/again"]["tabs"]["t1"]
    saved = json.loads((chrome.brain.home / "browser" / "tabs.json").read_text(encoding="utf-8"))
    assert saved["cli/again"]["tabs"]["t1"]["target"] == tab.target  # where it is, for after a restart too
    target, link = tab.target, chrome.brain.browser.link
    link.close()  # as SentientMilk restarting does
    until(lambda: chrome.brain.browser.link not in (None, link))  # the extension connects again by itself
    seen = kit.browser_view.func(ctx).text
    assert seen.startswith("t1 · Terms") and "let go of you" in seen and tab.target == target  # the same tab


def test_when_chrome_does_not_connect_she_is_told_what_the_user_does(chrome, site, monkeypatch):
    opened = []
    monkeypatch.setattr(chrome.brain.browser, "link", None)  # not connected, and the Chrome opened for it has no
    monkeypatch.setattr(desktops, "start", lambda args, desktop=None, tied=False: opened.append(args))  # extension
    monkeypatch.setattr(browser, "CONNECT_WAIT", 1.0)
    ctx = context(chrome, "alone")
    with pytest.raises(ToolError, match="did not connect to you"):
        kit.browser_open.func(ctx, site + "/terms")
    assert opened and not chrome.brain.browser.owners["cli/alone"]["tabs"]  # no tab left behind


def test_only_the_extension_with_the_code_connects(chrome):
    url = f"ws://127.0.0.1:{chrome.brain.browser.bridge.port}/extension"
    with connect(url, origin="http://example.com") as socket:  # a web page
        assert refused(socket) == (1008, "only SentientMilk's extension connects here")
    with fake(chrome) as socket:  # 0.13's extension said hello with the code itself, and shows the reason
        assert json.loads(socket.recv(timeout=5))["sentientmilk"]["version"] == __version__
        socket.send(json.dumps({"hello": {"token": chrome.brain.browser.bridge.token}}))
        code, reason = refused(socket)
        assert code == extension.OUTDATED and reason.startswith(f"This extension is older than SentientMilk {__version__}")
    with fake(chrome) as socket:  # the code is never sent: what proves it is keyed with this nonce
        hello(chrome, socket, token="nope")
        assert refused(socket)[0] == extension.WRONG_CODE
    with fake(chrome) as socket:  # the right code, from another browser: SentientMilk has one, which it names
        hello(chrome, socket)
        code, reason = refused(socket)
        assert code == extension.BUSY and re.fullmatch(r"Edge \d+", reason)
    assert chrome.brain.browser.link is not None  # the extension's own connection stays


def test_another_browser_takes_over_only_when_the_user_says_and_gives_back(chrome):
    bridge, edge_link = chrome.brain.browser.bridge, chrome.brain.browser.link
    with extension_page(chrome) as run, fake(chrome) as first:
        hello(chrome, first, take=True)  # the user pressed Connect in that browser
        assert json.loads(first.recv(timeout=5)) == {"welcome": {"version": __version__}}
        until(lambda: edge_link.closed.is_set())
        assert chrome.client.browser()["chrome"]["browser"] == "Fake 1"
        until(lambda: says(run) == "SentientMilk moved to Fake 1")  # the extension in Edge says where it went
        assert run("document.getElementById('act').textContent") == "Use this Edge instead"
        with fake(chrome) as second:  # the same browser again, its old connection perhaps dead: no take needed
            hello(chrome, second)
            assert "welcome" in json.loads(second.recv(timeout=5))
            assert refused(first) == (extension.REPLACED, "Fake 1")
            run("document.getElementById('act').click()")  # Use this Edge instead
            until(lambda: bridge.current and bridge.current["name"].startswith("Edge "))
            assert refused(second)[0] == extension.REPLACED
        until(lambda: says(run) == f"✓ Connected to SentientMilk {__version__}")


def test_disconnect_in_the_extension_stops_her_until_the_user_connects(chrome, site):
    ctx = context(chrome, "unplugged")
    kit.browser_open.func(ctx, site + "/terms")
    with extension_page(chrome) as run:
        until(lambda: run("document.getElementById('act').textContent") == "Disconnect")
        run("document.getElementById('act').click()")
        until(lambda: chrome.brain.browser.link is None)
        until(lambda: says(run) == "Disconnected")
        status = chrome.client.browser()["chrome"]
        assert status["disconnected"] and not status["connected"]
        before = len(chrome.stand.opened)
        with pytest.raises(ToolError, match="disconnected their Chrome"):
            kit.browser_view.func(ctx)
        assert len(chrome.stand.opened) == before  # what the user did is theirs to undo: no Chrome opened for it
        time.sleep(1.5)  # not even the half-minute alarm brings it back
        assert chrome.brain.browser.link is None
        run("document.getElementById('act').click()")  # Connect
        until(lambda: chrome.brain.browser.link is not None)
    seen = kit.browser_view.func(ctx).text
    assert seen.startswith("t1 · Terms") and "let go of you" not in seen  # her tab again, and no tale of a loss


assert "/form" in PAGES and Path(FOLDER / "manifest.json").is_file()
