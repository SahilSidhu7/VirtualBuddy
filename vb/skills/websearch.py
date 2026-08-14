"""Searching and reading the web."""
from __future__ import annotations

from vb import llm, progress, slots
from vb.registry import Result, skill
from vb.web import fetch, search


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.replace("www.", "") or url


def _no_model_note(pages) -> str:
    """What to say when there is no model to write the answer.

    Dumping the scraped text was the old behaviour and it is worse than
    useless: the user asked a question and got a wall of website. Say plainly
    that the model is missing, and give the openings so the sources are still
    usable.
    """
    why = llm.last_error() or llm.status()["message"]
    lines = [f"I read {len(pages)} pages but cannot write them up: {why}",
             "Right click me and set the model up, and this becomes an answer.",
             ""]
    for page in pages:
        lines.append(f"**{page.title}** — {_host(page.url)}")
        lines.append(page.summary(280))
        lines.append("")
    return "\n".join(lines)

SEARCH_VERBS = ("search", "google", "find", "look", "lookup", "duckduckgo", "web")
READ_VERBS = ("read", "open", "fetch", "scrape", "get", "summarise", "summarize")


def _search_slots(text: str) -> dict:
    return {"query": slots.query_of(text, SEARCH_VERBS),
            "limit": slots.count(text, 6)}


@skill(
    "web_search",
    "Search the web and list the top results with links",
    ["search the web for python tutorials", "google best budget laptops",
     "google the weather", "look up who won the match", "look this up online",
     "find articles about sleep", "search for something", "what is the price of"],
    slots=_search_slots, tags=["web"],
    triggers=[r"\b(google|search|look up|dig up)\b", r"\bon the (web|internet)\b",
              r"\b(find|show me)\b.{0,20}\barticles?\b"],
)
def web_search(query: str = "", limit: int = 6, **_) -> Result:
    if not query:
        return Result.fail("Nothing to search for.", "Try: search the web for <topic>")
    progress.say(f"Searching for “{query}”…")
    hits = search.search(query, limit=min(int(limit or 6), 10))
    if not hits:
        return Result.fail("No results came back.", "Search engines may be blocking us.")
    body = "\n\n".join(h.line(i) for i, h in enumerate(hits, 1))
    return Result(text=f"Top results for “{query}”:\n\n{body}", data=hits)


def _read_slots(text: str) -> dict:
    return {"url": slots.first_url(text), "topic": slots.query_of(text, READ_VERBS)}


@skill(
    "read_page",
    "Open a web page and give back its readable text",
    ["read this page", "read this link", "summarise this article link", "summarise this link",
     "what does this article say", "scrape the text from that link",
     "read that link and tell me what's on it", "give me the gist of this page"],
    slots=_read_slots, slow=True, tags=["web"],
    triggers=[r"\b(read|summari[sz]e|scrape|gist of)\b.{0,20}\b(link|page|article|site)\b",
              r"\blink\b.{0,24}\b(say|says|about)\b"],
)
def read_page(url: str = "", topic: str = "", **_) -> Result:
    if not url:
        progress.say(f"Finding a page about “{topic}”…")
        hits = search.search(topic, limit=1) if topic else []
        if not hits:
            return Result.fail("No URL in that.", "Paste a link, or say: search for <topic>")
        url = hits[0].url
    progress.say(f"Fetching {_host(url)}…")
    page = fetch.get(url)
    if not page.text:
        err = fetch.last_error(url)
        return Result.fail(f"Couldn't read {url}.", err or "The page returned nothing.")
    head = f"{page.title}\n{page.url}  ({page.words} words, via {page.via})"

    if llm.enabled():
        progress.say("Reading it…")
    brief = llm.ask(
        f"Page:\n{page.text[:7000]}\n\n"
        + (f"The user asked: {topic}\nAnswer that from the page, then add "
           "up to five bullets of anything else worth knowing.\n" if topic else
           "Say in one sentence what this page is, then up to six bullets of the "
           "specifics: numbers, names, dates, conclusions.\n")
        + "Never copy whole sentences, never describe the layout of the page.",
        system="You read a web page and report what it actually says, briefly.",
        max_tokens=650)
    if not brief:
        why = llm.last_error() or llm.status()["message"]
        return Result(text=f"{head}\n\nI cannot summarise this: {why}\n\n"
                           f"{page.summary(900)}",
                      detail="Set the model up and you get an answer instead of "
                             "the page text.", data=page)
    return Result(text=f"{head}\n\n{brief}", data=page)


