"""A second opinion on the loop's own work.

A small model is confident in the same tone whether or not it did the job. Left
alone it will announce that it has researched something after one failed fetch,
because that is what the shape of a finished answer looks like. The critic is
the thing that reads the answer back against what was asked and the steps that
actually ran.

Most of its work is free. The deterministic checks below catch the common
failures — an empty answer, a claim that nothing supports, an answer that is
really an apology — without asking a model anything. Only what survives those
costs a call, and that call goes to the `fast` tier, so a critique is a
fraction of the price of the step it is checking.

It can also say "try again", once. A retry is another handful of cheap local
calls, which is nearly always worth it against handing the user something
wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vb import backends

# Phrases that mean the answer is about the agent rather than the question.
DEFLECTION = re.compile(
    r"\bi (can'?t|cannot|am unable|was unable|don'?t have)\b|"
    r"\bas an ai\b|\bi do not have access\b|\bplease try again\b", re.I)

# Claims of having done something. Cheap to spot, and worth checking against
# whether a step actually succeeded.
CLAIMS = re.compile(
    r"\bi (have )?(searched|found|read|downloaded|opened|created|wrote|ran|"
    r"checked|installed|deleted|saved)\b", re.I)

# "The task is done." A small model reaches for this when it has lost track of
# what the answer was, and it is never an answer to anything.
CONTENT_FREE = re.compile(
    r"^\W*(the\s+)?(task|job|work|request|it|everything)?\s*"
    r"(is|has been|was)?\s*(now\s+)?"
    r"(done|complete|completed|finished|handled|sorted|ready|all set)\W*$", re.I)

_WORD = re.compile(r"[A-Za-z0-9_.\\/:-]{4,}")

STATUS_BANNER = re.compile(r"^\[(ok|failed|ran)[^\]]*\]\s*")
NOTHING = re.compile(r"^\(no output\)$|^that tells you nothing", re.I)


def clean_output(output: str) -> str:
    """The part of a step's output that could serve as evidence.

    Strips the `[ok in 0.4s]` banner, which is context for the next decision
    and noise in a final answer, and returns nothing at all for a step that
    printed nothing. Silence is the failure this exists to catch: a script that
    exits zero without a word is the easiest thing to mistake for a result.
    """
    text = STATUS_BANNER.sub("", (output or "").strip()).strip()
    return "" if NOTHING.match(text) else text


def echoes_result(answer: str, output: str) -> bool:
    """Does the answer contain anything the last step actually produced?

    Token overlap, not meaning: the point is to catch an answer that could have
    been written before any tool ran, which is the failure this is for.
    """
    from_output = {w.lower() for w in _WORD.findall(output)}
    from_answer = {w.lower() for w in _WORD.findall(answer)}
    return bool(from_output & from_answer)


@dataclass
class Verdict:
    passed: bool
    summary: str = ""
    retry: bool = False
    checked_by: str = "rules"      # rules | model

    def badge(self) -> str:
        return "✓" if self.passed else "✗"


# Long numbers are the tell. A model that never read the file sizes will write
# 123456 and 654321, because those are what a number looks like.
_FIGURE = re.compile(r"\d[\d,]{2,}")
WRITING = ("write_file", "create_file", "edit_file")

# Figures that turn up in honest writing and prove nothing either way. A report
# is allowed to mention the year, or a version, without having measured it.
_INNOCENT = re.compile(r"^(19|20)\d\d$")


def _checkable(text: str) -> set[str]:
    """Figures in this text that a run should be able to account for."""
    out = set()
    for raw in _FIGURE.findall(text or ""):
        figure = raw.replace(",", "")
        if _INNOCENT.match(figure):
            continue
        out.add(figure)
    return out


def unsupported_write(outcome) -> str:
    """Figures written into a file that no earlier step ever produced.

    This is the failure worth catching above all the others. A wandering run
    wastes time and a vague answer wastes patience, but a file full of invented
    numbers looks exactly like a correct one, and the user has no way to tell.
    So: every figure written out has to have appeared in the output of a step
    that already ran. If it did not, it was made up.
    """
    seen: set[str] = set()
    for step in outcome.steps:
        if step.tool in WRITING:
            content = " ".join(str(v) for v in step.args.values())
            invented = _checkable(content) - seen
            # Two or more. A single unexplained figure is usually something the
            # user put in the request, or a count the model did in its head;
            # a list of them is a model filling in a table it never read.
            if len(invented) >= 2:
                return (f"it wrote figures no step produced: "
                        f"{', '.join(sorted(invented)[:4])}")
        if step.ok:
            seen.update(_checkable(step.output))
    return ""


# "write a file called biggest.txt", "save it as report.md". When the request
# names the thing it wants produced, whether it exists is a fact, not a matter
# of opinion, and a model critic should never have been asked in the first
# place.
_ASKED_FOR_FILE = re.compile(
    r"\b(write|create|save|make|produce|output)\b[^.]{0,60}?"
    r"\b([\w-]+\.(?:txt|md|csv|json|py|html|log|yaml|yml|ini))\b", re.I)


def missing_deliverable(request: str, outcome) -> str:
    """A named file the request asked for that no step actually wrote."""
    match = _ASKED_FOR_FILE.search(request or "")
    if not match:
        return ""
    wanted = match.group(2).lower()
    for step in outcome.steps:
        if not step.ok or step.tool not in WRITING:
            continue
        if wanted in " ".join(str(v) for v in step.args.values()).lower():
            return ""
    return wanted


def _rule_check(request: str, outcome) -> Verdict | None:
    """The free pass. Returns None when nothing obvious is wrong."""
    answer = (outcome.answer or "").strip()
    if not answer:
        return Verdict(False, "It produced no answer.", retry=bool(outcome.steps))
    if len(answer) < 15 and len(request) > 40:
        return Verdict(False, "The answer is too short to be one.", retry=True)

    absent = missing_deliverable(request, outcome)
    if absent:
        return Verdict(False, f"It never wrote {absent}, which is what was asked "
                              f"for.", retry=True)

    made_up = unsupported_write(outcome)
    if made_up:
        return Verdict(False, f"The run cannot be trusted: {made_up}.", retry=True)

    if CONTENT_FREE.match(answer):
        return Verdict(False, "It announced it had finished instead of saying "
                              "what the answer is.", retry=True)

    good = [s for s in outcome.steps if s.ok]
    # Every step ran and not one of them printed anything. The model has
    # inferred success from exit codes, which is exactly the mistake that gets
    # a user told a file was written when it was not.
    if good and not any(clean_output(s.output) for s in good):
        return Verdict(False, "Nothing it ran actually produced a result, so "
                              "there is nothing behind this answer.", retry=True)

    # The work happened and then got thrown away. Common with small models:
    # they run the script, see the number, and call finish with a summary of
    # the process rather than the number.
    if good and len(answer) < 200:
        produced = clean_output(good[-1].output)
        if len(produced) > 30 and not echoes_result(answer, produced):
            return Verdict(False, "The answer does not include what the last "
                                  "step actually produced.", retry=True)

    if CLAIMS.search(answer) and outcome.steps and not good:
        # Every step failed and the answer still says it did the thing.
        return Verdict(False, "It says it did things that every step failed to do.",
                       retry=True)
    if DEFLECTION.search(answer) and not outcome.steps:
        return Verdict(False, "It gave up without trying a single tool.", retry=True)
    return None


SYSTEM = ("You check an assistant's work strictly. You are not being polite. "
          "A partial answer is a fail. An answer that describes what it would "
          "do instead of doing it is a fail.")

PROMPT = """The user asked:
{request}

