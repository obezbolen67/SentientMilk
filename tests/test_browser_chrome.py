"""Her tabs in the user's own Chrome, through SentientMilk's extension: a real Edge with the extension stands in for
the user's Chrome (Chrome 137 and later no longer add an unpacked extension from the command line; Edge still
does), on a hidden desktop, with a profile of the test's own."""

import json
import re
import shutil
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_browser import PAGES, Site, ids

from sentientmilk_framework import BrainClient, browser, desktops
from sentientmilk_framework.config import BrainConfig
from sentientmilk_framework.extension import EXTENSION_ID, FOLDER
from sentientmilk_framework.server import start
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import browser as kit

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
    edge = desktops.start([EDGE, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                           f"--load-extension={FOLDER}", "about:blank"], desktop="SentientMilkTestsChrome", tied=True)
    until(lambda: desktops.windows_of(edge))  # up, so the page goes to it (with the extension), not a new one
    time.sleep(2)
    # then as the panel's Connect does, to a Chrome with the extension: its page, given the code (a page asked for
    # while the extension is still loading is blocked, so again until it connects)
    deadline = time.monotonic() + 60
    while server.brain.browser.link is None:
        assert time.monotonic() < deadline, "the extension never connected"
        desktops.start([EDGE, f"--user-data-dir={profile}", server.brain.browser.bridge.connect_url()],
                       desktop="SentientMilkTestsChrome")
        time.sleep(3)
    yield SimpleNamespace(server=server, brain=server.brain, client=client, work=work, edge=edge, downloads=downloads)
    server.close()
    desktops.stop(edge, 5)
    shutil.rmtree(profile, ignore_errors=True)


def context(chrome, session="main", kind="turn"):
    if session != "main":
        chrome.client.update_session("cli", session, cwd=str(chrome.work), roots=[str(chrome.work)])
    run_id = chrome.brain.store.add_run("cli", session, kind, {}, status="working")
    return ToolContext(chrome.brain, chrome.brain.store.run(run_id), chrome.brain.profile("cli", session), "call-1")


def test_the_panel_s_code_connects_the_extension_and_says_so(chrome, monkeypatch):
    status = chrome.client.browser()["chrome"]
    assert status["connected"] and "Edg/" in status["browser"] and status["folder"] == str(FOLDER)
    assert re.fullmatch(r"\d+-\S+", status["code"]) and not status["error"]
    assert chrome.brain.browser.mode == "off"  # her own browser was never needed
    started = []
    monkeypatch.setattr(desktops, "start", lambda args, desktop=None, tied=False: started.append((args, desktop)))
    chrome.client.connect_chrome()  # Connect: the user's Chrome (theirs, on their screen) at the extension's page
    assert started == [([browser.find_browser(), chrome.brain.browser.bridge.connect_url()], "SentientMilkTestsUser")]


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
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    url = f"ws://127.0.0.1:{chrome.brain.browser.bridge.port}/extension"
    for origin, token, words in [("http://example.com", chrome.brain.browser.bridge.token, "only SentientMilk"),
                                 (f"chrome-extension://{EXTENSION_ID}", "nope", "wrong code")]:
        with connect(url, origin=origin) as socket:
            with pytest.raises(ConnectionClosed):  # refused at once, or once it says hello
                socket.send(json.dumps({"hello": {"token": token}}))
                socket.recv(timeout=5)
            assert words in (socket.close_reason or "")
    assert chrome.brain.browser.link is not None  # the extension's own connection stays


def test_pages_there_are_saved_and_logged(chrome, site):
    ctx = context(chrome, "keep")
    kit.browser_open.func(ctx, site + "/console", in_user_chrome=True)
    time.sleep(0.6)
    assert "[error] spilled" in kit.browser_log.func(ctx)
    kit.browser_act.func(ctx, [{"action": "save", "text": "console.pdf"}, {"action": "save", "text": "console.png"}])
    assert (chrome.work / "console.pdf").read_bytes().startswith(b"%PDF")
    assert (chrome.work / "console.png").read_bytes().startswith(b"\x89PNG")


assert "/form" in PAGES and Path(FOLDER / "manifest.json").is_file()
