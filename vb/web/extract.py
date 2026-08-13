"""HTML -> readable text.

trafilatura when it's installed (it strips nav/ads properly); otherwise a plain
tag-stripper, so the buddy still works on a bare install.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


@dataclass
class Page:
    url: str
    title: str
    text: str
    html: str = ""
    via: str = "http"        # http | browser

    @property
    def words(self) -> int:
        return len(self.text.split())

    def summary(self, limit: int = 1200) -> str:
        return self.text[:limit] + ("…" if len(self.text) > limit else "")


def _fallback(raw: str) -> str:
    body = _DROP.sub(" ", raw)
    body = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", body, flags=re.I)
    body = _TAG.sub(" ", body)
    body = html.unescape(body)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()]
    return _WS.sub("\n\n", "\n".join(ln for ln in lines if ln))


def title_of(raw: str, fallback: str = "") -> str:
    m = _TITLE.search(raw or "")
    return html.unescape(m.group(1)).strip() if m else fallback


def to_text(raw: str, url: str = "") -> str:
    try:
        import trafilatura
        out = trafilatura.extract(raw, url=url or None, include_links=False,
                                  include_comments=False, favor_recall=True)
        if out and len(out.split()) > 40:
            return out.strip()
    except Exception:
        pass
    return _fallback(raw)


def looks_empty(text: str) -> bool:
    """A JS shell renders to almost nothing — the signal to retry in a browser."""
    return len(text.split()) < 60


def links(raw: str, base: str = "") -> list[tuple[str, str]]:
    """(href, anchor text) pairs, absolute where possible."""
    from urllib.parse import urljoin
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.S | re.I):
        href, label = m.group(1), _TAG.sub("", m.group(2))
        label = html.unescape(label).strip()
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        out.append((urljoin(base, href) if base else href, label))
    return out
