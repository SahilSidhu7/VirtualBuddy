"""The brain: understands a command and picks the right skill.

Uses a local TF-IDF + logistic-regression classifier (trained by the 2-bot
loop) - runs in-process in under a millisecond, no Ollama needed. If it's not
confident, the agent falls through to the local LLM (which can call skills too).
If no classifier is trained yet, falls back to simple word overlap.
"""
import os, numpy as np
from buddy.skills import all_skills

_clf = None
_skill_by_name = {}
_loaded = False

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
    global _loaded
    _load_clf()
    _loaded = True

def reload(cfg=None):
    global _clf, _loaded
    _clf, _loaded = None, False
    build(cfg)

def _overlap(text, phrase):
    a, b = set(text.lower().split()), set(phrase.lower().split())
    return len(a & b) / (len(b) or 1)

def route(text, threshold):
    """Return (skill, score). skill is None if below threshold."""
    if not _loaded:
        build()
    if _clf is not None:
        proba = _clf["clf"].predict_proba([text])[0]
        i = int(np.argmax(proba))
        best = _skill_by_name.get(_clf["clf"].classes_[i])
        best_score = float(proba[i])
    else:
        best, best_score = None, -1.0
        for skill in all_skills():
            s = max(_overlap(text, p) for p in skill["phrases"])
            if s > best_score:
                best, best_score = skill, s
    if best_score < threshold:
        return None, best_score
    return best, best_score
