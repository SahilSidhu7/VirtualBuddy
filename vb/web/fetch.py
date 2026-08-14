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
# Connecting gets its own, much shorter budget. Plenty of hosts publish an IPv6
# address that a home connection cannot reach; the connection then sits there
# until the timeout expires before anything tries IPv4. With one overall 20s
# timeout that made example.com take 20.07s. At 4s it takes 4.3s, and a host
# that genuinely needs longer than four seconds to accept a socket is down.
CONNECT_TIMEOUT = 2.5

_BLOCKED = {401, 403, 405, 429, 503}


# Hosts whose IPv6 address does not accept connections from here. IPv6 is not
# all-or-nothing: this machine reaches Cloudflare's IPv6 resolver fine while
# example.com's AAAA address is a black hole, so a single global "is IPv6 up"
# probe answers the wrong question. Learn it per host instead, once.
_ipv4_only: set[str] = set()


def client(*, ipv4: bool = False, **kw):
    """The one place HTTP clients are configured."""
    import httpx
    if ipv4:
        # Binding to the IPv4 wildcard makes every connection IPv4.
        kw.setdefault("transport", httpx.HTTPTransport(local_address="0.0.0.0"))
    return httpx.Client(headers=HEADERS, follow_redirects=True,
                        timeout=httpx.Timeout(TIMEOUT, connect=CONNECT_TIMEOUT), **kw)


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower()


_client = client          # older name, kept so nothing breaks mid-refactor


def http_get(url: str) -> tuple[int, str]:
    """Fetch a URL, retrying over IPv4 if the connection stalls.

    A host with an unreachable IPv6 address costs the whole connect timeout
    before anything tries IPv4. When that happens the host is remembered, so
    only the first request to it pays.
    """
    import time

    import httpx
    host = _host_of(url)
    forced = host in _ipv4_only
    started = time.monotonic()
    try:
        with client(ipv4=forced) as c:
            r = c.get(url)
    except (httpx.ConnectTimeout, httpx.ConnectError):
        if forced:
            raise
        _ipv4_only.add(host)
        with client(ipv4=True) as c:
            r = c.get(url)
            return r.status_code, r.text

    # httpx falls back to IPv4 by itself, without raising, so a dead IPv6
    # address shows up only as time: the request succeeds having spent the
    # whole connect budget waiting first. Remember the host so the next
    # request skips straight to IPv4.
    if not forced and time.monotonic() - started >= CONNECT_TIMEOUT * 0.9:
        _ipv4_only.add(host)
    return r.status_code, r.text


def get(url: str, *, force_browser: bool = False, allow_browser: bool = True) -> Page:
    """Fetch and extract one page, escalating to a browser if needed.

    `allow_browser=False` is for callers reading several pages in a row: one
    stubborn source is not worth twenty five seconds of Chromium when three
    others already answered.
    """
    tier = config.get("browser_tier")
    if not allow_browser and not force_browser:
        tier = "http"
    raw, status = "", 0

    if not force_browser:
        try:
            status, raw = http_get(url)
        except Exception as exc:
            status, raw = 0, ""
            _last_error[url] = str(exc)
        if status and status not in _BLOCKED:
            text = extract.to_text(raw, url)
            if tier == "http" or not extract.needs_browser(raw, text):
                return Page(url=url, title=extract.title_of(raw, url), text=text,
                            html=raw, via="http")

    if tier == "http" and not force_browser:
        return Page(url=url, title=extract.title_of(raw, url),
                    text=extract.to_text(raw, url), html=raw, via="http")

    from vb import progress
    progress.say("The page needs a browser. Rendering it…")
    page = browser.render(url)
    if page is None:                       # browser unavailable — keep what we got
        return Page(url=url, title=extract.title_of(raw, url),
                    text=extract.to_text(raw, url), html=raw, via="http")
    return page


_last_error: dict[str, str] = {}


def last_error(url: str) -> str:
    return _last_error.get(url, "")
