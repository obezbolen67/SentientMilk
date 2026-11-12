"""Her browser against a site of its own on 127.0.0.1, in a real Chrome (or Edge) on a hidden desktop: nothing
shows on the user's screen, and the user's windows of it (show, Open to sign in) go to another hidden desktop."""

import json
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sentientmilk_framework import BrainClient, browser, desktops
from sentientmilk_framework.server import start
from sentientmilk_framework.testing import tool_call
from sentientmilk_framework.toolkits import ToolContext, ToolError
from sentientmilk_framework.toolkits import browser as kit

pytestmark = pytest.mark.skipif(not desktops.WINDOWS or not browser.find_browser(),
                                reason="needs Windows (a hidden desktop) and Chrome or Edge")

PAGES = {
    "/form": """<!doctype html><title>Sign up</title><h1>Sign up</h1>
<form action="/done" method="get">
<label>Name <input name="name"></label>
<label for="pw">Password</label><input id="pw" name="pw" type="password">
<select name="milk" aria-label="Milk"><option>Whole</option><option>Oat</option><option>Soy</option></select>
<label><input type="checkbox" name="news"> Send news</label>
<button>Create account</button>
</form><p>Read the <a href="/terms">terms</a> first.</p>""",
    "/dialogs": """<!doctype html><title>Dialogs</title>
<button onclick="out.textContent = confirm('Delete it?') ? 'deleted' : 'kept'">Delete</button>
<button onclick="alert('Saved!'); out.textContent = 'saved'">Save</button>
<button onclick="out.textContent = 'named ' + prompt('Your name?', '')">Name</button><p id=out>nothing yet</p>""",
    "/popups": """<!doctype html><title>Popups</title><a href="/form" target="_blank">Form in a new tab</a>
<button onclick="window.open('/closing', 'w', 'width=500,height=600')">Sign in window</button>""",
    "/closing": """<!doctype html><title>Signing in</title><button onclick="window.close()">Done</button>""",
    "/files": """<!doctype html><title>Files</title><a href="/notes.txt">Get the notes</a>""",
    "/upload": """<!doctype html><title>Upload</title>
<label><span>Choose a photo</span><input type=file id=f style="display:none"
 onchange="out.textContent = [...this.files].map(f => f.name).join(',')"></label>
<button onclick="g.click()">Attach</button><input type=file id=g hidden
 onchange="out2.textContent = [...this.files].map(f => f.name).join(',')">
<p id=out>none</p><p id=out2>none</p>""",
    "/long": "<!doctype html><title>Long</title><ul>" + "".join(f"<li>Item {n}</li>" for n in range(1, 61)) + "</ul>",
    "/covered": """<!doctype html><title>Covered</title><button onclick="out.textContent = 'bought'">Buy</button>
<p id=out>not yet</p><div id=banner style="position:fixed;inset:0;background:#fffc;padding:40vh 0 0 40vw">
<p>We use cookies</p><button onclick="banner.remove()">Accept</button></div>""",
    "/frames": """<!doctype html><title>Frames</title><iframe src="/inner" title="Inner"></iframe>
<iframe src="http://localhost:{port}/inner" title="Other"></iframe>""",
    "/inner": """<!doctype html><title>Inner</title><button onclick="this.textContent = 'pressed'">Press</button>""",
    "/canvas": """<!doctype html><title>Canvas</title><body style="margin:0">
<canvas id=c width=400 height=300 style="width:400px;height:300px;display:block;background:#ddd"></canvas>
<p id=out>none</p><script>c.onclick = e => out.textContent = 'at ' + e.offsetX + ',' + e.offsetY</script>""",
    "/spa": """<!doctype html><title>Slow</title><button onclick="setTimeout(() => fetch('/api').then(r => r.text())
 .then(t => out.textContent = t), 200)">Load</button><p id=out>empty</p>""",
    "/signals": """<!doctype html><title>Signals</title><p id=s>?</p><script>
setTimeout(() => s.textContent = JSON.stringify({webdriver: navigator.webdriver, inner: [innerWidth, innerHeight],
  outer: [outerWidth, outerHeight], visibility: document.visibilityState, focus: document.hasFocus()}), 100)</script>""",
    "/terms": "<!doctype html><title>Terms</title><h1>Terms</h1><p>Be kind to milk.</p>",
    "/shop": """<!doctype html><title>Shop</title><h1>Checkout</h1><p>Pay below.</p><div style="height:1400px"></div>
<iframe src="http://localhost:{port}/pay" title="Payment" style="width:500px;height:200px;padding:9px"></iframe>""",
    "/pay": """<!doctype html><title>Pay</title><label>Card <input id=c></label>
<button onclick="out.textContent = 'checked ' + c.value">Check card</button><p id=out>unpaid</p>""",
    "/cookie": """<!doctype html><title>Cookie</title><p id=out></p><script>
if (!document.cookie.includes('milk=')) document.cookie = 'milk=fresh; path=/';
out.textContent = document.cookie</script>""",
    "/console": """<!doctype html><title>Console</title><p>Logs</p><script>
console.log('hello', {cups: 2}); console.warn('low milk'); console.error('spilled');
fetch('/api'); fetch('/missing'); setTimeout(() => { throw new Error('boom') }, 50)</script>""",
    "/menu": """<!doctype html><title>Menu</title><div id=box tabindex=0 style="width:400px;height:300px;background:#ccc"
 oncontextmenu="out.textContent = 'its own menu'">Right click here</div><p id=out>none</p>""",
    "/doc.pdf": "",
    "/article": "<!doctype html><title>Article</title><nav><a href=/terms>Terms</a></nav>" + "".join(
        f"<h2>Part {part}</h2>" + "".join(f"<p>Milk fact {part}.{n} is told here, see <a href=/f{part}{n}>source "
                                          f"{part}.{n}</a> for more words about it.</p>" for n in range(60))
        for part in range(5)) + "<form><input aria-label=Comment><button>Send</button></form>",
}


