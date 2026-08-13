"""Web search with no API key and no cost.

DuckDuckGo's HTML endpoint first, then its lite endpoint, then public SearXNG
instances. All return plain HTML we parse ourselves, so there is no SDK and no
quota. Free endpoints do rate limit, which is why there is more than one.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from vb.web.fetch import client

DDG = "https://html.duckduckgo.com/html/"
DDG_LITE = "https://lite.duckduckgo.com/lite/"
# Mojeek was tried here and returns a 339 byte block page to anything scripted.
SEARX_INSTANCES = ("https://searx.be/search",
                   "https://search.bus-hit.me/search",
                   "https://searxng.site/search")


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
    with client() as c:
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


def _ddg_lite(query: str, limit: int) -> list[Hit]:
    """The lite endpoint often still answers when the html one is rate limiting.

    Note the quoting: lite writes class='result-link' with single quotes, which
    is why the character class matters here.
    """
    with client() as c:
        raw = c.post(DDG_LITE, data={"q": query}).text
    hits = []
    for m in re.finditer(
            r"""<a[^>]+href=["'](http[^"']+)["'][^>]*class=["']result-link["'][^>]*>(.*?)</a>""",
            raw, re.S):
        url, title = _unwrap(html.unescape(m.group(1))), _clean(m.group(2))
        if url.startswith("http") and title:
            hits.append(Hit(title=title, url=url))
        if len(hits) >= limit:
            break
    snippets = [_clean(s) for s in re.findall(
        r'<td[^>]*class=["\']result-snippet["\'][^>]*>(.*?)</td>', raw, re.S)]
    for hit, snip in zip(hits, snippets):
        hit.snippet = snip
    return hits


def _searx(query: str, limit: int) -> list[Hit]:
    """Public SearXNG instances. JSON when the instance allows it, HTML when not."""
    for base in SEARX_INSTANCES:
        try:
            with client() as c:
                r = c.get(base, params={"q": query, "format": "json"})
                if "json" in r.headers.get("content-type", ""):
                    data = r.json().get("results", [])
                    hits = [Hit(title=d.get("title", ""), url=d.get("url", ""),
                                snippet=d.get("content", "")) for d in data[:limit]]
                    if hits:
                        return hits
                raw = c.get(base, params={"q": query}).text
            hits = []
            for m in re.finditer(
                    r'<a[^>]+href="(https?://[^"]+)"[^>]*class="url_wrapper"'
                    r'|<h3><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a></h3>',
                    raw, re.S):
                url = m.group(1) or m.group(2)
                title = _clean(m.group(3) or "") or url
                if url:
                    hits.append(Hit(title=title, url=html.unescape(url)))
                if len(hits) >= limit:
                    break
            if hits:
                return hits
        except Exception:
            continue
    return []


ENGINES = (("DuckDuckGo", _ddg), ("DuckDuckGo lite", _ddg_lite),
           ("SearXNG", _searx))


def search(query: str, limit: int = 6) -> list[Hit]:
    """Try engines in turn until one answers.

    Free endpoints rate limit, and a run of quick queries will get one of them
    to stop replying. The lite endpoint usually keeps answering after the html
    one has started refusing, so it is worth trying before giving up.
    """
    from vb import progress
    for i, (name, engine) in enumerate(ENGINES):
        try:
            hits = engine(query, limit)
            if hits:
                return hits
        except Exception:
            pass
        if i + 1 < len(ENGINES):
            progress.say(f"{name} did not answer, trying {ENGINES[i + 1][0]}…")
    return []
