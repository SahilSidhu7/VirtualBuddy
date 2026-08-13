"""Pulling arguments out of a prompt.

"open chrome" -> {"target": "chrome"}. Deliberately dumb and deterministic:
strip the words that made the skill match, keep what's left. The LLM is only
consulted when the cheap path returns nothing useful and one is available.
"""
from __future__ import annotations

import re

# Words that carry intent, never arguments.
FILLER = {
    "please", "can", "you", "could", "would", "hey", "buddy", "for", "me",
    "the", "a", "an", "my", "i", "want", "to", "wanna", "need", "let", "s",
    "up", "now", "some", "and", "then", "just", "go", "ahead",
    "give", "show", "tell", "results", "result", "sources",
}

QUOTED = re.compile(r"[\"'“”‘’](.+?)[\"'“”‘’]")


def quoted(text: str) -> str | None:
    m = QUOTED.search(text)
    return m.group(1).strip() if m else None


def after(text: str, verbs: tuple[str, ...]) -> str:
    """Everything following the first matching verb, cleaned of filler.

    >>> after("hey buddy please open up spotify", ("open", "launch"))
    'spotify'
    """
    words = re.findall(r"[\w.:/@-]+", text.lower())
    for i, w in enumerate(words):
        if w in verbs:
            rest = [x for x in words[i + 1:] if x not in FILLER]
            return " ".join(rest).strip()
    return strip_filler(text)


def strip_filler(text: str) -> str:
    words = [w for w in re.findall(r"[\w.:/@-]+", text.lower()) if w not in FILLER]
    return " ".join(words).strip()


# Words that describe *where* to look, not what to look for. "search the web
# for python" must not send "web python" to the search engine.
CHANNEL = ("web", "online", "internet", "google", "net", "browser", "about",
           "into", "on", "of", "out", "everything", "some", "news")


def query_of(text: str, verbs: tuple[str, ...]) -> str:
    """A search-engine query: prefer quoted text, else whatever follows the verb."""
    q = quoted(text)
    if q:
        return q
    # "top 3 results for cheap ssd" — the count is an instruction, not a term.
    words = after(COUNT.sub(" ", text), verbs).split()
    while words and words[0] in CHANNEL:
        words.pop(0)
    return " ".join(words)


def first_url(text: str) -> str | None:
    m = re.search(r"(https?://\S+|(?:www\.)?[\w-]+\.[a-z]{2,}(?:/\S*)?)", text, re.I)
    if not m:
        return None
    url = m.group(1).rstrip(".,)")
    return url if url.startswith("http") else "https://" + url


COUNT = re.compile(
    r"\b(?:top|first|best|give me|show me)\s+(\d{1,2})\b"
    r"|\b(\d{1,2})\s+(?:results?|sources?|links?|sites?|pages?|articles?)\b", re.I)


def count(text: str, default: int) -> int:
    """How many things the user asked for.

    Deliberately narrow: a bare digit in "python 3.13 release date" is part of
    the query, not a result count, so only explicit count phrasings match.
    """
    m = COUNT.search(text)
    if not m:
        return default
    return int(m.group(1) or m.group(2))
