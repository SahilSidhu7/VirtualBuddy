"""Semantic search over the skill list.

Every phrase of every skill is encoded once at startup (hashed n-grams, so this
costs milliseconds and no download). A user prompt is encoded the same way and
scored by cosine similarity; a skill's score is its best-matching phrase.

Scores are calibrated against textvec, not a neural embedder: a solid hit lands
around 0.55-0.85, unrelated text around 0.05-0.20.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vb import textvec
from vb.registry import Skill, load_all

AUTO_THRESHOLD = 0.45     # run without asking, in auto mode
SHOW_THRESHOLD = 0.22     # below this we admit we have no idea

TRIGGER_BONUS = 0.22      # a skill's giveaway word is present
TRIGGER_EXTRA = 0.08      # each further one
TRIGGER_CAP = 0.34        # never enough to win on keywords alone

# How far ahead an irreversible skill must be before it is offered first.
# Deleting and reading are one word apart in a sentence full of path characters,
# and the cost of guessing wrong is not symmetric.
DANGER_MARGIN = 0.12


_URL = re.compile(r"https?://\S+|\b(?:www\.)?[\w-]+\.(?:com|org|net|io|dev|ai|co|in)\b\S*", re.I)
# A typed path: drive letter, ~, or two or more separated segments.
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|~[\\/])[^\s\"']*|[\w.-]+(?:[\\/][\w.-]+){2,}")


def normalise(text: str) -> str:
    """What the router actually encodes.

    A pasted URL or a long path is dozens of characters of noise that swamp the
    six words of intent around them, so both collapse to a single token. Before
    this, "read C:/Users/…/Temp/tmp_187j5zn/probe.txt" scored read_file at 0.35
    and delete_file at 0.30 purely on path characters, and a near-tie is no way
    to decide whether to open a file or bin it.
    """
    clean = _URL.sub(" link ", text.lower())
    return _PATH.sub(" path ", clean).strip()


@dataclass
class Match:
    skill: Skill
    score: float
    slots: dict


def _safety_first(matches: list[Match]) -> list[Match]:
    """Demote an irreversible skill that only just won.

    It stays on the list as an alternative the user can pick; it just does not
    get to be the default when something reversible scored nearly as well.
    """
    if len(matches) < 2 or not matches[0].skill.danger:
        return matches
    for i, other in enumerate(matches[1:], start=1):
        if not other.skill.danger and matches[0].score - other.score < DANGER_MARGIN:
            return [other] + matches[:i] + matches[i + 1:]
    return matches


class Router:
    def __init__(self, skills: dict[str, Skill] | None = None):
        self.skills = skills if skills is not None else load_all()
        self._names: list[str] = []
        self._matrix = None
        self._build()

    def _compile(self):
        self._triggers = {
            name: [re.compile(pattern, re.I) for pattern in sk.triggers]
            for name, sk in self.skills.items() if sk.triggers
        }

    def _bonus(self, name: str, prompt: str) -> float:
        """Bounded lift for skills whose giveaway words are present."""
        hits = sum(1 for rx in self._triggers.get(name, ()) if rx.search(prompt))
        if not hits:
            return 0.0
        return min(TRIGGER_BONUS + (hits - 1) * TRIGGER_EXTRA, TRIGGER_CAP)

    def _build(self):
        self._compile()
        texts, owners = [], []
        for name, sk in self.skills.items():
            for phrase in sk.match_text():
                texts.append(normalise(phrase))
                owners.append(name)
        self._names = owners
        self._matrix = textvec.encode(texts) if texts else None

    def rank(self, prompt: str, top: int = 3) -> list[Match]:
        """Best skills for this prompt, highest score first."""
        if self._matrix is None or not prompt.strip():
            return []
        clean = normalise(prompt)
        sims = textvec.similarity(self._matrix, textvec.encode(clean)[0])
        best: dict[str, float] = {}
        for name, score in zip(self._names, sims):
            if score > best.get(name, -1):
                best[name] = float(score)
        for name in best:
            best[name] = min(1.0, best[name] + self._bonus(name, clean))
        ordered = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for name, score in ordered[:top]:
            if score < SHOW_THRESHOLD:
                break
            sk = self.skills[name]
            out.append(Match(skill=sk, score=score, slots=sk.extract(prompt)))
        return _safety_first(out)

    def best(self, prompt: str) -> Match | None:
        ranked = self.rank(prompt, top=1)
        return ranked[0] if ranked else None
