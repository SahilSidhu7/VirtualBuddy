"""A personal to-do list, kept in the user's data folder.

Plain JSON on purpose: the list is small, the user can open it in any editor,
and it survives reinstalling the app.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

from vb import config
from vb.registry import Result, skill

STORE = config.HOME / "tasks.json"

ADD_VERBS = ("add", "remind", "note", "task", "todo", "remember")
DONE_VERBS = ("done", "finish", "finished", "complete", "completed", "tick", "check")


def _load() -> list[dict]:
    try:
        return json.loads(STORE.read_text("utf-8"))
    except Exception:
        return []


def _save(tasks: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(tasks, indent=2), "utf-8")


def _parse_due(text: str) -> tuple[str, str]:
    """Split "buy milk tomorrow" into ("buy milk", "2026-08-14")."""
    today = date.today()
    patterns = [
        (r"\btoday\b", lambda _m: today),
        (r"\btomorrow\b", lambda _m: today + timedelta(days=1)),
        (r"\bin (\d+) days?\b", lambda m: today + timedelta(days=int(m.group(1)))),
        (r"\bnext week\b", lambda _m: today + timedelta(days=7)),
        (r"\bon (\d{4}-\d{2}-\d{2})\b",
         lambda m: datetime.strptime(m.group(1), "%Y-%m-%d").date()),
    ]
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"]
    for i, day in enumerate(weekdays):
        patterns.append((rf"\b(?:on |next )?{day}\b",
                         lambda _m, i=i: today + timedelta(
                             days=(i - today.weekday()) % 7 or 7)))
    for pattern, resolve in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            due = resolve(m)
            return (text[: m.start()] + text[m.end():]).strip(" ,."), due.isoformat()
    return text.strip(" ,."), ""


LEAD_ADD = re.compile(
    r"^\s*(?:hey\s+|buddy\s+)?(?:please\s+)?"
    r"(?:remind me to|remind me|jot down|note down|write down|make a note of|"
    r"add a task|add task|add|note|put|remember to|remember|todo)\s+", re.I)
LEAD_DONE = re.compile(
    r"^\s*(?:i\s+(?:just\s+)?(?:finished|did|completed|am done with)|"
    r"mark(?: off)?|tick(?: off)?|cross(?: off)?|complete|completed|finish|"
    r"finished|done with|done)\s+", re.I)
TAIL_LIST = re.compile(
    r"\s*(?:to|on|in)?\s*(?:my\s+)?(?:to-?\s?do|task)\s*(?:list)?\s*$", re.I)


def _clean(text: str, which: str = "add") -> str:
    """Strip the command wrapper, keep the user's own words.

    Filler-stripping is wrong here: a task is text the user will read back
    later, and "pick up parcel" must not become "pick parcel".
    """
    body = TAIL_LIST.sub("", text.strip())
    body = (LEAD_ADD if which == "add" else LEAD_DONE).sub("", body)
    body = re.sub(r"^\s*(?:a\s+task\s+|task\s+|that\s+|as\s+done\s+)", "", body, flags=re.I)
    return re.sub(r"\s*(?:as\s+)?done\s*$", "", body, flags=re.I).strip(" ,.")


def _due_label(due: str) -> str:
    if not due:
        return ""
    left = (date.fromisoformat(due) - date.today()).days
    if left < 0:
        return f"overdue by {-left}d"
    return {0: "today", 1: "tomorrow"}.get(left, f"in {left}d")


@skill(
    "add_task",
    "Add something to my to-do list",
    ["add buy milk to my todo list", "remind me to call the dentist tomorrow",
     "note down finish the report by friday", "add a task pay rent",
     "jot down pick up the parcel on saturday", "put buy bread on my list"],
    slots=lambda t: dict(zip(("text", "due"), _parse_due(_clean(t, "add")))),
    tags=["tasks"],
    triggers=[r"\bremind me\b", r"\bjot down\b", r"\bnote down\b",
              r"\b(add|put)\b.{0,30}\b(todo|to-do|to do|task|list)\b",
              r"\badd a task\b"],
)
def add_task(text: str = "", due: str = "", **_) -> Result:
    if not text:
        return Result.fail("Add what?", "Try: remind me to call the dentist tomorrow")
    tasks = _load()
    tasks.append({"text": text, "due": due, "done": False, "created": time.time()})
    _save(tasks)
    when = f" ({_due_label(due)})" if due else ""
    open_count = sum(1 for t in tasks if not t["done"])
    return Result(text=f"Added: {text}{when}", detail=f"{open_count} open tasks.")


@skill(
    "list_tasks",
    "Show my to-do list",
    ["what's on my todo list", "show my tasks", "what do i need to do",
     "list my todos", "what's due today", "what's left for me to do today",
     "anything on my list"],
    tags=["tasks"],
    triggers=[r"\b(todo|to-do|to do)\b", r"\bmy (tasks|list)\b",
              r"\bwhat (do i|have i got|'?s left)\b.{0,20}\bdo\b", r"\bwhat'?s due\b"],
)
def list_tasks(**_) -> Result:
    tasks = _load()
    open_tasks = [t for t in tasks if not t["done"]]
    if not open_tasks:
        return Result(text="Nothing on your list.",
                      detail="Add one: remind me to call the dentist tomorrow")

    def sort_key(t):
        return (t["due"] or "9999-99-99", t["created"])

    lines = []
    for i, t in enumerate(sorted(open_tasks, key=sort_key), 1):
        label = _due_label(t["due"])
        lines.append(f"  {i}. {t['text']}" + (f"   ·  {label}" if label else ""))
    done_today = sum(1 for t in tasks
                     if t["done"] and t.get("done_at", 0) > time.time() - 86400)
    tail = f"{done_today} finished in the last day." if done_today else ""
    return Result(text=f"{len(open_tasks)} open:\n" + "\n".join(lines), detail=tail,
                  data=open_tasks)


@skill(
    "complete_task",
    "Mark something on my to-do list as done",
    ["mark buy milk as done", "i finished the report", "tick off pay rent",
     "complete task 2", "done with the dentist call", "cross off buy milk"],
    slots=lambda t: {"which": _clean(t, "done")},
    tags=["tasks"],
    triggers=[r"\b(mark|tick|cross)\b.{0,24}\b(done|off|complete)\b",
              r"\bi (just )?(finished|did|completed)\b", r"\bdone with\b"],
)
def complete_task(which: str = "", **_) -> Result:
    tasks = _load()
    open_tasks = [t for t in tasks if not t["done"]]
    if not open_tasks:
        return Result.fail("Nothing to complete.", "Your list is empty.")
    which = re.sub(r"^(?:off|with|as done|task)\s*", "", (which or "").strip(), flags=re.I)
    which = re.sub(r"\s*(?:as\s+)?done$", "", which, flags=re.I).strip()

    target = None
    if which.isdigit():
        ordered = sorted(open_tasks, key=lambda t: (t["due"] or "9999", t["created"]))
        idx = int(which) - 1
        if 0 <= idx < len(ordered):
            target = ordered[idx]
    if target is None and which:
        from vb import textvec
        sims = textvec.similarity(textvec.encode([t["text"] for t in open_tasks]),
                                  textvec.encode(which)[0])
        best = max(range(len(open_tasks)), key=lambda i: sims[i])
        if sims[best] > 0.35:
            target = open_tasks[best]
    if target is None:
        return Result.fail(f"Nothing on the list matches “{which}”.",
                           "Ask to see your tasks first.")

    target["done"] = True
    target["done_at"] = time.time()
    _save(tasks)
    left = sum(1 for t in tasks if not t["done"])
    return Result(text=f"Done: {target['text']}", detail=f"{left} left.")


@skill(
    "clear_tasks",
    "Remove finished tasks from the list",
    ["clear my finished tasks", "clean up my todo list",
     "delete completed tasks"],
    danger=True, tags=["tasks"],
)
def clear_tasks(**_) -> Result:
    tasks = _load()
    keep = [t for t in tasks if not t["done"]]
    removed = len(tasks) - len(keep)
    _save(keep)
    return Result(text=f"Cleared {removed} finished task{'s' if removed != 1 else ''}.",
                  detail=f"{len(keep)} still open.")
