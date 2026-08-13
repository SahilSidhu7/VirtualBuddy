"""Web search with no API key and no cost.

DuckDuckGo's HTML endpoint first, a public SearXNG instance as backup. Both
return plain HTML we parse ourselves, so there's no SDK and no quota.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from vb.web.fetch import HEADERS, TIMEOUT

DDG = "https://html.duckduckgo.com/html/"
SEARX = "https://searx.be/search"


@dataclass
class Hit:
    title: str
    url: str
    snippet: str = ""

    def line(self, i: int) -> str:
        return f"{i}. {self.title}\n   {self.url}\n   {self.snippet}".rstrip()


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _unwrap(href: str) -> str:
    """DDG wraps results in /l/?uddg=<encoded>."""
    if "uddg=" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if q.get("uddg"):
            return q["uddg"][0]
    return "https:" + href if href.startswith("//") else href


def _ddg(query: str, limit: int) -> list[Hit]:
    import httpx
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as c:
        r = c.post(DDG, data={"q": query})
        raw = r.text
    hits = []
    for m in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            raw, re.S):
        url, title = _unwrap(html.unescape(m.group(1))), _clean(m.group(2))
        if url.startswith("http") and title:
            hits.append(Hit(title=title, url=url))
        if len(hits) >= limit:
            break
    snippets = [_clean(s) for s in re.findall(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', raw, re.S)]
    for hit, snip in zip(hits, snippets):
        hit.snippet = snip
    return hits


def _searx(query: str, limit: int) -> list[Hit]:
    import httpx
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as c:
        r = c.get(SEARX, params={"q": query, "format": "json"})
        if "json" in r.headers.get("content-type", ""):
            data = r.json().get("results", [])
            return [Hit(title=d.get("title", ""), url=d.get("url", ""),
                        snippet=d.get("content", "")) for d in data[:limit]]
    return []


def search(query: str, limit: int = 6) -> list[Hit]:
    for engine in (_ddg, _searx):
        try:
            hits = engine(query, limit)
            if hits:
                return hits
        except Exception:
            continue
    return []