The assistant ran these steps (a long argument is abbreviated for display and
marked "… (+N chars)" — that is the display shortening it, not the step being
cut short, so never fail a run for it):
{steps}

And answered:
{answer}

Reply with exactly one line, in this form:
PASS or FAIL | one short sentence saying why

Fail it if: the answer does not address what was asked, or claims a result no
step produced, or stops halfway, or is a description of a plan rather than the
thing itself.

Do not fail it for any of these:
- The answer is zero, none, or empty, and the steps show that is the truth.
  "There are 0 .py files in that folder" is a complete and correct answer to
  "how many .py files are in that folder", not a failure to find any.
- The answer is short. A one-line answer to a one-line question is right.
- A step failed but a later step got the result anyway."""


def judge(request: str, outcome) -> Verdict:
    """Grade a finished run. Cheap checks first, then one small model call."""
    hard = _rule_check(request, outcome)
    if hard is not None:
        return hard

    # A wider view than the panel gets. The critic decides whether a step did
    # what it claimed, and it cannot do that from forty characters of source
    # and two hundred of output — it was reading the display truncation as a
    # broken step and failing runs that were correct.
    steps = outcome.transcript(width=400, output=600) or "(no tools were used)"
    reply = backends.ask_text(
        PROMPT.format(request=request[:600], steps=steps[:6000],
                      answer=(outcome.answer or "")[:2000]),
        system=SYSTEM, tier="fast", timeout=45, max_tokens=120)
    if not reply:
        # No critic available is not a reason to withhold an answer.
        return Verdict(True, "", checked_by="rules")

    line = reply.strip().splitlines()[0]
    failed = line.upper().startswith("FAIL")
    why = line.split("|", 1)[1].strip() if "|" in line else line
    return Verdict(not failed, "" if not failed else why,
                   retry=failed, checked_by="model")


def mid_run_note(request: str, outcome) -> str | None:
    """A nudge partway through, when the run is visibly going nowhere.

    Only fires on evidence: half the steps failed, or the same tool has been
    used over and over. Otherwise it is noise in the context window.
    """
    steps = outcome.steps
    if len(steps) < 3:
        return None
    failed = [s for s in steps if not s.ok]
    if len(failed) >= len(steps) / 2:
        last = failed[-1]
        return (f"Most of your steps are failing — {last.tool} said: "
                f"{last.output[:200]}. Change approach: try run_python, or call "
                f"finish and tell the user plainly what is blocked.")
    used = [s.tool for s in steps]
    if len(set(used[-3:])) == 1:
        return (f"You have used {used[-1]} three times running. If it has not "
                f"got you there, it will not. Try something else or finish.")
    return None
