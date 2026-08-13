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


_URL = re.compile(r"https?://\S+|\b(?:www\.)?[\w-]+\.(?:com|org|net|io|dev|ai|co|in)\b\S*", re.I)


def normalise(text: str) -> str:
    """What the router actually encodes.

    A pasted URL is 40 characters of noise that swamps the six words of intent
    around it, so every link collapses to the single token "link" — which is
    also what the skill phrases say.
    """
    return _URL.sub(" link ", text.lower()).strip()


@dataclass
class Match:
    skill: Skill
    score: float
    slots: dict


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
        return out

    def best(self, prompt: str) -> Match | None:
        ranked = self.rank(prompt, top=1)
        return ranked[0] if ranked else None
