"""Turning text into vectors, through NVIDIA's free embedding endpoint.

Keyword search cannot answer "what am I working on". The words in the question
appear in none of the notes that would answer it, so BM25 scores them all zero
and the buddy says it remembers nothing while the answer sits in the table. A
vector search finds it, because "working on" and "project" land near each other
whether or not they share a letter.

This used to run nomic-embed-text in a local Ollama. It now asks the API, with
the same model for everything (`vb.provider.EMBED_MODEL`, 2048 dimensions).
Vectors are stored with the name of the model that made them, so the old 768
dimension ones are simply never matched and get re-made by the backfill.

Retrieval models are asymmetric: a search is embedded as a "query" and what it
searches as "passage". Mixing them up costs accuracy without raising an error.

Everything degrades rather than fails. No key, no network: callers get None
and fall back to keyword search, which is worse but is not nothing.
"""
from __future__ import annotations

import struct

from vb import config, provider

_state: dict = {}


def model() -> str | None:
    """The embedding model to use, or None when there is no key."""
    if not provider.api_key():
        return None
    return config.get("embed_model") or provider.EMBED_MODEL


def available() -> bool:
    return bool(model())


def embed(texts: list[str], input_type: str = "passage") -> list[list[float]] | None:
    """Vectors for a list of texts, or None if it could not be done. Batched,
    because one request for sixty-four texts is one request against the rate
    limit instead of sixty-four."""
    if not model() or not texts:
        return None
    out = []
    for i in range(0, len(texts), 64):
        got = provider.embed(texts[i:i + 64], input_type=input_type)
        if not got:
            return None
        out.extend(got)
    return out


def embed_one(text: str, input_type: str = "passage") -> list[float] | None:
    got = embed([text], input_type=input_type)
    return got[0] if got else None


def embed_query(text: str) -> list[float] | None:
    return embed_one(text, input_type="query")


# ------------------------------------------------------------------ storage
def pack(vector: list[float]) -> bytes:
    """A vector as bytes for SQLite.

    float32, not float64: half the disk and half the bytes read per search, and
    the precision lost is far below what cosine similarity can distinguish.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))
