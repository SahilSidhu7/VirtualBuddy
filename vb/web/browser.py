"""Tier 2: a real browser, for pages HTTP cannot read.

Two ways in, best first:

* **Playwright**, which can also click, type and scroll. It is an optional
  dependency plus a ~150MB Chromium, installed on demand, but only when
  running from source. The packaged app has no pip and no python.exe:
  `sys.executable` is VirtualBuddy.exe, so `sys.executable -m pip install`
  started a *second buddy* and waited on it forever. A user watched "Installing
  Playwright" for over seven minutes.
* **The browser already on the machine.** Every Windows PC has Edge, and
  `--headless --dump-dom` prints the page after its JavaScript has run. No
  download, no dependency: enough to read a JavaScript-only page, not enough
  to click on it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from vb.web.extract import Page, title_of, to_text

_state: dict = {}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_TIMEOUT = 600
DUMP_TIMEOUT = 45


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def chromium_ready() -> bool:
    """Playwright present *and* a browser binary actually downloaded."""
    if not installed():
        return False
    if _state.get("ready"):
        return True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        _state["ready"] = bool(path and os.path.exists(path))
    except Exception:
        _state["ready"] = False
    return _state["ready"]


def system_browser() -> str | None:
    """Edge or Chrome already installed here, for headless rendering."""
    if "system" in _state:
        return _state["system"]
    found = None
    roots = [os.environ.get(k, "") for k in
             ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in roots:
        if not root:
            continue
        for rel in ("Microsoft/Edge/Application/msedge.exe",
                    "Google/Chrome/Application/chrome.exe"):
            if (Path(root) / rel).exists():
                found = str(Path(root) / rel)
                break
        if found:
            break
    if not found:
        for name in ("msedge", "chrome", "chromium", "google-chrome"):
            found = shutil.which(name)
            if found:
                break
    _state["system"] = found
    return found


def can_render() -> bool:
    return chromium_ready() or bool(system_browser())


def can_act() -> bool:
    return chromium_ready()


def ensure(on_progress=None) -> bool:
    """Make clicking possible: install Playwright + Chromium. Source only.

    Blocking; run on a worker thread. Returns False at once in the packaged
    app, where there is nothing to install into.
    """
    def say(msg):
        if on_progress:
            on_progress(msg)

    if chromium_ready():
        return True
    if frozen():
        return False
    try:
        if not installed():
            say("Installing Playwright…")
            if subprocess.run([sys.executable, "-m", "pip", "install", "playwright"],
                              capture_output=True, timeout=INSTALL_TIMEOUT,
                              creationflags=NO_WINDOW).returncode != 0:
                return False
        say("Downloading Chromium (~150MB, one time)…")
        if subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                          capture_output=True, timeout=INSTALL_TIMEOUT,
                          creationflags=NO_WINDOW).returncode != 0:
            return False
    except subprocess.TimeoutExpired:
        return False
    _state.pop("ready", None)
    say("Browser ready.")
    return chromium_ready()


def _dump_dom(url: str) -> Page | None:
    """Render with the system browser, headless, and read back the DOM."""
    exe = system_browser()
    if not exe:
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as profile:
        try:
            done = subprocess.run(
                [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", f"--user-data-dir={profile}",
                 "--virtual-time-budget=8000", "--dump-dom", url],
                capture_output=True, timeout=DUMP_TIMEOUT, creationflags=NO_WINDOW,
                encoding="utf-8", errors="replace")
        except (subprocess.TimeoutExpired, OSError):
            return None
    raw = done.stdout or ""
    if len(raw) < 200:
        return None
    return Page(url=url, title=title_of(raw, url), text=to_text(raw, url),
                html=raw, via="system-browser")


def render(url: str, *, wait: str = "domcontentloaded", settle_ms: int = 1200) -> Page | None:
    """Load a URL in a browser and return the rendered page. None if unavailable."""
    if not chromium_ready():
        return _dump_dom(url)
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
