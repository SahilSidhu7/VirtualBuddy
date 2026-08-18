"""Driving a real browser, as a tool the agent can call.

`vb.web.browser.act` has been able to click, type and scroll for a while, but
nothing exposed it, so the agent could read pages and not use them. This is the
wrapper.

The actions are a flat string rather than nested JSON — `click:text=Next;
fill:#search=socks; press:Enter` — because a small model writes a
semicolon-separated line correctly far more often than it writes a list of
objects inside a JSON argument, and every malformed argument costs a whole
turn. The parser is forgiving in the ways models are sloppy.

Signing in, paying and submitting applications stay out of reach on purpose:
this opens pages and reads them, and the person does the rest.
"""
from __future__ import annotations

import re

from vb import progress
from vb.registry import Result, skill
from vb.web import browser

MAX_ACTIONS = 12
FORBIDDEN = re.compile(
    r"\b(password|passwd|cvv|card ?number|ssn|social security)\b", re.I)


def _parse(actions: str) -> tuple[list[dict], str]:
    """Turn "click:text=Next; wait:2000" into steps. Returns (steps, problem)."""
    steps: list[dict] = []
    for chunk in re.split(r"\s*;\s*|\s*\n\s*", actions or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        verb, _, rest = chunk.partition(":")
        verb, rest = verb.strip().lower(), rest.strip()
        if verb == "click" and rest:
            steps.append({"click": rest})
        elif verb == "fill" and "=" in rest:
            selector, _, value = rest.partition("=")
            steps.append({"fill": selector.strip(), "value": value.strip()})
        elif verb == "press" and rest:
            steps.append({"press": rest})
        elif verb == "wait":
            steps.append({"wait": int(rest) if rest.isdigit() else 1000})
        elif verb == "scroll":
            steps.append({"scroll": int(rest) if rest.isdigit() else 3})
        else:
            return [], (f"“{chunk}” is not an action. Use click:SELECTOR, "
                        f"fill:SELECTOR=VALUE, press:KEY, wait:MS or scroll:N.")
        if len(steps) > MAX_ACTIONS:
            return [], f"That is more than {MAX_ACTIONS} actions. Do it in stages."
    return steps, ""


@skill(
    "browse",
    "Open a page in a real browser and click, type or scroll on it",
    ["click the next button on", "search on that site for", "type into the box on",
     "scroll down the page and read", "use the site's own search",
     "interact with the page", "press the button on"],
    slow=True, tags=["web"],
    triggers=[r"\bclick\b", r"\bscroll\b", r"\btype into\b", r"\bpress the\b"],
)
def browse(url: str, actions: str = "") -> Result:
    """Open a page in a real browser and act on it.

    `actions` is a semicolon-separated list: click:text=Next; fill:#q=socks;
    press:Enter; wait:2000; scroll:3. Leave it empty to just render the page.
    """
    if not url.strip():
        return Result.fail("Which page?")
    if FORBIDDEN.search(actions):
        return Result.fail(
            "I won't type passwords or card details into a page.",
            "Open it and I'll hand it over — that part is yours.")

    steps, problem = _parse(actions)
    if problem:
        return Result.fail(problem)

    if not browser.chromium_ready():
        progress.say("Setting up the browser (one time, ~150MB)…")
        if not browser.ensure(on_progress=progress.say):
            return Result.fail(
                "The browser could not be set up.",
                "Try `pip install playwright` then `playwright install chromium`.")

    progress.say(f"Opening {url}…" if not steps else
                 f"Working through {len(steps)} actions on {url}…")
    page = browser.act(url, steps) if steps else browser.render(url)
    if not page:
        return Result.fail(f"The page did not load, or an action found nothing.",
                           "Check the selector — text=… matches visible text, "
                           "#id and .class match the markup.")
    text = (page.text or "").strip()
    return Result(
        text=f"{page.title}\n{page.url}\n\n{text[:3000]}"
             + ("\n… [page continues]" if len(text) > 3000 else ""),
        data={"url": page.url, "title": page.title})
