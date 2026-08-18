"""The agent loop: think, act, look at what happened, think again.

This is the difference between the old planner and something that can do a real
task. The planner asked the model once for a list of steps and then ran them
blind — which is why it had to throw away any step whose argument was "the
first result", because there was no first result to pass on. Here every tool
result goes back into the transcript before the next decision, so a step can
build on the one before it and a failed step can be worked around instead of
ending the task.

Cost is the constraint that shapes the rest. A loop asks the model once per
step, so the model has to be cheap: `work` is whatever local model fits the
card, and it drives everything. The expensive tier is only reached after the
local one has visibly failed twice, and even then "expensive" means the Claude
Code CLI the user already pays a flat rate for. A task that finishes locally
costs nothing but electricity.

Three things keep a cheap model on the rails:

* one tool call per turn, so it always sees the result before choosing again;
* a stall detector, because a small model that repeats itself will repeat
  itself forever;
* a critic that reads the finished answer against the original request and can
  send the loop back out for more.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from vb import (backends, config, critic, learning, memory, progress, sandbox,
                tools, traces)
from vb.registry import Result

MAX_STEPS = 12               # a hard stop, not a target
MAX_SECONDS = 300
ESCALATE_AFTER = 2           # consecutive bad turns before paying for a better model
OBSERVATION_CHARS = 4000

SYSTEM = """You are VirtualBuddy, an agent running on the user's own computer.

You work in steps. Each turn you call exactly one tool, see what it returned,
and then decide the next one. Keep going until the task is genuinely done, then
call finish with the complete answer.

How to work:
- Look before you act. Read the file, list the folder, search the web, and base
  the next step on what came back rather than on what you assumed.
- run_python is the general tool. If no other tool fits, write a short script.
- Never invent a result. If a tool failed, say so and try another way.
- Prefer the smallest number of steps that actually finishes the job.
- finish is not optional. An answer that never calls finish never reaches the
  user.
- finish takes the answer itself, not a report on your progress. Put the
  numbers, names, paths and findings in it. "The task is done" is not an
  answer, and neither is "I ran the script". Write what the script said.
- When a tool gives you a wrong-arguments error, read the argument names it
  listed and use those. Do not guess a different name.
- A step that printed nothing has told you nothing. If you wrote a file, read
  it back. If you counted something, print the count. Verify, then finish.
- Never write a number you have not seen. If you are putting sizes, counts or
  dates into a file or an answer, they must be figures a tool printed to you.
  Go and get them first.
- Earlier turns above are there for context, not to copy. When the user follows
  up — "and my cpu?", "do the same for downloads", "the first one" — work out
  what they now mean from that context, then go and get it with a tool. A short
  follow-up is still a fresh request: answer it with new information, never by
  restating an earlier answer.

What you must not do:
- Do not sign in to anything, fill in an application, buy anything or pay.
  Open the page and tell the user that part is theirs.
