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
          triggers=None):
    """Decorator registering the wrapped function as a skill."""
    def deco(fn):
        _REGISTRY[name] = Skill(
            name=name, description=description, phrases=phrases, run=fn,
            slots=slots, danger=danger, slow=slow, tags=list(tags or []),
            triggers=list(triggers or []),
        )
        return fn
    return deco


def load_all() -> dict[str, Skill]:
    """Import every module in vb.skills so decorators run. Idempotent."""
    from vb import skills as pkg
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
    return _REGISTRY


def all_skills() -> dict[str, Skill]:
    return _REGISTRY


def get(name: str) -> Skill | None:
    return _REGISTRY.get(name)
