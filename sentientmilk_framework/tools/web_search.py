"""Brave web search tool."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

DESCRIPTION = """
Search the web using Brave Search API. Returns structured web (and optional news) results
with customizable pagination, localization, and safety controls.
""".strip()

ARGS_DESCRIPTION = {
    "query": "Search query string (required).",
    "count": "Number of web results to return (1-20, default 5).",
    "offset": "Result page offset (0-9) to paginate through results.",
    "safesearch": "Safe-search level: off, moderate, or strict.",
    "country": "2-letter country code for localized rankings (default US).",
    "search_lang": "Language code for returned documents (default en).",
    "ui_lang": "Locale for UI strings (default en-US).",
    "freshness": "Optional freshness filter (pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD).",
    "extra_snippets": "Whether to request extra snippets (true/false).",
    "summary": "Whether to request summarizer key generation (true/false).",
    "api_key": "Override Brave subscription token (defaults to env BRAVE_API_KEY or baked-in key).",
}

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT = 30


class BraveSearchError(RuntimeError):
    """Raised when the Brave API responds with an error."""


def _resolve_api_key(override_key: Optional[str]) -> str:
    token = override_key or os.getenv("BRAVE_API_KEY")
    if not token:
        raise BraveSearchError("Brave API key not provided. Set BRAVE_API_KEY or pass api_key.")
    return token


def _build_params(
    query: str,
    count: int,
    offset: int,
    safesearch: str,
    country: str,
    search_lang: str,
    ui_lang: str,
    freshness: Optional[str],
    extra_snippets: bool,
    summary: bool,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "q": query,
        "count": count,
        "offset": offset,
        "safesearch": safesearch,
        "country": country,
        "search_lang": search_lang,
        "ui_lang": ui_lang,
        "extra_snippets": str(extra_snippets).lower(),
        "summary": str(summary).lower(),
    }
    if freshness:
        params["freshness"] = freshness
    return params


def _extract_results(payload: Dict[str, Any]) -> Dict[str, Any]:
    web_results: List[Dict[str, Any]] = []
    web_section = payload.get("web", {}) or {}
    for item in web_section.get("results", []) or []:
        web_results.append(
            {
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "page_age": item.get("page_age"),
                "thumbnail": item.get("thumbnail"),
            }
        )

    news_section = payload.get("news") or {}
    news_results: List[Dict[str, Any]] = []
    for item in news_section.get("results", []) or []:
        news_results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "publisher": item.get("source"),
                "published": item.get("published"),
            }
        )

    return {
        "query": payload.get("query", {}),
        "web_results": web_results,
        "news_results": news_results,
        "summary_key": (payload.get("summarizer") or {}).get("key"),
    }


def _coerce_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer value, got {value!r}") from exc


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean value, got {value!r}")


def run(
    query: str,
    count: Any = 5,
    offset: Any = 0,
    safesearch: str = "moderate",
    country: str = "US",
    search_lang: str = "en",
    ui_lang: str = "en-US",
    freshness: Optional[str] = None,
    extra_snippets: Any = False,
    summary: Any = False,
    api_key: Optional[str] = None,
):
    """Execute a Brave web search and return simplified results."""
    query = (query or "").strip()
    if not query:
        raise ValueError("Query must be a non-empty string.")
    count = _coerce_int(count, 5)
    offset = _coerce_int(offset, 0)
    extra_snippets = _coerce_bool(extra_snippets, False)
    summary = _coerce_bool(summary, False)

    if not (1 <= count <= 20):
        raise ValueError("count must be between 1 and 20")
    if not (0 <= offset <= 9):
        raise ValueError("offset must be between 0 and 9")
    if safesearch not in {"off", "moderate", "strict"}:
        raise ValueError("safesearch must be one of: off, moderate, strict")

    token = _resolve_api_key(api_key)
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": token,
    }

    params = _build_params(
        query=query,
        count=count,
        offset=offset,
        safesearch=safesearch,
        country=country,
        search_lang=search_lang,
        ui_lang=ui_lang,
        freshness=freshness,
        extra_snippets=extra_snippets,
        summary=summary,
    )

    try:
        response = requests.get(
            BRAVE_ENDPOINT,
            headers=headers,
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise BraveSearchError(f"Network error communicating with Brave: {exc}") from exc

    if response.status_code != 200:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = response.text
        raise BraveSearchError(
            f"Brave API error ({response.status_code}): {error_payload}"
        )

    payload: Dict[str, Any] = response.json()
    return _extract_results(payload)
