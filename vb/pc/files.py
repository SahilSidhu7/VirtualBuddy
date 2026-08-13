"""Creating and editing files on behalf of the user, with guard rails.

The buddy is allowed to write inside the user's own folders. It is not allowed
to touch the operating system, and it never overwrites an existing file unless
the caller asked for exactly that — a skill that silently replaced a document
would be a data-loss bug, not a feature.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

FORBIDDEN = [
    Path(os.environ.get("SYSTEMROOT", "C:/Windows")),
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
    Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")),
]

TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv",
            ".html", ".css", ".xml", ".ini", ".cfg", ".toml", ".bat", ".ps1",
            ".sh", ".sql", ".log", ".rst", ""}

MAX_READ = 400_000          # bytes; beyond this we summarise rather than load


class Denied(Exception):
    """A path the buddy must not touch."""


def resolve(text: str, *, base: Path | None = None) -> Path:
    """Turn what the user typed into a real path.

    Understands "desktop", "downloads/notes.txt", "~/x", and absolute paths.
    """
    raw = (text or "").strip().strip('"').strip("'")
    if not raw:
        raise Denied("No path given.")
    home = Path.home()
    shortcuts = {"desktop": home / "Desktop", "downloads": home / "Downloads",
                 "documents": home / "Documents", "docs": home / "Documents",
                 "pictures": home / "Pictures", "music": home / "Music",
                 "videos": home / "Videos", "home": home}
    parts = raw.replace("\\", "/").split("/")
    head = parts[0].lower()
    if head in shortcuts:
        path = shortcuts[head].joinpath(*parts[1:])
    else:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (base or home / "Desktop") / path
    return path


def check(path: Path, *, write: bool) -> Path:
    """Raise if this path is off limits; return it resolved otherwise."""
    try:
        target = path.resolve()
    except OSError as exc:
        raise Denied(str(exc)) from exc
    if write:
        for bad in FORBIDDEN:
            try:
                target.relative_to(bad.resolve())
            except (ValueError, OSError):
                continue
            raise Denied(f"{target} is inside {bad.name}. I don't write there.")
        if target.parent == target:
            raise Denied("That's a drive root, not a file.")
    return target


def make_folder(path: Path) -> tuple[Path, bool]:
    target = check(path, write=True)
    existed = target.is_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target, existed


def write_file(path: Path, content: str = "", *, overwrite: bool = False) -> Path:
    target = check(path, write=True)
    if target.exists() and overwrite and target.suffix.lower() not in TEXT_EXT:
        raise Denied(f"{target.name} isn't a text file — I won't overwrite it.")
    if target.exists() and not overwrite:
        raise Denied(f"{target.name} already exists. Say “overwrite” to replace it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def append_file(path: Path, content: str) -> Path:
    target = check(path, write=True)
    # Appending text to a .jpg or .exe is never what anyone meant, whatever the
    # sentence parser decided. This check is the backstop for that.
    if target.exists() and target.suffix.lower() not in TEXT_EXT:
        raise Denied(f"{target.name} isn't a text file — I won't append to it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        if target.stat().st_size and content and not content.startswith("\n"):
            f.write("\n")
        f.write(content)
    return target


def read_file(path: Path) -> tuple[Path, str, bool]:
    """(path, text, truncated). Refuses binaries rather than printing noise."""
    target = check(path, write=False)
    if not target.is_file():
        raise Denied(f"No file at {target}")
    if target.suffix.lower() not in TEXT_EXT:
        raise Denied(f"{target.name} isn't a text file.")
    data = target.read_bytes()[: MAX_READ + 1]
    truncated = len(data) > MAX_READ
    try:
        text = data[:MAX_READ].decode("utf-8")
    except UnicodeDecodeError:
        text = data[:MAX_READ].decode("latin-1", errors="replace")
    return target, text, truncated


def replace_in_file(path: Path, old: str, new: str) -> tuple[Path, int]:
    target, text, truncated = read_file(path)
    if truncated:
        raise Denied(f"{target.name} is too big to edit safely.")
    count = text.count(old)
    if not count:
        raise Denied(f"“{old}” doesn't appear in {target.name}.")
    check(target, write=True)
    target.write_text(text.replace(old, new), encoding="utf-8")
    return target, count


def move(src: Path, dst: Path) -> tuple[Path, Path]:
    source = check(src, write=True)
    target = check(dst, write=True)
    if not source.exists():
        raise Denied(f"Nothing at {source}")
    if target.is_dir():
        target = target / source.name
    if target.exists():
        raise Denied(f"{target} already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return source, target


def recycle(path: Path) -> Path:
    """Delete via the Recycle Bin when we can, so it stays undoable."""
    target = check(path, write=True)
    if not target.exists():
        raise Denied(f"Nothing at {target}")
    try:
        from send2trash import send2trash
        send2trash(str(target))
        return target
    except ImportError:
        pass
    if target.is_dir():
        raise Denied("Deleting folders needs send2trash: pip install send2trash")
    target.unlink()
    return target
