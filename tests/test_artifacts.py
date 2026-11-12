"""Artifacts (artifacts.py) in a real Chrome (or Edge) on a hidden desktop, against a shop of its own on 127.0.0.1:
what the user types for her goes into the page and nowhere else, and an order is shown as the page says it."""

import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sentientmilk_framework import BrainClient, browser, desktops
from sentientmilk_framework import loop as loop_module
from sentientmilk_framework.exceptions import BrainError
from sentientmilk_framework.server import start
from sentientmilk_framework.testing import PROVIDER_URL, FakeProvider, tool_call
from sentientmilk_framework.toolkits import ToolContext
from sentientmilk_framework.toolkits import browser as kit

pytestmark = pytest.mark.skipif(not desktops.WINDOWS or not browser.find_browser(),
                                reason="needs Windows (a hidden desktop) and Chrome or Edge")

CARD = "7319 4462 0185 5023"  # what the user types: it must show up nowhere but in the page
CARD_PLAIN = CARD.replace(" ", "")
CART = {}  # the shop's basket now: tests change it, the page shows it as it is

CHECKOUT = """<!doctype html><title>Checkout</title><h1>Card</h1>
<form action="/thanks" method="get">
<label>Card number <input id=card name=card autocomplete=cc-number></label>
<label>Note <input id=note name=note></label>
<button type=button onclick="echo.textContent = 'Card: ' + card.value">Show card</button>
<button type=submit>Pay now</button>
<button type=button onclick="paid.textContent = confirm('Confirm payment of 74,92 zł?') ? 'paid' : 'kept'">Finish</button>
</form><p id=echo>-</p><p id=paid>unpaid</p>
<script>card.addEventListener('change', () => console.log('card is', card.value));
document.forms[0].onsubmit = e => { e.preventDefault(); paid.textContent = 'paid'; }</script>"""
OTHER = """<!doctype html><title>Other</title><h1>Somewhere else</h1>
<label>Card number <input id=card></label>"""


def cart_page() -> str:
    lines = [("l1", "Mleko UHT 3,2% Łaciate", "1 l", "6", CART["milk"], CART["milk_total"])]
    if CART["butter"]:
        lines.append(("l2", "Masło Ekstra", "200 g", "1", "7,99 zł", "7,99 zł"))
    rows = "".join(f"<tr id={key}><td>{name}</td><td>{size}</td><td>{count}</td><td>{price}</td><td>{total}</td></tr>"
                   for key, name, size, count, price, total in lines)
    return f"""<!doctype html><title>Koszyk</title><h1>Koszyk</h1><table>{rows}</table>
<p>Dostawa: <span id=fee>9,99 zł</span></p><p>Brakuje <span id=short>12,00 zł</span> do darmowej dostawy</p>
<p>Termin: <span id=slot>wt 14.11, 18:00–20:00</span></p><p>Adres: <span id=addr>ul. Mleczna 5/2, 00-001 Warszawa</span></p>
<p>Razem: <strong id=total>{CART['total']}</strong></p>
<button onclick="paid.textContent = 'paid'">Zapłać</button><p id=paid>unpaid</p>"""


