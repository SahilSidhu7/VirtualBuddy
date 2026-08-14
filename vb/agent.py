"""The bit in the middle: prompt in, skill run, answer out.

Manual mode proposes the top match and waits for a yes. Auto mode runs it when
the router is confident enough. Dangerous skills always ask, in either mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import re

from vb import config, planner, progress
from vb.planner import Plan
from vb.registry import Result
from vb.router import AUTO_THRESHOLD, Match, Router

# Below this, a single skill is a guess rather than a match, and the planner
# gets a look instead.
PLAN_THRESHOLD = 0.45
STRONG_MATCH = 0.80       # above this, one skill clearly covers it

# "do X and then Y": one sentence, two jobs. The verb list has to be generous,
# because "open browser and start applying to jobs" is two jobs and the second
# verb is "start".
SECOND_VERB = (r"open|search|research|add|create|read|find|show|list|kill|start|"
               r"apply|applying|begin|send|write|save|download|install|play|"
               r"check|remind|delete|close|make|index|scan|summari[sz]e|tell")
MULTI_STEP = re.compile(
    rf"\b(and then|then also|after that|and also)\b"
    rf"|\band\b\s+(?:{SECOND_VERB})\b"
    rf"|,\s*(?:then\s+)?(?:{SECOND_VERB})\b", re.I)


def _looks_multi_step(prompt: str) -> bool:
    return bool(MULTI_STEP.search(prompt))


@dataclass
class Turn:
    """One exchange. `pending` is set when we need the user to confirm."""
    prompt: str
    matches: list[Match] = field(default_factory=list)
    result: Result | None = None
    pending: Match | None = None
    auto: bool = False        # confident enough to run without being asked
    plan: "Plan | None" = None   # a multi-step answer, when one skill will not do

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
    def handle(self, prompt: str, on_progress=None) -> Turn:
        turn = Turn(prompt=prompt, matches=self.router.rank(prompt, top=3))

        # One skill is the common case. When nothing matches well, or the
        # sentence asks for two things, hand it to the planner instead of
        # forcing the request through the nearest single skill.
        best_score = turn.matches[0].score if turn.matches else 0.0
        # A sentence with two verbs gets planned even when one skill scores
        # well, because scoring well on half a request is the failure mode:
        # "open browser and start applying to jobs" matched open_app at 0.61
        # and would have opened a browser and stopped there.
        if _looks_multi_step(prompt) or best_score < PLAN_THRESHOLD:
            with progress.listening(on_progress):
                if on_progress:
                    on_progress("Working out how to do that…")
                plan = planner.plan(prompt)
            if plan.steps and (len(plan.steps) > 1 or not turn.matches):
                turn.plan = plan
                self.last = turn
                return turn
            if not turn.matches:
                turn.result = Result.fail(
                    "I don't have a skill for that yet.",
                    plan.cannot or plan.note
                    or "Try: research …, where did i put …, what's using my cpu")
                self.last = turn
                return turn

        top = turn.matches[0]
        # Routing decides; running is the caller's job. Deciding here used to
        # mean auto mode executed on whatever thread asked, which froze the UI
        # for the whole of a slow skill.
        turn.auto = (config.get("mode") == "auto"
                     and top.score >= AUTO_THRESHOLD
                     and not top.skill.danger)
        turn.pending = top
        self.last = turn
        return turn

    # -- execution -------------------------------------------------------
    def run(self, match: Match, on_progress=None) -> Result:
        try:
            with progress.listening(on_progress):
                out = match.skill.run(**match.slots)
        except TypeError as exc:           # slot names out of step with the function
            return Result.fail(f"{match.skill.name} couldn't accept those arguments.",
                               str(exc))
        except Exception as exc:
            return Result.fail(f"{match.skill.name} failed.", f"{type(exc).__name__}: {exc}")
        return out if isinstance(out, Result) else Result(text=str(out))

    def run_plan(self, turn: Turn, on_progress=None) -> Result:
        """Run a plan's steps in order, reporting which one is going.

        A failed step stops the run: the later steps were chosen assuming the
        earlier ones worked.
        """
        plan = turn.plan
        if not plan or not plan.steps:
            return Result.fail("Nothing to run.")
        lines, data = [], []
        for i, step in enumerate(plan.steps, start=1):
            if on_progress:
                on_progress(f"Step {i} of {len(plan.steps)}: {step.describe()}")
            match = Match(skill=step.skill, score=1.0, slots=step.args)
            res = self.run(match, on_progress=on_progress)
            data.append(res)
            head = (res.text or "").strip()
            lines.append(f"{i}. {step.describe()}\n{head}")
            if not res.ok:
                lines.append(f"\nStopped after step {i}.")
                break
        detail = " ".join(x for x in (plan.cannot, plan.note) if x)
        turn.result = Result(ok=True, text="\n\n".join(lines), detail=detail,
                             data=data)
        return turn.result

    def confirm(self, turn: Turn | None = None, choice: int = 0,
                on_progress=None) -> Result:
        """Run the pending match (or the nth alternative the UI offered)."""
        turn = turn or self.last
        if not turn or not turn.matches:
            return Result.fail("Nothing to run.")
        match = turn.matches[min(choice, len(turn.matches) - 1)]
        turn.pending = None
        turn.result = self.run(match, on_progress=on_progress)
        return turn.result
