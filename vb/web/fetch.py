"""Tiered page fetching: cheap HTTP first, real browser only when needed.

Tier 1 is httpx — a few hundred milliseconds, no install, works for most of the
web. Tier 2 is Playwright Chromium, used when tier 1 is blocked or the page is
a JavaScript shell. Tier 2 is never downloaded until something needs it.
"""
from __future__ import annotations

from vb import config
from vb.web import browser, extract
from vb.web.extract import Page

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 20

_BLOCKED = {401, 403, 405, 429, 503}


def _client():
    import httpx
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)


def http_get(url: str) -> tuple[int, str]:
    with _client() as c:
        r = c.get(url)
        return r.status_code, r.text


def get(url: str, *, force_browser: bool = False) -> Page:
    """Fetch and extract one page, escalating to a browser if needed."""
    tier = config.get("browser_tier")
    raw, status = "", 0

    if not force_browser:
        try:
            status, raw = http_get(url)
        except Exception as exc:
            status, raw = 0, ""
            _last_error[url] = str(exc)
        if status and status not in _BLOCKED:
            text = extract.to_text(raw, url)
            if not extract.looks_empty(text) or tier == "http":
                return Page(url=url, title=extract.title_of(raw, url), text=text,
                            html=raw, via="http")

    if tier == "http" and not force_browser:
        return Page(url=url, title=extract.title_of(raw, url),
                    text=extract.to_text(raw, url), html=raw, via="http")

    page = browser.render(url)
    if page is None:                       # browser unavailable — keep what we got
        return Page(url=url, title=extract.title_of(raw, url),
                    text=extract.to_text(raw, url), html=raw, via="http")
    return page


_last_error: dict[str, str] = {}


def last_error(url: str) -> str:
    return _last_error.get(url, "")
