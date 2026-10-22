"""Asking the buddy to build itself a tool, and looking after the ones it has.

Tools are also forged on their own after any run that worked (`vb.forge`).
These skills are for when the user wants one on purpose — "make a tool that
counts the lines of code in a project" — and for seeing and pruning the shelf.
"""
from __future__ import annotations

import re

from vb import forge, loop, progress
from vb.registry import Result, skill

_MAKE = re.compile(
    r"^.*?\b(?:make|build|create|write|teach yourself|learn)\b"
    r"(?:\s+(?:me|yourself))?(?:\s+an?)?(?:\s+new)?\s+(?:tool|skill|way)?\s*"
    r"(?:that|which|to|for|how to)?\s*", re.I)


def _task(text: str) -> dict:
    return {"task": _MAKE.sub("", text, count=1).strip(" .?!")}


@skill(
    "forge_tool",
    "Build a new reusable tool for a job, test it, and keep it for next time",
    ["make a tool that", "build yourself a tool to", "create a skill that",
     "learn how to", "teach yourself to", "make a new tool for",
     "write a tool which"],
    slots=_task,
    triggers=[r"\b(make|build|create|write)\b.*\b(tool|skill)\b",
              r"\b(learn how to|teach yourself)\b"],
    slow=True,
)
def forge_tool(task: str = "", **_) -> Result:
    task = (task or "").strip()
    if not task:
        return Result.fail("What should the tool do?",
                           "Try: make a tool that counts lines of code in a folder")
    progress.say("Working it out the long way first…")
    outcome = loop.run(task)
    if not (outcome.ok and outcome.answer):
        return Result.fail("I could not do that yet, so there is nothing to "
                           "turn into a tool.", outcome.note)
    progress.say("Turning that into a tool…")
    tool, why = forge.forge(outcome)
    head = outcome.answer.strip()
    if tool:
        args = ", ".join(tool.params) or "no arguments"
        return Result(text=f"{head}\n\nNew tool: {tool.name} ({args}). "
                           f"Next time this is one quick step.",
                      detail=tool.description)
    return Result(text=head, detail=f"No tool kept: {why}")


@skill(
    "list_learned_tools",
    "Show the tools I have built for myself and how they are doing",
    ["what tools have you made", "list your learned tools", "show your tools",
     "what have you learned", "which skills did you build"],
    triggers=[r"\b(tools|skills)\b.*\b(made|built|learned|learnt)\b",
              r"\blearned tools\b"],
)
def list_learned_tools(**_) -> Result:
    have = forge.all_forged(include_quarantined=True)
    if not have:
        return Result(text="I have not built any tools yet. They appear after "
                           "I solve something new, or ask me to make one.")
    lines = []
    for t in sorted(have, key=lambda t: -t.uses):
        state = "retired" if t.quarantined else f"used {t.uses}x"
        if t.fails:
            state += f", failed {t.fails}x"
        lines.append(f"- {t.name} — {t.description} ({state})")
    return Result(text=f"{len(have)} tools I made:\n" + "\n".join(lines),
                  detail=f"Stored in {forge.tools_dir()}")


@skill(
    "forget_learned_tool",
    "Delete one of the tools I built for myself",
    ["forget the tool", "delete your tool", "remove the learned tool",
     "unlearn"],
    slots=lambda text: {"name": (re.findall(r"[a-z][a-z0-9_]{2,}", text.lower())
                                 or [""])[-1]},
    triggers=[r"\b(forget|delete|remove|unlearn)\b.*\btool\b"],
    danger=True,
)
def forget_learned_tool(name: str = "", **_) -> Result:
    if forge.forget(name):
        return Result(text=f"Deleted {name}.")
    names = ", ".join(t.name for t in forge.all_forged(include_quarantined=True))
    return Result.fail(f"I have no tool called {name}.",
                       f"I have: {names}" if names else "")
