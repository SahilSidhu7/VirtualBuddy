"""Drive the browser: search a site, open a bookmark-ish shortcut, play something.

Different from web_search (which answers in the terminal) — this puts the result
on screen in a real browser, which is what "search youtube for X" actually means.
"""
import re, webbrowser, urllib.parse

from buddy import slots

# engine -> (search url template, friendly name, bare site url)
ENGINES = {
    "youtube":   ("https://www.youtube.com/results?search_query={q}", "YouTube", "https://www.youtube.com"),
    "google":    ("https://www.google.com/search?q={q}", "Google", "https://www.google.com"),
    "amazon":    ("https://www.amazon.com/s?k={q}", "Amazon", "https://www.amazon.com"),
    "wikipedia": ("https://en.wikipedia.org/w/index.php?search={q}", "Wikipedia", "https://en.wikipedia.org"),
    "github":    ("https://github.com/search?q={q}", "GitHub", "https://github.com"),
    "maps":      ("https://www.google.com/maps/search/{q}", "Maps", "https://www.google.com/maps"),
    "reddit":    ("https://www.reddit.com/search/?q={q}", "Reddit", "https://www.reddit.com"),
    "twitter":   ("https://twitter.com/search?q={q}", "X", "https://twitter.com"),
    "x":         ("https://twitter.com/search?q={q}", "X", "https://twitter.com"),
    "spotify":   ("https://open.spotify.com/search/{q}", "Spotify", "https://open.spotify.com"),
    "gmail":     ("https://mail.google.com/mail/u/0/#search/{q}", "Gmail", "https://mail.google.com"),
    "stackoverflow": ("https://stackoverflow.com/search?q={q}", "Stack Overflow", "https://stackoverflow.com"),
    "news":      ("https://news.google.com/search?q={q}", "Google News", "https://news.google.com"),
}

_ALIASES = {"yt": "youtube", "the tube": "youtube", "google maps": "maps",
            "stack overflow": "stackoverflow", "so": "stackoverflow",
            "the news": "news", "wiki": "wikipedia"}

# words that separate the engine from the thing being searched for
_QUERY_CUT = re.compile(
    r"\b(?:search(?:\s+for)?|look(?:\s+up|\s+for)?|find|play|watch|show me|google|"
    r"buy|shop for|browse(?:\s+for)?|pull up)\b", re.I)

_NOISE = re.compile(
    r"\b(?:on|in|using|with|via|through|at)\s+(?:the\s+)?"
    r"(?:youtube|google|amazon|wikipedia|github|maps|reddit|twitter|x|spotify|gmail|"
    r"stack ?overflow|news|browser|web|internet|yt|wiki)\b", re.I)


def _engine(text):
    t = text.lower()
    for alias, name in _ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return name
    for name in sorted(ENGINES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return name
    return None


def _query(text, engine):
    q = slots.quoted(text)
    if not q:
        q = slots.clean(text)
        parts = _QUERY_CUT.split(q)
        q = parts[-1] if len(parts) > 1 else q
        q = _NOISE.sub(" ", q)
        if engine:
            q = re.sub(rf"\b{re.escape(engine)}\b", " ", q, flags=re.I)
        q = re.sub(r"\b(?:for me|please|browser|website|site|video|videos|song|songs)\b",
                   " ", q, flags=re.I)
        # "search youtube for X" cuts at "search", leaving "for X" once the engine goes
        q = re.sub(r"^\s*(?:for|about|up|on|in|some|any)\b\s*", "", q.strip(), flags=re.I)
    return re.sub(r"\s+", " ", q or "").strip(" .?!,")


def _go(url, ctx):
    """Prefer buddy's own controlled browser so follow-ups (read/click) work."""
    cfg = ctx.get("cfg") or {}
    if cfg.get("web_automation"):
        try:
            from buddy import primitives
            from buddy.primitives import web
            if web.available():
                return primitives.run("web_open", {"url": url})
        except Exception:
            pass
    webbrowser.open(url)
    return None


def browser_search(text, ctx):
    engine = _engine(text) or "google"
    q = _query(text, engine)
    tmpl, label, home = ENGINES[engine]
    if not q:
        _go(home, ctx)
        return f"Opening {label}."
    url = tmpl.format(q=urllib.parse.quote_plus(q))
    err = _go(url, ctx)
    if err and err.startswith("("):
        return err
    return f"Searching {label} for \"{q}\"."


def open_shortcut(text, ctx):
    """"open youtube" / "take me to gmail" — the site itself, no query."""
    engine = _engine(text)
    if not engine:
        return "Which site?"
    _, label, home = ENGINES[engine]
    _go(home, ctx)
    return f"Opening {label}."


SKILLS = [
    {"name": "browser_search", "desc": "search a website in the browser",
     "phrases": ["search youtube for lofi beats", "google how to boil an egg",
                 "look up python decorators on google", "play a song on youtube",
                 "search amazon for headphones", "find directions to the airport on maps",
                 "search github for fastapi examples", "look up the weather on google",
                 "browse the news", "search reddit for laptop advice"],
     "run": browser_search},
    {"name": "open_shortcut", "desc": "open a common website",
     "phrases": ["open youtube", "take me to gmail", "open google", "go to reddit",
                 "pull up wikipedia", "open my email"],
     "run": open_shortcut},
]
