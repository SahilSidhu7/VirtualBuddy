"""Making and changing files and folders.

Everything that writes goes through vb.pc.files, which refuses system folders
and never overwrites without being told to. Deleting is marked dangerous, so it
asks first even in auto mode.
"""
from __future__ import annotations

import re

from vb import slots
from vb.pc import files
from vb.pc.files import Denied
from vb.registry import Result, skill

MAKE_VERBS = ("create", "make", "new", "add")
IN_AT = re.compile(r"\b(?:in|inside|on|at|under|to|from)\s+(?:my\s+)?([\w~. -]+)$", re.I)
# Words that mean the "place" match ran into the rest of the sentence.
NOT_A_PLACE = re.compile(r"\b(replace|saying|with|and|says|line|text)\b", re.I)
GENERIC = {"folder", "file", "directory", "dir", "document", "new", "one"}


def _place_ok(place: str) -> str:
    """Keep a location only if it still looks like one."""
    if not place or NOT_A_PLACE.search(place) or len(place.split()) > 3:
        return ""
    return place
# The name stops at the next locator word, or the sentence would eat "in C:/…".
CALLED = re.compile(
    r"\b(?:called|named)\s+([\w.()-]+(?:\s+[\w.()-]+)*?)"
    r"(?=\s+\b(?:in|inside|on|at|under|to|saying|with|that)\b|\s*$)", re.I)
WITH_TEXT = re.compile(
    r"\b(?:saying|containing|with (?:the )?(?:text|content)|that says)\s+(.+)$",
    re.I | re.S)

# An explicit path the user typed: a drive letter, a ~, or anything with a
# separator in it. When one is present it *is* the target, and no guessing of
# any kind is allowed on top of it.
PATHLIKE = re.compile(r"""(?:[A-Za-z]:[\\/]|~[\\/]|\.{1,2}[\\/])[^\s"']+"""
                      r"""|[^\s"']+[\\/][^\s"']+""")


def explicit_path(text: str) -> str:
    """The path the user typed, if they typed one."""
    for chunk in PATHLIKE.finditer(text):
        candidate = chunk.group(0).rstrip(".,;")
        if candidate.startswith(("http://", "https://")):
            continue
        return candidate
    return ""


FILENAME = re.compile(r"^[\w][\w.()-]*\.[A-Za-z0-9]{1,6}$")


def _filename(text: str) -> str:
    """A bare filename with an extension: "add a line to notes.txt" -> notes.txt.

    Whitespace-delimited on purpose. A regex allowing spaces inside the name
    happily swallowed the whole leading clause ("create a file called notes.txt"),
    so names containing spaces have to be quoted instead.
    """
    quoted = slots.quoted(text)
    if quoted and "." in quoted:
        return quoted
    for token in text.replace(",", " ").split():
        candidate = token.strip("\"'?!;:")
        if FILENAME.match(candidate):
            return candidate
    return ""


def _name_and_place(text: str) -> tuple[str, str]:
    """("notes.txt", "desktop") out of "make a file called notes.txt on my desktop".

    A typed path short-circuits everything and comes back as the name.
    """
    typed = explicit_path(text)
    named = CALLED.search(text)
    if typed and named:
        # "a file called notes.txt in C:/tmp" — the path is the destination.
        return named.group(1).strip().rstrip("."), typed
    if typed:
        return typed, ""
    bare = _filename(text)
    if bare:
        rest = text.replace(bare, " ", 1)
        where = IN_AT.search(rest.split(" saying ")[0])
        return bare, _place_ok(where.group(1).strip().rstrip(".") if where else "")
    place = ""
    m = IN_AT.search(text.split(" saying ")[0])
    if m:
        place = _place_ok(m.group(1).strip().rstrip("."))
        text = text[: m.start()]
    m = CALLED.search(text)
    if m:
        return m.group(1).strip().rstrip("."), place
    tail = slots.after(text, MAKE_VERBS + ("folder", "file", "directory"))
    tail = re.sub(r"^(?:a|new|folder|file|directory|dir)\s+", "", tail).strip()
    name = tail.split(" in ")[0].strip()
    # "make a new folder in documents" names nothing; better to ask than to
    # create a folder literally called "folder".
    return ("" if name.lower() in GENERIC else name), place


def _target(name: str, place: str):
    return files.resolve(f"{place}/{name}" if place else name)


