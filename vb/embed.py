"""Turning text into vectors, locally and for nothing.

Keyword search cannot answer "what am I working on". The words in the question
appear in none of the notes that would answer it, so BM25 scores them all zero
and the buddy says it remembers nothing while the answer sits in the table. A
vector search finds it, because "working on" and "project" land near each other
whether or not they share a letter.

The model runs in the Ollama that is already there, so this costs nothing but a
tenth of a second. Two are supported and the order is measured, not assumed:

    nomic-embed-text   109ms for one query warm, 274MB on the card
    embeddinggemma     183ms for one query warm, 622MB

Both are 768 dimensions and both do about 15ms per text in a batch, so the
difference that matters is the single-query latency — which is what a search
pays — and the memory taken away from the 6.6GB work model on an 8GB card.
nomic wins twice, so nomic is first.

Everything degrades rather than fails. No Ollama, no model, no answer: callers
get None and fall back to keyword search, which is worse but is not nothing.
"""
from __future__ import annotations

import json
import struct
import urllib.request

from vb import config, llm

# Best first. `installed()` decides which is actually available.
MODELS = ["nomic-embed-text", "embeddinggemma"]
DIM = 768
TIMEOUT = 120
# Long: the point of the index is that it is on disk and read when needed, so
# the model should not be paged out between two searches a minute apart.
KEEP_ALIVE = "30m"

_state: dict = {}


def model() -> str | None:
    """The embedding model to use, or None when there is not one."""
    if "model" in _state:
        return _state["model"]
    chosen = config.get("embed_model")
    found = None
    if chosen and llm.installed(chosen):
        found = chosen
    else:
        for name in MODELS:
            if llm.installed(name) or llm.installed(f"{name}:latest"):
                found = name
                break
    _state["model"] = found
    return found


def available() -> bool:
    return bool(model())


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vectors for a list of texts, or None if it could not be done.

    Batched deliberately: one text costs about 109ms and sixty-four cost 15ms
    each, so indexing in batches is seven times cheaper than one at a time.
    """
    name = model()
    if not name or not texts:
        return None
    payload = {"model": name, "input": texts, "keep_alive": KEEP_ALIVE}
    req = urllib.request.Request(
        llm.HOST + "/api/embed", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.loads(r.read()).get("embeddings")
    except Exception:
        return None
    if not out or len(out) != len(texts):
        return None
    return out


def embed_one(text: str) -> list[float] | None:
    got = embed([text])
    return got[0] if got else None


# ------------------------------------------------------------------ storage
def pack(vector: list[float]) -> bytes:
    """A vector as bytes for SQLite.

    float32, not float64: half the disk and half the bytes read per search, and
    the precision lost is far below what cosine similarity can distinguish.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))
