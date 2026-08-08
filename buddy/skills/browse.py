"""Open and read web pages in a real browser (Playwright-backed web primitives).

Direct routes for the common cases; open-ended multi-step web tasks (click/fill/
submit) are handled by the planner composing the web_* primitives.
"""
import re
from buddy import primitives

_URL = re.compile(r"(https?://[^\s]+|[a-z0-9-]+\.[a-z]{2,}(?:/[^\s]*)?)", re.I)


def _url(text):
    m = _URL.search(text)
    return m.group(1) if m else None


def open_site(text, ctx):
    if not ctx["cfg"].get("web_automation"):
        return "Web automation is off — turn it on in the dashboard."
    url = _url(text)
    if not url:
        return "Which website?"
    return primitives.run("web_open", {"url": url})


def read_page(text, ctx):
    if not ctx["cfg"].get("web_automation"):
        return "Web automation is off — turn it on in the dashboard."
    cfg = ctx["cfg"]
    txt = primitives.run("web_read", {"url": _url(text)})
    if len(txt) > 600:
        from buddy import llm
        if llm.is_up(cfg):
            return llm.ask("Summarize this page in 2-3 sentences:\n" + txt[:3000], cfg)
        return txt[:600] + " ..."
    return txt


SKILLS = [
    {"name": "open_site", "desc": "open a website in a real browser",
     "phrases": ["open youtube.com", "go to github.com", "open reddit in the browser",
                 "pull up twitter.com", "navigate to wikipedia.org"],
     "run": open_site},
    {"name": "read_page", "desc": "read / summarize a web page",
     "phrases": ["read this page", "summarize this webpage", "what does this article say",
                 "get the text from this url", "read wikipedia.org/wiki/Dog"],
     "run": read_page},
]