- Do not claim you did something a tool did not confirm.
"""


@dataclass
class Step:
    n: int
    tool: str
    args: dict
    output: str = ""
    ok: bool = True
    seconds: float = 0.0
    approved: bool | None = None       # None when approval was not needed

    def describe(self, width: int = 40) -> str:
        """One line naming the call. `width` caps each argument.

        The ellipsis is not decoration. At the default width a `run_python`
        call shows forty characters of source and stops mid-token, and the
        critic — which reads this same line — was failing correct runs on the
        grounds that "the execution step is truncated and incomplete". A cut
        that is visibly a cut is judged as a cut, not as a broken step.
        """
        parts = []
        for k, v in self.args.items():
            text = str(v)
            parts.append(f"{k}={text[:width]!r}"
                         + (f"… (+{len(text) - width} chars)"
                            if len(text) > width else ""))
        return f"{self.tool}({', '.join(parts)})"


@dataclass
class Outcome:
    request: str
    answer: str = ""
    steps: list[Step] = field(default_factory=list)
    ok: bool = True
    note: str = ""
    verdict: "critic.Verdict | None" = None
    seconds: float = 0.0
    escalated: bool = False
    learned: str = ""          # title of the skill this run taught itself
    # True when the answer was assembled by the harness from a step's output
    # rather than written by the model. The user should not care; a training
    # set very much does, because recording harness prose as if the model had
    # chosen it teaches the model to produce that prose.
    rescued: bool = False

    def as_result(self) -> Result:
        detail = " ".join(x for x in (self.note, self.verdict.summary
                                      if self.verdict else "") if x)
        return Result(ok=self.ok, text=self.answer or "I could not finish that.",
                      detail=detail.strip(), data=self)

    def transcript(self, width: int = 40, output: int = 200) -> str:
        return "\n".join(f"{s.n}. {s.describe(width)} → {s.output[:output]}"
                         for s in self.steps)


ApprovalFn = Callable[[str, dict, str], bool]


def _needs_approval(tool: tools.Tool, args: dict) -> str:
    """The reason this call has to be asked about, or '' when it does not."""
    if tool.name in ("run_shell", "run_python"):
        text = args.get("command") or args.get("code") or ""
        verdict = sandbox.classify(text)
        if verdict.action == "deny":
            return f"REFUSED: {verdict.reason}"
        if verdict.action == "confirm":
            return verdict.reason
        return ""
    if tool.name == "write_file":
        target = str(args.get("path", ""))
        if sandbox.inside_workspace(target):
            return ""
        return f"writes to {target}, outside its workspace"
    if tool.danger:
        return f"{tool.name} cannot be undone"
    return ""


def _dispatch(call: backends.ToolCall, approve: ApprovalFn | None,
              step_no: int, offered: list[str]) -> Step:
    step = Step(n=step_no, tool=call.name, args=dict(call.args))
    # Only what was offered. A model that has seen a tool name once will call
    # it again from memory long after it was taken off the menu, and the
    # registry would happily run it — that is how a request to count files ends
    # up reading the to-do list.
    tool = tools.get(call.name) if call.name in offered else None
    if tool is None:
        step.ok = False
        step.output = (f"There is no tool called {call.name} available for this "
                       f"task. You may use: {', '.join(offered)}")
        return step

    reason = _needs_approval(tool, call.args)
    if reason.startswith("REFUSED"):
        step.ok = False
        step.approved = False
        step.output = (f"Refused, and this will not be allowed on a retry: "
                       f"{reason[9:]}. Find another way or tell the user.")
        return step
    if reason:
        granted = bool(approve and approve(call.name, dict(call.args), reason))
        step.approved = granted
        tools.set_approved(call.name, granted)
        if not granted:
            step.ok = False
            step.output = (f"The user did not approve this ({reason}). "
                           f"Do not ask again; continue without it.")
            return step

    progress.say(f"Step {step_no}: {step.describe()[:80]}")
    started = time.time()
    try:
        out = tool.run(**call.args)
    except TypeError as exc:
        step.ok = False
        step.output = (f"Wrong arguments for {call.name}: {exc}. "
                       f"It takes: {', '.join(tool.params) or 'nothing'}.")
        return step
    except Exception as exc:
        step.ok = False
        step.output = f"{call.name} raised {type(exc).__name__}: {exc}"
        return step
    finally:
        step.seconds = time.time() - started
        tools.set_approved(call.name, False)     # approval is per call, never sticky

    if isinstance(out, Result):
        step.ok = out.ok
        step.output = (out.text or "") + (f"\n{out.detail}" if out.detail else "")
    else:
        step.output = str(out)
    if len(step.output) > OBSERVATION_CHARS:
        step.output = (step.output[:OBSERVATION_CHARS]
                       + f"\n… [{len(step.output) - OBSERVATION_CHARS} characters cut]")
    return step


def _signature(call: backends.ToolCall) -> str:
    """An exact fingerprint of a call, for spotting a repeat.

    Hashed in full rather than truncated. Every script the model writes starts
    with the same imports and the same path setup, so comparing the first 200
    characters declared two genuinely different scripts identical and refused
    to run the second one.
    """
    body = json.dumps(call.args, sort_keys=True, default=str)
    return call.name + ":" + hashlib.sha1(body.encode("utf-8")).hexdigest()


def _conversation(history: list[dict] | None) -> list[dict]:
    """Sanitised prior turns for the prompt.

    Only user and assistant text, only strings, and never a system role slipped
    in from elsewhere. Empty when there is nothing, which is the common case and
    keeps a first request exactly as it was before history existed.
    """
    if not history:
        return []
    out = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            out.append({"role": role, "content": content})
    return out[-(HISTORY_MESSAGES):]


HISTORY_MESSAGES = 12          # six exchanges, matching the Agent's own cap


def run(request: str, *, approve: ApprovalFn | None = None,
        max_steps: int = MAX_STEPS, allow_critic: bool = True,
        deadline: float | None = None, start_tier: str = "work",
        only_tools: list[str] | None = None,
        history: list[dict] | None = None,
        _record_episode: bool = True) -> Outcome:
    """Work on a request until it is done, refused, or out of budget.

    `deadline` is an absolute time, shared with any retry. Giving the second
    attempt a fresh clock is how a five minute budget quietly becomes thirteen.
    """
    started = time.time()
    deadline = deadline or (started + MAX_SECONDS)
    outcome = Outcome(request=request)

    # Two kinds of recall, and the order matters. Learned procedures are
    # instructions for doing this class of task and go last, closest to the
    # request; remembered facts are background and go first.
    known = memory.context_for(request)
    procedure = learning.context_for(request)
    system = SYSTEM + (f"\n\n{known}" if known else "") \
                    + (f"\n\n{procedure}" if procedure else "")
    # Not every tool, only the ones this request scored against. See
    # tools.relevant: a shorter menu is the cheapest accuracy there is.
    offered = tools.relevant(request)
    if only_tools is not None:
        # An explicit menu, used when generating training data: masking
        # run_python forces the skills to be exercised, and a dataset where
        # every answer is a Python script teaches a model to ignore the skills
        # it has. `finish` is never masked — without it a run cannot end.
        offered = [t for t in only_tools if tools.get(t)] + ["finish"]
        offered = list(dict.fromkeys(offered))
    schemas = tools.schemas(offered)
    # Prior turns go between the system prompt and this request, so a follow-up
    # like "and my cpu?" or "delete the first one" is read against what was
    # just said. These are the plain question/answer pairs the front end kept,
    # not full transcripts — enough to resolve a reference without dragging a
    # whole earlier task's tool output into this one's context.
    prior = _conversation(history)
    messages = [{"role": "system", "content": system},
                *prior,
                {"role": "user", "content": request}]

    # Starting on a tier that cannot answer is not a slow start, it is a dead
    # one: the first call fails, the loop breaks, and escalation — which only
    # happens after a completed turn — never gets a chance. So the entry tier
    # is the best one that actually works right now.
    tier = start_tier
    if tier == "work" and not _llm_ready() and backends.claude_code_path():
        tier, outcome.escalated = "hard", True

    bad_turns = 0
    seen: list[str] = []
    retried_critic = False
    refused_bare_finish = False

    step_no = 0
    turns = 0                 # model calls, including the ones that did nothing
    max_turns = max_steps * 2
    while step_no < max_steps:
        # A turn that produces no tool call does not advance step_no, so
        # without this a model that only ever emits prose spins until the wall
        # clock runs out and the user waits five minutes for nothing.
        turns += 1
        if turns > max_turns:
            outcome.note = f"Gave up after {turns} turns without finishing."
            break
        left = deadline - time.time()
        if left <= 0:
            outcome.note = f"Ran out of time after {time.time() - started:.0f}s."
            break

        # Never wait longer than the budget has left: a 240s call started with
        # 30s remaining spends the whole overrun before anyone notices.
        budget = max(20, min(120 if tier != "hard" else 240, int(left)))
        reply = backends.chat(messages, schemas, tier=tier, timeout=budget)
        if not reply:
            outcome.ok = False
            outcome.note = reply.error or "The model did not answer."
            break

        if not reply.tool_calls:
            # Prose with no call. Once, that is the model answering directly and
            # forgetting the protocol, which is fine if it said something. Twice
            # in a row means it is stuck talking instead of working.
            spoken = _prose_only(reply.content)
            # Prose with no tool call is the other way an unsupported answer
            # gets out — the model states a file count it never counted, the
            # loop accepts it on the second try, and it lands as a confident
            # wrong answer with zero steps behind it. Once a tool has run there
            # is evidence to talk about, so one repeat is enough; with nothing
            # run at all it has to insist twice.
            if spoken and bad_turns >= (1 if outcome.steps else 2):
                outcome.answer = spoken
                break
            bad_turns += 1
            messages.append({"role": "assistant", "content": reply.content})
            # The old nudge offered "or call finish with the answer" even when
            # nothing had been run yet, which invited exactly the fabrication
            # above. Only offer finishing once there is something to finish on.
            messages.append({"role": "user", "content":
                             "Call a tool now, or call finish with the answer."
                             if outcome.steps else
                             "You have not run anything yet. Call a tool to "
                             "find out — do not answer from memory."})
            if bad_turns >= ESCALATE_AFTER and tier == "work":
                tier, outcome.escalated = "hard", True
                progress.say("Asking a stronger model…")
            continue

        call = reply.tool_calls[0]
        # The whole history, not just the last turn. An identical call made
        # five steps ago has its result sitting in the transcript already, and
        # a small model that circles back to it will keep circling.
        if _signature(call) in seen:
            bad_turns += 1
            messages.append({"role": "user", "content":
                             f"You already ran {call.name} with those arguments and "
                             f"got the result above. Do something different, or "
                             f"call finish."})
            if bad_turns >= ESCALATE_AFTER and tier == "work":
                tier, outcome.escalated = "hard", True
                progress.say("Asking a stronger model…")
            continue
        seen.append(_signature(call))

        if call.name == "finish":
            answer = str(call.args.get("answer")
                         or _prose_only(reply.content) or "").strip()
            # Finishing before a single tool has run is not an answer, it is a
            # guess dressed as one — the model reporting a file count it never
            # counted. It showed up as runs of "0 steps" in every model tested,
            # base and fine-tuned alike, so it is the harness accepting
            # fabrication rather than any one model inventing it.
            #
            # Pushed back on once, not forbidden. Some requests genuinely need
            # no tool, and a model that insists after being told to look is
            # more likely to be right about that than a rule written here.
            if not outcome.steps and not refused_bare_finish:
                refused_bare_finish = True
                bad_turns += 1
                messages.append({"role": "assistant", "content": reply.content,
                                 "tool_calls": [{"function": {
                                     "name": call.name, "arguments": call.args}}]})
                messages.append({"role": "user", "content":
                                 "You have not run anything yet, so that answer "
                                 "is a guess. Use a tool to find out, then call "
                                 "finish with what it actually returned. If the "
                                 "question truly needs no tool, call finish again."})
                # The signature is dropped so the retry may legitimately call
                # finish again — the repeat-call guard above would otherwise
                # treat insisting as circling.
                seen.pop()
                continue
            outcome.answer = answer
            break

        step_no += 1
        step = _dispatch(call, approve, step_no, offered)
        outcome.steps.append(step)
        bad_turns = 0 if step.ok else bad_turns + 1
        if bad_turns >= ESCALATE_AFTER and tier == "work":
            tier, outcome.escalated = "hard", True
            progress.say("That is not working — asking a stronger model…")

        # `arguments` goes back as an object, not a JSON string. Ollama parses
        # the transcript it is given and rejects the whole request with
        # "Value looks like object, but can't find closing '}' symbol" when a
        # string turns up where it expects a map.
        messages.append({"role": "assistant", "content": reply.content,
                         "tool_calls": [{"function": {"name": call.name,
                                                      "arguments": call.args}}]})
        messages.append({"role": "tool", "name": call.name,
                         "tool_name": call.name, "content": step.output})

        # A critic pass mid-run, but only at the point where a run has usually
        # either gone wrong or is nearly done. Running it every step would
        # double the number of model calls for no benefit.
        if allow_critic and step_no == max_steps // 2 and not retried_critic:
            nudge = critic.mid_run_note(request, outcome)
            if nudge:
                retried_critic = True
                messages.append({"role": "user", "content": nudge})

    else:
        outcome.note = f"Stopped after {max_steps} steps."

    if not outcome.answer and outcome.steps:
        outcome.answer = _fallback_answer(outcome)
    elif outcome.answer and outcome.steps:
        outcome.answer = _with_evidence(outcome)

    outcome.seconds = time.time() - started

    if allow_critic and outcome.answer:
        outcome.verdict = critic.judge(request, outcome)
        if (not outcome.verdict.passed and outcome.verdict.retry
                and step_no < max_steps and time.time() < deadline):
            progress.say("The answer did not hold up — trying again…")
            # The second attempt gets the first one's steps, not just its
            # verdict. Without them it re-runs the same list_dir and the same
            # broken script, and a retry that repeats the work is only a way of
            # taking twice as long to fail.
            second = run(
                f"{request}\n\n"
                f"An earlier attempt already ran these steps:\n"
                f"{outcome.transcript()[:2500]}\n\n"
                f"It answered: {outcome.answer[:500]}\n"
                f"That was rejected because: {outcome.verdict.summary}\n"
                f"Do not repeat the steps that already worked — use what they "
                f"returned. Fix what went wrong and give the real answer.",
                approve=approve, max_steps=max(4, max_steps // 2),
                allow_critic=False, deadline=deadline, _record_episode=False)
            if second.answer:
                second.request = request
                second.steps = outcome.steps + second.steps
                second.escalated = outcome.escalated or second.escalated
                # Judge the retry on its own work. Re-attaching the first
                # attempt's verdict marked a successful second try as failed,
                # and let a failed one through unexamined — exactly backwards.
                second.verdict = critic.judge(request, second)
                second.seconds = time.time() - started
                outcome = second

    if _record_episode:
        _after(outcome, system, offered)
    return outcome


def _after(outcome: Outcome, system: str, offered: list[str]) -> None:
    """Everything that happens once the answer already exists.

    All of it is bookkeeping — an episode, a trace, a learned note — and none
    of it is worth the answer. So every part is individually guarded: an
    exception here used to escape `run()` entirely, which in the panel meant
    `done()` never ran, `_busy` stayed set, and the window was stuck until
    restart with a finished answer it never showed.

    Only the outer call reaches here. The retry's request is a 3,000 character
    synthetic prompt containing the first attempt's transcript, and storing
    that as "something I remember" poisons every later recall.
    """
    from vb import testlog

    for job in (lambda: _record(outcome),
                lambda: traces.record(outcome, system=system, offered=offered),
                lambda: testlog.record_outcome(outcome),
                lambda: _maybe_learn(outcome),
                memory.maybe_consolidate):
        try:
            job()
        except Exception:
            continue


def _maybe_learn(outcome: Outcome) -> None:
    """Write a procedure note, but only from work that survived the critic.

    A note written from a run that quietly went wrong teaches the wrong
    procedure to every later run, and that is much harder to notice than a
    single bad answer — the bad answer is on screen, the bad note is in the
    next prompt.
    """
    if not (outcome.ok and outcome.answer):
        return
    if outcome.verdict is not None and not outcome.verdict.passed:
        return
    taught = learning.learn_from(outcome)
    if taught:
        outcome.learned = taught.title
        progress.say(f"Noted how to do that: {taught.title}")


_clean = critic.clean_output


def _prose_only(content: str) -> str:
    """The part of a model reply that is meant for a person.

    A reply that is really a malformed tool call must never be shown as an
    answer. The user asked for the three biggest files, not for
    `{"name": "write_file", "parameters": {…}}`, and printing that is worse
    than printing nothing.
    """
    text = backends.strip_json_blocks(content or "").strip()
    if not text or backends.parse_text_tool_calls(text):
        return ""
    return text


def _with_evidence(outcome: Outcome) -> str:
    """Put the result back into an answer that dropped it.

    A small model will happily run the script, read the number, and then call
    finish with "The task is done." The work is not lost — it is sitting in the
    last successful step — so rather than failing the run and paying for a
    retry that does the same thing, the answer is rebuilt from what actually
    came back. Free, and it cannot be wrong about what the tool returned.
    """
    good = [s for s in outcome.steps if s.ok and s.output.strip()]
    if not good:
        return outcome.answer
    produced = _clean(good[-1].output)
    if not produced or len(produced) < 3:
        return outcome.answer

    answer = outcome.answer.strip()
    if critic.CONTENT_FREE.match(answer):
        outcome.rescued = True
        return f"Here is what came back:\n\n{produced}"
    if not critic.echoes_result(answer, produced):
        # A sentence that mentions nothing the tools returned is not a partial
        # answer, it is filler — "There is no task to perform" on top of a
        # result. Short filler is dropped; a longer answer might be real
        # commentary, so that keeps its place above the evidence.
        if len(answer) < 80:
            outcome.rescued = True
            return f"Here is what came back:\n\n{produced}"
        if len(answer) < 200:
            outcome.rescued = True
            return f"{answer}\n\n{produced}"
    return answer


def _fallback_answer(outcome: Outcome) -> str:
    """What to say when the loop ran out of room without calling finish.

    The steps did happen, and the user is owed what they produced, rather than
    a bare "I gave up".
    """
    useful = [s for s in outcome.steps if s.ok and s.output.strip()]
    if not useful:
        outcome.ok = False
        return ""
    last = useful[-1]
    outcome.rescued = True
    return (f"I did not get to a clean finish, but here is where I got to "
            f"after {len(outcome.steps)} steps.\n\n{_clean(last.output)}")


def _record(outcome: Outcome) -> None:
    """Write one line about how this went, for the next similar request.

    What goes in matters more than that something does. Recording "used
    list_dir, disk_hogs, run_python" tells a later run which tools a previous
    one happened to touch, including the wrong ones, and that gets injected
    into its prompt as something it supposedly knows. So: the tool that
    actually produced the result, and the tools that wasted a step. Those are
    the two things worth carrying forward.
    """
    if not outcome.steps:
        return
    worked = outcome.ok and bool(outcome.answer)
    useful = [s.tool for s in outcome.steps if s.ok and critic.clean_output(s.output)]
    wasted = list(dict.fromkeys(s.tool for s in outcome.steps if not s.ok))

    note = f'For "{outcome.request[:110]}": '
    if worked and useful:
        note += f"{useful[-1]} produced the answer"
        if len(outcome.steps) > len(set(useful)):
            note += f" after {len(outcome.steps)} steps"
    elif worked:
        note += "answered without a tool producing anything"
    else:
        note += "no answer was reached"
    if wasted:
        note += f"; {', '.join(wasted[:3])} got nowhere"

    # And what the run actually established. The line above is about machinery
    # — which tool fired, how many steps — and machinery is close to useless to
    # recall later: asked "what am I working on", memory offered
    # `run_shell produced the answer after 9 steps` and nothing about the
    # answer. Worse, that sentence was not even true of the run it described,
    # because a rescued answer counts as one nobody wrote.
    #
    # So the finding is carried too, and only when the model wrote it. A
    # harness-written answer is not a finding, it is an apology, and storing it
    # as something remembered repeats the mistake that poisoned the first
    # training set.
    if worked and outcome.answer and not getattr(outcome, "rescued", False):
        note += f". It found: {' '.join(outcome.answer.split())[:400]}"
    memory.remember(note + ".", kind="episode", tags=" ".join(useful[-1:] + wasted[:2]))


def _llm_ready() -> bool:
    import vb.llm as llm
    return llm.enabled()


def available() -> tuple[bool, str]:
    """Whether the loop can run at all, and why not when it cannot."""
    import vb.llm as llm
    if _llm_ready() or backends.claude_code_path():
        return True, ""
    return False, llm.status()["message"]
