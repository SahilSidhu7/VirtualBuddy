"""Skill contract and discovery.

A skill is a plain function plus a description of when to use it. Modules under
vb/skills/ declare their skills with @skill; importing the package registers
them. Nothing else in the app needs to know a skill exists.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Any

_REGISTRY: dict[str, "Skill"] = {}


@dataclass
class Skill:
    name: str
    description: str
    phrases: list[str]
    run: Callable[..., "Result"]
    slots: Callable[[str], dict] | None = None
    danger: bool = False          # needs confirmation even in auto mode
    slow: bool = False            # long-running; UI shows a working state
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    """Words at least one of which must appear for this skill to be considered.

    Similarity matches a sentence *frame*, not its subject: "what is my gpu
    doing" scored `claude_status` at 0.65 purely on "what is my ___ doing",
    with the word that carried the meaning — claude — absent. A skill named for
    an entity declares it here, and the router drops the skill outright when
    none of the words is present, rather than ranking it on the frame alone.
    """
    broad: bool = False
    """A whole-machine skill that takes no particular path.

    `pc_summary` answers "what is on my pc"; asked "how many .py files are in
    C:/Projects/MAIN/miniVE/src" it counted the whole disk, because "how many"
    matched. When the prompt names a specific path the router demotes these, so
    the precise question reaches the agent loop that can actually answer it.
    """
    triggers: list[str] = field(default_factory=list)
    """Regexes that give this skill away.

    Similarity alone can't separate skills that share vocabulary — "open my
    downloads" and "what's in my downloads" are one word apart and mean
    different things. A trigger is that word: matching one is worth a bounded
    bonus on top of the cosine score, never a decision on its own.
    """

    def match_text(self) -> list[str]:
        """Phrases the router encodes for this skill."""
        return [self.name.replace("_", " "), self.description, *self.phrases]

    def extract(self, text: str) -> dict:
        return self.slots(text) if self.slots else {}


@dataclass
class Result:
    """What a skill hands back to the UI."""
    ok: bool = True
    text: str = ""
    detail: str = ""
    data: Any = None

    @staticmethod
    def fail(text: str, detail: str = "") -> "Result":
        return Result(ok=False, text=text, detail=detail)


def skill(name: str, description: str, phrases: list[str], *,
          slots=None, danger: bool = False, slow: bool = False, tags=None,
          triggers=None, requires=None, broad: bool = False):
    """Decorator registering the wrapped function as a skill."""
    def deco(fn):
        _REGISTRY[name] = Skill(
            name=name, description=description, phrases=phrases, run=fn,
            slots=slots, danger=danger, slow=slow, tags=list(tags or []),
            triggers=list(triggers or []), requires=list(requires or []),
            broad=broad,
        )
        return fn
    return deco


def load_all() -> dict[str, Skill]:
    """Import every module in vb.skills so decorators run. Idempotent."""
    from vb import skills as pkg
    found = {m.name for m in pkgutil.iter_modules(pkg.__path__)
             if not m.name.startswith("_")}
    # Scanning finds files a checkout has; the declared list covers the frozen
    # app, where there is no directory to scan. Either alone would miss cases.
    for name in sorted(found | set(getattr(pkg, "MODULES", ()))):
        try:
            importlib.import_module(f"{pkg.__name__}.{name}")
        except ImportError:
            continue
    return _REGISTRY


def all_skills() -> dict[str, Skill]:
    return _REGISTRY


def get(name: str) -> Skill | None:
    return _REGISTRY.get(name)
