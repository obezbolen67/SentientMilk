"""Her tabs in the user's own Chrome, through SentientMilk's extension: a real Edge with the extension stands in for
the user's Chrome (Chrome 137 and later no longer add an unpacked extension from the command line; Edge still
does), on a hidden desktop, with a profile of the test's own. Its debugging port lets the tests use the
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
from test_browser import PAGES, Site, ids
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from sentientmilk_framework import BrainClient, __version__, browser, desktops, extension
from sentientmilk_framework.config import BrainConfig
from sentientmilk_framework.extension import EXTENSION_ID, FOLDER
from sentientmilk_framework.server import start
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import browser as kit

ORIGIN = f"chrome-extension://{EXTENSION_ID}"

EDGE = browser.find_browser(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not desktops.WINDOWS or not EDGE or not browser.find_browser(),
                                reason="needs Windows, Edge (as the user's Chrome) and Chrome or Edge")


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def until(check, seconds=30.0):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


@pytest.fixture(scope="module")
def chrome(tmp_path_factory):
    home, work = tmp_path_factory.mktemp("home"), tmp_path_factory.mktemp("work")
    downloads, profile = tmp_path_factory.mktemp("downloads"), tmp_path_factory.mktemp("edge")
    (profile / "Default").mkdir()
    (profile / "Default" / "Preferences").write_text(json.dumps(  # never the user's own Downloads folder
        {"download": {"default_directory": str(downloads), "prompt_for_download": False}}), encoding="utf-8")
    BrainConfig(home / "config.json").update({"browser_extension_port": 0})
    server = start(home)
    server.brain.browser.desktop, server.brain.browser.user_desktop = "SentientMilkTests", "SentientMilkTestsUser"
    client = BrainClient(server.url, server.token)
    client.declare_app("cli", name="CLI", environment="A terminal.", toolkits=["browser", "files"])
    client.update_session("cli", "main", cwd=str(work), roots=[str(work)])
    port = browser._free_port()
    # as the panel's Connect does to a Chrome that was not running: its page, given the code, at its start (Chrome
    # blocks that page while the extension loads; the extension picks it up)
    edge = desktops.start([EDGE, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                           f"--remote-debugging-port={port}", f"--load-extension={FOLDER}",
                           server.brain.browser.bridge.connect_url()], desktop="SentientMilkTestsChrome", tied=True)
    until(lambda: server.brain.browser.link is not None, 60)
    yield SimpleNamespace(server=server, brain=server.brain, client=client, work=work, edge=edge, downloads=downloads,
                          profile=profile, port=port)
    server.close()
    desktops.stop(edge, 5)
    shutil.rmtree(profile, ignore_errors=True)


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


def test_the_panel_s_code_connects_the_extension_and_says_so(chrome, monkeypatch):
    status = chrome.client.browser()["chrome"]
    assert status["connected"] and re.fullmatch(r"Edge \d+", status["browser"]) and status["extension"] == __version__
    assert status["folder"] == str(FOLDER) and re.fullmatch(r"\d+-\S+", status["code"]) and not status["error"]
    assert chrome.brain.browser.mode == "off"  # her own browser was never needed
    with extension_page(chrome) as run:  # the popup's page says so too, in its colours
        until(lambda: says(run) == f"✓ Connected to SentientMilk {__version__}")
        assert run("document.getElementById('legend').textContent") == "This Edge"
        assert run("document.getElementById('code-card').hidden") is True
    started, real = [], desktops.start

    def hand_over(args, desktop=None, tied=False):  # the user's Chrome (theirs, on their screen): here, the stand-in
        started.append((args, desktop))
        return real([EDGE, f"--user-data-dir={chrome.profile}", args[1]], desktop="SentientMilkTestsChrome")

    monkeypatch.setattr(desktops, "start", hand_over)
    link = chrome.brain.browser.link
    status = chrome.client.connect_chrome()  # Connect, while it is connected already: it says the page opened
    assert started == [([browser.find_browser(), chrome.brain.browser.bridge.connect_url()], "SentientMilkTestsUser")]
    assert status["chrome"]["took"] and chrome.brain.browser.link is link  # nothing let go of
    until(lambda: not [t for t in requests.get(f"http://127.0.0.1:{chrome.port}/json/list", timeout=5).json()
                       if "popup.html#code" in t["url"]])  # and the page closed itself


def test_a_tab_in_the_user_s_chrome_is_used_like_her_own(chrome, site):
    ctx = context(chrome)
    page = kit.browser_open.func(ctx, site + "/form", in_user_chrome=True)
    assert page.splitlines()[0].endswith("· in the user's Chrome") and re.search(r'textbox e\d+ "Name"', page)
    done = kit.browser_act.func(ctx, [{"action": "fill", "target": ids(page, '"Name"'), "text": "Milk"},
                                      {"action": "fill", "target": ids(page, '"Milk"'), "text": "soy"},
                                      {"action": "click", "target": ids(page, '"Create account"')}])
    assert "Hello Milk, milk Soy" in done
    assert chrome.brain.browser.mode == "off"  # all of it in the user's Chrome
    page = kit.browser_open.func(ctx, site + "/dialogs")  # her tab is there: it stays there
    asked = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Delete"')},
                                       {"action": "dialog", "accept": True}])
    assert "deleted" in asked
    page = kit.browser_open.func(ctx, site + "/shop")  # a frame of another site, there too
    paid = kit.browser_act.func(ctx, [{"action": "fill", "target": ids(page, '"Card"'), "text": "4242"},
                                      {"action": "click", "target": ids(page, '"Pay now"')}])
    assert "paid with 4242" in paid
    assert len(kit.browser_view.func(ctx, picture=True).images) == 1
    saved = json.loads((chrome.brain.home / "browser" / "tabs.json").read_text(encoding="utf-8"))
    assert saved["cli/main"]["tabs"]["t1"]["user"] is True and saved["cli/main"]["tabs"]["t1"]["target"]


def test_popups_and_downloads_there_are_hers(chrome, site):
    ctx = context(chrome, "popups")
    page = kit.browser_open.func(ctx, site + "/popups", in_user_chrome=True)
    opened = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Form in a new tab"')}])
    assert "It opened a new tab, t2" in opened
    assert chrome.brain.browser.owners["cli/popups"]["tabs"]["t2"].user
    page = kit.browser_open.func(ctx, site + "/files")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Get the notes"')}])
    saved = chrome.work / "milk notes.txt"
    until(lambda: saved.exists(), 15)
    assert saved.read_text() == "milk is good" and not list(chrome.downloads.iterdir())  # moved, not copied
    assert "download" in result.lower() or "Downloaded" in kit.browser_view.func(ctx).text
    with extension_page(chrome) as run:  # her tabs wear SentientMilk's colour; the toolbar button counts them
        assert set(run("chrome.tabGroups.query({title: 'SentientMilk'}).then(gs => gs.map(g => g.color))")) == {"purple"}
        grouped = run("chrome.tabs.query({}).then(ts => ts.filter(t => t.groupId !== -1).length)")
        assert grouped >= 2 and run("chrome.action.getBadgeText({})") == str(grouped)  # the popup t2 joined it too


def test_her_browser_and_the_user_s_chrome_side_by_side(chrome, site):
    ctx = context(chrome, "both")
    kit.browser_open.func(ctx, site + "/terms")
    assert chrome.brain.browser.mode == "hidden"
    there = kit.browser_open.func(ctx, in_user_chrome=True)  # the same page, in the user's Chrome
    assert there.startswith("t2 · Terms") and "in the user's Chrome" in there.splitlines()[0]
    assert "Your other tabs: t1 Terms" in there and "(in the user's Chrome)" not in there.split("Your other tabs")[1]
    assert kit.browser_view.func(ctx, "t1").text.startswith("t1 · Terms ·")
    seen = chrome.brain.browser.seen(ctx.run, {"steps": [{"action": "click", "target": "e1"}], "tab": "t2"})
    assert seen["chrome"] == "user" and seen["site"] == "127.0.0.1"  # the user sees it is their Chrome
    assert "chrome" not in chrome.brain.browser.seen(ctx.run, {"steps": [], "tab": "t1"})
    back = kit.browser_open.func(ctx, site + "/form", in_user_chrome=True)  # from t1 (hers): a tab there
    assert back.startswith("t3 · Sign up") and "in the user's Chrome" in back.splitlines()[0]
    again = kit.browser_open.func(ctx, site + "/form", in_user_chrome=False)  # and back: one of hers
    assert again.startswith("t4 · Sign up") and "in the user's Chrome" not in again.splitlines()[0]


def test_a_lost_connection_lets_go_and_her_tab_is_taken_up_again(chrome, site):
    ctx = context(chrome, "again")
    kit.browser_open.func(ctx, site + "/terms", in_user_chrome=True)
    tab = chrome.brain.browser.owners["cli/again"]["tabs"]["t1"]
    target, link = tab.target, chrome.brain.browser.link
    link.close()  # as SentientMilk restarting does
    until(lambda: chrome.brain.browser.link not in (None, link))  # the extension connects again by itself
    seen = kit.browser_view.func(ctx).text
    assert seen.startswith("t1 · Terms") and "let go of you" in seen and tab.target == target  # the same tab


def test_without_the_extension_she_is_told_what_the_user_does(chrome, site, monkeypatch):
    monkeypatch.setattr(chrome.brain.browser, "link", None)
    ctx = context(chrome, "alone")
    with pytest.raises(ToolError, match="needs SentientMilk's extension"):
        kit.browser_open.func(ctx, site + "/terms", in_user_chrome=True)
    assert not chrome.brain.browser.owners["cli/alone"]["tabs"]  # no tab left behind


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
    kit.browser_open.func(ctx, site + "/terms", in_user_chrome=True)
    with extension_page(chrome) as run:
        until(lambda: run("document.getElementById('act').textContent") == "Disconnect")
        run("document.getElementById('act').click()")
        until(lambda: chrome.brain.browser.link is None)
        until(lambda: says(run) == "Disconnected")
        status = chrome.client.browser()["chrome"]
        assert status["disconnected"] and not status["connected"]
        with pytest.raises(ToolError, match="disconnected their Chrome"):
            kit.browser_view.func(ctx)
        time.sleep(1.5)  # not even the half-minute alarm brings it back
        assert chrome.brain.browser.link is None
        run("document.getElementById('act').click()")  # Connect
        until(lambda: chrome.brain.browser.link is not None)
    seen = kit.browser_view.func(ctx).text
    assert seen.startswith("t1 · Terms") and "let go of you" not in seen  # her tab again, and no tale of a loss


def test_pages_there_are_saved_and_logged(chrome, site):
    ctx = context(chrome, "keep")
    kit.browser_open.func(ctx, site + "/console", in_user_chrome=True)
    time.sleep(0.6)
    assert "[error] spilled" in kit.browser_log.func(ctx)
    kit.browser_act.func(ctx, [{"action": "save", "text": "console.pdf"}, {"action": "save", "text": "console.png"}])
    assert (chrome.work / "console.pdf").read_bytes().startswith(b"%PDF")
    assert (chrome.work / "console.png").read_bytes().startswith(b"\x89PNG")


assert "/form" in PAGES and Path(FOLDER / "manifest.json").is_file()
