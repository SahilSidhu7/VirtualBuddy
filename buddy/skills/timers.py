"""Timers and reminders — set one, hear about it when it fires.

Timers live in this process, so they end when buddy does; that's the honest
trade for having no background service. Buddy says so when you set a long one.
"""
import re, threading, time, datetime

from buddy import slots, voice

_timers = []              # [{"id", "label", "due", "timer"}]
_next_id = [1]
_lock = threading.Lock()

_UNITS = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hour": 3600, "hr": 3600}


# people say "an hour" far more often than "1 hour"
_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
             "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50,
             "sixty": 60, "ninety": 90, "couple of": 2, "couple": 2, "few": 3}

_UNIT_RE = r"(sec|second|min|minute|hour|hr)s?"


def _parse_when(text):
    """Seconds from now. Handles '5 minutes', 'an hour', 'half an hour', 'at 7:30 pm'."""
    t = text.lower()
    total = 0
    for n, unit in re.findall(rf"(\d+)\s*{_UNIT_RE}\b", t):
        total += int(n) * _UNITS[unit]
    if not total and re.search(rf"half an?\s+{_UNIT_RE}\b", t):
        unit = re.search(rf"half an?\s+{_UNIT_RE}\b", t).group(1)
        total = _UNITS[unit] // 2
    if not total:
        words = "|".join(sorted(_WORD_NUM, key=len, reverse=True))
        for n, unit in re.findall(rf"\b({words})\s+{_UNIT_RE}\b", t):
            total += _WORD_NUM[n] * _UNITS[unit]
    if total:
        return total
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        now = datetime.datetime.now()
        due = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += datetime.timedelta(days=1)
        return int((due - now).total_seconds())
    return None


def _label(text):
    q = slots.quoted(text)
    if q:
        return q
    m = re.search(r"\b(?:to|about|that)\s+(.+?)(?:\s+in\s+\d|\s+at\s+\d|$)", text, re.I)
    if m:
        return m.group(1).strip(" .?!")
    m = re.search(r"\breminder\s+(?:for\s+)?(.+?)(?:\s+in\s+\d|\s+at\s+\d|$)", text, re.I)
    return m.group(1).strip(" .?!") if m else None


def _pretty(secs):
    if secs < 60:
        return f"{secs} seconds"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m} minute{'s' if m != 1 else ''}" + (f" {s}s" if s else "")


def _fire(tid, label, cfg):
    with _lock:
        entry = next((t for t in _timers if t["id"] == tid), None)
        if entry:
            _timers.remove(entry)
    msg = f"Time's up: {label}" if label else "Time's up."
    print(f"\n[buddy] ⏰ {msg}")
    try:
        voice.say(msg, True)                # always speak a timer, even if replies are muted
    except Exception:
        pass
    _notify(msg)


def _notify(msg):
    """Best-effort desktop notification; silent if the OS won't play along."""
    try:
        import os
        if os.name != "nt":
            return
        import ctypes
        ctypes.windll.user32.MessageBeep(0)
    except Exception:
        pass


def set_timer(text, ctx):
    secs = _parse_when(text)
    if not secs:
        return "How long? Try \"remind me in 10 minutes\" or \"set a timer for 5 minutes\"."
    label = _label(text)
    with _lock:
        tid = _next_id[0]
        _next_id[0] += 1
        t = threading.Timer(secs, _fire, args=(tid, label, ctx["cfg"]))
        t.daemon = True
        t.start()
        _timers.append({"id": tid, "label": label or "timer", "due": time.time() + secs,
                        "timer": t})
    when = datetime.datetime.now() + datetime.timedelta(seconds=secs)
    tail = "" if secs < 3600 else " (I need to stay running for it to fire.)"
    if label:
        return f"Reminder #{tid} set for {_pretty(secs)} from now ({when:%I:%M %p}): {label}.{tail}"
    return f"Timer #{tid} set for {_pretty(secs)} ({when:%I:%M %p}).{tail}"


def list_timers(text, ctx):
    with _lock:
        live = [t for t in _timers if t["due"] > time.time()]
    if not live:
        return "No timers running."
    lines = ["Timers:"]
    for t in sorted(live, key=lambda x: x["due"]):
        lines.append(f"  #{t['id']} {t['label']} — {_pretty(int(t['due'] - time.time()))} left")
    return "\n".join(lines)


def cancel_timer(text, ctx):
    n = slots.number(text)
    with _lock:
        if not _timers:
            return "No timers to cancel."
        targets = [t for t in _timers if n is None or t["id"] == n]
        if not targets:
            return f"No timer #{n}."
        for t in targets:
            t["timer"].cancel()
            _timers.remove(t)
    return f"Cancelled {len(targets)} timer{'s' if len(targets) > 1 else ''}."


SKILLS = [
    {"name": "set_timer", "desc": "set a timer or reminder",
     "phrases": ["set a timer for 5 minutes", "remind me in 10 minutes to stretch",
                 "wake me in an hour", "timer for 30 seconds",
                 "remind me at 7 pm to call mum", "set a 20 minute timer"],
     "run": set_timer},
    {"name": "list_timers", "desc": "what timers are running",
     "phrases": ["what timers do i have", "list my reminders", "how long left on my timer",
                 "any timers running"],
     "run": list_timers},
    {"name": "cancel_timer", "desc": "cancel a timer",
     "phrases": ["cancel my timer", "stop the timer", "cancel timer 2",
                 "forget that reminder", "clear all timers"],
     "run": cancel_timer},
]
