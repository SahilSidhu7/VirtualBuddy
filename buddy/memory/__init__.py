"""Buddy's memory — human-like, three tiers.

  episodic   - things that happened ("you asked me to screenshot at 3pm")
  semantic   - facts you told me ("my server IP is 192.168.1.42")
  procedural - how to do things (lessons that later get baked into the brain)

Public API lives in memory.py. Storage lives in store.py (JSONL + cosine index).
Everything degrades gracefully: no embedder -> falls back to word-overlap search,
so the light client still works with no torch.
"""
from buddy.memory.memory import Memory, remember, recall, recent  # noqa: F401
