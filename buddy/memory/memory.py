"""Buddy's memory — the friendly front door.

Three long-term tiers (each its own JSONL file under ~/.virtualbuddy/memory/)
plus a tiny in-process short-term buffer for the current session.

  Memory(cfg).remember("my server is 192.168.1.42", kind="semantic")
  Memory(cfg).recall("what's my server ip")      -> [ {text, score, ...}, ... ]

Module-level remember()/recall()/recent() use a lazily-built singleton so callers
that don't want to thread cfg around (skills, the feedback loop) can just import them.
"""
import os

from buddy import settings
from buddy.memory.store import Store

TIERS = ("episodic", "semantic", "procedural")


class Memory:
    def __init__(self, cfg):
        self.cfg = cfg
        d = settings.memory_dir()
        self.stores = {t: Store(os.path.join(d, f"{t}.jsonl"), cfg) for t in TIERS}
        self.working = []                       # short-term: (text, kind) this session

    # ---- write ----
    def remember(self, text, kind="semantic", meta=None):
        """Store a memory. kind is one of TIERS (defaults to a fact)."""
        text = (text or "").strip()
        if not text:
            return None
        if kind not in self.stores:
            kind = "semantic"
        self.working.append((text, kind))
        if len(self.working) > 50:
            self.working.pop(0)
        return self.stores[kind].add(kind, text, meta)

    def note_episode(self, text, meta=None):
        return self.remember(text, kind="episodic", meta=meta)

    def learn_fact(self, text, meta=None):
        return self.remember(text, kind="semantic", meta=meta)

    def learn_procedure(self, text, meta=None):
        return self.remember(text, kind="procedural", meta=meta)

    # ---- read ----
    def recall(self, query, k=None, min_score=None, kinds=None):
        """Top memories relevant to `query`, across the given tiers (default all)."""
        if not self.cfg.get("memory_enabled", True):
            return []
        k = k if k is not None else self.cfg.get("memory_top_k", 5)
        min_score = min_score if min_score is not None else self.cfg.get("memory_min_score", 0.35)
        kinds = kinds or TIERS
        hits = []
        for t in kinds:
            hits.extend(self.stores[t].search(query, k=k, min_score=min_score))
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:k]

    def recall_block(self, query):
        """Recall formatted as a plain-text block to prepend to an LLM prompt."""
        hits = self.recall(query)
        if not hits:
            return ""
        lines = [f"- ({h['kind']}) {h['text']}" for h in hits]
        return "What I remember that may be relevant:\n" + "\n".join(lines)

    def recent(self, n=10, kind="episodic"):
        return self.stores.get(kind, self.stores["episodic"]).recent(n)


# ---- module-level singleton convenience ----
_singleton = None


def get(cfg=None):
    global _singleton
    if _singleton is None:
        if cfg is None:
            cfg = settings.load()
        _singleton = Memory(cfg)
    return _singleton


def remember(text, kind="semantic", meta=None, cfg=None):
    return get(cfg).remember(text, kind=kind, meta=meta)


def recall(query, cfg=None, **kw):
    return get(cfg).recall(query, **kw)


def recent(n=10, kind="episodic", cfg=None):
    return get(cfg).recent(n=n, kind=kind)