class Shop(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.partition("?")[0]
        body = {"/checkout": CHECKOUT, "/other": OTHER}.get(path) or (cart_page() if path == "/cart" else None)
        if body is None:
            self.send_response(404)
            return self.end_headers()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setattr(loop_module, "RETRIES", (0, 0, 0))
    provider = FakeProvider().install(patch)
    home, work = tmp_path_factory.mktemp("home"), tmp_path_factory.mktemp("work")
    server = start(home)
    server.brain.browser.desktop = "SentientMilkTests"  # nothing shows on the user's screen
    server.brain.browser.user_desktop = "SentientMilkTestsUser"
    client = BrainClient(server.url, server.token)
    client.update_config(api_key="sk-test-secret", base_url=PROVIDER_URL)
    client.declare_app("cli", name="CLI", environment="A terminal.", toolkits=["browser", "files"])
    yield SimpleNamespace(server=server, brain=server.brain, client=client, work=work, home=home, provider=provider)
    server.close()
    patch.undo()


def context(web, session):
    web.client.update_session("cli", session, cwd=str(web.work), roots=[str(web.work)])
    run_id = web.brain.store.add_run("cli", session, "turn", {}, status="working")
    return ToolContext(web.brain, web.brain.store.run(run_id), web.brain.profile("cli", session), "call-1")


def ids(text, what):
    """The id on the line that has ``what``."""
    line = next(line for line in text.splitlines() if what in line)
    return re.search(r"\be(\d+)\b", line).group(0)


def at(view, text):
    """The id a piece of text has in a view with texts=true."""
    return re.search(re.escape(text) + r" ⟨(e\d+)⟩", view).group(1)


def asking(web, session, call):
    """``call`` (a tool that waits for a panel) in a thread; the panel once it is open."""
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("result", call()), daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not web.client.artifacts("cli", session):
        assert time.time() < deadline and thread.is_alive(), out
        time.sleep(0.05)
    out["thread"] = thread
    return web.client.artifacts("cli", session)[0], out


def answered(out):
    out["thread"].join(30)
    return out["result"]


def tab_of(web, session):
    return web.brain.browser.owners[f"cli/{session}"]["tabs"]["t1"]


def page_says(web, session, expression):
    tab = tab_of(web, session)
    with tab.lock:
        return web.brain.browser._eval(tab, expression)


def typed_for_her(web, site, session, value=CARD):
    """The checkout open, the user typed ``value`` for its card field: (ctx, the page, the card's id)."""
    ctx = context(web, session)
    page = kit.browser_open.func(ctx, site + "/checkout")
    card = ids(page, '"Card number"')
    panel, out = asking(web, session, lambda: kit.browser_secrets.func(
        ctx, [{"name": "card_number", "target": card, "purpose": "your card number, to pay for the milk"}]))
    assert panel["kind"] == "secrets" and panel["site"] == "127.0.0.1"
    field = panel["fields"][0]
    assert (field["name"], field["target"], field["state"]) == ("card_number", card, "waiting")
    assert "Card number" in field["label"] and field["purpose"].startswith("your card number")
    web.client.artifact(panel["id"], "fill", values={"card_number": value})
    said = answered(out)
    assert "typed card_number" in said and value not in said
    return ctx, page, card


def test_what_the_user_types_reaches_the_page_and_nowhere_else(web, site, caplog):
    """1. Leak: a whole turn, the value typed into a page that shows it back in its text and its console; it is
    in no tool result, event, transcript, database, log or error, and no picture, script or saved copy is made."""
    caplog.set_level(logging.DEBUG)
    found = {}

    def secrets(payload):
        page = next(m for m in reversed(payload["messages"]) if m["role"] == "tool")["content"]
        found.update(card=ids(page, '"Card number"'), show=ids(page, '"Show card"'))
        return tool_call("browser_secrets", {"fields": [{"name": "card_number", "target": found["card"],
                                                          "purpose": "your card number"}]})

    web.provider.replies[:] = [
        tool_call("browser_open", {"url": site + "/checkout"}), secrets,
        lambda payload: tool_call("browser_act", {"steps": [
            {"action": "fill", "target": found["card"], "secret": "card_number"},
            {"action": "click", "target": found["show"]}]}),
        tool_call("browser_view", {"texts": True}), tool_call("browser_read", {}), tool_call("browser_log", {}),
        tool_call("browser_view", {"picture": True}), tool_call("browser_script", {"code": "card.value"}),
        tool_call("browser_act", {"steps": [{"action": "save", "text": "page.html"}]}), "Done."]
    errors = []

    def on_event(event):
        if event["type"] == "artifact.requested":
            def answer():
                try:  # a wrong answer's error never quotes what was sent
                    web.client.artifact(event["artifact"]["id"], "fill", values={"pin": CARD})
                except BrainError as exc:
                    errors.append(str(exc))
                web.client.artifact(event["artifact"]["id"], "fill", values={"card_number": CARD})
            threading.Thread(target=answer, daemon=True).start()

    web.client.update_session("cli", "leak", cwd=str(web.work), roots=[str(web.work)])
    events = []
    web.client.turn("cli", "leak", "Pay for the milk.", on_event=lambda e: (events.append(e), on_event(e)),
                    on_approval=lambda event: "allow")
    results = {e["name"] + str(i): e.get("result", "") for i, e in enumerate(events) if e["type"] == "tool.end"}
    assert len(results) == 9, [e["type"] for e in events]
    assert errors and "card_number" in errors[0]
    filled = next(r for r in results.values() if "filled" in r)
    assert f"1. filled {found['card']} (secret card_number)" in filled.splitlines()
    assert "Card: [the user's card_number]" in filled  # the page showed it back: she reads where, not what
    view, read, log, picture, script, save = list(results.values())[3:]
    assert "(filled with the user's card_number)" in view and "[the user's card_number]" in read
    assert "card is [the user's card_number]" in log
    assert "could show it" in picture and "could show it" in script and "could show it" in save
    assert page_says(web, "leak", "document.getElementById('card').value") == CARD  # the page has it
    assert page_says(web, "leak", "getComputedStyle(card).webkitTextSecurity") == "disc"  # dots in a picture
    assert not list(web.work.iterdir())  # nothing saved
    places = {"events": json.dumps(events, ensure_ascii=False), "errors": " ".join(errors), "logs": caplog.text,
              "transcript": json.dumps(web.client.session("cli", "leak"), ensure_ascii=False),
              "provider": json.dumps(web.provider.sent, ensure_ascii=False)}
    for name in ("brain.sqlite3", "brain.sqlite3-wal"):  # the database and its journal, as bytes
        path = web.home / name
        places[name] = path.read_bytes().decode("utf-8", "replace") if path.exists() else ""
    assert "card_number" in places["brain.sqlite3"] + places["brain.sqlite3-wal"]  # the turn is in there
    for name, text in places.items():
        assert CARD not in text and CARD_PLAIN not in text, name
    assert not web.client.artifacts("cli", "leak")  # the panel closed with the turn


def test_a_blind_fill_types_into_the_page_and_says_only_which_field(web, site):
    """2. The page's own value is set; the reply names the field, never the value or its length."""
    ctx, page, card = typed_for_her(web, site, "blind")
    result = kit.browser_act.func(ctx, [{"action": "fill", "target": card, "secret": "card_number"}])
    line = next(line for line in result.splitlines() if line.startswith("1. "))
    assert line == f"1. filled {card} (secret card_number)"
    assert page_says(web, "blind", "document.getElementById('card').value") == CARD
    assert "(filled with the user's card_number)" in kit.browser_view.func(ctx, find="Card number").text
    again = kit.browser_act.func(ctx, [{"action": "fill", "target": card, "secret": "card_number"}])
    assert "No value named card_number waits" in again  # once: it is gone
    assert not web.client.artifacts("cli", "blind")


def test_a_page_that_moved_on_is_not_typed_into(web, site):
    """3. Asked on page A, the tab went to B: the fill is refused and nothing is typed anywhere."""
    ctx, page, card = typed_for_her(web, site, "moved")
    kit.browser_open.func(ctx, site + "/other")
    result = kit.browser_act.func(ctx, [{"action": "fill", "target": card, "secret": "card_number"}])
    assert f"1. fill {card} (secret card_number): not typed: page changed" in result
    assert page_says(web, "moved", "document.getElementById('card').value") == ""
    assert "No value named card_number" in kit.browser_act.func(
        ctx, [{"action": "fill", "target": card, "secret": "card_number"}])  # refused: gone, not kept for later


def test_the_field_gets_the_value_not_whatever_has_the_focus(web, site):
    """4. Another field has the focus: the value goes into its own field, and the focused one stays empty."""
    ctx, page, card = typed_for_her(web, site, "focus")
    assert page_says(web, "focus", "(document.getElementById('note').focus(), document.activeElement.id)") == "note"
    result = kit.browser_act.func(ctx, [{"action": "fill", "target": card, "secret": "card_number"}])
    assert f"1. filled {card} (secret card_number)" in result
    assert page_says(web, "focus", "document.getElementById('card').value") == CARD
    assert page_says(web, "focus", "document.getElementById('note').value") == ""
    other = typed_for_her(web, site, "focus")[2]  # the same field on a new page: asked for e14, not the note
    note = ids(kit.browser_view.func(ctx, find="Note").text, '"Note"')
    refused = kit.browser_act.func(ctx, [{"action": "fill", "target": note, "secret": "card_number"}])
    assert f"not typed: card_number is for {other}" in refused
    assert page_says(web, "focus", "document.getElementById('note').value") == ""


def test_an_order_is_shown_as_the_page_says_it_and_a_changed_one_asks_again(web, site):
    """5. The panel's numbers are read from the page, with a picture; a price that changes makes it stale, with
    what changed, and only a yes to the order as it is now counts."""
    CART.update(milk="8,39 zł", milk_total="50,34 zł", butter=True, total="68,32 zł")
    ctx = context(web, "order")
    kit.browser_open.func(ctx, site + "/cart")
    view = kit.browser_view.func(ctx, texts=True).text
    line = {"name": at(view, "Mleko UHT 3,2% Łaciate"), "size": at(view, "1 l"), "quantity": at(view, "6"),
            "price": at(view, "8,39 zł"), "total": at(view, "50,34 zł"), "why": "cheapest per litre of the 3,2% ones"}
    butter = {"name": at(view, "Masło Ekstra"), "price": at(view, "7,99 zł"), "total": at(view, "7,99 zł")}
    panel, out = asking(web, "order", lambda: kit.browser_review.func(
        ctx, lines=[line, butter], charges=[{"label": "Delivery", "amount": at(view, "9,99 zł")}],
        total=at(view, "68,32 zł"), shortfall=at(view, "12,00 zł"), slot=at(view, "wt 14.11, 18:00–20:00"),
        address=at(view, "ul. Mleczna 5/2, 00-001 Warszawa"), unverified="Substitutions: the shop did not say."))
    assert panel["kind"] == "review" and panel["state"] == "open" and panel["site"] == "127.0.0.1"
    first = panel["lines"][0]
    assert [first[key]["text"] for key in ("name", "size", "quantity", "price", "total")] == \
        ["Mleko UHT 3,2% Łaciate", "1 l", "6", "8,39 zł", "50,34 zł"]
    assert first["why"] == "cheapest per litre of the 3,2% ones" and first["price"]["rect"][2] > 0
    assert panel["address"]["text"] == "ul. Mleczna 5/2, 00-001 Warszawa" and panel["slot"]["text"].startswith("wt")
    assert panel["charges"][0] == {"label": "Delivery", "amount": panel["charges"][0]["amount"]}
    assert panel["charges"][0]["amount"]["text"] == "9,99 zł" and panel["shortfall"]["text"] == "12,00 zł"
    assert panel["picture"].startswith("data:image/jpeg;base64,") and re.fullmatch(r"[0-9a-f]{16}", panel["fingerprint"])
    assert panel["unverified"].startswith("Substitutions")
    same = web.client.artifact(panel["id"], "refresh")
    assert same["fingerprint"] == panel["fingerprint"] and same["state"] == "open"

    CART.update(milk="9,49 zł", milk_total="56,94 zł", total="74,92 zł")  # the shop changed a price
    kit.browser_act.func(context(web, "order"), [{"action": "reload"}])
    stale = web.client.artifact(panel["id"], "refresh")
    assert stale["state"] == "changed" and stale["fingerprint"] != panel["fingerprint"]
    assert {"what": "line 1 price", "was": "8,39 zł", "now": "9,49 zł"} in stale["changes"]
    assert {"what": "total", "was": "68,32 zł", "now": "74,92 zł"} in stale["changes"]
    old = web.client.artifact(panel["id"], "approve", fingerprint=panel["fingerprint"])  # a yes to what was
    assert old["state"] == "changed" and web.client.artifacts("cli", "order") and out["thread"].is_alive()

    CART.update(butter=False)  # out of stock
    kit.browser_act.func(context(web, "order"), [{"action": "reload"}])
    gone = web.client.artifact(panel["id"], "refresh")
    assert {"what": "line 2 name", "was": "Masło Ekstra", "now": None} in gone["changes"]
    approved = web.client.artifact(panel["id"], "approve", fingerprint=gone["fingerprint"])
    assert approved["state"] == "approved"
    said = answered(out)
    assert "approved the order" in said and gone["fingerprint"] in said and "never yours" in said
    assert page_says(web, "order", "document.getElementById('paid').textContent") == "unpaid"


def test_nothing_pays_neither_the_panel_nor_her_browser(web, site):
    """6. The panel has no pay; her browser refuses to press what pays, by click, by Enter in its form, by
    pointing at it, and a dialog that pays."""
    CART.update(milk="8,39 zł", milk_total="50,34 zł", butter=True, total="68,32 zł")
    ctx = context(web, "pay")
    page = kit.browser_open.func(ctx, site + "/cart")
    view = kit.browser_view.func(ctx, texts=True).text
    panel, out = asking(web, "pay", lambda: kit.browser_review.func(
        ctx, lines=[{"name": at(view, "Masło Ekstra"), "total": at(view, "7,99 zł")}], total=at(view, "68,32 zł")))
    for action in ("pay", "buy", "confirm", "click"):
        with pytest.raises(BrainError, match="approve"):
            web.client.artifact(panel["id"], action)
    web.client.artifact(panel["id"], "approve", fingerprint=panel["fingerprint"])
    assert "approved" in answered(out)
    assert page_says(web, "pay", "document.getElementById('paid').textContent") == "unpaid"

    refused = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Zapłać"')}])
    assert "pays: paying is the user's own" in refused
    page = kit.browser_open.func(ctx, site + "/checkout")
    note = ids(page, '"Note"')
    for steps in ([{"action": "click", "target": ids(page, '"Pay now"')}],
                  [{"action": "type", "target": note, "text": "hi\n"}],
                  [{"action": "key", "target": note, "text": "Enter"}]):
        assert "pays: paying is the user's own" in kit.browser_act.func(ctx, steps)
    kit.browser_view.func(ctx, picture=True)
    tab = tab_of(web, "pay")
    with tab.lock:
        place = web.brain.browser._point(tab, ids(page, '"Pay now"'))
    x, y = round(place["x"] / tab.picture), round(place["y"] / tab.picture)
    assert "pays" in kit.browser_act.func(ctx, [{"action": "click", "target": f"{x},{y}"}])
    assert page_says(web, "pay", "document.getElementById('paid').textContent") == "unpaid"
    assert page_says(web, "pay", "document.getElementById('note').value") == ""  # stopped before typing
    asked = kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Finish"')},
                                       {"action": "dialog", "accept": True}])
    assert "The page's dialog \"Confirm payment of 74,92 zł?\" pays" in asked
    kit.browser_act.func(ctx, [{"action": "dialog", "accept": False}])
    assert page_says(web, "pay", "document.getElementById('paid').textContent") == "kept"
    assert "Show card" in kit.browser_act.func(ctx, [{"action": "click", "target": ids(page, '"Show card"')}])
