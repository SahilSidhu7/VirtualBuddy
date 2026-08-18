"""Work that happens without being asked.

Hermes runs continuously and delivers results to wherever you are. The desktop
equivalent on Windows is the Task Scheduler, which is already running, already
survives reboots, and already has a UI the user can inspect and cancel from —
three things a background thread in a Tk app does not have.

So a scheduled job here is a real `schtasks` entry that runs

    python -m vb.run_once "<the request>"

at the chosen time. The answer is appended to `inbox.jsonl` and shown next time
the panel opens. Nothing is hidden: the jobs are visible in Task Scheduler
under the `VirtualBuddy\\` folder, and `unschedule` removes them properly.

Everything irreversible in a scheduled run is declined rather than queued —
there is nobody at the keyboard to approve it, and a job that silently waits
for an approval that will never come is worse than one that says what it
skipped.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from vb import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FOLDER = "VirtualBuddy"
PREFIX = "VB_"
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def inbox_path() -> Path:
    return config.data_dir() / "inbox.jsonl"


def repo_root() -> Path:
    """The folder containing the `vb` package."""
    return Path(__file__).resolve().parent.parent


def _runner() -> str:
    """The command line that runs one request, quoted and ready for /TR.

    The subtlety that made every scheduled job fail silently: the Task
    Scheduler starts a task in `%SystemRoot%\\system32`, and there is no
    working-directory option on the `schtasks` command line — Start-in needs
    XML or COM. VirtualBuddy is run from a checkout, not installed, so `python
    -m vb.run_once` from system32 dies on `ModuleNotFoundError: No module named
    'vb'` before it can reach the code that would have reported the failure.
    The task looked healthy and the inbox stayed empty forever.

    So the command changes directory first. `cmd /c cd /d <repo> && python -m
    vb.run_once ...` runs where the package actually is.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --once'
    return f'cmd /c cd /d "{repo_root()}" && "{sys.executable}" -m vb.run_once'


@dataclass
class Job:
    name: str
    request: str
    when: str = ""       # what schtasks reports as Status, e.g. "Ready"
    next_run: str = ""


def _task_name(name: str) -> str:
    return f"\\{FOLDER}\\{PREFIX}{SAFE_NAME.sub('_', name)[:60]}"


def schedule(name: str, request: str, *, daily: str = "", hourly: int = 0,
             once_at: str = "") -> tuple[bool, str]:
    """Register a repeating job. Returns (ok, message).

    One of `daily` ("09:00"), `hourly` (every N hours) or `once_at`
    ("2026-08-16 14:30").
    """
    if sys.platform != "win32":
        return False, "Scheduling is Windows-only for now."
    if not request.strip():
        return False, "A scheduled job needs something to do."

    if daily:
        timing = ["/SC", "DAILY", "/ST", daily]
    elif hourly:
        timing = ["/SC", "HOURLY", "/MO", str(max(1, int(hourly)))]
    elif once_at:
        try:
            date_part, time_part = once_at.split()
        except ValueError:
            return False, 'once_at looks like "2026-08-16 14:30".'
        timing = ["/SC", "ONCE", "/SD", date_part, "/ST", time_part]
    else:
        return False, "Say when: daily, hourly, or once_at."

    # schtasks re-parses /TR, so a request containing a double quote would end
    # the command early. Single quotes read the same to a person and cannot.
    command = _runner()
    safe_request = request.replace('"', "'")
    argv = ["schtasks", "/Create", "/F", "/TN", _task_name(name),
            "/TR", f'{command} "{safe_request}"', *timing]
    ok, message = _run_schtasks(argv)
    if ok:
        return True, f"Scheduled “{name}”. It is in Task Scheduler under {FOLDER}."

    # `/SD` is parsed in the machine's own short-date format, not ISO. On this
    # locale it wants dd/mm/yyyy and answers an ISO date with
    # `ERROR: Invalid Start Date (Date should be in "dd/mm/yyyy" format)`, so
    # every one-off job failed here while daily and hourly ones — which take no
    # date at all — worked, which is why it went unnoticed.
    #
    # The format is read back out of the refusal rather than guessed from the
    # locale: schtasks states what it wants, and believing it is more reliable
    # than deriving the same string from `GetLocaleInfo` and hoping they agree.
    if once_at and "start date" in message.lower():
        retry = _redate(argv, once_at, message)
        if retry:
            ok, message = _run_schtasks(retry)
            if ok:
                return True, (f"Scheduled “{name}”. It is in Task Scheduler "
                              f"under {FOLDER}.")
    return False, message


def _run_schtasks(argv: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not reach the Task Scheduler: {exc}"
    if done.returncode != 0:
        return False, (done.stderr or done.stdout
                       or "schtasks refused it.").strip()[:200]
    return True, ""


# The format schtasks names in its own error, e.g. dd/mm/yyyy or MM/dd/yyyy.
_WANTED_FORMAT = re.compile(r'"([dDmMyY/\-.]{8,10})"')


def _redate(argv: list[str], once_at: str, complaint: str) -> list[str] | None:
    """The same command with the date written the way schtasks asked for."""
    found = _WANTED_FORMAT.search(complaint)
    if not found:
        return None
    pattern = found.group(1)
    try:
        when = time.strptime(once_at, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    # Only the field order varies; the separator comes along with the pattern.
    formatted = (pattern.replace("dd", f"{when.tm_mday:02d}")
                        .replace("MM", f"{when.tm_mon:02d}")
                        .replace("mm", f"{when.tm_mon:02d}")
                        .replace("yyyy", str(when.tm_year)))
    if not formatted or any(c.isalpha() for c in formatted):
        return None
    out = list(argv)
    out[out.index("/SD") + 1] = formatted
    return out


def unschedule(name: str) -> tuple[bool, str]:
    try:
        done = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", _task_name(name)],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if done.returncode != 0:
        return False, f"No scheduled job called “{name}”."
    return True, f"Removed “{name}”."


def jobs() -> list[Job]:
    """Everything currently scheduled, read back from Windows itself."""
    if sys.platform != "win32":
        return []
    try:
        done = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in done.stdout.splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if not parts or f"\\{FOLDER}\\{PREFIX}" not in parts[0]:
            continue
        # Columns are TaskName, Next Run Time, Status. The third is the status,
        # not the schedule — reporting it as `when` showed every job as
        # "Ready", which reads like a schedule and is not one.
        name = parts[0].rsplit(PREFIX, 1)[-1]
        out.append(Job(name=name, request="",
                       when=parts[2] if len(parts) > 2 else "",
                       next_run=parts[1] if len(parts) > 1 else ""))
    return out


# -------------------------------------------------------------------- inbox
def deliver(request: str, answer: str, ok: bool = True) -> None:
    """Leave the result of an unattended run where the user will see it."""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": ok,
           "request": request[:300], "answer": answer[:4000], "read": False}
    try:
        with inbox_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def unread() -> list[dict]:
    try:
        lines = inbox_path().read_text("utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("read"):
            out.append(row)
    return out


def mark_all_read() -> None:
    try:
        lines = inbox_path().read_text("utf-8").splitlines()
    except OSError:
        return
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row["read"] = True
        rows.append(json.dumps(row))
    try:
        inbox_path().write_text("\n".join(rows) + ("\n" if rows else ""), "utf-8")
    except OSError:
        pass
