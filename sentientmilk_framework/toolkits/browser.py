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
         "stay; links that open a new tab or window open one of yours. Sign-ins (unless the user gave you what to "
         "type), checks that you are a human (never try to pass them yourself) and payments are the user's: the "
         "step show puts your browser in front of them for it.")


def _seen(brain, run, arguments):
    return brain.browser.seen(run, arguments)


@tool(core=True, policy="auto", rule_arg="site", seen=_seen, guide=GUIDE, args={
    "url": "The address to open (https://...); empty with headless: the tab you are in, moved.",
    "new_tab": "Open it in a new tab of yours (keeping the page you are on); otherwise in the tab you are in.",
    "headless": "false: your browser on the user's screen from now on, for them to watch you; true: out of their "
                "sight again. Leave it out to keep it where it is."})
def browser_open(ctx: ToolContext, url: str = "", new_tab: bool = False, headless: Optional[bool] = None):
    """Open a page in your browser and see it: its text, with an id on each thing you can use (links, buttons,
    fields), to act on with browser_act."""
    return cap(ctx, ctx.brain.browser.open(ctx, url, new_tab, headless), "page")


@tool(readonly=True, rule_arg="site", seen=_seen, args={  # open and act show the page: this is for looking again
    "tab": TAB,
    "find": "Only the lines with these words (and what they are in): to find a field or a button on a long page.",
    "part": "An id (e12) of a part of the page, to see all of it: a long list or table shows only its start.",
    "picture": "Add a picture of the tab's window: for what text does not show (a canvas, a map, a layout), and "
               "for pointing at things without ids."})
def browser_view(ctx: ToolContext, tab: str = "", find: str = "", part: str = "", picture: bool = False):
    """See a tab as it is now: its text, with an id on each thing you can use."""
    result = ctx.brain.browser.view(ctx, tab, find, part, picture)
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


TOOLKIT = Toolkit("browser", "Your own web browser (Chrome): open sites, read them, click, type, fill in forms, sign "
                             "in once and stay signed in; out of the user's sight, or on their screen to watch.",
                  [browser_open, browser_view, browser_act, browser_read, browser_script, browser_log])
