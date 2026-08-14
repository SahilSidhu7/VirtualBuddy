"""Turning a request into a sequence of skills.

The router answers "which one skill is this?", which is the wrong question for
"find the best laptop deals and open the top three". This asks the model to
break a request into skills that actually exist, with arguments that actually
fit, and to say plainly which parts it cannot do.

The model never runs anything. It proposes; the user approves; the agent runs.
That ordering is the whole safety story for a feature like this.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field

from vb import llm
from vb.registry import Skill, all_skills

MAX_STEPS = 4

# Values that are really "whatever the last step produced". Steps do not pass
# results to each other yet, so a step built on one of these would run with
# nonsense arguments. Better to drop it and say so.
PLACEHOLDER = re.compile(
    r"\b(result|results|previous|above|earlier|step \d|first|top \d*|"
    r"the link|that link|link from|from search|from the search|it|them)\b"
    r"|^<.*>$|\.\.\.", re.I)


@dataclass
class Step:
    skill: Skill
    args: dict
    why: str = ""

    def describe(self) -> str:
        shown = ", ".join(f"{k}={v}" for k, v in self.args.items() if v)
        return f"{self.skill.name.replace('_', ' ')}" + (f" ({shown})" if shown else "")


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    cannot: str = ""
    note: str = ""

    def __bool__(self) -> bool:
        return bool(self.steps)


def _accepted_args(skill: Skill) -> list[str]:
    try:
        params = inspect.signature(skill.run).parameters
    except (TypeError, ValueError):
        return []
    return [name for name, p in params.items()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            and not name.startswith("_")]


def catalogue() -> str:
    lines = []
    for name, skill in sorted(all_skills().items()):
        args = ", ".join(_accepted_args(skill)) or "no arguments"
        danger = "  [asks first]" if skill.danger else ""
        lines.append(f"- {name}({args}): {skill.description}{danger}")
    return "\n".join(lines)


SYSTEM = (
    "You turn a user's request into a short plan built only from the skills you "
    "are given. You never invent skills or arguments. You are candid about what "
    "the skills cannot do rather than pretending a near miss will work."
)

PROMPT = """The user said: "{request}"

Skills available:
{catalogue}

Reply with JSON only:
{{"steps": [{{"skill": "name", "args": {{"arg": "value"}}, "why": "six words"}}],
  "cannot": "one sentence about any part these skills cannot do, or empty"}}

Rules:
- Use the fewest steps that do the job, at most {max_steps}. Two is usually plenty.
- Never add a step the request did not ask for. No tidying up, no listing tasks.
- Use only skill names from the list, and only their listed arguments.
- Fill every argument with a real value taken from the request. You cannot refer
  to what an earlier step returned, so never write "the first result" or
  "the link from above" as an argument: leave that step out entirely.
- If the request needs signing in, filling forms, paying, or judgement about
  someone's personal documents, put that in "cannot" instead of inventing a step.
- If nothing in the list fits at all, return an empty steps list.
"""


def plan(request: str) -> Plan:
    """Ask the model for a plan. Returns an empty Plan when it cannot help."""
    if not llm.enabled():
        return Plan(note=llm.status()["message"])

    data = llm.ask_json(
        PROMPT.format(request=request, catalogue=catalogue(), max_steps=MAX_STEPS),
        system=SYSTEM, timeout=90)
    if not data:
        return Plan(note=llm.last_error() or "The model did not answer.")

    known = all_skills()
    steps: list[Step] = []
    dropped: list[str] = []
    for raw in (data.get("steps") or [])[:MAX_STEPS]:
        skill = known.get(str(raw.get("skill", "")).strip())
        if not skill:
            continue
        allowed = set(_accepted_args(skill))
        args = {k: str(v) for k, v in (raw.get("args") or {}).items()
                if k in allowed and v not in (None, "")}

        vague = [k for k, v in args.items() if PLACEHOLDER.search(v)]
        if vague:
            # A step that wanted the previous step's output. Say so instead of
            # running it with the literal words "the first result".
            dropped.append(f"{skill.name} (needs the previous step's result)")
            continue
        # An irreversible step has to name its target. "delete_file in
        # downloads" with no filename is a plan to delete something unspecified.
        wanted = _accepted_args(skill)
        if skill.danger and wanted and wanted[0] not in args:
            dropped.append(f"{skill.name} (irreversible, and it never said what to)")
            continue
        if steps and steps[-1].skill is skill:
            continue                        # no repeating the same step
        steps.append(Step(skill=skill, args=args, why=str(raw.get("why", ""))[:60]))

    note = ""
    if dropped:
        note = "Left out: " + "; ".join(dropped)
    cannot = str(data.get("cannot", "")).strip()
    hard = _hard_limit(request)
    if hard and hard not in cannot:
        cannot = f"{hard} {cannot}".strip()
    return Plan(steps=steps, cannot=cannot, note=note)


BEYOND = re.compile(
    r"\bappl(y|ying|ication)\b|\bsign (in|up)\b|\blog ?in\b|\bcheckout\b|"
    r"\bbuy\b|\bpay(ment)?\b|\border\b|\bbook (a|the)\b|\bemail (him|her|them)\b|"
    r"\bsend .*(email|message|dm)\b|\bpost (a|to)\b|\bupload\b", re.I)


def _hard_limit(request: str) -> str:
    """Say the quiet part regardless of what the model claims it can do.

    Filling in applications, signing into accounts and paying for things need
    credentials and a human reading the form. The buddy opens the page; the
    person does the rest. Leaving this to the model's own "cannot" field is not
    good enough, because sometimes it just does not mention it.
    """
    if BEYOND.search(request):
        return ("I can find and open the pages, but I cannot sign in, fill in "
                "an application or pay for anything. That part is yours.")
    return ""
