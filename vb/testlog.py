"""The testing log: what you asked, what it said, and what went wrong.

This is the record for *people*. `traces.jsonl` next door is the record for a
fine-tune, and the two want different things badly enough that sharing one file
was a mistake worth not making:

* **Traces only hold what the model decided.** A request that the router
  matched to a single skill never reaches the model at all — the skill is
  picked by cosine similarity — and writing those into the training set would
  teach the model to emit tool calls it never reasoned about. That is the same
  class of error as recording harness prose as if the model had written it,
  which poisoned 77% of the first dataset. So the fast path is recorded *here*
  and deliberately not there.
* **A person wants the answer they saw**, not the cleaned-up version the
  trainer stores, and wants failures findable rather than mixed in with several
  hundred synthetic harvester runs.

So every answered request lands in `interactions.jsonl`, whichever path it took,
and `report()` renders it as markdown you can read or send to someone.

Two decisions worth stating, because they are what make the report usable:

* **Only real front ends.** Anything without a `source` came from a script.
* **Failures are never the thing that gets trimmed.** When a report has to be
  shortened it keeps the failures, because a session is interesting exactly
  where it went wrong.

Nothing here leaves the machine on its own. It writes a file and says where.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from vb import config, traces

# Per step, in the report. Enough to see what ran and what came back, short
# enough that fifty of them stay readable.
STEP_ARGS = 300
STEP_OUTPUT = 400
ANSWER = 1500
MAX_ROWS = 2000            # oldest are dropped past this; a log, not an archive


def path() -> Path:
    return config.data_dir() / "interactions.jsonl"


def report_path() -> Path:
    return config.data_dir() / "testlog.md"


def enabled() -> bool:
    return bool(config.get("collect_traces", True))


# ------------------------------------------------------------------ writing
def _append(row: dict) -> bool:
    try:
        with path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        return False
    return True


def _base(question: str, route: str) -> dict:
    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": traces.source(),
        "model": config.get("llm_model") or "",
        "question": question,
        # "skill" when the router answered it outright, "agent" when the model
        # worked through it in steps. Which one handled a request is usually
        # the first thing worth knowing when it answered badly.
        "route": route,
        # The critic's opinion, and the person's. They are kept apart on
        # purpose: the critic passed every answer in a run where an independent
        # checker found a third of them factually wrong, so it is a hint and
        # `user` is the only label worth trusting.
        "verdict": "",
        "why": "",
        "user": "",
        "user_note": "",
    }


def record_skill(question: str, skill: str, args: dict, result,
                 seconds: float = 0.0) -> bool:
    """A request the router answered with one skill, no model involved."""
    if not enabled() or not question.strip():
        return False
    row = _base(question, "skill")
    row.update({
        "answer": (getattr(result, "text", "") or "")[:ANSWER],
        "ok": bool(getattr(result, "ok", True)),
        "seconds": round(seconds, 1),
        "steps": [{"tool": skill,
                   "args": {k: str(v)[:STEP_ARGS] for k, v in (args or {}).items()},
                   "output": (getattr(result, "text", "") or "")[:STEP_OUTPUT]}],
    })
    detail = (getattr(result, "detail", "") or "").strip()
    if detail:
        # A skill's own footnote, not a judgement — nothing grades the fast
        # path. Kept in its own field so the report does not caption it
        # "Critic:", which read as though something had reviewed the answer
        # when nothing had.
        row["detail"] = detail[:500]
    return _append(row)


def record_outcome(outcome) -> bool:
    """A request the agent loop worked through in steps."""
    if not enabled() or not (outcome.request or "").strip():
        return False
    row = _base(outcome.request, "agent")
    verdict = getattr(outcome, "verdict", None)
    row.update({
        "answer": (outcome.answer or "")[:ANSWER],
        "ok": bool(outcome.ok),
        "seconds": round(outcome.seconds, 1),
        "escalated": bool(outcome.escalated),
        # The harness wrote this answer, the model did not. Worth seeing in a
        # review: it means the model failed to finish and was papered over.
        "rescued": bool(getattr(outcome, "rescued", False)),
        "verdict": "" if verdict is None else ("pass" if verdict.passed else "fail"),
        "why": "" if verdict is None or verdict.passed else verdict.summary,
        "steps": [{"tool": s.tool,
                   "args": {k: str(v)[:STEP_ARGS] for k, v in (s.args or {}).items()},
                   "output": (s.output or "")[:STEP_OUTPUT]}
                  for s in outcome.steps],
    })
    return _append(row)


def mark_last(verdict: str, note: str = "") -> dict | None:
    """Record what the *person* thought of the answer just given.

    Returns the row that was marked, or None when there is nothing to mark.
    Rewrites the file rather than appending a correction, because everything
    that reads this reads whole rows; the write goes via a temporary file so an
    interrupted mark cannot lose the history.
    """
    verdict = (verdict or "").strip().lower()
    if verdict not in ("good", "bad"):
        return None
    # `_read_all`, not `read`: `read` returns only the most recent MAX_ROWS, and
    # this function writes back what it was given. Marking one answer would
    # therefore have deleted every row past the cap — a quiet truncation of the
    # history, triggered by pressing "Yes".
    rows = _read_all()
    if not rows:
        return None

    # The last answer *this front end* gave, not simply the last line in the
    # file. Scheduled jobs write here too, from their own process, and one
    # firing between the answer appearing and the button being pressed would
    # otherwise take the label meant for what is on screen.
    here = traces.source()
    target = None
    for row in reversed(rows):
        if not here or row.get("source") == here:
            target = row
            break
    if target is None:
        return None
    target["user"] = verdict
    target["user_note"] = note.strip()[:500]

    scratch = path().with_suffix(".jsonl.tmp")
    try:
        with scratch.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        scratch.replace(path())
    except OSError:
        return None
    return target


# ------------------------------------------------------------------ reading
def _read_all() -> list[dict]:
    """Every row on disk. Use this when writing the file back."""
    try:
        lines = path().read_text("utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read() -> list[dict]:
    """The recent rows, for reading. Capped so a long-lived log stays cheap."""
    return _read_all()[-MAX_ROWS:]


def clear() -> bool:
    try:
        path().unlink()
        return True
    except OSError:
        return False


def _verdict(row: dict) -> str:
    """One word for how it went, the person's word winning."""
    user = (row.get("user") or "").lower()
    if user == "bad":
        return "wrong"
    if user == "good":
        return "ok"
    if row.get("verdict") == "fail" or not row.get("ok", True):
        return "failed"
    return "ok"


