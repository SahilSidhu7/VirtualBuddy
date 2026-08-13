"""Tier 2: a real Chromium, driven by Playwright.

Only reached when HTTP can't do the job. Playwright itself is an optional
dependency and Chromium is a ~150MB download, so `ensure()` exists to install
both on demand with progress the UI can show — never silently at import time.
"""
from __future__ import annotations

import subprocess
import sys

from vb.web.extract import Page, title_of, to_text

_state: dict = {}


def installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def chromium_ready() -> bool:
    """Package present *and* a browser binary actually downloaded."""
    if not installed():
        return False
    if _state.get("ready"):
        return True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        import os
        _state["ready"] = bool(path and os.path.exists(path))
    except Exception:
        _state["ready"] = False
    return _state["ready"]


def ensure(on_progress=None) -> bool:
    """Install playwright + Chromium. Blocking; run on a worker thread."""
    def say(msg):
        if on_progress:
            on_progress(msg)

    if not installed():
        say("Installing Playwright…")
        if subprocess.run([sys.executable, "-m", "pip", "install", "playwright"],
                          capture_output=True).returncode != 0:
            return False
    if not chromium_ready():
        say("Downloading Chromium (~150MB, one time)…")
        if subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                          capture_output=True).returncode != 0:
            return False
        _state.pop("ready", None)
    say("Browser ready.")
    return chromium_ready()


def render(url: str, *, wait: str = "domcontentloaded", settle_ms: int = 1200) -> Page | None:
    """Load a URL in Chromium and return the rendered page. None if unavailable."""
    if not chromium_ready():
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page()
                pg.goto(url, wait_until=wait, timeout=45000)
                pg.wait_for_timeout(settle_ms)
                raw = pg.content()
                title = pg.title()
            finally:
                b.close()
        return Page(url=url, title=title or title_of(raw, url),
                    text=to_text(raw, url), html=raw, via="browser")
    except Exception:
        return None


def act(url: str, steps: list[dict], *, settle_ms: int = 800) -> Page | None:
    """Run a small script of actions against a page, then return what's on screen.

    steps: [{"click": "text=Next"}, {"fill": "#q", "value": "socks"},
            {"press": "Enter"}, {"wait": 2000}, {"scroll": 3}]
    """
    if not chromium_ready():
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page()
                pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                for step in steps:
                    if "click" in step:
                        pg.click(step["click"], timeout=15000)
                    elif "fill" in step:
                        pg.fill(step["fill"], step.get("value", ""), timeout=15000)
                    elif "press" in step:
                        pg.keyboard.press(step["press"])
                    elif "wait" in step:
                        pg.wait_for_timeout(int(step["wait"]))
                    elif "scroll" in step:
                        for _ in range(int(step["scroll"])):
                            pg.mouse.wheel(0, 1400)
                            pg.wait_for_timeout(400)
                pg.wait_for_timeout(settle_ms)
                raw, title, final = pg.content(), pg.title(), pg.url
            finally:
                b.close()
        return Page(url=final, title=title, text=to_text(raw, final),
                    html=raw, via="browser")
    except Exception:
        return None
