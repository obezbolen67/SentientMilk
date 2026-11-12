"""Browser: her own Chrome (browser.py), for the web as a person uses it: pages that need scripts, clicks, forms,
sign-ins. Pages come as text with an id on each thing she can use; she acts on ids, several steps per call."""

from typing import Optional

from . import ToolContext, Toolkit, ToolResult, cap, tool

STEP = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["click", "fill", "type", "key", "hover", "scroll", "drag", "upload",
                                              "wait", "open", "back", "forward", "reload", "dialog", "save", "close",
                                              "show"]},  # browser.STEPS
        "target": {"type": "string", "description": "An id from the latest view (e5), or \"x,y\" in the tab's "
                                                    "latest picture."},
        "text": {"type": "string", "description": "fill: what the field holds after (an option's text for a "
                                                  "select, true/false for a checkbox); type: text to type; key: keys "
                                                  "(Enter, Tab, Escape, ctrl+a, shift+Tab, several with spaces); "
                                                  "scroll: down, up, top or bottom; wait: words to wait for; "
                                                  "open: the address; dialog: a prompt's answer; save: a file name "
                                                  "in the working folder (.pdf, .png, .jpg, .html, .mhtml)."},
        "secret": {"type": "string", "description": "fill, in place of text: the name of a value the user typed for "
                                                    "this field in browser_secrets. It goes into the field unseen; "
                                                    "each value types once."},
        "to": {"type": "string", "description": "drag: where it ends (an id or \"x,y\")."},
        "files": {"type": "array", "items": {"type": "string"}, "description": "upload: the files' paths."},
        "amount": {"type": "number", "description": "scroll: screens (1 if not given); wait: seconds at most."},
        "accept": {"type": "boolean", "description": "dialog: true to accept (OK), false to dismiss (Cancel)."},
        "double": {"type": "boolean", "description": "click: a double click."},
        "button": {"type": "string", "enum": ["left", "right", "middle"]},
    },
    "required": ["action"],
}
TAB = "Which of your tabs (t1, t2...); empty: the one you are in."
GUIDE = ("Your browser is a Chrome of your own on the user's connection: the sites you sign in to stay signed in. It "
         "runs out of their sight unless they want to watch you: then browser_open headless=false puts it on their "
         "screen (it works the same there, in front or not), and headless=true takes it back. Use it for the web "
         "(pages that need scripts, clicks, forms, accounts) rather than the screen; web_fetch stays quicker for "
         "reading a public page once. A page comes as lines, and each thing you can use has an id: button e5 \"Sign "
         "in\" (frames of other sites too). Act by ids in browser_act, all the steps you know in one call (fill e3, "
         "fill e4, click e5); its reply says what changed. Ids hold while the page lives; after a page changes to "
         "another, use the ids of its new view. What has no id (a canvas, a map) you point at in a picture: "
         "browser_view picture=true, then target \"x,y\" in it. Your tabs (t1, t2...) are this conversation's and "
         "stay; links that open a new tab or window open one of yours. When the user wants you to use their own "
         "Chrome (where they are signed in), browser_open in_user_chrome=true opens a tab of yours there, and every "
         "tool works in it the same; their own tabs are never yours. Sign-ins (unless the user gave you what to "
         "type), checks that you are a human (never try to pass them yourself) and payments are the user's: the "
         "step show puts your browser in front of them for it. What you must not see (a card number, a password, a "
         "code) the user types in a panel: browser_secrets, then fill steps with secret. Before they pay for an "
         "order you put together, browser_review shows it to them as the page says it, for their yes; you never "
         "press pay (your browser refuses).")


def _seen(brain, run, arguments):
    return brain.browser.seen(run, arguments)


@tool(core=True, policy="auto", rule_arg="site", seen=_seen, guide=GUIDE, args={
    "url": "The address to open (https://...); empty with headless: the tab you are in, moved.",
    "new_tab": "Open it in a new tab of yours (keeping the page you are on); otherwise in the tab you are in.",
    "headless": "false: your browser on the user's screen from now on, for them to watch you; true: out of their "
                "sight again. Leave it out to keep it where it is.",
    "in_user_chrome": "true: in a tab of yours in the user's own Chrome, signed in as they are there (their saved "
                      "accounts); false: in your browser again. Leave it out to stay where your tab is."})
