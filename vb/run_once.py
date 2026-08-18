"""One request, no window, no user. What a scheduled job actually runs.

    python -m vb.run_once "check my downloads folder and tell me what is new"

The result goes to the inbox rather than a terminal nobody is watching. Every
approval is declined, because declining is the only honest answer when there is
no one there to ask: the run reports what it skipped instead of hanging on a
prompt until the Task Scheduler kills it.
"""
from __future__ import annotations

import sys

from vb import loop, progress, schedule, traces
from vb.registry import load_all


def _declined(tool: str, args: dict, reason: str) -> bool:
    """Nobody is at the keyboard, so nothing irreversible happens."""
    progress.say(f"Skipped {tool}: {reason} and there is nobody to ask.")
    return False


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    request = " ".join(argv).strip()
    if not request:
        print("usage: python -m vb.run_once \"what to do\"")
        return 2

    traces.set_source("scheduled")
    load_all()
    ready, why = loop.available()
    if not ready:
        schedule.deliver(request, f"Could not run: {why}", ok=False)
        return 1

    outcome = loop.run(request, approve=_declined)
    schedule.deliver(request, outcome.answer or "No answer.",
                     ok=bool(outcome.ok and outcome.answer))
    print(outcome.answer or "(no answer)")
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
