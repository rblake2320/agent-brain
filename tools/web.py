"""Internet access tools — web search and page fetch."""
from __future__ import annotations

import re
import urllib.parse

import httpx

from ..config import WEB_FETCH_MAX_CHARS
from . import tool

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s{3,}")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_html(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub("\n", text)
    return text.strip()


@tool(
    name="web_search",
    description=(
        "Search the internet using DuckDuckGo. Returns a list of results with "
        "title, URL, and snippet. Use this to find information, research topics, "
        "or discover URLs to fetch."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, num_results: int = 5) -> str:
    num_results = min(num_results, 10)
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        return f"[ERROR] Search failed: {exc}"

    # Parse DuckDuckGo HTML results
    results = []
    # Result blocks use class="result__body"
    result_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    for m in result_pattern.finditer(html):
        href = m.group(1)
        # DuckDuckGo redirects — extract actual URL
        parsed = urllib.parse.urlparse(href)
        if parsed.path == "/l/":
            qs = urllib.parse.parse_qs(parsed.query)
            href = qs.get("uddg", [href])[0]

        title = _TAG_RE.sub("", m.group(2)).strip()
        snippet = _TAG_RE.sub("", m.group(3)).strip()
        if title and href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= num_results:
            break

    if not results:
        # Fallback: extract any links from the page
        link_pattern = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>')
        for m in link_pattern.finditer(html):
            url_found = m.group(1)
            title = m.group(2).strip()
            if "duckduckgo.com" not in url_found and title:
                results.append({"title": title, "url": url_found, "snippet": ""})
            if len(results) >= num_results:
                break

    if not results:
        return f"[No results found for: {query}]"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


@tool(
    name="web_fetch",
    description=(
        "Fetch the content of a web page and return it as readable text. "
        "HTML is stripped. Content is truncated to 8000 chars. "
        "Use this after web_search to read the content of a specific URL."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    },
)
async def web_fetch(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type or "text/plain" in content_type:
                text = _strip_html(resp.text)
            else:
                text = resp.text
    except httpx.HTTPStatusError as exc:
        return f"[ERROR] HTTP {exc.response.status_code} for {url}"
    except Exception as exc:
        return f"[ERROR] Fetch failed: {exc}"

    if len(text) > WEB_FETCH_MAX_CHARS:
        text = text[:WEB_FETCH_MAX_CHARS] + f"\n... [truncated — {len(text)} chars total]"

    return f"Content from {url}:\n\n{text}"
