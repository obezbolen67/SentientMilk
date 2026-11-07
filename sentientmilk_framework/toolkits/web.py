"""Web: search with Brave Search and read pages as text."""

import re
from html.parser import HTMLParser

import requests

from . import ToolContext, ToolError, Toolkit, tool

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
PAGE_CHARS = 20_000
MAX_DOWNLOAD = 5 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; SentientMilk/0.4; +local assistant)"
_SKIPPED = {"script", "style", "noscript", "svg", "template", "head"}
_BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
           "footer", "pre", "blockquote", "table", "ul", "ol", "dd", "dt", "hr"}


@tool(core=True, readonly=True, args={"query": "What to search for, as you would type it into a search engine.",
                           "count": "Number of results, 1-20 (default 8).",
                           "freshness": "Optional: pd (past day), pw (week), pm (month) or py (year)."})
def web_search(ctx: ToolContext, query: str, count: int = 8, freshness: str = ""):
    """Search the web. Returns title, URL, age and a snippet per result; read promising pages with web_fetch.
    Do not add the current year to queries unless the user asks about a specific time."""
    key = ctx.brain.config.values()["web_search_key"]
    if not key:
        raise ToolError("Web search is not set up: the brain needs a Brave Search key (setting web_search_key).")
    if not query.strip():
        raise ToolError("query is empty.")
    params = {"q": query.strip(), "count": max(1, min(int(count or 8), 20))}
    if freshness:
        params["freshness"] = freshness
    try:
        response = requests.get(BRAVE_ENDPOINT, params=params, timeout=30,
                                headers={"Accept": "application/json", "X-Subscription-Token": key})
    except requests.RequestException as exc:
        raise ToolError(f"Brave Search could not be reached: {exc}")
    if response.status_code != 200:
        raise ToolError(f"Brave Search answered {response.status_code}: {response.text[:300]}")
    results = (response.json().get("web") or {}).get("results") or []
    if not results:
        return f"No results for {query!r}."
    return "\n\n".join(
        f"{n}. {item.get('title', '')}\n   {item.get('url', '')}" + (f" ({item['age']})" if item.get("age") else "")
        + f"\n   {_strip_tags(item.get('description', ''))}" for n, item in enumerate(results, 1))


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIPPED and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        joined = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.parts))
        return re.sub(r"\n\s*\n+", "\n\n", joined).strip()


def page_text(html: str):
    parser = _Text()
    parser.feed(html)
    return parser.title.strip(), parser.text()


@tool(core=True, readonly=True, rule_arg="url", args={"url": "Full http(s) URL.",
                                           "offset": "Character to start from, to read further into a long page."})
def web_fetch(ctx: ToolContext, url: str, offset: int = 0):
    """Read a web page as plain text (HTML is converted; text and JSON come as they are). Long pages come in
    parts of 20,000 characters: continue with the offset the result names."""
    if not re.match(r"https?://", url or ""):
        raise ToolError("url must start with http:// or https://")
    try:
        response = requests.get(url, timeout=(10, 30), stream=True, headers={"User-Agent": USER_AGENT})
        body = response.raw.read(MAX_DOWNLOAD + 1, decode_content=True)
        response.close()
    except requests.RequestException as exc:
        raise ToolError(f"Could not fetch {url}: {exc}")
    if response.status_code >= 400:
        raise ToolError(f"{url} answered {response.status_code}.")
    kind = response.headers.get("Content-Type", "").lower()
    encoding = response.encoding or "utf-8"
    if "html" in kind or (not kind and body.lstrip()[:1] == b"<"):
        title, text = page_text(body.decode(encoding, errors="replace"))
    elif kind.startswith("text/") or "json" in kind or "xml" in kind or not kind:
        title, text = "", body.decode(encoding, errors="replace")
    else:
        raise ToolError(f"{url} is {kind or 'binary'}, not a page that can be read as text.")
    if len(body) > MAX_DOWNLOAD:
        text += "\n[The page is over 5 MB; the rest was not downloaded.]"
    start = max(0, int(offset or 0))
    part = text[start:start + PAGE_CHARS]
    header = f"{title}\n{response.url}\n\n" if title else f"{response.url}\n\n"
    if start + PAGE_CHARS < len(text):
        if start == 0:
            ctx.save_output(text, "page")
        part += f"\n\n[Characters {start}-{start + len(part)} of {len(text)}. Continue with offset={start + PAGE_CHARS}.]"
    return header + part


TOOLKIT = Toolkit("web", "Search the web and read pages.", [web_search, web_fetch])
