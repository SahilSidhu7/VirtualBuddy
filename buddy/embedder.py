"""Turns text into vectors for intent matching. Backends, best first:
  1. Ollama embeddings (nomic-embed-text) - light, already installed with the brain.
  2. sentence-transformers (all-MiniLM) - only if installed.
  3. none -> caller falls back to word overlap.

Keeping this on Ollama means the app needs NO torch, so installers stay small.
"""
import json, urllib.request
import numpy as np

_backend = None      # "ollama" | "st" | "none" | None(unknown)
_st_model = None

def _embed_call(base, model, chunk):
    body = json.dumps({"model": model, "input": chunk, "keep_alive": "30m"}).encode()
    req = urllib.request.Request(base + "/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["embeddings"]

def _ollama_embed(texts, cfg):
    base = cfg.get("ollama_url", "http://localhost:11434")
    model = cfg.get("embed_model", "nomic-embed-text")
    out = []
    for i in range(0, len(texts), 64):                  # batch for speed (Ollama caps ~256)
        chunk = texts[i:i + 64]
        try:
            out.extend(_embed_call(base, model, chunk))
        except Exception:
            for t in chunk:                              # fall back to one-at-a-time
                out.extend(_embed_call(base, model, [t]))
    return np.array(out, dtype="float32")

def available(cfg):
    global _backend, _st_model
    if _backend is not None:
        return _backend != "none"
    try:
        _ollama_embed(["ping"], cfg)
        _backend = "ollama"
        print("[embedder] using Ollama embeddings.")
        return True
    except Exception:
        pass
    try:
        import os
        os.environ.setdefault("USE_TF", "0")
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        _backend = "st"
        print("[embedder] using sentence-transformers.")
        return True
    except Exception:
        _backend = "none"
        return False

def backend():
    return _backend

def embed(texts, cfg):
    if isinstance(texts, str):
        texts = [texts]
    if _backend is None:
        available(cfg)
    if _backend == "ollama":
        return _ollama_embed(texts, cfg)
    if _backend == "st":
        return np.array(_st_model.encode(texts), dtype="float32")
    raise RuntimeError("no embedder available")
