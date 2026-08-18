"""The bit in the middle: prompt in, work done, answer out.

There are two ways through here and the split matters, because one of them is
free and the other is not.

The fast path is the router: a cosine match against skill phrases, sub-
millisecond, no model involved. "what's using my cpu" is one skill and there is
nothing to think about, so nothing thinks about it. Manual mode proposes the
match and waits for a yes; auto mode runs it when the score is high enough;
dangerous skills always ask.

The slow path is the agent loop, and it is where anything real happens. A
request that no single skill covers, or that asks for two things, or that needs
one step's output to feed the next, goes to `vb.loop` — which calls the model
once per step and can write and run code. It costs model calls, so the fast
path keeps as much traffic off it as possible.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from vb import config, loop, planner, progress, testlog
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


def _log(job) -> None:
    """Run a logging call, and never let it take the answer down with it.

    Same reasoning as `loop._after`: this is bookkeeping, it is worth less than
    the answer, and an exception on the way out of `run` would reach the panel
    as a failed request that had in fact succeeded.
    """
    try:
        job()
    except Exception:
        pass


@dataclass
class Turn:
    """One exchange. `pending` is set when we need the user to confirm."""
    prompt: str
    matches: list[Match] = field(default_factory=list)
    result: Result | None = None
    pending: Match | None = None
    auto: bool = False        # confident enough to run without being asked
    plan: "Plan | None" = None   # a multi-step answer, when one skill will not do
    task: bool = False        # this one needs the agent loop, not a single skill
    outcome: "loop.Outcome | None" = None

    @property
    def needs_confirm(self) -> bool:
        return self.pending is not None

    def describe(self) -> str:
        if not self.pending:
            return ""
        args = ", ".join(f"{k}={v!r}" for k, v in self.pending.slots.items() if v)
        return f"{self.pending.skill.name}({args})"


# How much of the conversation to carry forward. Six exchanges is enough for
# "open my downloads / delete the first one / no the other one" without letting
# a long session push the actual request out of the model's context.
HISTORY_TURNS = 6
# Each remembered answer is clipped: a directory listing or a research write-up
# is thousands of characters, and the follow-up only needs to know what was
# being discussed, not to re-read all of it.
HISTORY_ANSWER_CHARS = 600

# A message that only makes sense as a reply to the last one. Either it opens
# like a continuation ("and…", "what about…", "no, the other one"), or it
# points back at something already on screen ("that", "the first one",
# "them", "do it again"). These carry no subject of their own, so the router
# scores them as noise — they have to go to the loop with the history attached.
_FOLLOWUP = re.compile(
    r"^\s*(and|also|then|or|but|what about|how about|no[, ]|actually|"
    r"instead|plus|again)\b"
    r"|\b(that one|this one|the (first|second|third|last|next|other|same) one|"
    r"those|them|it|do it again|the same|that file|that folder)\b",
    re.I)


def _looks_like_followup(prompt: str) -> bool:
    # Long sentences carry their own subject; the short ones are the ones that
    # lean on what came before. The length guard stops "and then generate a
    # full report on…" — a complete request that happens to start with "and" —
    # from being treated as a bare reference.
    return len(prompt.split()) <= 8 and bool(_FOLLOWUP.search(prompt))


class Agent:
    def __init__(self, router: Router | None = None):
        self.router = router or Router()
        self.last: Turn | None = None
        # The conversation so far, as chat messages. In memory only: this is
        # the thread of one sitting, not a fact worth keeping between runs, and
        # writing it to disk would be the wrong kind of permanence.
        self.history: list[dict] = []

    def _remember(self, prompt: str, result: "Result | None") -> None:
        """Add one completed exchange to the running history."""
        if not result or not (result.text or "").strip():
            return
        answer = " ".join(result.text.split())[:HISTORY_ANSWER_CHARS]
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": answer})
        # Kept in whole exchanges, so a truncation never leaves a dangling
        # question with no answer or an answer with no question.
        extra = len(self.history) - HISTORY_TURNS * 2
        if extra > 0:
            self.history = self.history[extra:]

    def forget_conversation(self) -> None:
        """Drop the running history — a fresh start without a restart."""
        self.history = []

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
        # A follow-up leans on the last answer, which only the loop can see.
        # It goes there even when a skill scored well, because the fast path
        # runs a skill with no memory of the conversation — "delete the first
        # one" would match delete_file and then have nothing to delete.
        followup = bool(self.history) and _looks_like_followup(prompt)

        if followup or _looks_multi_step(prompt) or best_score < PLAN_THRESHOLD:
            ready, why = loop.available()
            if ready:
                # Hand it to the loop. Routing stays cheap: nothing is asked of
                # the model here, because deciding to think is not thinking.
                turn.task = True
                turn.auto = config.get("mode") == "auto"
                self.last = turn
                return turn

            # No model at all. The planner cannot help either, but it produces
            # the message explaining what is missing.
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
                    plan.cannot or plan.note or why
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
    def run(self, match: Match, on_progress=None, question: str = "") -> Result:
        started = time.time()
        try:
            with progress.listening(on_progress):
                out = match.skill.run(**match.slots)
        except TypeError as exc:           # slot names out of step with the function
            out = Result.fail(f"{match.skill.name} couldn't accept those arguments.",
                              str(exc))
        except Exception as exc:
            out = Result.fail(f"{match.skill.name} failed.",
                              f"{type(exc).__name__}: {exc}")
        if not isinstance(out, Result):
            out = Result(text=str(out))
        # The fast path answers most requests, and until now it recorded
        # nothing at all — so a testing session showed only the questions that
        # happened to need the model. Deliberately kept out of `traces`: the
        # router chose this skill by cosine similarity, and a training set that
        # calls that a model decision teaches the model to guess tools.
        _log(lambda: testlog.record_skill(question or match.slots.get("_prompt", ""),
                                          match.skill.name, match.slots, out,
                                          time.time() - started))
        return out

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
            res = self.run(match, on_progress=on_progress,
                           question=turn.prompt)
            data.append(res)
            head = (res.text or "").strip()
            lines.append(f"{i}. {step.describe()}\n{head}")
            if not res.ok:
                lines.append(f"\nStopped after step {i}.")
                break
        detail = " ".join(x for x in (plan.cannot, plan.note) if x)
        turn.result = Result(ok=True, text="\n\n".join(lines), detail=detail,
                             data=data)
        self._remember(turn.prompt, turn.result)
        return turn.result

    def run_task(self, turn: Turn, approve: Callable[[str, dict, str], bool] | None = None,
                 on_progress=None) -> Result:
        """Work the request with the agent loop.

        `approve` is asked before anything irreversible: it gets the tool name,
        its arguments and a plain sentence about why it is being asked. Passing
        None means every such call is declined, which is the right default for
        anything running unattended.
        """
        with progress.listening(on_progress):
            outcome = loop.run(turn.prompt, approve=approve,
                               history=self.history,
                               max_steps=int(config.get("agent_max_steps")
                                             or loop.MAX_STEPS))
        turn.outcome = outcome
        turn.result = outcome.as_result()
        self.last = turn
        self._remember(turn.prompt, turn.result)
        return turn.result

    def confirm(self, turn: Turn | None = None, choice: int = 0,
                on_progress=None) -> Result:
        """Run the pending match (or the nth alternative the UI offered)."""
        turn = turn or self.last
        if not turn or not turn.matches:
            return Result.fail("Nothing to run.")
        match = turn.matches[min(choice, len(turn.matches) - 1)]
        turn.pending = None
        turn.result = self.run(match, on_progress=on_progress,
                               question=turn.prompt)
        self._remember(turn.prompt, turn.result)
        return turn.result
