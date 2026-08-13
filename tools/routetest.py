"""Route-only self test: does each phrasing reach the right skill?

Never executes a skill — routing is what we are checking, and running things
like open_app for real would fling windows around.

    python tools/routetest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vb.router import Router  # noqa: E402

CASES = [
    ("search the web for cheap flights to goa", "web_search"),
    ("google the weather in delhi", "web_search"),
    ("look up when the shop closes", "web_search"),
    ("find articles about intermittent fasting", "web_search"),
    ("research the best budget gpus for me", "research"),
    ("do some research on creatine", "research"),
    ("dig into the news about the merger", "research"),
    ("compare the top noise cancelling headphones", "research"),
    ("read https://example.com and tell me what it says", "read_page"),
    ("summarise this article https://news.ycombinator.com", "read_page"),
    ("scrape the text from https://example.com", "read_page"),
    ("get all the links from https://example.com", "extract_links"),
    ("list the urls on https://example.com", "extract_links"),
    ("open chrome", "open_app"),
    ("launch spotify", "open_app"),
    ("start the calculator", "open_app"),
    ("fire up vs code", "open_app"),
    ("open youtube", "open_site"),
    ("take me to reddit", "open_site"),
    ("visit github.com", "open_site"),
    ("open my downloads folder", "open_folder"),
    ("show me the desktop folder", "open_folder"),
]


def main() -> int:
    router = Router()
    bad = []
    for prompt, want in CASES:
        ranked = router.rank(prompt, top=3)
        got = ranked[0].skill.name if ranked else "-none-"
        score = ranked[0].score if ranked else 0.0
        mark = "ok  " if got == want else "MISS"
        if got != want:
            alts = ", ".join(f"{m.skill.name}:{m.score:.2f}" for m in ranked)
            bad.append((prompt, want, got, alts))
        print(f"{mark} {score:.2f}  {prompt!r:55} -> {got}")
    print(f"\n{len(CASES) - len(bad)}/{len(CASES)} routed correctly")
    for prompt, want, got, alts in bad:
        print(f"  MISS {prompt!r}\n       want {want}, got {got}  [{alts}]")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