PDF = (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/done":
            fields = urllib.parse.parse_qs(query)
            body = (f"<!doctype html><title>Done</title><p>Hello {fields.get('name', ['?'])[0]}, milk "
                    f"{fields.get('milk', ['?'])[0]}, news {fields.get('news', ['off'])[0]}, password "
                    f"{len(fields.get('pw', [''])[0])} long</p>")
            return self._send(body)
        if path == "/notes.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="milk notes.txt"')
            self.end_headers()
            return self.wfile.write(b"milk is good")
        if path == "/api":
            time.sleep(0.5)
            return self._send("loaded data", "text/plain")
        if path == "/doc.pdf":
            return self._send(PDF.decode(), "application/pdf")
        if path not in PAGES:
            self.send_response(404)
            return self.end_headers()
        self._send(PAGES[path].replace("{port}", str(self.server.server_address[1])))

    def _send(self, body, kind="text/html"):
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _hide(brain_server):
    """The user's windows of it on a hidden desktop too: tests never show anything."""
    brain_server.brain.browser.desktop = "SentientMilkTests"
    brain_server.brain.browser.user_desktop = "SentientMilkTestsUser"


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    home, work = tmp_path_factory.mktemp("home"), tmp_path_factory.mktemp("work")
    server = start(home)
    _hide(server)
    client = BrainClient(server.url, server.token)
    client.declare_app("cli", name="CLI", environment="A terminal.", toolkits=["browser", "files"])
    client.update_session("cli", "main", cwd=str(work), roots=[str(work)])
    yield SimpleNamespace(server=server, brain=server.brain, client=client, work=work)
    server.close()


def context(web, session="main", kind="turn"):
    if session != "main":
        web.client.update_session("cli", session, cwd=str(web.work), roots=[str(web.work)])
    run_id = web.brain.store.add_run("cli", session, kind, {}, status="working")
    return ToolContext(web.brain, web.brain.store.run(run_id), web.brain.profile("cli", session), "call-1")


def ids(text, what):
    """The id on the line that has ``what``."""
    line = next(line for line in text.splitlines() if what in line)
    return re.search(r"\be(\d+)\b", line).group(0)


def test_a_page_comes_as_text_with_ids_and_a_form_is_filled_by_them(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/form")
    assert page.startswith("t1 · Sign up · ") and "# Sign up" in page
    assert re.search(r'textbox e\d+ "Name"', page) and re.search(r'textbox e\d+ "Password"', page)
    assert re.search(r'select e\d+ "Milk" = "Whole" \(options: Whole \| Oat \| Soy\)', page)
    assert re.search(r'checkbox e\d+ "Send news" \[not checked\]', page)
    assert re.search(r'\[link e\d+ "terms"\]', page)  # in its sentence, in brackets
    steps = [{"action": "fill", "target": ids(page, '"Name"'), "text": "Milk Chan"},
             {"action": "fill", "target": ids(page, '"Password"'), "text": "s3cret!"},
             {"action": "fill", "target": ids(page, '"Milk"'), "text": "oat"},
             {"action": "fill", "target": ids(page, '"Send news"'), "text": "true"},
             {"action": "click", "target": ids(page, '"Create account"')}]
    done = kit.browser_act.func(ctx, steps)
    assert "4. fill" in done and "checked" in done and "5. click" in done and "the page went to" in done
    assert "Hello Milk Chan, milk Oat, news on, password 7 long" in done and done.splitlines()[0].startswith("t1 · Done")


def test_old_ids_miss_after_the_page_changes(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/form")
    name = ids(page, '"Name"')
    kit.browser_open.func(ctx, site + "/terms")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": name}])
    assert "is not on the page" in result and "latest" in result


def test_a_covered_button_says_what_covers_it(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/covered")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Buy"')}])
    assert "covered by" in result and "We use cookies" in result or "Accept" in result
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Accept"')},
                                        {"action": "click", "target": ids(page, '"Buy"')}])
    assert "bought" in result


def test_dialogs_wait_for_her_answer_and_alerts_close_themselves(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/dialogs")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Delete"')},
                                        {"action": "click", "target": ids(page, '"Save"')}])
    assert 'A dialog of the page waits (confirm): "Delete it?"' in result and "Steps 2-2 did not run" in result
    result = kit.browser_act.func(ctx, [{"action": "dialog", "accept": False}])
    assert "dismissed" in result and "kept" in result
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Save"')}])
    assert 'The page showed a message: "Saved!" (closed)' in result and "saved" in result
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Name"')},
                                        {"action": "dialog", "text": "Milk"}])
    assert "named Milk" in result


