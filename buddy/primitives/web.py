"""Web-automation primitives — a real browser buddy can drive (Playwright/Chromium).

A single persistent, visible browser page is reused across calls so a multi-step web
task (open -> fill -> click -> read) works as one flow. These are exposed as
primitives so the planner (or a Claude-authored skill) can compose them.

Gated by cfg.web_automation; degrades to an install hint if Playwright is missing.
Actions that change page state (click, fill) are risk:confirm in the catalog.
"""
import os, sys, threading

# In the packaged app Chromium is bundled inside the playwright package (built with
# PLAYWRIGHT_BROWSERS_PATH=0), so point playwright there. In dev, leave the default
# so the browser installed in the user cache is used.
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

_lock = threading.Lock()
_pw = _browser = _page = None


def available():
    try:
        import playwright  # noqa
        return True
    except Exception:
        return False


def _ensure_page():
    global _pw, _browser, _page
    if _page is not None:
        return _page
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=False)      # visible: buddy drives a real browser
    _page = _browser.new_page()
    return _page


def _norm(url):
    return url if url.startswith(("http://", "https://")) else "https://" + url


def web_open(url):
    if not available():
        return "Web automation needs Playwright: pip install playwright && playwright install chromium"
    if not url:
        return "Which URL?"
    with _lock:
        p = _ensure_page()
        p.goto(_norm(url), timeout=30000, wait_until="domcontentloaded")
        return f"Opened {p.title() or url}."


def web_read(url=None):
    if not available():
        return "Web automation needs Playwright (see web_open)."
    with _lock:
        p = _ensure_page()
        if url:
            p.goto(_norm(url), timeout=30000, wait_until="domcontentloaded")
        try:
            return p.inner_text("body")[:4000]
        except Exception as e:
            return f"Couldn't read the page: {e}"


def web_click(target):
    if not available():
        return "Web automation needs Playwright (see web_open)."
    with _lock:
        p = _ensure_page()
        try:
            p.click(target, timeout=8000)                # CSS/text selector
        except Exception:
            try:
                p.get_by_text(target, exact=False).first.click(timeout=8000)
            except Exception as e:
                return f"Couldn't click '{target}': {e}"
        return f"Clicked {target}."


def web_fill(selector, text=""):
    if not available():
        return "Web automation needs Playwright (see web_open)."
    with _lock:
        p = _ensure_page()
        try:
            p.fill(selector, text or "", timeout=8000)
            return f"Filled {selector}."
        except Exception as e:
            return f"Couldn't fill '{selector}': {e}"


def web_screenshot(path=None):
    if not available():
        return "Web automation needs Playwright (see web_open)."
    with _lock:
        p = _ensure_page()
        out = os.path.abspath(os.path.expanduser(path or "web_shot.png"))
        p.screenshot(path=out)
        return f"Saved web screenshot to {out}."


def close():
    global _pw, _browser, _page
    try:
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _pw = _browser = _page = None
