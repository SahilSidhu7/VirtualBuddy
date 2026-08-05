"""Web search - answers questions from the internet. Free, no API key, no Claude tokens.

Layered, first hit wins:
  1. DuckDuckGo Instant Answer API  (quick facts)
  2. Wikipedia summary               (great for 'who/what is X')
  3. DuckDuckGo Lite scrape          (general web snippets)
Uses only built-in urllib - zero extra installs.
"""
import json, re, urllib.parse, urllib.request

_UA = {"User-Agent": "Mozilla/5.0 (VirtualBuddy)"}

def _get(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", "ignore")

def _clean_query(text):
    q = text.lower()
    for w in ("search the web for", "search for", "search", "look this up online", "look up",
              "google it", "google", "find online", "on the internet", "find information about",
              "tell me about"):
        q = q.replace(w, "")
    return q.strip(" ?.") or text

def _instant(q):
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1})
    d = json.loads(_get(url))
    return d.get("AbstractText") or d.get("Answer") or None

def _wiki(q):
    # strip lead-in so "who is elon musk" -> "elon musk"
    title = re.sub(r"^(who|what|where|when)\s+(is|are|was|were)\s+", "", q).strip()
    title = urllib.parse.quote(title.replace(" ", "_"))
    d = json.loads(_get("https://en.wikipedia.org/api/rest_v1/page/summary/" + title))
    return d.get("extract") if d.get("type") == "standard" else None

def _lite(q):
    html = _get("https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q}))
    rows = re.findall(r"result-snippet[^>]*>(.*?)</td>", html, re.S)
    out = []
    for s in rows[:3]:
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            out.append(s)
    return " | ".join(out) if out else None

def search(text, ctx):
    q = _clean_query(text)
    for fn in (_instant, _wiki, _lite):
        try:
            ans = fn(q)
            if ans:
                return ans[:700]
        except Exception:
            continue
    return f"No web result for '{q}'."

SKILLS = [
    {"name": "web_search",
     "phrases": ["search the web", "look this up online", "google it", "find on the internet",
                 "who is", "what is the latest", "search for", "look up the news",
                 "what is the weather", "how do i", "find information about"],
     "run": search},
]
