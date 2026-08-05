"""Pull details (slots) out of a command. Deterministic = reliable, no tokens.

Skills call these instead of ad-hoc string slicing. Small models fumble this;
plain patterns do it right for PC commands.
"""
import re

# common apps -> what to actually launch
APPS = {
    "chrome": "chrome", "google chrome": "chrome", "browser": "chrome",
    "notepad": "notepad", "calculator": "calc", "calc": "calc",
    "explorer": "explorer", "files": "explorer", "file explorer": "explorer",
    "cmd": "cmd", "terminal": "cmd", "powershell": "powershell",
    "paint": "mspaint", "settings": "start ms-settings:", "task manager": "taskmgr",
    "vscode": "code", "vs code": "code", "code": "code", "spotify": "spotify",
}

_FILLER = ("please", "for me", "could you", "can you", "would you", "buddy",
           "hey", "now", "the", "a", "an", "my", "up", "right", "asap", "thanks")

def clean(text):
    """Lowercased command with polite filler removed."""
    t = text.lower().strip(" ?.!")
    for w in _FILLER:
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def filename(text):
    """First token that looks like a file (has an extension). Else quoted name + .txt."""
    m = re.search(r"[\w\-]+\.[a-z0-9]{1,5}\b", text, re.I)
    if m:
        return m.group(0)
    q = quoted(text)
    if q:
        return q if "." in q else q.replace(" ", "_") + ".txt"
    m = re.search(r"called\s+([\w\-]+)", text, re.I)
    return (m.group(1) + ".txt") if m else None

def quoted(text):
    m = re.search(r"[\"']([^\"']+)[\"']", text)
    return m.group(1).strip() if m else None

def app(text):
    """Resolve an app name to a launch target using the APPS table, else the word after open/launch/start."""
    t = clean(text)
    for name in sorted(APPS, key=len, reverse=True):     # match longest first
        if name in t:
            return APPS[name]
    m = re.search(r"\b(?:open|launch|start|run)\s+([\w .-]+)", t)
    return m.group(1).strip() if m else None

def duration_seconds(text):
    """'in 5 minutes' -> 300, '30 sec' -> 30, '2 hours' -> 7200. None if absent."""
    m = re.search(r"(\d+)\s*(sec|second|min|minute|hour|hr)s?\b", text, re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    mult = 1 if unit.startswith("sec") else 60 if unit.startswith("min") else 3600
    return n * mult

def number(text):
    m = re.search(r"\b(\d+)\b", text)
    return int(m.group(1)) if m else None