@skill(
    "create_folder",
    "Create a new folder",
    ["create a folder called invoices on my desktop", "make a new folder in documents",
     "add a directory named photos", "new folder called work",
     "make me a folder for taxes on the desktop", "set up a folder for the trip"],
    slots=lambda t: dict(zip(("name", "place"), _name_and_place(t))), tags=["pc"],
    triggers=[r"\b(create|make|new|add|set up)\b.{0,20}\b(folder|directory|dir)\b"],
)
def create_folder(name: str = "", place: str = "", **_) -> Result:
    if not name:
        return Result.fail("What should the folder be called?",
                           "Try: create a folder called invoices on my desktop")
    try:
        path, existed = files.make_folder(_target(name, place))
    except Denied as exc:
        return Result.fail("Can't create that folder.", str(exc))
    return Result(text=("Already there: " if existed else "Created ") + str(path))


@skill(
    "create_file",
    "Create a new file, optionally with some text in it",
    ["create a file called notes.txt on my desktop",
     "make a new text file in documents saying remember the milk",
     "new file called todo.md", "write a file with the text hello",
     "start a new document called ideas", "make me a text file for the meeting"],
    slots=lambda t: {**dict(zip(("name", "place"), _name_and_place(t))),
                     "content": (WITH_TEXT.search(t).group(1).strip()
                                 if WITH_TEXT.search(t) else ""),
                     "overwrite": bool(re.search(r"\boverwrite|replace\b", t, re.I))},
    tags=["pc"],
    triggers=[r"\b(create|make|new|start|write)\b.{0,20}\b(file|document|txt|note)\b",
              r"\b(file|document)\b.{0,14}\b(called|named)\b"],
)
def create_file(name: str = "", place: str = "", content: str = "",
                overwrite: bool = False, **_) -> Result:
    if not name:
        return Result.fail("What should the file be called?",
                           "Try: create a file called notes.txt on my desktop")
    if "." not in name:
        name += ".txt"
    try:
        path = files.write_file(_target(name, place), content, overwrite=overwrite)
    except Denied as exc:
        return Result.fail("Can't create that file.", str(exc))
    size = f"{len(content)} characters" if content else "empty"
    return Result(text=f"Created {path}  ({size})")


@skill(
    "read_file",
    "Show what is inside a text file",
    ["read notes.txt on my desktop", "show me the contents of that file",
     "open todo.md and show it", "what does the config file say"],
    slots=lambda t: dict(zip(("name", "place"),
                             _name_and_place(t.replace("read", "open", 1)))),
    tags=["pc"],
    # "path" and "link" are what router.normalise leaves behind for a typed
    # path and a URL, so these separate reading a file on disk from reading a
    # web page.
    triggers=[r"\b(read|contents? of|what does|show me)\b.{0,24}\.\w{1,5}\b",
              r"\bread\b.{0,20}\b(file|note|txt|md)\b",
              r"\b(read|open|show|print)\b.{0,20}\bpath\b"],
)
def read_file(name: str = "", place: str = "", **_) -> Result:
    if not name:
        return Result.fail("Which file?", "Try: read notes.txt on my desktop")
    path = _target(name, place)
    if not path.exists():
        found = _lookup(name)
        if not found:
            return Result.fail(f"No file called {name}.",
                               "Index your PC and I can find it anywhere.")
        path = found
    try:
        path, text, truncated = files.read_file(path)
    except Denied as exc:
        return Result.fail("Can't read that.", str(exc))
    body = text if len(text) < 4000 else text[:4000] + "\n…"
    note = "Showing the first part only." if truncated else ""
    return Result(text=f"{path}\n\n{body}", detail=note, data=text)


@skill(
    "edit_file",
    "Add text to a file, or replace text inside it",
    ["add a line to notes.txt saying call mum",
     "append to my todo list buy milk",
     "in notes.txt replace monday with tuesday",
     "edit the shopping list and add eggs",
     "stick a note in ideas.txt saying try again",
     "put another line in my notes file"],
    slots=lambda t: _edit_slots(t), tags=["pc"],
    triggers=[r"\b(append|add|stick|put|write)\b.{0,30}\b(to|in|into)\b.{0,24}\.\w{1,5}\b",
              r"\breplace\b.+\bwith\b", r"\bedit\b", r"\badd a line\b"],
)
def edit_file(name: str = "", place: str = "", add: str = "",
              old: str = "", new: str = "", **_) -> Result:
    if not name:
        return Result.fail("Which file?", "Try: add a line to notes.txt saying call mum")
    path = _target(name, place)
    if not path.exists():
        found = _lookup(name)
        if not found:
            return Result.fail(f"No file called {name}.", "Create it first.")
        path = found
    try:
        if old:
            path, count = files.replace_in_file(path, old, new)
            return Result(text=f"Replaced {count} occurrence"
                               f"{'s' if count != 1 else ''} in {path.name}.",
                          detail=str(path))
        if not add:
            return Result.fail("Add what?", "Try: add a line to notes.txt saying call mum")
        path = files.append_file(path, add)
    except Denied as exc:
        return Result.fail("Can't edit that.", str(exc))
    return Result(text=f"Added to {path.name}: “{add}”", detail=str(path))


