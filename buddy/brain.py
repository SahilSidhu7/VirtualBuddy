"""The brain: understands a command and picks the right skill.

How: embed the user's words, compare to each skill's example phrases,
best match wins. If nothing is close enough -> hand to Claude.

If sentence-transformers isn't installed, falls back to simple word
overlap so text mode still works with zero installs.
"""
from buddy.skills import all_skills

_model = None
_index = []          # embed mode: list of (skill, phrase_vector)
_use_embed = None    # None=unknown, True/False once decided
_clf = None          # trained intent classifier (from the 2-bot loop), if any
_skill_by_name = {}

def _try_model():
    global _model, _use_embed
    if _use_embed is None:
        try:
            import os
            os.environ.setdefault("USE_TF", "0")  # torch backend only, skip TF/Keras
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")  # small, free, local
            _use_embed = True
        except Exception:
            _use_embed = False
            print("[brain] embeddings unavailable -> using simple word match. "
                  "pip install sentence-transformers for smarter matching.")
    return _use_embed

def _cos(a, b):
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

def _load_clf():
    """Use the trained classifier from the 2-bot loop if it exists (more accurate)."""
    global _clf, _skill_by_name
    import os, joblib
    path = os.path.join(os.path.dirname(__file__), "..", "models", "intent_clf.joblib")
    if os.path.exists(path):
        try:
            _clf = joblib.load(path)
            _skill_by_name = {s["name"]: s for s in all_skills()}
            print("[brain] using trained intent classifier.")
        except Exception:
            _clf = None

def reload():
    """Drop the cached classifier + index and rebuild (after retraining)."""
    global _clf, _index
    _clf, _index = None, []
    build()

def build():
    """Embed every skill's phrases once at startup (embed mode only)."""
    global _index
    if not _try_model():
        return
    _load_clf()
    if _clf is None:  # only need cosine index when there's no classifier
        _index = [(sk, _model.encode(p)) for sk in all_skills() for p in sk["phrases"]]

def _overlap(text, phrase):
    a, b = set(text.lower().split()), set(phrase.lower().split())
    return len(a & b) / (len(b) or 1)

def route(text, threshold):
    """Return (skill, score). skill is None if below threshold."""
    if _try_model():
        if not _index and _clf is None:
            build()
        q = _model.encode(text)
        if _clf is not None:                          # trained classifier path
            import numpy as np
            proba = _clf["clf"].predict_proba([q])[0]
            i = int(np.argmax(proba))
            name = _clf["clf"].classes_[i]
            best, best_score = _skill_by_name.get(name), float(proba[i])
        else:                                          # raw cosine path
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
