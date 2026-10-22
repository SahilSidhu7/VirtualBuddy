"""Opening apps, sites and folders on this machine."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from urllib.parse import quote_plus
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
    # "open chrome" is an app; "open C:/…/readme.md" is a file. The router
    # replaces a typed path with the token "path", so this declines those.
    triggers=[r"^\s*(open|launch|start|run|fire up)\b(?!.*\b(path|link)\b)"],
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


# ------------------------------------------------------- search in a browser
# Where each browser keeps its executable, relative to the usual roots. Brave
# installs per user into LOCALAPPDATA by default, so Program Files alone misses
# it — which is how "open brave" fell through to the Start Menu fuzzy match.
BROWSERS = {
    "brave": ("BraveSoftware/Brave-Browser/Application/brave.exe",
              "https://search.brave.com/search?q="),
    "chrome": ("Google/Chrome/Application/chrome.exe",
               "https://www.google.com/search?q="),
    "edge": ("Microsoft/Edge/Application/msedge.exe",
             "https://www.bing.com/search?q="),
    "firefox": ("Mozilla Firefox/firefox.exe",
                "https://duckduckgo.com/?q="),
    "opera": ("Programs/Opera/opera.exe", "https://www.google.com/search?q="),
    "vivaldi": ("Vivaldi/Application/vivaldi.exe",
                "https://www.google.com/search?q="),
}
_BROWSER_WORD = "|".join(list(BROWSERS) + ["microsoft edge", "google chrome",
                                           "the browser", "my browser",
                                           "browser"])
_SEARCH_WORDS = (r"(?:search(?: for)?|look(?: up| for)?|find|google|show me|"
                 r"check(?: out)?)")


def _browser_slots(text: str) -> dict:
    """"open brave and look for the best new mobiles" ->
    browser=brave, query="the best new mobiles"."""
    low = text.lower()
    found = re.search(rf"\b({_BROWSER_WORD})\b", low)
    name = found.group(1) if found else ""
    name = {"microsoft edge": "edge", "google chrome": "chrome"}.get(name, name)
    if name not in BROWSERS:
        name = ""
    query = ""
    m = re.search(rf"\b{_SEARCH_WORDS}\s+(.+)$", low)
    if m:
        query = m.group(1)
        # "... in brave" / "... on chrome" at the end is the browser, not the query
        query = re.sub(rf"\s+(?:in|on|using|with)\s+(?:{_BROWSER_WORD})\b.*$",
                       "", query)
    return {"browser": name, "query": query.strip(" .?!")}


def _browser_exe(name: str) -> str | None:
    rel = BROWSERS.get(name, ("", ""))[0]
    if not rel:
        return None
    for key in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(key, "")
        if root and (Path(root) / rel).exists():
            return str(Path(root) / rel)
    exe = Path(rel).name
    from shutil import which
    return which(exe) or which(exe.removesuffix(".exe"))


@skill(
    "search_in_browser",
    "Open a browser the user names, on screen, and search for something in it",
    ["open brave and search for cheap flights",
     "open chrome and look for the best new phones",
     "search for laptops in edge", "look up the weather in firefox",
     "open my browser and find concert tickets",
     "google best headphones in chrome"],
    slots=_browser_slots, tags=["web", "local", "compound"],
    # Beats `open_app`, which otherwise takes "open brave and look for X" as
    # an app called "brave and look for X", and the agent's hidden `browse`
    # tool, which renders off screen when the user wanted to see the window.
    triggers=[rf"\b({_BROWSER_WORD})\b.*\b{_SEARCH_WORDS}\b",
              rf"\b{_SEARCH_WORDS}\b.*\b(in|on|using|with)\s+({_BROWSER_WORD})\b"],
)
def search_in_browser(browser: str = "", query: str = "", **_) -> Result:
    name = (browser or "").strip().lower()
    query = (query or "").strip()
    engine = BROWSERS.get(name, ("", "https://www.google.com/search?q="))[1]
    url = engine + quote_plus(query) if query else engine.split("/search")[0]

    exe = _browser_exe(name) if name else None
    if name and not exe:
        hit = _closest(name, _index_cache())
        if hit and sys.platform == "win32":
            # A Start Menu shortcut takes arguments through startfile.
            os.startfile(str(hit), arguments=url)              # noqa: S606
            return Result(text=f"Opened {hit.stem} and searched for “{query}”."
                          if query else f"Opened {hit.stem}.")
        webbrowser.open(url)
        return Result(text=f"I could not find {name}, so I searched in your "
                           f"default browser instead.", detail=url)
    try:
        if exe:
            subprocess.Popen([exe, url])
        else:
            webbrowser.open(url)
    except OSError as exc:
        return Result.fail(f"Couldn't start {name or 'the browser'}.", str(exc))
    shown = name.title() if name else "your browser"
    return Result(text=f"Opened {shown} and searched for “{query}”."
                  if query else f"Opened {shown}.", detail=url)
