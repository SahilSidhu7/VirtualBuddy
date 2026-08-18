"""Handing work to Claude Code, and asking what it has been doing.

Kept as skills rather than agent-loop tools on purpose. Claude Code spends the
user's five-hour plan quota, and a quota the user also wants for themselves is
not something a local model should be able to spend on a hunch mid-loop. These
run when they are asked for by name.
"""
from __future__ import annotations

from pathlib import Path

from vb import claudecode, progress
from vb.registry import Result, skill


@skill(
    "claude_status",
    "What Claude Code is doing: recent sessions, plan, and anything queued",
    ["what is claude doing", "claude status", "my claude sessions",
     "what was i doing in claude", "show me my claude work",
     "what has claude been working on", "claude sessions"],
    triggers=[r"\bclaude\b.*\b(status|sessions?|doing|working)\b",
              r"\b(what|show).*\bclaude\b"],
    requires=["claude"],
)
def claude_status(**_) -> Result:
    ready, why = claudecode.available()
    if not ready:
        return Result.fail(why, "Install Claude Code to use this.")
    return Result(text=claudecode.status())


@skill(
    "ask_claude",
    "Give a coding job to Claude Code in one of your projects",
    ["ask claude to", "get claude to", "have claude build",
     "use claude to build", "tell claude to fix", "claude build me"],
    triggers=[r"\b(ask|get|have|tell|use)\s+claude\b"],
    requires=["claude"],
    danger=True,          # spends the plan's quota, and writes files
)
def ask_claude(task: str = "", project: str = "", **_) -> Result:
    """Run one Claude Code job and report what came back.

    `danger=True` so it always asks first. It writes to a real repository and
    draws down a quota that resets only every five hours; both are things to
    confirm rather than assume.
    """
    task = (task or "").strip()
    if not task:
        return Result.fail("What should Claude do?",
                           'Try: ask claude to add tests to ServManager')

    cwd = _resolve_project(project)
    if project and not cwd:
        return Result.fail(f"I could not find a project called “{project}”.",
                           "Say “what am I working on” to see what I know.")

    if claudecode.bills_per_token():
        # Only reachable if overage has been turned on for the account. Worth
        # saying out loud rather than discovering on an invoice.
        progress.say("Note: this account has extra usage enabled, so this "
                     "call can cost money.")
    progress.say(f"Handing this to Claude in {Path(cwd).name if cwd else 'here'}…")
    job = claudecode.run(task, cwd or "")

    if job.ok:
        return Result(
            text=job.answer,
            detail=f"Claude Code · {job.seconds:.0f}s · session {job.session_id[:8]}"
                   + (f" · in {cwd}" if cwd else ""))

    if job.limited:
        item = claudecode.defer(job)
        import time
        mins = max(0, int((item["retry_at"] - time.time()) // 60))
        return Result(
            text=("Claude is out of quota for now, so I have queued this and "
                  f"will run it when the window resets — about {mins} minutes."),
            detail="Queued to disk and booked in Task Scheduler, so it "
                   "survives a restart. Say “what is claude doing” to check.")
    return Result.fail("Claude Code could not do that.", job.error[:300])


@skill(
    "run_queued_claude",
    "Run any Claude jobs that were waiting for the usage window to reset",
    ["run my queued claude jobs", "retry my claude jobs",
     "resume claude", "run queued claude work"],
    triggers=[r"\b(queued|resume|retry)\b.*\bclaude\b"],
    requires=["claude"],
)
def run_queued_claude(**_) -> Result:
    """What the scheduled wake-up runs. Also safe to run by hand."""
    waiting = claudecode.pending()
    if not waiting:
        return Result(text="Nothing is queued for Claude.")
    finished = claudecode.run_due(on_progress=progress.say)
    if not finished:
        import time
        soonest = min(float(i.get("retry_at") or 0) for i in waiting)
        mins = max(0, int((soonest - time.time()) // 60))
        return Result(text=f"{len(waiting)} job(s) still waiting — the window "
                           f"resets in about {mins} minutes.")
    done = [j for j in finished if j.ok]
    lines = [f"Ran {len(finished)} queued job(s), {len(done)} succeeded.", ""]
    for job in finished:
        head = job.answer if job.ok else (job.error or "failed")
        lines.append(f"• {job.prompt[:70]}\n  {' '.join(head.split())[:220]}")
    return Result(text="\n".join(lines))


def _resolve_project(name: str) -> str:
    """Turn a project name into a folder, using what memory already knows.

    The projects were read once by `vb.projects`, so "ServManager" resolves
    without a disk search — which also means Claude is pointed at the folder
    the user means rather than wherever the buddy happens to be standing.
    """
    name = (name or "").strip()
    if not name:
        return ""
    candidate = Path(name)
    if candidate.is_dir():
        return str(candidate)
    from vb import memory, projects
    known = [(projects._folder_of(n.text))
             for n in memory.recent(limit=500, kind=projects.TAG)]
    known = [f for f in known if f]
    wanted = name.lower()
    for folder in known:                       # exact name first
        if folder.name.lower() == wanted:
            return str(folder)
    for folder in known:                       # then a partial one
        if wanted in folder.name.lower():
            return str(folder)
    return ""
