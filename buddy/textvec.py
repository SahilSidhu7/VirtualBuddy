"""Fast in-process text vectors — no model, no network, sub-millisecond.

The command graph only needs to answer "is this basically the same command I ran
before?". That's a surface-similarity question, and hashed word+character n-grams
answer it instantly. Calling out to Ollama for an embedding cost ~2 seconds per
command, three times per turn — it was the single biggest source of lag.

Hashing (not TF-IDF) means there is nothing to fit and nothing to persist: the
same text always maps to the same vector, in this run and the next.
"""
import numpy as np

_DIM = 512
_vec = None


def _vectorizer():
    global _vec
    if _vec is None:
        from sklearn.feature_extraction.text import HashingVectorizer
        from sklearn.pipeline import FeatureUnion
        _vec = FeatureUnion([
            ("w", HashingVectorizer(analyzer="word", ngram_range=(1, 2),
                                    n_features=_DIM, alternate_sign=False, norm=None)),
            ("c", HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                    n_features=_DIM, alternate_sign=False, norm=None)),
        ])
    return _vec


def available():
    try:
        _vectorizer()
        return True
    except Exception:
        return False


def encode(texts):
    """(n, 2*_DIM) float32, L2-normalised. Accepts a string or a list."""
    if isinstance(texts, str):
        texts = [texts]
    m = _vectorizer().transform(texts).toarray().astype("float32")
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / (n + 1e-9)


def similarity(mat, vec):
    """Cosine of one vector against a matrix of already-normalised rows."""
    return mat @ (vec / (np.linalg.norm(vec) + 1e-9))