def _research_slots(text: str) -> dict:
    return {"topic": slots.query_of(text, ("research", "about", "on") + SEARCH_VERBS),
            "sources": slots.count(text, 4)}


@skill(
    "research",
    "Research a topic across several sites and write up what they say",
    ["research electric cars for me", "do some research on vitamin d",
     "dig into the news about the election", "find out everything about rust lifetimes",
     "compare the best mechanical keyboards",
     "give me the lowdown on creatine from a few sites",
     "what do people say about this drug", "brief me on the housing market"],
    slots=_research_slots, slow=True, tags=["web"],
    triggers=[r"\bresearch\b", r"\bdig into\b", r"\bbrief me\b", r"\blowdown\b",
              r"\bfind out (everything|more)\b", r"\bcompare\b",
              r"\b(few|several|multiple|couple of) (sites|sources)\b"],
)
def research(topic: str = "", sources: int = 4, **_) -> Result:
    if not topic:
        return Result.fail("No topic given.", "Try: research <topic>")
    progress.say(f"Searching for “{topic}”…")
    hits = search.search(topic, limit=max(int(sources or 4), 3) + 2)
    if not hits:
        return Result.fail("Search returned nothing.", f"Topic: {topic}")

    wanted = int(sources or 4)
    pages, notes = [], []
    for i, hit in enumerate(hits[:wanted], start=1):
        progress.say(f"Reading {i} of {wanted}: {_host(hit.url)}")
        page = fetch.get(hit.url, allow_browser=False)
        if page.words < 80:
            continue
        pages.append(page)
        # Trimmed hard: four sources at 3500 characters each made the model
        # spend most of its time reading rather than answering.
        notes.append(f"### {page.title}\n{page.url}\n{page.text[:1800]}")
    if not pages:
        return Result.fail("Every source failed to load.",
                           "\n".join(h.url for h in hits[:3]))

    progress.say("Writing it up…" if llm.enabled()
                 else "Pulling out the useful parts…")
    joined = "\n\n".join(notes)
    write_up = llm.ask(
        f"Question: {topic}\n\nSources:\n{joined}\n\n"
        "Answer the question using only these sources. Rules:\n"
        "- Open with one sentence that actually answers it.\n"
        "- Then at most six short bullets of specifics: numbers, names, prices, dates.\n"
        "- Name the site in brackets after a claim, like (jeffgeerling.com).\n"
        "- If the sources disagree, say so in one line.\n"
        "- Never copy sentences out of the sources, and never describe the page.",
        system="You answer questions from supplied sources, briefly and concretely. "
               "You never pad, and you never quote at length.",
        max_tokens=700)

    if not write_up:
        write_up = _no_model_note(pages)

    src = "\n".join(f"- {p.title} — {p.url}" for p in pages)
    return Result(text=f"Research: {topic}\n\n{write_up}\n\nSources:\n{src}", data=pages)


@skill(
    "extract_links",
    "List every link on a page",
    ["get all the links from this page", "list the links on that site",
     "extract urls from this page", "list the urls on this link",
     "grab every link from that link", "show me all links"],
    slots=lambda t: {"url": slots.first_url(t)}, slow=True, tags=["web"],
)
def extract_links(url: str = "", **_) -> Result:
    if not url:
        return Result.fail("No URL in that.", "Paste a link to pull links from.")
    page = fetch.get(url)
    from vb.web.extract import links as parse_links
    found = parse_links(page.html, base=page.url)
    seen, rows = set(), []
    for href, label in found:
        if href in seen:
            continue
        seen.add(href)
        rows.append(f"- {label or '(no text)'} — {href}")
    if not rows:
        return Result.fail("No links found.", page.url)
    return Result(text=f"{len(rows)} links on {page.title}:\n" + "\n".join(rows[:100]),
                  data=found)
