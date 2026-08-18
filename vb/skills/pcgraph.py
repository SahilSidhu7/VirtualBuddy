"""Asking questions about this PC, answered from the file graph."""
from __future__ import annotations

from pathlib import Path

from vb import progress, slots
from vb.pc import graph as G
from vb.registry import Result, skill

FIND_VERBS = ("find", "where", "locate", "search", "look", "show", "get", "which")


def _need_index() -> Result | None:
    if not G.graph().is_built():
        return Result.fail("I haven't indexed your PC yet.",
                           "Say “index my pc” and I'll build the graph first.")
    return None


def _listing(nodes: list[G.Node], *, show_size: bool = False,
             show_age: bool = False) -> str:
    rows = []
    for n in nodes:
        bits = [n.name]
        if show_size and n.kind == "file":
            bits.append(n.human_size())
        if show_age:
            bits.append(n.age())
        rows.append("  " + "  ·  ".join(bits) + f"\n    {n.parent}")
    return "\n".join(rows)


@skill(
    "index_pc",
    "Scan this computer and build the file graph",
    ["index my pc", "scan my computer", "rebuild the file index",
     "learn my files", "refresh the pc graph", "scan everything on this machine",
     "build an index of my computer", "reindex my files"],
    slow=True, tags=["pc"],
    triggers=[r"\b(index|reindex|scan)\b.*\b(pc|computer|machine|files|drive|everything)\b",
              r"\b(index|reindex)\b"],
)
def index_pc(**_) -> Result:
    def report(files, dirs, where):
        progress.say(f"{files:,} files so far · {Path(where).name or where}")

    progress.say("Walking your folders…")
    stats = G.graph().scan(on_progress=report)
    progress.say("Building the search index…")
    roots = "\n".join(f"  {r}" for r in stats["roots"])
    return Result(
        text=f"Indexed {stats['files']:,} files in {stats['dirs']:,} folders "
             f"({stats['seconds']:.0f}s).",
        detail=f"Roots:\n{roots}" + (f"\nDropped {stats['removed']:,} stale entries."
                                     if stats["removed"] else ""))


@skill(
    "find_file",
    "Find a file or folder anywhere on this computer",
    ["find my tax pdf", "where is the invoice spreadsheet",
     "locate resume docx", "which folder has my holiday photos",
     "search my pc for budget notes", "where did i put my resume",
     "where did i save that file", "do i have a file about pensions",
     "find the folder with my thesis in it"],
    slots=lambda t: {"query": slots.after(t, FIND_VERBS)}, tags=["pc"],
    triggers=[r"\bwhere (?:is|are|did|the hell)\b", r"\bfind\b", r"\blocate\b",
              r"\bwhere.{0,12}\b(put|save[d]?)\b", r"\bdo i have\b"],
)
def find_file(query: str = "", **_) -> Result:
    if (gate := _need_index()):
        return gate
    if not query:
        return Result.fail("Find what?", "Try: find my tax pdf")
    hits = G.graph().search(query, limit=10)
    if not hits:
        return Result.fail(f"Nothing matching “{query}”.",
                           "The index may be stale — try: index my pc")
    return Result(text=f"{len(hits)} matches for “{query}”:\n" +
                       _listing(hits, show_size=True, show_age=True), data=hits)


@skill(
    "whats_in",
    "List what is inside a folder",
    ["what's in my downloads", "list the desktop folder",
     "show me what's inside documents", "what files are in that folder",
     "peek inside my downloads", "what's sitting in that folder",
     "contents of my documents folder"],
    slots=lambda t: {"folder": slots.location(t) or slots.after(t, ("list", "show"))},
    tags=["pc"],
    triggers=[r"\b(what'?s?|which files?|contents?)\b.{0,14}\b(in|inside)\b",
              r"\b(peek|look)\b.{0,10}\b(in|inside)\b", r"\blist\b.{0,16}\b(folder|directory|files)\b"],
)
def whats_in(folder: str = "", **_) -> Result:
    if (gate := _need_index()):
        return gate
    node = G.graph().resolve_folder(folder or "desktop")
    if not node:
        return Result.fail(f"No folder like “{folder}”.", "Try: what's in my downloads")
    kids = G.graph().children(node.path, limit=400)
    if not kids:
        return Result(text=f"{node.path} is empty.")
    dirs = [k for k in kids if k.kind == "dir"]
    files = [k for k in kids if k.kind == "file"]
    body = ""
    if dirs:
        body += "Folders:\n" + "\n".join(f"  {d.name}/" for d in dirs[:25]) + "\n\n"
    if files:
        body += "Files:\n" + "\n".join(
            f"  {f.name}  ·  {f.human_size()}  ·  {f.age()}" for f in files[:35])
    return Result(text=f"{node.path}\n{len(dirs)} folders, {len(files)} files\n\n{body}",
                  data=kids)