def test_links_to_new_tabs_and_windows_open_tabs_of_hers(web, site):
    ctx = context(web, "popups")
    page = kit.browser_open.func(ctx, site + "/popups")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Form in a new tab"')}])
    assert "It opened a new tab, t2" in result
    seen = kit.browser_view.func(ctx).text
    assert seen.startswith("t2 · Sign up") and "Your other tabs: t1 Popups" in seen
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Sign in window"')}], "t1")
    assert "It opened a new tab, t3" in result
    window = kit.browser_view.func(ctx).text
    assert window.startswith("t3 · Signing in")
    closed = kit.browser_act.func(ctx, [{"action": "click", "target": ids(window, '"Done"')}])
    assert "Tab t3 closed itself." in closed and "Now in t2 · Sign up" in closed  # no tab of hers any more
    assert set(web.brain.browser.owners["cli/popups"]["tabs"]) == {"t1", "t2"}


def test_a_download_goes_to_the_working_folder(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/files")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Get the notes"')}])
    saved = web.work / "milk notes.txt"
    if "Downloaded" not in result:  # a slow disk: it is told at the next call
        result += kit.browser_view.func(ctx).text
    assert f"Downloaded milk notes.txt to {saved}" in result and saved.read_text() == "milk is good"


def test_uploads_take_files_from_open_folders_only(web, site, tmp_path):
    ctx = context(web)
    (web.work / "photo.png").write_bytes(b"\x89PNG")
    page = kit.browser_open.func(ctx, site + "/upload")
    assert re.search(r'file input e\d+ "Choose a photo" \[hidden\]', page)
    result = kit.browser_act.func(ctx, [{"action": "upload", "target": ids(page, '"Choose a photo"'),
                                         "files": ["photo.png"]}])
    assert "gave it photo.png" in result and '"Choose a photo" [hidden] (photo.png)' in result
    result = kit.browser_act.func(ctx, [{"action": "upload", "target": ids(page, '"Attach"'), "files": ["photo.png"]}])
    assert "gave it photo.png" in result
    assert kit.browser_script.func(ctx, "out2.textContent") == "photo.png"
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    result = kit.browser_act.func(ctx, [{"action": "upload", "target": ids(page, '"Choose a photo"'),
                                         "files": [str(outside)]}])
    assert "outside the folders open to you" in result


def test_a_long_list_shows_its_start_and_the_rest_by_part(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/long")
    assert "Item 20" in page and "Item 21" not in page
    more = re.search(r"… 40 more: browser_view part=(e\d+)", page)
    assert more
    whole = kit.browser_view.func(ctx, part=more.group(1)).text
    assert "Item 60" in whole and "more:" not in whole
    found = kit.browser_view.func(ctx, find="Item 45").text
    assert found.splitlines()[1:] == ["- Item 45"]


def test_a_long_page_keeps_its_shape_and_leaves_its_prose_to_reading(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/article")
    assert len(page) < 4000 and page.count("## Part") == 5  # every heading, field and button, each part's start
    assert re.search(r'textbox e\d+ "Comment"', page) and re.search(r'button e\d+ "Send"', page)
    assert "Milk fact 3.1 " in page and "Milk fact 3.2 " not in page
    assert "… 58 more lines of text with 58 links: browser_read reads them" in page
    assert '[link e' in kit.browser_view.func(ctx, find="source 3.40").text  # what is left out is found
    first = kit.browser_read.func(ctx)
    assert "Milk fact 0.0 is told here" in first and "Go on with offset=20000." in first
    rest = kit.browser_read.func(ctx, offset=20000)
    assert "Milk fact 4.59 is told here" in rest and "[source 4.59](" in rest


def test_frames_of_the_site_are_read_and_another_site_s_are_named(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/frames")
    assert 'frame "Inner"' in page and 'frame "Other" (another site: localhost' in page
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Press"')}])
    assert '"pressed"' in result


def test_what_has_no_id_is_pointed_at_in_a_picture(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/canvas")
    assert "canvas 400x300" in page
    seen = kit.browser_view.func(ctx, picture=True)
    assert len(seen.images) == 1 and "pixels" in seen.text
    scale = web.brain.browser.owners["cli/main"]["tabs"]["t1"].picture
    x, y = round(100 / scale), round(50 / scale)
    result = kit.browser_act.func(ctx, [{"action": "click", "target": f"{x},{y}"}])
    shown = re.search(r"at (\d+),(\d+)", result)
    assert shown and abs(int(shown.group(1)) - 100) <= 2 and abs(int(shown.group(2)) - 50) <= 2


def test_an_act_waits_for_what_the_page_loads(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/spa")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Load"')}])
    assert "loaded data" in result and "empty" not in result


def test_sites_see_a_plain_chrome_and_nothing_shows_on_the_user_s_screen(web, site):
    ctx = context(web)
    kit.browser_open.func(ctx, site + "/signals")
    signals = json.loads(kit.browser_script.func(ctx, "s.textContent"))
    assert signals["webdriver"] is False and signals["visibility"] == "visible" and signals["focus"] is True
    assert signals["outer"][1] - signals["inner"][1] < 150  # no "controlled by automated software" bar
    process = web.brain.browser.process
    assert desktops.windows_of(process)  # its windows are on the hidden desktop...
    assert not desktops.windows_of(desktops.Process(process.pid, process._handle, desktop=None))  # ...not here


def test_tabs_are_each_conversation_s_own_and_go_with_it(web, site):
    first, second = context(web, "one"), context(web, "two")
    kit.browser_open.func(first, site + "/form")
    kit.browser_open.func(second, site + "/terms")
    assert kit.browser_view.func(first).text.startswith("t1 · Sign up")
    assert kit.browser_view.func(second).text.startswith("t1 · Terms")
    web.brain.delete_session("cli", "two")
    assert "cli/two" not in web.brain.browser.owners
    with pytest.raises(ToolError, match="no tab open"):
        kit.browser_view.func(context(web, "two"))


def test_tabs_open_again_where_they_were_after_the_browser_closed(web, site):
    ctx = context(web, "again")
    kit.browser_open.func(ctx, site + "/terms")
    web.brain.browser.close()
    assert web.brain.browser.mode == "off"
    assert kit.browser_view.func(ctx).text.startswith("t1 · Terms")
    crashed = web.brain.browser.process
    crashed.kill()  # a crash: the next call opens it again
    crashed.wait(5)
    assert kit.browser_view.func(ctx).text.startswith("t1 · Terms") and web.brain.browser.process is not crashed


def where(web):
    """The desktop her browser's windows are on."""
    browser_ = web.brain.browser
    return {browser_.desktop: "hidden", browser_.user_desktop: "shown"}[browser_.process.desktop]


def test_only_the_lead_hands_the_browser_to_the_user_and_everyone_goes_on_there(web, site):
    agent = context(web, "agent-1", kind="agent")
    kit.browser_open.func(agent, site + "/terms")
    assert "Only the lead" in kit.browser_act.func(agent, [{"action": "show"}])
    lead = context(web, "lead")
    kit.browser_open.func(lead, site + "/form")
    shown = kit.browser_act.func(lead, [{"action": "show"}, {"action": "click", "target": "e1"}])
    assert "on the user's screen at t1 (" + site + "/form)" in shown and "Steps 2-2 did not run" in shown
    assert web.brain.browser.mode == "shown" and where(web) == "shown"
    seen = kit.browser_view.func(lead).text  # still hers, on their screen
    assert seen.startswith("t1 · Sign up") and "on the user's screen" in seen.splitlines()[0]
    assert kit.browser_view.func(agent).text.startswith("t1 · Terms")  # its page came back there too
    kit.browser_open.func(lead, headless=True)
    assert web.brain.browser.mode == "hidden" and where(web) == "hidden"


def test_headless_or_not_she_works_the_same_and_keeps_her_session(web, site):
    ctx = context(web, "watched")
    page = kit.browser_open.func(ctx, site + "/cookie")
    assert "milk=fresh" in page and where(web) == "hidden"
    moved = kit.browser_open.func(ctx, headless=False)  # "don't run it headless, I want to see"
    assert moved.startswith("t1 · Cookie") and "moved to the user's screen" in moved and where(web) == "shown"
    assert kit.browser_script.func(ctx, "document.cookie") == "milk=fresh"  # a session cookie came along
    page = kit.browser_open.func(ctx, site + "/form")
    done = kit.browser_act.func(ctx, [{"action": "fill", "target": ids(page, '"Name"'), "text": "Milk"},
                                      {"action": "click", "target": ids(page, '"Create account"')}])
    assert "Hello Milk" in done  # its window never had the focus
    browser_ = web.brain.browser
    tab = browser_.owners["cli/watched"]["tabs"]["t1"]
    browser_.wire.call("Browser.setWindowBounds", {"windowId": tab.window, "bounds": {"windowState": "minimized"}})
    assert "Hello Milk" in kit.browser_read.func(ctx)  # minimized: read...
    pictured = kit.browser_view.func(ctx, picture=True)  # ...and pictured, its window back first
    assert len(pictured.images) == 1
    state = browser_.wire.call("Browser.getWindowBounds", {"windowId": tab.window})["bounds"]["windowState"]
    assert state == "normal"
    hidden = kit.browser_open.func(ctx, headless=True)
    assert "out of the user's sight" in hidden and where(web) == "hidden"
    assert web.brain.browser.status()["shown"] is False


def test_a_right_click_opens_the_page_s_menu_and_never_chrome_s(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/menu")
    windows = len(desktops.windows_of(web.brain.browser.process))
    box = ids(page, "Right click here")
    result = kit.browser_act.func(ctx, [{"action": "click", "target": box, "button": "right"}])
    assert "its own menu" in result
    time.sleep(0.5)
    assert len(desktops.windows_of(web.brain.browser.process)) == windows  # no menu window of Chrome's


def test_a_frame_of_another_site_is_read_and_used_like_the_page(web, site):
    ctx = context(web)
    page = kit.browser_open.func(ctx, site + "/shop")
    assert 'frame "Payment" (another site: localhost' in page and "not readable" not in page
    assert re.search(r'^  textbox e\d+ "Card"', page, re.M) and re.search(r'button e\d+ "Check card"', page)
    result = kit.browser_act.func(ctx, [{"action": "fill", "target": ids(page, '"Card"'), "text": "4242"},
                                        {"action": "click", "target": ids(page, '"Check card"')}])
    assert "checked 4242" in result
    found = kit.browser_view.func(ctx, find="Check card").text
    assert 'frame "Payment"' in found and '"Check card"' in found
    assert "checked 4242" in kit.browser_read.func(ctx)
    assert '"checked 4242" shows' in kit.browser_act.func(ctx, [{"action": "wait", "text": "checked 4242"}])
    browser_ = web.brain.browser
    tab = browser_.owners["cli/main"]["tabs"]["t1"]
    kit.browser_view.func(ctx, picture=True)
    with tab.lock:
        place = browser_._point(tab, ids(page, '"Check card"'), hit_test=False)  # in the window, the frame in view
    kit.browser_view.func(ctx, picture=True)
    x, y = round(place["x"] / tab.picture), round(place["y"] / tab.picture)
    pointed = kit.browser_act.func(ctx, [{"action": "click", "target": f"{x},{y}"}])
    assert 'at button e' in pointed and '"Check card"' in pointed  # what is there, from the frame's own world


def test_the_console_and_the_network_are_read(web, site):
    ctx = context(web)
    kit.browser_open.func(ctx, site + "/console")
    time.sleep(0.6)  # the error is thrown a moment after it loads, /api answers in half a second
    console = kit.browser_log.func(ctx)
    assert '[log] hello {"cups":2}' in console and "[warning] low milk" in console and "[error] spilled" in console
    assert "[uncaught error] Error: boom" in console
    assert kit.browser_log.func(ctx, find="spilled").splitlines()[1:] == [
        next(line for line in console.splitlines() if "spilled" in line)]
    network = kit.browser_log.func(ctx, "network")
    assert re.search(r"GET 200 document .*/console \(text/html\)", network)
    assert re.search(r"GET 200 fetch .*/api", network) and re.search(r"GET 404 fetch .*/missing", network)


def test_a_page_is_saved_as_a_file(web, site):
    ctx = context(web)
    kit.browser_open.func(ctx, site + "/form")
    result = kit.browser_act.func(ctx, [{"action": "save", "text": "form.pdf"}, {"action": "save", "text": "form.png"},
                                        {"action": "save", "text": "form.html"}, {"action": "save", "text": "form.pdf"}])
    assert (web.work / "form.pdf").read_bytes().startswith(b"%PDF")
    assert (web.work / "form (1).pdf").exists()  # never over a file that is there
    assert (web.work / "form.png").read_bytes().startswith(b"\x89PNG")
    assert "<h1>Sign up</h1>" in (web.work / "form.html").read_text(encoding="utf-8")
    assert "saved a PDF to" in result and "Nothing changed" in result
    page = kit.browser_open.func(ctx, site + "/doc.pdf")
    assert "This tab shows a PDF" in page
    kit.browser_act.func(ctx, [{"action": "save", "text": "doc.pdf"}])
    assert (web.work / "doc.pdf").read_bytes() == PDF  # the document itself, not a print of the viewer


def test_approvals_are_per_site(tmp_path, monkeypatch, site):
    from sentientmilk_framework import loop as loop_module
    from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider

    monkeypatch.setattr(loop_module, "RETRIES", (0, 0, 0))
    provider = FakeProvider().install(monkeypatch)
    server = start(tmp_path / "home")
    _hide(server)
    try:
        client = BrainClient(server.url, server.token)
        client.update_config(api_key="sk-test", base_url=PROVIDER_URL)
        client.declare_app("cli", name="CLI", environment="A terminal.", toolkits=["browser"])
        other = site.replace("127.0.0.1", "localhost")
        provider.replies += [tool_call("browser_open", {"url": site + "/form"}, "o1"),
                             tool_call("browser_act", {"steps": [{"action": "click", "target": "e3"}]}, "a1"), "ok",
                             tool_call("browser_act", {"steps": [{"action": "scroll", "text": "down"}]}, "a2"), "ok",
                             tool_call("browser_open", {"url": other + "/form"}, "o2"),
                             tool_call("browser_act", {"steps": [{"action": "scroll", "text": "down"}]}, "a3"), "ok"]
        asked = []
        client.turn("cli", "main", "sign up", on_approval=lambda event: asked.append(event) or "always")
        assert [event["arguments"]["site"] for event in asked] == ["127.0.0.1"]
        assert asked[0]["arguments"]["steps"][0]["about"]  # what e3 is, for the user to see
        assert client.app("cli")["settings"]["rules"]["allow"] == ["browser_act(127.0.0.1)"]
        client.turn("cli", "main", "scroll", on_approval=lambda event: asked.append(event) or "deny")
        assert len(asked) == 1
        client.turn("cli", "main", "the other site", on_approval=lambda event: asked.append(event) or "deny")
        assert [event["arguments"]["site"] for event in asked] == ["127.0.0.1", "localhost"]
    finally:
        server.close()


def test_show_and_hide_from_the_panel_and_clear(web, site):
    status = web.client.browser()
    assert status["command"] and status["has_profile"] and status["shown"] is False
    kit.browser_open.func(context(web), site + "/terms")
    opened = web.client.open_browser()
    assert opened["mode"] == "shown" and where(web) == "shown"
    assert kit.browser_view.func(context(web)).text.startswith("t1 · Terms")  # she goes on there
    hidden = web.client.open_browser(headless=True)
    assert hidden["mode"] == "off" and hidden["shown"] is False  # out of sight from her next call on
    cleared = web.client.clear_browser()
    assert not cleared["has_profile"]
