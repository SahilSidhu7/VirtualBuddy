"""Scheduling work for later, and reading back what came in.

These are ordinary skills, so the agent can reach them as tools and the user
can reach them by typing. Creating a job is marked dangerous: something that
will run on its own, repeatedly, when nobody is watching, is worth one
confirmation even in auto mode.
"""
from __future__ import annotations

import re

from vb import schedule
from vb.registry import Result, skill

TIME = re.compile(r"\b(?:at\s+)?([01]?\d|2[0-3])[:.]([0-5]\d)\s*(am|pm)?\b", re.I)
EVERY_HOURS = re.compile(r"\bevery\s+(\d+)\s*hours?\b", re.I)


def _slots(text: str) -> dict:
    out: dict[str, str] = {}
    hours = EVERY_HOURS.search(text)
    if hours:
        out["hourly"] = hours.group(1)
    clock = TIME.search(text)
    if clock and not hours:
        hour = int(clock.group(1))
        if (clock.group(3) or "").lower() == "pm" and hour < 12:
            hour += 12
        out["daily"] = f"{hour:02d}:{clock.group(2)}"
    return out


@skill(
    "schedule_task",
    "Run something automatically at a set time, every day or every few hours",
    ["schedule", "every morning at 9", "run this daily", "remind me every 2 hours",
     "do this every day at", "set up a recurring job", "run it automatically"],
    slots=_slots, danger=True, tags=["agenda"],
    triggers=[r"\bschedul", r"\bevery (day|morning|\d+ hours?)\b", r"\brecurring\b"],
)
def schedule_task(what: str, name: str = "", daily: str = "",
                  hourly: str = "") -> Result:
    """Schedule a request to run on its own. `what` is the request, `daily` is
    a time like 09:00, `hourly` is a number of hours between runs."""
    if not what.strip():
        return Result.fail("What should it do?")
    ok, message = schedule.schedule(
        name or what[:40], what, daily=daily,
        hourly=int(hourly) if str(hourly).isdigit() else 0)
    if not ok:
        return Result.fail(message)
    return Result(text=message, detail="Anything needing approval will be "
                                       "skipped, since nobody is there to ask.")


@skill(
    "list_scheduled",
    "Show what is set to run automatically",
    ["what is scheduled", "list my scheduled jobs", "show recurring tasks",
     "what runs automatically"],
    tags=["agenda"],
)
def list_scheduled() -> Result:
    """List every job VirtualBuddy has scheduled."""
    jobs = schedule.jobs()
    if not jobs:
        return Result(text="Nothing is scheduled.")
    lines = [f"  {j.name}  ·  next {j.next_run or 'unknown'}" for j in jobs]
    return Result(text=f"{len(jobs)} scheduled:\n" + "\n".join(lines))


@skill(
    "cancel_scheduled",
    "Stop something from running automatically",
    ["cancel the scheduled", "stop running that daily", "unschedule",
     "remove the recurring job"],
    danger=True, tags=["agenda"],
)
def cancel_scheduled(name: str) -> Result:
    """Remove a scheduled job by name."""
    ok, message = schedule.unschedule(name)
    return Result(ok=ok, text=message)


@skill(
    "check_inbox",
    "Show results from jobs that ran while you were away",
    ["what did you do while i was out", "check the inbox", "any results",
     "what came in", "show background results"],
    tags=["agenda"],
)
def check_inbox() -> Result:
    """Read results left by scheduled runs."""
    rows = schedule.unread()
    if not rows:
        return Result(text="Nothing new.")
    parts = []
    for row in rows[-6:]:
        mark = "" if row.get("ok") else "! "
        parts.append(f"{mark}{row['at']} — {row['request']}\n{row['answer']}")
    schedule.mark_all_read()
    return Result(text=f"{len(rows)} result(s):\n\n" + "\n\n".join(parts))