def sessions(limit: int = 0, only_failures: bool = False) -> list[dict]:
    """Recorded interactions, oldest first. `limit` keeps the most recent N."""
    rows = [r for r in read() if r.get("source")]
    if only_failures:
        rows = [r for r in rows if _verdict(r) != "ok"]
    return rows[-limit:] if limit else rows


BADGE = {"ok": "OK", "wrong": "WRONG (you said so)", "failed": "FAILED"}


def report(limit: int = 0, only_failures: bool = False) -> str:
    rows = sessions(limit, only_failures)
    if not rows:
        return ("# VirtualBuddy testing log\n\nNothing recorded yet. Ask the "
                "buddy something first — only questions asked through the app, "
                "the terminal or chat are kept here.\n")

    counts: dict[str, int] = {}
    for row in rows:
        key = _verdict(row)
        counts[key] = counts.get(key, 0) + 1
    marked = sum(1 for r in rows if r.get("user"))

    lines = [
        "# VirtualBuddy testing log",
        "",
        f"Written {time.strftime('%Y-%m-%d %H:%M')}. {len(rows)} "
        + ("interaction" if len(rows) == 1 else "interactions")
        + (" (failures only)" if only_failures else "") + ".",
        "",
        "| verdict | count |",
        "| --- | --- |",
    ]
    for key in ("ok", "wrong", "failed"):
        if counts.get(key):
            lines.append(f"| {BADGE[key]} | {counts[key]} |")
    lines += [
        "",
        f"{marked} of {len(rows)} were judged by hand; the rest carry the "
        "critic's opinion, which is worth less.",
        "",
    ]

    for n, row in enumerate(rows, start=1):
        steps = row.get("steps") or []
        lines += [
            "---",
            "",
            f"## {n}. {row.get('question', '(no question)')}",
            "",
            f"- **{BADGE[_verdict(row)]}** · {row.get('at', '')} · "
            f"{row.get('source', '?')} · {row.get('route', '?')} route · "
            f"{row.get('model', '?')} · {len(steps)} steps · "
            f"{row.get('seconds', '?')}s"
            + (" · escalated" if row.get("escalated") else "")
            + (" · answer written by the harness, not the model"
               if row.get("rescued") else ""),
        ]
        if row.get("user_note"):
            lines.append(f"- **You said:** {row['user_note']}")
        if row.get("why"):
            lines.append(f"- **Critic:** {row['why']}")
        if row.get("detail"):
            lines.append(f"- **Note from the skill:** {row['detail']}")
        if row.get("route") == "skill":
            # Worth saying once per fast-path row: an "OK" here means nobody
            # disagreed, not that anything checked. The critic only runs on the
            # agent loop, so a wrong skill answer arrives unchallenged — which
            # is precisely the case this log exists to surface.
            lines.append("- _Fast path: matched by the router, never seen by "
                         "the model, and not graded by the critic._")
        lines.append("")
        if steps:
            lines += ["**Steps**", ""]
            for i, step in enumerate(steps, start=1):
                args = ", ".join(f"{k}={v}" for k, v in (step.get("args") or {}).items())
                body = (step.get("output") or "").splitlines() or ["(no output)"]
                lines += [f"{i}. `{step.get('tool', '?')}({args})`", "",
                          "   ```", *(f"   {ln}" for ln in body), "   ```", ""]
        lines += ["**Answer**", "", "```",
                  (row.get("answer") or "(no answer)")[:ANSWER], "```", ""]

    return "\n".join(lines)


def write(limit: int = 0, only_failures: bool = False) -> Path:
    target = report_path()
    target.write_text(report(limit, only_failures), "utf-8")
    return target


def summary() -> str:
    """One line for the CLI and the panel."""
    rows = sessions()
    if not rows:
        return "Nothing recorded yet."
    counts: dict[str, int] = {}
    for row in rows:
        key = _verdict(row)
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{counts[k]} {k}" for k in ("ok", "wrong", "failed") if counts.get(k)]
    marked = sum(1 for r in rows if r.get("user"))
    return (f"{len(rows)} interactions — " + ", ".join(parts)
            + f" ({marked} judged by hand)")
