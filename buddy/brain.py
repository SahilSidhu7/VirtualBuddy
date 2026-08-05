"""The brain: understands a command and picks the right skill.

Embeds the command + skill phrases (via Ollama or sentence-transformers), best
match wins. If a trained classifier exists (from the 2-bot loop) it's used
instead - more accurate. If no embedder at all, falls back to word overlap so
text mode still works.
"""
import os, numpy as np
from buddy import embedder
from buddy.skills import all_skills

_cfg = {}
_index = []          # [(skill, vec)] when using raw cosine
_clf = None          # trained classifier bundle
_skill_by_name = {}
_use_embed = None

def _cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

def _load_clf():
    global _clf, _skill_by_name
    import joblib
    from buddy import settings
    path = settings.clf_path()
    if os.path.exists(path):
        try:
            _clf = joblib.load(path)
            _skill_by_name = {s["name"]: s for s in all_skills()}
            print("[brain] using trained intent classifier.")
        except Exception:
            _clf = None

def build(cfg=None):
    global _cfg, _index, _use_embed
    if cfg is not None:
        _cfg = cfg
    _use_embed = embedder.available(_cfg)
    if not _use_embed:
        print("[brain] no embedder -> word match. (start Ollama or pip install sentence-transformers)")
        return
    _load_clf()
    if _clf is None:
        skills = all_skills()
        phrases = [p for s in skills for p in s["phrases"]]
        owners = [s for s in skills for _ in s["phrases"]]
        vecs = embedder.embed(phrases, _cfg)
        _index = list(zip(owners, vecs))

def reload(cfg=None):
    global _clf, _index
    _clf, _index = None, []
    build(cfg)

def _overlap(text, phrase):
    a, b = set(text.lower().split()), set(phrase.lower().split())
    return len(a & b) / (len(b) or 1)

def route(text, threshold):
    if _use_embed is None:
        build()
    if _use_embed:
        q = embedder.embed([text], _cfg)[0]
        if _clf is not None:
            proba = _clf["clf"].predict_proba([q])[0]
            i = int(np.argmax(proba))
            best = _skill_by_name.get(_clf["clf"].classes_[i])
            best_score = float(proba[i])
        else:
            best, best_score = None, -1.0
            for skill, vec in _index:
                s = _cos(q, vec)
                if s > best_score:
                    best, best_score = skill, s
    else:
        best, best_score = None, -1.0
        for skill in all_skills():
            s = max(_overlap(text, p) for p in skill["phrases"])
            if s > best_score:
                best, best_score = skill, s
    if best_score < threshold:
        return None, best_score
    return best, best_score
