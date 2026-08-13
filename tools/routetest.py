"""Route-only self test: does each phrasing reach the right skill?

Never executes a skill — routing is what we are checking, and running things
like open_app for real would fling windows around.

    python tools/routetest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vb.router import Router  # noqa: E402

CASES = [
    ("search the web for cheap flights to goa", "web_search"),
    ("google the weather in delhi", "web_search"),
    ("look up when the shop closes", "web_search"),
    ("find articles about intermittent fasting", "web_search"),
    ("research the best budget gpus for me", "research"),
    ("do some research on creatine", "research"),
    ("dig into the news about the merger", "research"),
    ("compare the top noise cancelling headphones", "research"),
    ("read https://example.com and tell me what it says", "read_page"),
    ("summarise this article https://news.ycombinator.com", "read_page"),
    ("scrape the text from https://example.com", "read_page"),
    ("get all the links from https://example.com", "extract_links"),
    ("list the urls on https://example.com", "extract_links"),
    ("open chrome", "open_app"),
    ("launch spotify", "open_app"),
    ("start the calculator", "open_app"),
    ("fire up vs code", "open_app"),
    ("open youtube", "open_site"),
    ("take me to reddit", "open_site"),
    ("visit github.com", "open_site"),
    ("open my downloads folder", "open_folder"),
    ("show me the desktop folder", "open_folder"),

    # PC graph
    ("index my pc", "index_pc"),
    ("scan my computer for files", "index_pc"),
    ("find my tax pdf", "find_file"),
    ("where is the invoice spreadsheet", "find_file"),
    ("search my pc for budget notes", "find_file"),
    ("what's in my downloads", "whats_in"),
    ("list what's inside documents", "whats_in"),
    ("what's eating my disk space", "disk_hogs"),
    ("biggest files on my pc", "disk_hogs"),
    ("what did i work on today", "recent_files"),
    ("show me my recent files", "recent_files"),
    ("what's on my pc", "pc_summary"),
    ("how many files do i have", "pc_summary"),

    # file work
    ("create a folder called invoices on my desktop", "create_folder"),
    ("make a new folder in documents", "create_folder"),
    ("create a file called notes.txt on my desktop", "create_file"),
    ("new file called todo.md in documents", "create_file"),
    ("read notes.txt on my desktop", "read_file"),
    ("show me the contents of config.ini", "read_file"),
    ("add a line to notes.txt saying call mum", "edit_file"),
    ("in notes.txt replace monday with tuesday", "edit_file"),
    ("move report.pdf to documents", "move_file"),
    ("rename notes.txt to ideas.txt", "move_file"),
    ("delete temp.txt from my desktop", "delete_file"),

    # processes
    ("what's running on my pc", "running_apps"),
    ("what's using my cpu", "running_apps"),
    ("why is my pc slow", "running_apps"),
    ("kill chrome", "kill_app"),
    ("close spotify", "kill_app"),
    ("how much disk space is left", "pc_health"),
    ("check my battery", "pc_health"),

    # to-do list
    ("remind me to call the dentist tomorrow", "add_task"),
    ("add buy milk to my todo list", "add_task"),
    ("what's on my todo list", "list_tasks"),
    ("what do i need to do", "list_tasks"),
    ("mark buy milk as done", "complete_task"),
    ("i finished the report", "complete_task"),
    ("clear my finished tasks", "clear_tasks"),
]

# Phrasings deliberately absent from every skill's phrase list. Declared
# phrases score 1.00 and prove nothing; these are what routing is really for.
UNSEEN = [
    ("hey where did i put my resume", "find_file"),
    ("do i have anything about pensions on here", "find_file"),
    ("how much room is left on my drive", "pc_health"),
    ("whats hogging the cpu right now", "running_apps"),
    ("shut down chrome please", "kill_app"),
    ("make me a folder for taxes on the desktop", "create_folder"),
    ("jot down pick up parcel on saturday", "add_task"),
    ("whats left for me to do today", "list_tasks"),
    ("scan everything on this machine", "index_pc"),
    ("which files are huge", "disk_hogs"),
    ("stuff i edited yesterday", "recent_files"),
    ("peek inside my downloads", "whats_in"),
    ("stick a note in ideas.txt saying try again", "edit_file"),
    ("bin that temp file", "delete_file"),
    ("whats the contents of readme.md", "read_file"),
    ("cross off buy milk", "complete_task"),
    ("break down my files by type", "pc_summary"),
    # "articles on X" is a list-of-links request, not a briefing; research is
    # for "tell me about X across sources".
    ("dig up some articles on sleep debt", "web_search"),
    ("give me the lowdown on creatine from a few sites", "research"),

    # Typed paths used to swamp the intent words: "read <long path>" once
    # scored read_file 0.35 against delete_file 0.30 and binned the file.
    ("read C:/Users/sam/Documents/notes.txt", "read_file"),
    ("read C:\\Users\\sam\\AppData\\Local\\Temp\\tmp_9f2/probe.txt", "read_file"),
    ("open C:/Projects/thing/readme.md", "read_file"),
    ("read https://example.com/article", "read_page"),
    ("summarise https://news.ycombinator.com/item?id=1", "read_page"),
]


def main() -> int:
    router = Router()
    bad = []
    cases = CASES + UNSEEN
    for prompt, want in cases:
        ranked = router.rank(prompt, top=3)
        got = ranked[0].skill.name if ranked else "-none-"
        score = ranked[0].score if ranked else 0.0
        mark = "ok  " if got == want else "MISS"
        if got != want:
            alts = ", ".join(f"{m.skill.name}:{m.score:.2f}" for m in ranked)
            bad.append((prompt, want, got, alts))
        print(f"{mark} {score:.2f}  {prompt!r:55} -> {got}")
    print(f"\n{len(cases) - len(bad)}/{len(cases)} routed correctly "
          f"({len(CASES)} declared, {len(UNSEEN)} unseen phrasings)")
    for prompt, want, got, alts in bad:
        print(f"  MISS {prompt!r}\n       want {want}, got {got}  [{alts}]")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
