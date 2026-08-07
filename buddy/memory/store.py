"""Vector store — the disk + index behind buddy's memory.

Dead simple on purpose: one JSONL file per tier, each line a record with its
embedding inline. On load we stack the vectors into a numpy matrix and do a
cosine search. No database, no server, no torch. A few thousand memories search
in single-digit milliseconds, which is all a personal assistant needs.

Record shape (one JSON object per line):
  { "id", "kind", "text", "meta", "ts", "vec": [float, ...] | null }

If the embedder is unavailable, records are stored with vec=null and search
falls back to word overlap, so the light client keeps working.
"""
import os, json, time, uuid
import numpy as np

from buddy import embedder


def _now():
    return time.time()


def _cos(mat, q):
    # mat: (n, d), q: (d,) -> (n,) cosine similarity, rows/q assumed non-zero
    qn = q / (np.linalg.norm(q) + 1e-9)
    mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    return mn @ qn


def _overlap(text, query):
    a = set(text.lower().split())
    b = set(query.lower().split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Store:
    """One JSONL file. Append-only writes, in-memory cosine index."""

    def __init__(self, path, cfg):
        self.path = path
        self.cfg = cfg
        self._records = []      # list of dicts (without vec)
        self._mat = None        # (n, d) float32 or None
        self._loaded = False

    # ---- load ----
    def _load(self):
        if self._loaded:
            return
        self._records, vecs = [], []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    v = r.pop("vec", None)
                    self._records.append(r)
                    vecs.append(v)
        # build matrix only from records that actually have a vector
        dim = next((len(v) for v in vecs if v), None)
        if dim:
            m = np.zeros((len(vecs), dim), dtype="float32")
            for i, v in enumerate(vecs):
                if v:
                    m[i] = np.asarray(v, dtype="float32")
            self._mat = m
        else:
            self._mat = None
        self._loaded = True

    # ---- write ----
    def add(self, kind, text, meta=None):
        self._load()
        vec = None
        try:
            if embedder.available(self.cfg):
                vec = embedder.embed([text], self.cfg)[0].astype("float32")
        except Exception:
            vec = None
        rec = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "text": text,
            "meta": meta or {},
            "ts": _now(),
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            out = dict(rec)
            out["vec"] = vec.tolist() if vec is not None else None
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        # keep the in-memory index in sync
        self._records.append(rec)
        if vec is not None:
            if self._mat is None:
                self._mat = vec.reshape(1, -1)
            elif self._mat.shape[1] == vec.shape[0]:
                self._mat = np.vstack([self._mat, vec])
        return rec["id"]

    # ---- read ----
    def search(self, query, k=5, min_score=0.0):
        self._load()
        if not self._records:
            return []
        scored = []
        if self._mat is not None and embedder.available(self.cfg):
            try:
                q = embedder.embed([query], self.cfg)[0].astype("float32")
                sims = _cos(self._mat, q)
                # records without a vector got a zero row -> score ~0, fine
                for r, s in zip(self._records, sims):
                    scored.append((float(s), r))
            except Exception:
                scored = None
        else:
            scored = None
        if scored is None:                              # embed path failed -> word overlap
            scored = [(_overlap(r["text"], query), r) for r in self._records]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**r, "score": round(s, 3)} for s, r in scored[:k] if s >= min_score]

    def recent(self, n=10):
        self._load()
        return list(reversed(self._records[-n:]))

    def all(self):
        self._load()
        return list(self._records)
