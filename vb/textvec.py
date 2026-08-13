"""Fast in-process text vectors — no model, no network, sub-millisecond.

Routing only needs a surface-similarity answer: "which skill phrase does this
look like?". Hashed word and character n-grams answer that instantly. Hashing
(not TF-IDF) means there is nothing to fit and nothing to persist: the same
text always maps to the same vector, in this run and the next.

This was scikit-learn's HashingVectorizer until the packaged build turned out
to weigh 227MB, nearly all of it scikit-learn and scipy pulled in for this one
class. The maths is small enough to own: hash each n-gram into a fixed number
of bins, count, and normalise. crc32 rather than hash() because Python
randomises string hashing per process, and vectors have to mean the same thing
tomorrow.
"""
from __future__ import annotations

import re
from zlib import crc32

import numpy as np

DIM = 512               # bins per block; word block and char block are separate
WORDS = re.compile(r"[\w']+")
WORD_NGRAMS = (1, 2)
CHAR_NGRAMS = (3, 5)


def available() -> bool:
    return True


def _bins(text: str) -> np.ndarray:
    vec = np.zeros(DIM * 2, dtype="float32")
    lowered = text.lower()
    words = WORDS.findall(lowered)

    for n in range(WORD_NGRAMS[0], WORD_NGRAMS[1] + 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i:i + n]).encode("utf-8", "ignore")
            vec[crc32(gram) % DIM] += 1.0

    # Character n-grams inside word boundaries, the way sklearn's char_wb does
    # it: pad each word so that prefixes and suffixes get their own grams.
    for word in words:
        padded = f" {word} "
        for n in range(CHAR_NGRAMS[0], CHAR_NGRAMS[1] + 1):
            for i in range(len(padded) - n + 1):
                gram = padded[i:i + n].encode("utf-8", "ignore")
                vec[DIM + crc32(gram) % DIM] += 1.0
    return vec


def encode(texts) -> np.ndarray:
    """(n, 2*DIM) float32, L2-normalised. Accepts a string or a list."""
    if isinstance(texts, str):
        texts = [texts]
    matrix = np.vstack([_bins(t) for t in texts]) if texts \
        else np.zeros((0, DIM * 2), dtype="float32")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / (norms + 1e-9)


def similarity(mat: np.ndarray, vec: np.ndarray) -> np.ndarray:
    """Cosine of one vector against a matrix of already-normalised rows."""
    return mat @ (vec / (np.linalg.norm(vec) + 1e-9))