def browser_open(ctx: ToolContext, url: str = "", new_tab: bool = False, headless: Optional[bool] = None,
                 in_user_chrome: Optional[bool] = None):
    """Open a page in your browser and see it: its text, with an id on each thing you can use (links, buttons,
    fields), to act on with browser_act."""
    return cap(ctx, ctx.brain.browser.open(ctx, url, new_tab, headless, in_user_chrome), "page")


@tool(readonly=True, rule_arg="site", seen=_seen, args={  # open and act show the page: this is for looking again
    "tab": TAB,
    "find": "Only the lines with these words (and what they are in): to find a field or a button on a long page.",
    "part": "An id (e12) of a part of the page, to see all of it: a long list or table shows only its start.",
    "picture": "Add a picture of the tab's window: for what text does not show (a canvas, a map, a layout), and "
               "for pointing at things without ids.",
    "texts": "true: every piece of text gets an id too (8,39 zł ⟨e44⟩): to point at names, prices and an address "
             "in browser_review."})
def browser_view(ctx: ToolContext, tab: str = "", find: str = "", part: str = "", picture: bool = False,
                 texts: bool = False):
    """See a tab as it is now: its text, with an id on each thing you can use."""
    result = ctx.brain.browser.view(ctx, tab, find, part, picture, texts)
    return ToolResult(cap(ctx, result.text, "page"), result.images)


@tool(core=True, policy="ask", rule_arg="site", seen=_seen, args={
    "steps": {"type": "array", "items": STEP, "description":
              "The steps in order, e.g. [{\"action\": \"fill\", \"target\": \"e3\", \"text\": \"milk\"}, "
              "{\"action\": \"click\", \"target\": \"e4\"}]. They stop at the first that fails, at a dialog of the "
              "page, and when the tab goes to another site. show: your browser in front of the user, on their "
              "screen (they sign in or pass a check there); save: the page as a file; close: closes the tab."},
    "tab": TAB})
def browser_act(ctx: ToolContext, steps: list, tab: str = ""):
    """Use a page as the user would: click, fill fields, type, press keys, scroll, drag, upload files, answer
    the page's dialogs, go back. Says how each step went and what changed on the page."""
    return cap(ctx, ctx.brain.browser.act(ctx, steps, tab), "page")


@tool(readonly=True, rule_arg="site", seen=_seen, args={
    "tab": TAB, "offset": "Character to start from, to read further into a long page."})
def browser_read(ctx: ToolContext, tab: str = "", offset: int = 0):
    """Read a tab's page as text to read (an article, documentation, results), with its links: no ids, 20,000
    characters at a time."""
    return ctx.brain.browser.read(ctx, tab, offset)


@tool(policy="ask", rule_arg="site", seen=_seen, args={
    "code": "JavaScript run in the page (await works); the value of its last expression comes back as JSON.",
    "tab": TAB})
def browser_script(ctx: ToolContext, code: str, tab: str = ""):
    """Run JavaScript in a tab's page, with the page's own variables: to take data out of a page in bulk (every
    row of a table) or to do what steps cannot."""
    return cap(ctx, ctx.brain.browser.script(ctx, code, tab), "script")


@tool(readonly=True, rule_arg="site", seen=_seen, args={
    "kind": {"type": "string", "enum": ["console", "network"], "description":
             "console: what the page said (its logs, warnings and errors, the uncaught ones too); network: the "
             "requests it made, each with its status."},
    "tab": TAB, "find": "Only the lines with these words."})
def browser_log(ctx: ToolContext, kind: str = "console", tab: str = "", find: str = ""):
    """A tab's console or network requests since its page loaded: for why a page does not work, or what it
    asks its server for."""
    return cap(ctx, ctx.brain.browser.log(ctx, kind, tab, find), "page")


