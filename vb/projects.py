"""A one-off read of what the user is actually building.

Asked "what am I working on", the buddy used to answer with whichever files
changed most recently — `run.py`, `__init__.py`, `config.py`, three days old.
That is a true answer to a question nobody asked. The reason it could not do
better is that nothing in memory described a *project*: there were facts about
paths and episodes about counting files, and not one line saying what any of
the folders on this machine are for.

So this reads each project once and writes a sentence about it into memory as a
durable fact. After that the question is answered from memory in 80ms with no
scan and no model call, which is the point — the expensive part happens once.

Deliberately shallow. It reads the README, the manifest and the shape of the
tree, not the source. A summary of what a project *is* survives; a summary of
what its code currently says is stale within a day and costs a hundred times
more to produce.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from vb import config, llm, memory, progress

# Files that say what a thing is, best first.
READMES = ("README.md", "README.rst", "README.txt", "readme.md", "README")
MANIFESTS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod",
             "requirements.txt", "pom.xml", "build.gradle", "composer.json")
# Enough of a README to know the project; more is the tutorial.
README_CHARS = 1800
MAX_ENTRIES = 40           # of the top-level listing shown to the model
SKIP = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist",
        "build", "target", ".idea", ".vscode", "env", ".next", "vendor"}

TAG = "project"


def roots() -> list[Path]:
    """Where projects live. Configurable; guessed sensibly when it is not."""
    configured = config.get("project_roots") or []
    if configured:
        return [Path(p) for p in configured if Path(p).is_dir()]
    home = Path.home()
    guesses = [Path("C:/Projects"), home / "Projects", home / "src",
               home / "code", home / "Documents/GitHub"]
    return [p for p in guesses if p.is_dir()]


def _looks_like_project(folder: Path) -> bool:
    """A folder someone works in, rather than a folder of folders.

    A project has a marker in it — a manifest, a README, a .git. Without this
    test the scan describes `C:/Projects/MAIN` as one project rather than the
    thirty inside it, and produces one useless sentence instead of thirty
    useful ones.
    """
    try:
        names = {p.name for p in folder.iterdir()}
    except OSError:
        return False
    return bool(names & set(MANIFESTS) or names & set(READMES) or ".git" in names)


def discover(max_depth: int = 2) -> list[Path]:
    """Every project under the roots, without walking the whole disk.

    Two levels by default: `C:/Projects/MAIN/VirtualBuddy` is depth two and is
    the common shape here. Descending further finds vendored copies inside
    `node_modules` and similar, which is why SKIP exists and why the depth is
    capped rather than unlimited.
    """
    found: list[Path] = []

    def walk(folder: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = [p for p in folder.iterdir()
                        if p.is_dir() and p.name not in SKIP
                        and not p.name.startswith(".")]
        except OSError:
            return
        for child in children:
            if _looks_like_project(child):
                found.append(child)
                # Not descending into a project: its subfolders are its parts,
                # not separate work.
                continue
            walk(child, depth + 1)

    for root in roots():
        walk(root, 1)
    return found


def _evidence(folder: Path) -> str:
    """What the model is shown about one project."""
    parts = [f"Folder: {folder}"]
    for name in READMES:
        target = folder / name
        if target.is_file():
            try:
                parts.append(f"--- {name} ---\n"
                             + target.read_text("utf-8", errors="replace")[:README_CHARS])
            except OSError:
                pass
            break
    for name in MANIFESTS:
        target = folder / name
        if target.is_file():
            try:
                parts.append(f"--- {name} ---\n"
                             + target.read_text("utf-8", errors="replace")[:600])
            except OSError:
                pass
            break
    try:
        entries = sorted(p.name + ("/" if p.is_dir() else "")
                         for p in folder.iterdir() if p.name not in SKIP)
        parts.append("--- contents ---\n" + ", ".join(entries[:MAX_ENTRIES]))
    except OSError:
        pass
    return "\n\n".join(parts)


def _last_touched(folder: Path) -> float:
    """When this project was last worked on. Shallow: the newest thing one
    level down, which is close enough and does not cost a recursive walk."""
    newest = 0.0
    try:
        for p in folder.iterdir():
            if p.name in SKIP:
                continue
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


SYSTEM = ("You describe a software project in one sentence, factually, from "
          "the evidence given. No adjectives, no praise, no speculation about "
          "what it could become.")

PROMPT = """{evidence}

In one sentence of at most 30 words: what is this project and what is it built
with? Start with the project name. If the evidence does not say what it does,
say what kind of project it appears to be from its files — do not invent a
purpose."""


def summarise(folder: Path) -> str | None:
    """One sentence about one project, or None when the model could not."""
    text = llm.ask(PROMPT.format(evidence=_evidence(folder)[:6000]),
                   system=SYSTEM, max_tokens=120, temperature=0.1)
    if not text:
        return None
    # One sentence, whatever it returned. A paragraph in a memory note crowds
    # out three other notes when it is recalled.
    line = " ".join(text.split())
    return line[:300]


def index(force: bool = False, on_progress=None) -> dict:
    """Read every project once and remember what each one is.

    Idempotent: a project already described is skipped unless `force`, so this
    can be re-run after adding a project without paying for the rest again.
    """
    projects = discover()
    known = {n.text for n in memory.recent(limit=500, kind=TAG)}
    done, skipped = 0, 0
    for i, folder in enumerate(projects, start=1):
        if on_progress:
            on_progress(f"Reading {folder.name} ({i} of {len(projects)})…")
        if not force and any(str(folder) in text for text in known):
            skipped += 1
            continue
        sentence = summarise(folder)
        if not sentence:
            continue
        days = (time.time() - _last_touched(folder)) / 86400
        when = ("touched today" if days < 1 else
                f"last touched {int(days)} days ago")
        memory.remember(f"{sentence} Located at {folder}, {when}.",
                        kind=TAG, tags="project")
        done += 1
    return {"found": len(projects), "described": done, "skipped": skipped}


def summary() -> str:
    known = memory.recent(limit=500, kind=TAG)
    if not known:
        return ("No projects described yet. Run `/projects` and I will read "
                "them once, then answer from memory after that.")
    return f"{len(known)} projects described. Ask me what you are working on."


def active(limit: int = 8) -> list[str]:
    """What is being worked on now, newest first.

    Recency comes from the folder rather than the note: a project described
    last month is not stale, but one untouched for a month is not what the
    person is working on this afternoon.
    """
    notes = memory.recent(limit=500, kind=TAG)
    dated = []
    for note in notes:
        folder = _folder_of(note.text)
        dated.append((_last_touched(folder) if folder else 0.0, note.text))
    dated.sort(key=lambda pair: -pair[0])
    return [text for _when, text in dated[:limit]]


# The folder this note is about, written by `index` as "Located at <path>,".
# Matching the sentence we wrote rather than hunting for the first path-shaped
# word in it: the model's own description usually mentions the *parent* first
# ("The homebrew-tap project in C:\\Projects\\MAIN contains …"), so the loose
# search picked up C:\\Projects\\MAIN — touched today, because something in it
# always is — and sorted a project untouched for six weeks to the top.
_LOCATED = re.compile(r"Located at (.+?),\s+(?:last )?touched", re.I)


def _folder_of(text: str) -> Path | None:
    found = _LOCATED.search(text or "")
    if not found:
        return None
    folder = Path(found.group(1).strip())
    return folder if folder.is_dir() else None