@skill(
    "move_file",
    "Move or rename a file",
    ["move report.pdf to documents", "rename notes.txt to ideas.txt",
     "put that file in my desktop folder"],
    slots=lambda t: _move_slots(t), danger=True, tags=["pc"],
    triggers=[r"\b(move|rename)\b", r"\bput\b.{0,24}\b(in|into)\b.{0,20}\bfolder\b"],
)
def move_file(source: str = "", destination: str = "", **_) -> Result:
    if not source or not destination:
        return Result.fail("Move what, and where?",
                           "Try: move report.pdf to documents")
    src = files.resolve(source)
    if not src.exists():
        found = _lookup(source)
        if not found:
            return Result.fail(f"Nothing called {source}.")
        src = found
    try:
        src, dst = files.move(src, files.resolve(destination))
    except Denied as exc:
        return Result.fail("Can't move that.", str(exc))
    return Result(text=f"Moved {src.name} → {dst}")


@skill(
    "delete_file",
    "Send a file or folder to the recycle bin",
    ["delete notes.txt from my desktop", "remove that folder",
     "bin the old invoice file", "throw away temp.txt", "get rid of that file"],
    slots=lambda t: dict(zip(("name", "place"),
                             _name_and_place(t.replace("delete", "open", 1)))),
    danger=True, tags=["pc"],
    triggers=[r"\b(delete|remove|bin|trash|get rid of|throw away)\b"],
)
def delete_file(name: str = "", place: str = "", **_) -> Result:
    if not name:
        return Result.fail("Delete what?", "Try: delete notes.txt from my desktop")
    path = _target(name, place)
    if not path.exists():
        found = _lookup(name)
        if not found:
            return Result.fail(f"Nothing called {name}.")
        path = found
    try:
        path = files.recycle(path)
    except Denied as exc:
        return Result.fail("Can't delete that.", str(exc))
    return Result(text=f"Sent {path.name} to the recycle bin.", detail=str(path))


def _edit_slots(text: str) -> dict:
    name, place = _name_and_place(text.replace("add", "open", 1))

    # Replacing wins over appending: "replace x with y" is unambiguous.
    m = re.search(r"\breplace\s+(.+?)\s+with\s+(.+)$", text, re.I)
    if m:
        return {"name": name, "place": place, "add": "",
                "old": m.group(1).strip(), "new": m.group(2).strip()}

    # Otherwise find the content marker, in order of how explicit it is. An
    # earlier version searched for "add" too, which swallowed the file path
    # into the text being written.
    add = ""
    for pattern in (r"\b(?:saying|that says|with the text|with text|containing)\s+(.+)$",
                    r"\b(?:append|add)\s+(?:a\s+line\s+)?(?:\"|')?(.+?)(?:\"|')?"
                    r"\s+(?:to|in|into)\s+\S+$"):
        m = re.search(pattern, text, re.I | re.S)
        if m:
            add = m.group(1).strip().strip("\"'")
            break
    return {"name": name, "place": place, "add": add, "old": "", "new": ""}


def _move_slots(text: str) -> dict:
    m = re.search(r"\b(?:move|rename|put)\s+(.+?)\s+(?:to|into|in)\s+(.+)$", text, re.I)
    if not m:
        return {"source": "", "destination": ""}
    return {"source": m.group(1).strip(), "destination": m.group(2).strip().rstrip(".")}


def _lookup(name: str):
    """Find a file in the PC graph when the user gave a bare filename.

    Strict on purpose. The graph's search is fuzzy, and a fuzzy answer is fine
    for "find my tax pdf" but catastrophic for "append this text to X" — an
    early version appended to a photo whose name merely scored well. So: no
    typed paths, and the filename has to actually match.
    """
    from pathlib import Path

    from vb.pc import graph as G
    if not name or explicit_path(name) or any(sep in name for sep in "\\/"):
        return None
    g = G.graph()
    if not g.is_built():
        return None
    wanted = name.strip().lower()
    stem = Path(wanted).stem
    for node in g.search(name, kind="file", limit=25):
        candidate = node.name.lower()
        if candidate == wanted or Path(candidate).stem == stem:
            return Path(node.path)
    return None
