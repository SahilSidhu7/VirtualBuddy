"""Driving Claude Code, and keeping track of it.

Three jobs, and the first one only became possible on 2026-08-18.

**Handing it work.** `claude -p` runs one request headlessly and prints JSON.
Until now this was believed to cost money per call and to refuse when driven
from another process; both were wrong. The account here is `claude_pro` with
`hasExtraUsageEnabled: false`, so there is no overage path at all — the
`total_cost_usd` in the output is a token-value estimate, not a charge, and
usage draws down the plan's rolling five-hour quota instead. The refusals were
a local configuration problem: ~34k tokens of offensive-security agents and
commands loaded into every session and tripped a `[cyber]` safeguard before the
prompt was read. Moved out, the same probe answers normally.

**Knowing what it is doing.** Claude Code writes a JSONL transcript per session
under `~/.claude/projects/<slug>/<session-id>.jsonl`, and it holds everything
worth reporting: the working directory, the model, the timestamps, the titles
it gave itself. Reading those files costs nothing and touches no quota, so the
buddy can answer "what was I doing in ServManager" without waking anything up.

**Waiting for the quota to come back.** The plan limit resets on a rolling
five-hour window. When a job is refused for that reason it is not dead, it is
early: it goes on a queue on disk and runs when the window turns over.

Nothing here is automatic. A local model is free and this is not — not in money
but in a quota the user also wants for themselves — so every job is asked for.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from vb import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_TIMEOUT = 900          # a real coding job is not a chat message
WINDOW_SECONDS = 5 * 3600      # the plan's rolling limit


def claude_path() -> str | None:
    return shutil.which("claude")


def available() -> tuple[bool, str]:
    if not claude_path():
        return False, "Claude Code is not installed (no `claude` on PATH)."
    return True, ""


# --------------------------------------------------------------- the account
def account() -> dict:
    """What plan this is, read from Claude Code's own config.

    Matters because it decides whether handing work to Claude spends money or
    spends quota. `hasExtraUsageEnabled: false` means there is no way to be
    billed past the subscription — requests get limited instead, which is a
    delay rather than an invoice.
    """
    try:
        raw = json.loads((Path.home() / ".claude.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    oauth = raw.get("oauthAccount") or {}
    return {
        "plan": oauth.get("organizationType") or "unknown",
        "billing": oauth.get("billingType") or "unknown",
        "extra_usage": bool(oauth.get("hasExtraUsageEnabled")),
        "email": oauth.get("emailAddress") or "",
    }


def bills_per_token() -> bool:
    """Whether running a job here can cost actual money."""
    return bool(account().get("extra_usage"))


# ------------------------------------------------------------- rate limiting
# What being out of quota looks like in the CLI's output. Matched against the
# result text, which is where the CLI puts it — there is no machine-readable
# field for it and nothing is written to disk, so this is the only signal
# available.
#
# **Unverified against a real limit.** Hitting one deliberately costs the
# user's whole window, so these come from the documented wording rather than
# from an observed failure here. `_reset_at` therefore always has a fallback:
# an unparsed reset time means "try again at the end of a fresh five-hour
# window", which is late rather than wrong, and being late merely delays a job
# that is already waiting.
_LIMIT_SIGNS = re.compile(
    r"(rate.?limit|usage limit|limit reached|out of (?:usage|credits)|"
    r"5-hour limit|five.hour limit|too many requests|429)", re.I)
# "resets 3pm", "resets at 15:00", "try again at 3:04pm"
_RESET_CLOCK = re.compile(
    r"(?:resets?|try again)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def is_limit_error(text: str) -> bool:
    return bool(_LIMIT_SIGNS.search(text or ""))


def reset_at(text: str = "", now: float | None = None) -> float:
    """When the quota should be back, as a timestamp.

    Reads a clock time out of the message when there is one, and otherwise
    assumes a full window from now.
    """
    now = now or time.time()
    found = _RESET_CLOCK.search(text or "")
    if found:
        hour = int(found.group(1))
        minute = int(found.group(2) or 0)
        suffix = (found.group(3) or "").lower()
        if suffix == "pm" and hour < 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            local = time.localtime(now)
            candidate = time.mktime((local.tm_year, local.tm_mon, local.tm_mday,
                                     hour, minute, 0, 0, 0, -1))
            # A reset time that has already passed today means tomorrow.
            if candidate <= now:
                candidate += 86400
            # Never trust a parse that lands beyond one window; a misread hour
            # would otherwise park a job for most of a day.
            if candidate - now <= WINDOW_SECONDS + 600:
                return candidate
    return now + WINDOW_SECONDS


# ------------------------------------------------------------------- running
@dataclass
class Job:
    prompt: str
    cwd: str = ""
    session: str = ""          # resume this session rather than starting one
    ok: bool = False
    answer: str = ""
    error: str = ""
    limited: bool = False      # refused for quota, not for content
    retry_at: float = 0.0
    session_id: str = ""
    seconds: float = 0.0
    cost_estimate: float = 0.0

    def __bool__(self) -> bool:
        return self.ok


def run(prompt: str, cwd: str = "", *, session: str = "",
        timeout: int = DEFAULT_TIMEOUT) -> Job:
    """Hand one request to Claude Code and wait for the answer.

    `cwd` is the repository it should work in, which is most of what makes this
    useful: Claude Code reads the project it is standing in.
    """
    job = Job(prompt=prompt, cwd=cwd, session=session)
    exe = claude_path()
    if not exe:
        job.error = "Claude Code is not installed."
        return job

    command = [exe, "-p", prompt, "--output-format", "json"]
    if session:
        command += ["--resume", session]

    started = time.time()
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            cwd=cwd or None, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW,
            # A nested session is a different thing from a fresh one and the
            # CLI behaves differently inside one. The buddy is not Claude Code,
            # so it should not claim to be its child.
            env={k: v for k, v in os.environ.items()
                 if not k.startswith("CLAUDE")})
    except subprocess.TimeoutExpired:
        job.error = f"Claude Code did not finish within {timeout}s."
        job.seconds = time.time() - started
        return job
    except OSError as exc:
        job.error = f"Could not start Claude Code: {exc}"
        return job

    job.seconds = time.time() - started
    raw = (done.stdout or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        text = raw or (done.stderr or "").strip()
        job.error = text[:600] or "Claude Code returned nothing."
        job.limited = is_limit_error(text)
        if job.limited:
            job.retry_at = reset_at(text)
        return job

    job.session_id = str(data.get("session_id") or "")
    # An estimate, not a charge, unless the account allows overage. Reported
    # rather than hidden so the number is never mistaken for a bill.
    job.cost_estimate = float(data.get("total_cost_usd") or 0.0)
    result = str(data.get("result") or "")
    if data.get("is_error"):
        job.error = result[:600] or f"Claude Code failed ({data.get('stop_reason')})."
        job.limited = is_limit_error(result)
        if job.limited:
            job.retry_at = reset_at(result)
        return job
    job.ok = True
    job.answer = result
    return job


# --------------------------------------------------------------- the backlog
def queue_path() -> Path:
    return config.data_dir() / "claude_queue.json"


def _load_queue() -> list[dict]:
    try:
        return json.loads(queue_path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_queue(items: list[dict]) -> None:
    try:
        queue_path().write_text(json.dumps(items, indent=2), "utf-8")
    except OSError:
        pass


def defer(job: Job) -> dict:
    """Put a rate-limited job on the queue to run when the window resets.

    On disk, not in memory: the whole point is that the wait is longer than the
    buddy's uptime is guaranteed to be, and a job that evaporates when the
    machine sleeps is worse than one that was never queued.
    """
    item = {
        "prompt": job.prompt,
        "cwd": job.cwd,
        "session": job.session or job.session_id,
        "queued_at": time.time(),
        "retry_at": job.retry_at or (time.time() + WINDOW_SECONDS),
        "tries": 0,
    }
    items = _load_queue()
    items.append(item)
    _save_queue(items)
    _wake_at(item["retry_at"])
    return item


RESUME_TASK = "claude-resume"
RESUME_REQUEST = "run my queued claude jobs"


def _wake_at(when: float) -> bool:
    """Book a real Windows task for when the window turns over.

    Not a timer in this process. The wait is up to five hours, and over five
    hours the buddy may well be closed, the machine asleep or logged out —
    an in-memory `threading.Timer` would quietly lose the job in every one of
    those cases, which is the failure the queue exists to prevent. The Task
    Scheduler survives all three.
    """
    from vb import schedule
    stamp = time.localtime(when + 60)          # a minute's grace past the reset
    ok, _why = schedule.schedule(
        RESUME_TASK, RESUME_REQUEST,
        once_at=time.strftime("%Y-%m-%d %H:%M", stamp))
    return ok


def pending() -> list[dict]:
    return _load_queue()


def due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [i for i in _load_queue() if float(i.get("retry_at") or 0) <= now]


def drop(item: dict) -> None:
    items = [i for i in _load_queue()
             if not (i.get("prompt") == item.get("prompt")
                     and i.get("queued_at") == item.get("queued_at"))]
    _save_queue(items)


MAX_TRIES = 4


def run_due(on_progress=None) -> list[Job]:
    """Run everything whose window has come round. Returns what was attempted.

    Called by the scheduler, and safe to call at any time: nothing runs before
    its `retry_at`.
    """
    finished: list[Job] = []
    for item in due():
        if on_progress:
            on_progress(f"Claude: retrying “{item['prompt'][:60]}”…")
        job = run(item["prompt"], item.get("cwd", ""),
                  session=item.get("session", ""))
        finished.append(job)
        if job.ok:
            drop(item)
            continue
        if job.limited and int(item.get("tries", 0)) + 1 < MAX_TRIES:
            # Still out of quota — the window had not really turned over.
            # Pushed back rather than dropped, but not for ever: a job that
            # has been refused four times is not going to succeed by waiting.
            items = _load_queue()
            for existing in items:
                if existing.get("queued_at") == item.get("queued_at"):
                    existing["tries"] = int(existing.get("tries", 0)) + 1
                    existing["retry_at"] = job.retry_at or (time.time() + WINDOW_SECONDS)
            _save_queue(items)
        else:
            drop(item)
    return finished


# ------------------------------------------------------------ what it's doing
@dataclass
class Session:
    id: str
    project: str
    cwd: str
    title: str
    model: str
    messages: int
    started: float
    updated: float
    path: Path = field(default_factory=Path)

    def age(self) -> str:
        hours = (time.time() - self.updated) / 3600
        if hours < 1:
            return f"{int(hours * 60)} minutes ago"
        if hours < 24:
            return f"{int(hours)} hours ago"
        return f"{int(hours / 24)} days ago"


def projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _read_session(path: Path) -> Session | None:
    """Summarise one transcript without holding it in memory.

    These files reach several megabytes — this session's own is 2.6MB — so it
    is read a line at a time and only the handful of fields that matter are
    kept. Loading them whole to count messages would be the single most
    wasteful thing in the codebase.
    """
    cwd = title = model = ""
    started = updated = 0.0
    messages = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = row.get("type")
                if kind in ("user", "assistant"):
                    messages += 1
                cwd = row.get("cwd") or cwd
                # The CLI names its own sessions; the newest name is the one
                # that describes what it ended up being about.
                if kind == "ai-title":
                    title = row.get("aiTitle") or title
                message = row.get("message")
                if isinstance(message, dict):
                    model = message.get("model") or model
                stamp = _parse_time(row.get("timestamp"))
                if stamp:
                    started = started or stamp
                    updated = max(updated, stamp)
    except OSError:
        return None
    if not messages:
        return None
    return Session(id=path.stem, project=path.parent.name, cwd=cwd,
                   title=title or "(untitled)", model=model, messages=messages,
                   started=started, updated=updated or path.stat().st_mtime,
                   path=path)


def _parse_time(value) -> float:
    if not value or not isinstance(value, str):
        return 0.0
    try:
        import datetime
        return datetime.datetime.fromisoformat(
            value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sessions(limit: int = 10, since_days: float = 14.0) -> list[Session]:
    """Recent Claude Code sessions, newest first.

    Filtered by the file's modification time before anything is opened, so an
    old project with a hundred megabytes of transcripts costs one `stat` rather
    than a hundred megabytes of reading.
    """
    root = projects_dir()
    if not root.is_dir():
        return []
    cutoff = time.time() - since_days * 86400
    candidates = []
    for path in root.glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime >= cutoff:
                candidates.append(path)
        except OSError:
            continue
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in candidates:
        if len(out) >= limit:
            break
        found = _read_session(path)
        if found and not _throwaway(found):
            out.append(found)
    return out


def _throwaway(session: "Session") -> bool:
    """A one-shot probe rather than a piece of work.

    The test is the pair, not the directory. Filtering on temp paths was the
    first attempt and it missed the probes run from inside a real repository,
    which then filled the list. But Claude Code names any session that went
    anywhere, so *no title* and *one exchange* together mean nothing happened —
    and either alone is innocent: a titled two-message session is a quick
    question worth remembering, and a long untitled one is work in progress.
    """
    return session.messages <= 2 and session.title == "(untitled)"


def status() -> str:
    """One block describing the whole picture, for `/claude` and the panel."""
    ready, why = available()
    if not ready:
        return why
    acct = account()
    lines = [f"Claude Code · {acct.get('plan', '?')} plan"
             + (" · overage ENABLED, calls can cost money"
                if acct.get("extra_usage")
                else " · no overage, calls use plan quota only")]
    waiting = pending()
    if waiting:
        soonest = min(float(i.get("retry_at") or 0) for i in waiting)
        wait = max(0, soonest - time.time())
        lines.append(f"{len(waiting)} job(s) waiting for the window to reset, "
                     f"next in {int(wait // 60)} min")
    recent = sessions(limit=5)
    if recent:
        lines.append("")
        lines.append("Recent sessions:")
        for s in recent:
            lines.append(f"  {s.title[:58]}")
            lines.append(f"    {Path(s.cwd).name or s.project} · "
                         f"{s.messages} messages · {s.age()}")
    return "\n".join(lines)
