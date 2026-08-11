"""Window and app control: close something, bring it to the front, clear the desktop."""
import os, re, sys, subprocess

from buddy import confirm, slots

# Editors mark unsaved work in the title: "*notes.txt - Notepad", "● file.py".
_DIRTY_MARKS = ("*", "●", "•", "◆")

# words that mean "the thing after this is the app name"
_TARGET = re.compile(
    r"\b(?:close|quit|kill|exit|end|switch to|go to|focus|bring up|show me|open)\s+"
    r"(?:the\s+|my\s+)?([\w .+-]{2,40})", re.I)

_STOP = ("app", "application", "window", "program", "please", "for me", "now", "up")

# "close this" / "close that window" means the window in front, not an app named "that"
_THIS = ("this", "that", "it", "these", "those", "current", "active", "front")


def _target(text):
    m = _TARGET.search(slots.clean(text))
    if not m:
        return None
    name = m.group(1).strip()
    for w in _STOP:
        name = re.sub(rf"\b{re.escape(w)}\b", " ", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    if not name or name.lower() in _THIS:
        return None
    return name


def _matching_windows(name):
    try:
        import pygetwindow as gw
    except Exception:
        return []
    low = name.lower()
    out = []
    for w in gw.getAllWindows():
        try:
            if w.title and low in w.title.lower():
                out.append(w)
        except Exception:
            continue
    return out


def _matching_procs(name):
    try:
        import psutil
    except Exception:
        return []
    low = name.lower().replace(".exe", "")
    out = []
    for p in psutil.process_iter(["name", "pid"]):
        try:
            pname = (p.info["name"] or "").lower().replace(".exe", "")
            if pname and (pname == low or low in pname):
                out.append(p)
        except Exception:
            continue
    return out


def _has_unsaved(win):
    try:
        return (win.title or "").lstrip().startswith(_DIRTY_MARKS)
    except Exception:
        return False


def _close_windows(wins, name):
    closed = 0
    for w in wins:
        try:
            w.close(); closed += 1
        except Exception:
            continue
    if not closed:
        return f"Couldn't close {name}."
    return f"Closed {closed} {name} window{'s' if closed > 1 else ''}."


def _active():
    try:
        import pygetwindow as gw
        return gw.getActiveWindow()
    except Exception:
        return None


def close_app(text, ctx):
    name = _target(text)
    if not name:
        if any(w in text.lower() for w in _THIS):     # "close this window"
            w = _active()
            if w is None:
                return "I can't tell which window is in front."
            title = w.title
            if _has_unsaved(w):
                return confirm.ask(f"{title} has unsaved changes. Close it anyway?",
                                   lambda: _close_windows([w], title))
            return _close_windows([w], title)
        return "Close what?"
    # prefer closing windows politely — that lets the app prompt to save
    wins = _matching_windows(name)
    if wins:
        dirty = [w for w in wins if _has_unsaved(w)]
        clean = [w for w in wins if w not in dirty]
        if not dirty:
            return _close_windows(clean, name)
        # never quietly discard someone's work: modern editors keep one window for
        # everything, so "close notepad" can mean "close the thing I was writing".
        # Clean windows go now; only the unsaved ones need a decision.
        done = _close_windows(clean, name) if clean else ""
        titles = ", ".join(w.title.lstrip("".join(_DIRTY_MARKS)).strip() for w in dirty)
        was = f"{done} " if clean else ""
        return was + confirm.ask(
            f"{titles} has unsaved changes — close that one too?",
            lambda: _close_windows(dirty, name))
    procs = _matching_procs(name)
    if not procs:
        return f"I don't see {name} running."

    # No window to close politely — the only option left is TerminateProcess, which
    # on Windows kills outright with no chance to save. Always ask first.
    def kill():
        killed = 0
        for p in procs:
            try:
                p.terminate(); killed += 1
            except Exception:
                continue
        return f"Force-closed {name} ({killed} process{'es' if killed != 1 else ''})."

    return confirm.ask(
        f"{name} has no window I can close normally — force-quit it? "
        f"Anything unsaved would be lost.", kill)


def focus_app(text, ctx):
    name = _target(text)
    if not name:
        return "Switch to what?"
    wins = _matching_windows(name)
    if not wins:
        return f"{name} isn't open — say \"open {name}\" and I'll start it."
    w = wins[0]
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
        w.activate()
        return f"Switched to {w.title}."
    except Exception:
        try:                                    # activate() is flaky on some Windows builds
            w.minimize(); w.restore()
            return f"Switched to {w.title}."
        except Exception as e:
            return f"Couldn't focus {name}: {e}"


def minimize_all(text, ctx):
    t = slots.clean(text)
    # "bring my windows back" loses the adjacency of "bring back" once filler is
    # stripped, so match the tell-tale words individually
    restore = bool(re.search(r"\b(restore|back|undo|unminimi[sz]e|return|reopen)\b", t))
    if os.name == "nt":
        try:
            import ctypes
            # 419 = minimize all, 416 = undo minimize all (shell tray commands)
            hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
            ctypes.windll.user32.SendMessageW(hwnd, 0x111, 416 if restore else 419, 0)
            return "Windows restored." if restore else "Desktop cleared."
        except Exception as e:
            return f"Couldn't do that: {e}"
    return "Minimize-all is wired for Windows only."


SKILLS = [
    {"name": "close_app", "desc": "close a running app or window",
     "phrases": ["close chrome", "quit spotify", "close notepad", "kill discord",
                 "close the browser", "exit vs code", "close that app", "close this window"],
     "run": close_app},
    {"name": "focus_app", "desc": "bring an app to the front",
     "phrases": ["switch to chrome", "switch to spotify", "go to my browser window",
                 "focus vs code", "show me the terminal window",
                 "bring the browser to the front", "put chrome in front"],
     "run": focus_app},
    {"name": "minimize_all", "desc": "show the desktop / restore windows",
     "phrases": ["minimize everything", "show my desktop", "clear the screen",
                 "hide all windows", "bring my windows back"],
     "run": minimize_all},
]
