"""Folders and files: open Downloads, find that PDF, open the file I just saved.

Search is a plain walk of the usual user folders — no index to build, no service
to run. Bounded so a stray "find *" can't spin for a minute.
"""
import os, re, subprocess, sys, time, fnmatch

from buddy import slots

HOME = os.path.expanduser("~")

FOLDERS = {
    "downloads": ["Downloads"],
    "documents": ["Documents", "OneDrive/Documents"],
    "desktop": ["Desktop", "OneDrive/Desktop"],
    "pictures": ["Pictures", "OneDrive/Pictures"],
    "photos": ["Pictures", "OneDrive/Pictures"],
    "videos": ["Videos"],
    "music": ["Music"],
    "home": [""],
    "recycle bin": ["__recycle__"],
}

_SEARCH_ROOTS = ["Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music",
                 "OneDrive/Documents", "OneDrive/Desktop"]

_SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "AppData",
              "site-packages", ".cache", "dist", "build"}

_KIND = {
    "pdf": ("*.pdf",), "pdfs": ("*.pdf",),
    "image": ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"),
    "picture": ("*.png", "*.jpg", "*.jpeg"), "photo": ("*.png", "*.jpg", "*.jpeg"),
    "screenshot": ("*.png",),
    "video": ("*.mp4", "*.mkv", "*.mov", "*.avi"),
    "song": ("*.mp3", "*.wav", "*.flac"), "music": ("*.mp3", "*.wav", "*.flac"),
    "spreadsheet": ("*.xlsx", "*.csv"), "excel": ("*.xlsx", "*.csv"),
    "doc": ("*.docx", "*.doc", "*.txt"), "document": ("*.docx", "*.doc", "*.txt", "*.pdf"),
    "zip": ("*.zip", "*.rar", "*.7z"),
}


def _reveal(path):
    """Open a folder or file with the OS default handler."""
    if os.name == "nt":
        os.startfile(path)                                  # noqa: S606 - intended
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _resolve_folder(name):
    for rel in FOLDERS.get(name, []):
        if rel == "__recycle__":
            return "shell:RecycleBinFolder"
        p = os.path.join(HOME, rel) if rel else HOME
        if os.path.isdir(p):
            return p
    return None


def open_folder(text, ctx):
    t = slots.clean(text)
    for name in sorted(FOLDERS, key=len, reverse=True):
        if name in t:
            path = _resolve_folder(name)
            if not path:
                return f"I couldn't find your {name} folder."
            if path.startswith("shell:"):
                subprocess.Popen(f'explorer "{path}"', shell=True)
                return "Opening the recycle bin."
            _reveal(path)
            return f"Opening {path}."
    # a literal path in the command
    m = re.search(r"([a-zA-Z]:[\\/][^\s\"']+|~[\\/][^\s\"']+)", text)
    if m:
        p = os.path.expanduser(m.group(1))
        if os.path.exists(p):
            _reveal(p)
            return f"Opening {p}."
        return f"{p} doesn't exist."
    return "Which folder? Try downloads, documents, desktop, pictures or a full path."


def _patterns(text):
    t = slots.clean(text)
    for word, pats in _KIND.items():
        if re.search(rf"\b{word}s?\b", t):
            return list(pats), word
    q = slots.quoted(text)
    if not q:
        m = re.search(r"\b(?:find|search for|look for|where is|locate)\s+"
                      r"(?:my\s+|the\s+|a\s+)?(?:files?\s+)?(?:called\s+|named\s+)?"
                      r"([\w .\-]{2,40})", t)
        q = m.group(1).strip() if m else None
    if not q:
        return None, None
    q = re.sub(r"\b(files?|called|named|on my pc|on my computer|anywhere|that i (?:made|took|saved)|"
               r"i (?:made|took|saved|downloaded))\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return [f"*{q}*"] if q else None, q


def find_files(text, ctx):
    pats, label = _patterns(text)
    if not pats:
        return "What should I look for? e.g. \"find my tax pdf\" or \"find files called report\"."
    newest_first = any(w in text.lower() for w in ("recent", "latest", "newest", "just"))
    hits, deadline = [], time.time() + 6          # hard cap: never hang the assistant
    for rel in _SEARCH_ROOTS:
        root = os.path.join(HOME, rel)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if any(fnmatch.fnmatch(fn.lower(), p.lower()) for p in pats):
                    full = os.path.join(dirpath, fn)
                    try:
                        hits.append((os.path.getmtime(full), full))
                    except OSError:
                        continue
            if time.time() > deadline or len(hits) > 400:
                break
        if time.time() > deadline or len(hits) > 400:
            break
    if not hits:
        return f"Nothing matching {label} in your usual folders."
    hits.sort(reverse=True)                       # newest first is almost always what's wanted
    show = hits[:8]
    ctx["last_files"] = [p for _, p in show]
    lines = [f"Found {len(hits)} match{'es' if len(hits) > 1 else ''} for {label}:"]
    for mtime, p in show:
        when = time.strftime("%d %b", time.localtime(mtime))
        lines.append(f"  - {os.path.basename(p)}  ({when}, {os.path.dirname(p)})")
    if newest_first:
        lines.append("Say \"open that\" and I'll open the newest one.")
    return "\n".join(lines)


def open_found(text, ctx):
    files = ctx.get("last_files")
    if not files:
        return "Find something first — e.g. \"find my invoice pdf\"."
    n = slots.number(text)
    idx = (n - 1) if n and 1 <= n <= len(files) else 0
    try:
        _reveal(files[idx])
        return f"Opening {os.path.basename(files[idx])}."
    except Exception as e:
        return f"Couldn't open it: {e}"


def recent_downloads(text, ctx):
    d = _resolve_folder("downloads")
    if not d:
        return "I couldn't find your Downloads folder."
    try:
        entries = [(os.path.getmtime(os.path.join(d, f)), f)
                   for f in os.listdir(d) if not f.startswith(".")]
    except OSError as e:
        return f"Couldn't read Downloads: {e}"
    if not entries:
        return "Downloads is empty."
    entries.sort(reverse=True)
    ctx["last_files"] = [os.path.join(d, f) for _, f in entries[:8]]
    lines = ["Most recent downloads:"]
    for mtime, f in entries[:8]:
        lines.append(f"  - {f}  ({time.strftime('%d %b %H:%M', time.localtime(mtime))})")
    return "\n".join(lines)


SKILLS = [
    {"name": "open_folder", "desc": "open a folder in the file explorer",
     "phrases": ["open my downloads", "show me my documents folder", "open the desktop folder",
                 "pull up my pictures", "open c:/projects", "open the recycle bin",
                 "take me to my videos folder"],
     "run": open_folder},
    {"name": "find_files", "desc": "search your folders for a file",
     "phrases": ["find my tax pdf", "where is my resume", "search for files called invoice",
                 "look for that screenshot", "find the spreadsheet i made",
                 "locate my presentation", "find recent pdfs"],
     "run": find_files},
    {"name": "open_found", "desc": "open a file from the last search",
     "phrases": ["open that file", "open the first one", "open number 2",
                 "open that one", "yes open it"],
     "run": open_found},
    {"name": "recent_downloads", "desc": "what was downloaded recently",
     "phrases": ["what did i just download", "show my recent downloads",
                 "where did that download go", "latest downloads", "what's in my downloads"],
     "run": recent_downloads},
]
