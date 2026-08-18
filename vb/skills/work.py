"""What the user is working on — answered from memory, not from a disk scan.

"What are the projects I am working on" used to route to `recent_files`, which
answered with `run.py`, `__init__.py`, `config.py`, all three days old. Every
word of that was true and none of it was the answer: the question is about
projects, and a list of recently saved files is not a list of projects.

`vb.projects` reads each project once and writes a sentence about it into
memory. This skill reads those back, newest folder first, so the answer costs
a memory lookup rather than a walk over 48,000 files.
"""
from __future__ import annotations

from vb import progress, projects
from vb.registry import Result, skill


@skill(
    "what_im_working_on",
    "List the projects being worked on, most recently touched first",
    ["what am i working on", "what are my projects",
     "what projects am i working on", "what have i been building",
     "show me my projects", "list my projects", "what am i building",
     "what are the projects i am working on", "my current work",
     "what was i working on"],
    triggers=[r"\bwhat (am|are) (i|my)\b.*\b(working|projects?|building)\b",
              r"\bmy (current )?projects?\b",
              r"\bwhat have i been (building|working)\b"],
)
def what_im_working_on(**_) -> Result:
    lines = projects.active(limit=8)
    if not lines:
        return Result.fail(
            "I have not read your projects yet.",
            "Say “index my projects” and I will read them once — after that "
            "this answers instantly from memory.")
    return Result(text="What you are working on, most recent first:\n\n"
                       + "\n\n".join(f"  {line}" for line in lines),
                  detail="From memory. Say “index my projects” after adding a "
                         "new one.")


@skill(
    "index_projects",
    "Read every project on this machine once and remember what each one is",
    ["index my projects", "scan my projects", "learn my projects",
     "read my projects", "refresh my projects", "reindex projects"],
    triggers=[r"\b(index|scan|read|learn|refresh|reindex)\b.*\bprojects?\b"],
)
def index_projects(force: bool = False, **_) -> Result:
    """Slow and deliberate: a model call per project, about ten seconds each.

    Only ever run when asked. Thirty-four projects took five minutes on this
    machine, which is fine once and unacceptable on every question — which is
    exactly why the result is written to memory instead of recomputed.
    """
    progress.say("Reading your projects. This happens once…")
    result = projects.index(force=bool(force), on_progress=progress.say)
    if not result["described"] and not result["skipped"]:
        return Result.fail("I could not find any projects to read.",
                           "I look under C:/Projects and your home folder. "
                           "Set project_roots in config.json to point me "
                           "somewhere else.")
    body = (f"Read {result['described']} of {result['found']} projects.")
    if result["skipped"]:
        body += f" {result['skipped']} were already described."
    return Result(text=body + "\n\nAsk me what you are working on.",
                  detail="Stored in memory, so it stays known between restarts.")
