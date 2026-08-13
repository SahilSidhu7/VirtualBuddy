"""The bit in the middle: prompt in, skill run, answer out.

Manual mode proposes the top match and waits for a yes. Auto mode runs it when
the router is confident enough. Dangerous skills always ask, in either mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from vb import config
from vb.registry import Result
from vb.router import AUTO_THRESHOLD, Match, Router


@dataclass
class Turn:
    """One exchange. `pending` is set when we need the user to confirm."""
    prompt: str
    matches: list[Match] = field(default_factory=list)
    result: Result | None = None
    pending: Match | None = None

    @property
    def needs_confirm(self) -> bool:
        return self.pending is not None

    def describe(self) -> str:
        if not self.pending:
            return ""
        args = ", ".join(f"{k}={v!r}" for k, v in self.pending.slots.items() if v)
        return f"{self.pending.skill.name}({args})"


class Agent:
    def __init__(self, router: Router | None = None):
        self.router = router or Router()
        self.last: Turn | None = None

    # -- routing ---------------------------------------------------------
    def handle(self, prompt: str) -> Turn:
        turn = Turn(prompt=prompt, matches=self.router.rank(prompt, top=3))
        if not turn.matches:
            turn.result = Result.fail(
                "I don't have a skill for that yet.",
                "Try: search the web for …, research …, open chrome")
            self.last = turn
            return turn

        top = turn.matches[0]
        auto = config.get("mode") == "auto" and top.score >= AUTO_THRESHOLD
        if auto and not top.skill.danger:
            turn.result = self.run(top)
        else:
            turn.pending = top
        self.last = turn
        return turn

    # -- execution -------------------------------------------------------
    def run(self, match: Match) -> Result:
        try:
            out = match.skill.run(**match.slots)
        except TypeError as exc:           # slot names out of step with the function
            return Result.fail(f"{match.skill.name} couldn't accept those arguments.",
                               str(exc))
        except Exception as exc:
            return Result.fail(f"{match.skill.name} failed.", f"{type(exc).__name__}: {exc}")
        return out if isinstance(out, Result) else Result(text=str(out))

    def confirm(self, turn: Turn | None = None, choice: int = 0) -> Result:
        """Run the pending match (or the nth alternative the UI offered)."""
        turn = turn or self.last
        if not turn or not turn.matches:
            return Result.fail("Nothing to run.")
        match = turn.matches[min(choice, len(turn.matches) - 1)]
        turn.pending = None
        turn.result = self.run(match)
        return turn.result
