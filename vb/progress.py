"""Telling the user what is happening while a skill runs.

A skill calls `progress.say("Reading rtings.com (2 of 4)")` and whatever is
driving it decides how to show that: the panel writes it under the working
line, the terminal prints it. Nothing has to be threaded through function
signatures, because the sink is a context variable set by whoever started the
run.

Skills should report before a slow step, not after it. The point is the ten
seconds where the user is wondering whether it has hung.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Callable

_sink: contextvars.ContextVar[Callable[[str], None] | None] = \
    contextvars.ContextVar("vb_progress_sink", default=None)


def say(message: str) -> None:
    """Report a step. Silently does nothing when nobody is listening."""
    sink = _sink.get()
    if sink:
        try:
            sink(message)
        except Exception:
            pass          # a broken display must never break the skill


@contextmanager
def listening(sink: Callable[[str], None] | None):
    """Route progress from this block to `sink`."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def counter(prefix: str, total: int) -> Callable[[int, str], None]:
    """Helper for "3 of 7" style reporting."""
    def report(done: int, detail: str = "") -> None:
        say(f"{prefix} {done} of {total}{': ' + detail if detail else ''}")
    return report