FIELD = {"type": "object", "properties": {
    "name": {"type": "string", "description": "What it is, in letters, digits and _ (card_number, password): the "
                                              "name a fill step types it by."},
    "target": {"type": "string", "description": "The field's id in the latest view (e14): where it goes, and nowhere "
                                                "else."},
    "purpose": {"type": "string", "description": "What it is for, in a few words the user reads beside it (\"your "
                                                 "card number, to pay for the order\")."}},
    "required": ["name", "target", "purpose"]}


@tool(policy="auto", rule_arg="site", seen=_seen, args={
    "fields": {"type": "array", "items": FIELD, "description": "The fields the user types into, one each."},
    "tab": TAB})
def browser_secrets(ctx: ToolContext, fields: list, tab: str = ""):
    """Ask the user to type what you must never see (a card number, a password, a one-time code) in a panel in their
    chat: it shows them the site and the field each goes into, and waits until they typed it or closed the panel.
    What they type stays out of your sight: a fill step with secret types it into its field."""
    return ctx.brain.browser.ask_secrets(ctx, fields, tab)


PART = ("Its id in the latest view (e44; browser_view texts=true gives each piece of text one): the brain reads it "
        "from the page, so the user sees what the page says.")
LINE = {"type": "object", "properties": {
    "name": {"type": "string", "description": "The item's name. " + PART},
    "size": {"type": "string", "description": "Its size or weight, if the page shows one. " + PART},
    "quantity": {"type": "string", "description": "How many. " + PART},
    "price": {"type": "string", "description": "Its price for one. " + PART},
    "total": {"type": "string", "description": "The line's total. " + PART},
    "why": {"type": "string", "description": "In one line, why this one, when you chose between options (a variant, "
                                             "a size, a pack, how many; cheapest per kg or per pack): the user checks "
                                             "the rule you used."}},
    "required": ["name", "total"]}
CHARGE = {"type": "object", "properties": {
    "label": {"type": "string", "description": "What it is, in your word: Delivery, Packing, Service."},
    "amount": {"type": "string", "description": "What it costs. " + PART}}, "required": ["label", "amount"]}


@tool(policy="auto", rule_arg="site", seen=_seen, args={
    "lines": {"type": "array", "items": LINE, "description": "Each item of the order, as the page lists it."},
    "charges": {"type": "array", "items": CHARGE, "description": "Every charge besides the items: delivery, "
                                                                 "packing, service fees."},
    "total": "What the order costs in all. " + PART,
    "shortfall": "What is missing to a minimum order or to free delivery (\"12,00 zł to free delivery\"), if the "
                 "page says it. " + PART,
    "slot": "The delivery or pick-up time. " + PART,
    "address": "Where it goes. " + PART,
    "unverified": "What you could not check, in plain words (a substitution policy, a price that only shows at "
                  "payment): the user reads it last.",
    "tab": TAB})
def browser_review(ctx: ToolContext, lines: list, total: str, charges: Optional[list] = None, shortfall: str = "",
                   slot: str = "", address: str = "", unverified: str = "", tab: str = ""):
    """Before the user pays for an order you put together (a basket, a booking, a form you filled), show it to
    them in a panel in their chat as the page says it: you point at the page's parts, the brain reads each from the
    page with a picture of it, and your why beside each choice. Waits for their yes or no; a yes is for exactly
    what they saw (an order that changes asks again). They pay themselves: there is no paying for you."""
    order = {"lines": lines, "charges": charges or [], "total": total, "shortfall": shortfall, "slot": slot,
             "address": address, "unverified": unverified}
    return ctx.brain.browser.review(ctx, order, tab)


TOOLKIT = Toolkit("browser", "Your own web browser (Chrome): open sites, read them, click, type, fill in forms, sign "
                             "in once and stay signed in; out of the user's sight, or on their screen to watch.",
                  [browser_open, browser_view, browser_act, browser_read, browser_script, browser_log, browser_secrets,
                   browser_review])
