"""Opening apps, sites and folders on this machine."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from difflib import get_close_matches
from pathlib import Path

from vb import slots
from vb.registry import Result, skill

OPEN_VERBS = ("open", "launch", "start", "run", "fire")

# Names Windows knows how to start directly, whatever the install path is.
KNOWN = {
    "chrome": "chrome", "edge": "msedge", "firefox": "firefox",
    "notepad": "notepad", "calculator": "calc", "calc": "calc",
    "paint": "mspaint", "explorer": "explorer", "files": "explorer",
    "file explorer": "explorer", "task manager": "taskmgr",
    "cmd": "cmd", "terminal": "wt", "powershell": "powershell",
    "settings": "ms-settings:", "control panel": "control",
    "vscode": "code", "vs code": "code", "code": "code",
    "spotify": "spotify:", "steam": "steam://open/main",
}

SITES = {
    "youtube": "https://youtube.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "reddit": "https://reddit.com",
    "twitter": "https://x.com", "x": "https://x.com",
    "maps": "https://maps.google.com", "drive": "https://drive.google.com",
    "amazon": "https://amazon.com", "netflix": "https://netflix.com",
    "chatgpt": "https://chat.openai.com", "claude": "https://claude.ai",
}


def _start_menu_index() -> dict[str, Path]:
    """Shortcut name -> .lnk path, from both Start Menu trees."""
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    index: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            index.setdefault(lnk.stem.lower(), lnk)
    return index


def _launch(target: str) -> None:
    if sys.platform == "win32":
        os.startfile(target)                                  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


@skill(
    "open_app",
    "Open an application installed on this computer",
    ["open chrome", "launch spotify", "start notepad", "run the calculator",
     "open vs code", "fire up steam"],
    slots=lambda t: {"target": slots.after(t, OPEN_VERBS)}, tags=["local"],
    triggers=[r"^\s*(open|launch|start|run|fire up)\b"],
)
def open_app(target: str = "", **_) -> Result:
    name = (target or "").strip().lower()
    if not name:
        return Result.fail("Which app?", "Try: open chrome")

    if name in SITES:
        webbrowser.open(SITES[name])
        return Result(text=f"Opened {name} in your browser.")

    if name in KNOWN:
        try:
            _launch(KNOWN[name])
            return Result(text=f"Opened {name}.")
        except OSError as exc:
            return Result.fail(f"Couldn't start {name}.", str(exc))

    index = _index_cache()
    hit = index.get(name) or _closest(name, index)
    if hit:
        try:
            _launch(str(hit))
            return Result(text=f"Opened {hit.stem}.")
        except OSError as exc:
            return Result.fail(f"Couldn't start {hit.stem}.", str(exc))

    try:                                   # last resort: let the shell try
        _launch(name)
        return Result(text=f"Asked Windows to open “{name}”.")
    except OSError:
        near = ", ".join(sorted(index)[:5])
        return Result.fail(f"No app called “{name}”.", f"Installed apps include: {near}")


_cache: dict[str, Path] | None = None


def _index_cache() -> dict[str, Path]:
    global _cache
    if _cache is None:
        _cache = _start_menu_index() if sys.platform == "win32" else {}
    return _cache


def _closest(name: str, index: dict[str, Path]) -> Path | None:
    keys = get_close_matches(name, list(index), n=1, cutoff=0.72)
    if keys:
        return index[keys[0]]
    for key in index:                      # "spotify" should match "Spotify Premium"
        if name in key:
            return index[key]
    return None


@skill(
    "open_site",
    "Open a website in the default browser",
    ["open youtube", "go to github.com", "take me to reddit",
     "open https://news.ycombinator.com", "visit amazon"],
    slots=lambda t: {"url": slots.first_url(t),
                     "name": slots.after(t, OPEN_VERBS + ("visit", "goto", "to"))},
    tags=["web"],
)
def open_site(url: str = "", name: str = "", **_) -> Result:
    target = url or SITES.get((name or "").strip().lower())
    if not target and name:
        target = f"https://duckduckgo.com/?q={name.replace(' ', '+')}"
    if not target:
        return Result.fail("Which site?", "Try: open youtube")
    webbrowser.open(target)
    return Result(text=f"Opened {target}")


@skill(
    "open_folder",
    "Open a folder in the file manager",
    ["open my downloads", "show me the desktop folder", "open documents",
     "take me to my pictures folder"],
    slots=lambda t: {"name": slots.after(t, OPEN_VERBS + ("show", "goto"))},
    tags=["local"],
    triggers=[r"\b(open|take me to|go to)\b.{0,20}\bfolder\b",
              r"^\s*open my (downloads|desktop|documents|pictures|music|videos)\b"],
)
def open_folder(name: str = "", **_) -> Result:
    home = Path.home()
    known = {"downloads": home / "Downloads", "desktop": home / "Desktop",
             "documents": home / "Documents", "pictures": home / "Pictures",
             "music": home / "Music", "videos": home / "Videos", "home": home}
    key = next((k for k in known if k in (name or "").lower()), None)
    path = known.get(key) if key else (Path(name).expanduser() if name else None)
    if not path or not path.exists():
        return Result.fail(f"No folder for “{name}”.",
                           "Known: " + ", ".join(known))
    _launch(str(path))
    return Result(text=f"Opened {path}")