@skill(
    "disk_hogs",
    "Show what is taking up the most space",
    ["what's eating my disk space", "biggest files on my pc",
     "which folders are the largest", "what's taking up space in downloads",
     "which files are huge", "show me the big files", "what's filling up my drive"],
    slots=lambda t: {"where": slots.location(t)},
    tags=["pc"],
    triggers=[r"\b(biggest|largest|huge|hogging|eating|filling)\b", r"\bbig files?\b",
              r"\btaking up\b", r"\bspace\b"],
)
def disk_hogs(where: str = "", **_) -> Result:
    if (gate := _need_index()):
        return gate
    g = G.graph()
    under = None
    if where:
        node = g.resolve_folder(where)
        under = node.path if node else None
    files = g.biggest(limit=10, under=under)
    folders = g.folder_sizes(under=under, limit=8)
    if not files:
        return Result.fail("Nothing indexed there yet.", where or "")
    head = f"Biggest files{' in ' + under if under else ''}:\n" + "\n".join(
        f"  {n.human_size():>8}  {n.name}\n    {n.parent}" for n in files)
    tail = "\n\nHeaviest folders:\n" + "\n".join(
        f"  {G.human_size(size):>8}  {Path(path).name or path}  ({n:,} files)"
        for path, size, n in folders)
    return Result(text=head + tail, data={"files": files, "folders": folders})


@skill(
    "recent_files",
    "Show files changed recently",
    ["what did i work on today", "recent files", "what changed yesterday",
     "show me my latest downloads", "what have i been editing",
     "stuff i edited yesterday", "files i touched this week",
     "what have i been working on lately"],
    slots=lambda t: {"where": slots.location(t), "ext": _ext_of(t)},
    tags=["pc"],
    triggers=[r"\b(recent|recently|lately|latest|yesterday|today|this week)\b",
              r"\b(work(?:ed|ing)? on|edit(?:ed|ing)?|touched|changed|modified)\b"],
)
def recent_files(where: str = "", ext: str = "", **_) -> Result:
    if (gate := _need_index()):
        return gate
    g = G.graph()
    under = None
    if where:
        node = g.resolve_folder(where)
        under = node.path if node else None
    hits = g.recent(limit=15, under=under, ext=ext or None)
    if not hits:
        return Result.fail("Nothing recent found.", "Try: index my pc")
    return Result(text="Recently changed:\n" + _listing(hits, show_age=True, show_size=True),
                  data=hits)


@skill(
    "pc_summary",
    "Summarise what is on this computer",
    ["what's on my pc", "summarise my files", "how many files do i have",
     "what kinds of files are on here", "give me an overview of my pc",
     "break down my files by type"],
    tags=["pc"],
    triggers=[r"\b(how many|overview|summar\w+|breakdown|break down)\b",
              r"\bwhat kinds?\b"],
    broad=True,
)
def pc_summary(**_) -> Result:
    if (gate := _need_index()):
        return gate
    g = G.graph()
    st = g.stats()
    kinds = g.ext_summary(limit=10)
    body = "\n".join(f"  {ext:<7} {n:>6,} files   {G.human_size(b)}"
                     for ext, n, b in kinds)
    roots = "\n".join(f"  {r}" for r in st["roots"])
    return Result(
        text=f"{st['files']:,} files in {st['dirs']:,} folders, "
             f"{G.human_size(st['bytes'])} total.\n\nBy type:\n{body}",
        detail=f"Indexed {G.ago(st['scanned_at'])} from:\n{roots}")


def _ext_of(text: str) -> str:
    """Pull a file type out of plain language: "my pdfs" -> ".pdf"."""
    words = {"pdf": ".pdf", "pdfs": ".pdf", "doc": ".docx", "docs": ".docx",
             "word": ".docx", "excel": ".xlsx", "spreadsheet": ".xlsx",
             "sheet": ".xlsx", "csv": ".csv", "photo": ".jpg", "photos": ".jpg",
             "picture": ".jpg", "pictures": ".jpg", "image": ".png",
             "images": ".png", "video": ".mp4", "videos": ".mp4",
             "song": ".mp3", "songs": ".mp3", "music": ".mp3",
             "note": ".txt", "notes": ".txt", "text": ".txt",
             "python": ".py", "script": ".py", "zip": ".zip"}
    for w in text.lower().split():
        if w.strip(",.?") in words:
            return words[w.strip(",.?")]
    return ""
