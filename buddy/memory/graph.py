"""Command graph — buddy's memory of *how it got things done*.

The idea (what the user asked for): when a command comes in, look for a similar
command buddy has already made work. If found, just do that skill again. If not,
fall back to normal routing / learning, and remember the result. Over days of use
(and the odd correction) this graph becomes buddy's real skill — routing that fits
*you*, not a generic classifier.

Structure is a small graph, persisted as one JSON file:
  nodes  : each a command buddy ran -> {id, text, skill, ok, bad, vec, ts}
  skills : per-skill tally {name: {ok, bad}}  (the command--skill edges, weighted)

Similarity is cosine over the node embeddings (same embedder as the rest of memory,
so no new deps; degrades to word-overlap if embeddings are unavailable).

Confirmed successes here are also the training set the fine-tuner (teach.py) batches
up — so "using buddy" and "training buddy" become the same act.
"""
import os, json, time, uuid
import numpy as np

from buddy import embedder, settings, textvec


def _cos(mat, q):
    qn = q / (np.linalg.norm(q) + 1e-9)
    mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    return mn @ qn


def _overlap(a, b):
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class CommandGraph:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = os.path.join(settings.memory_dir(), "command_graph.json")
        self.hit = float(cfg.get("cmd_sim_hit", 0.82))      # >= this to reuse a known skill
        self.dedup = float(cfg.get("cmd_sim_dedup", 0.93))   # >= this = same command, just bump
        # fast mode: hashed n-grams in-process (default). Calling an embedding model
        # here cost ~2s per command and was buddy's worst source of lag.
        self.fast = cfg.get("graph_vectors", "fast") != "embed" and textvec.available()
        self.nodes = []
        self.skills = {}
        self._mat = None
        self._load()

    # ---- persistence ----
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self.nodes = d.get("nodes", [])
                self.skills = d.get("skills", {})
            except Exception:
                self.nodes, self.skills = [], {}
        self._rebuild_matrix()

    def _rebuild_matrix(self):
        if self.fast:
            # vectors are recomputed from text — instant, and nothing to keep in the file
            self._mat = textvec.encode([n["text"] for n in self.nodes]) if self.nodes else None
            return
        vecs = [n.get("vec") for n in self.nodes if n.get("vec")]
        if vecs and len(vecs) == len(self.nodes):
            self._mat = np.asarray(vecs, dtype="float32")
        else:
            self._mat = None

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"nodes": self.nodes, "skills": self.skills}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _embed(self, text):
        if self.fast:
            return textvec.encode(text)[0]
        try:
            if embedder.available(self.cfg):
                return embedder.embed([text], self.cfg)[0].astype("float32")
        except Exception:
            pass
        return None

    # ---- search ----
    def _nearest(self, text, vec):
        """(index, score) of the most similar stored command, or (None, 0.0)."""
        if not self.nodes:
            return None, 0.0
        if vec is not None and self._mat is not None and self._mat.shape[0] == len(self.nodes):
            sims = _cos(self._mat, vec)
            i = int(np.argmax(sims))
            return i, float(sims[i])
        # no embeddings -> word overlap
        scored = [(_overlap(n["text"], text), i) for i, n in enumerate(self.nodes)]
        s, i = max(scored)
        return i, float(s)

    def recall(self, text):
        """(skill_name, score) if buddy has a confident, net-positive match; else (None, score)."""
        if not self.cfg.get("command_memory", True):
            return None, 0.0
        vec = self._embed(text)
        i, score = self._nearest(text, vec)
        if i is None or score < self.hit:
            return None, score
        node = self.nodes[i]
        if node["ok"] <= node["bad"]:            # this command mapping has been contradicted
            return None, score
        return node["skill"], score

    # ---- learning ----
    def record(self, text, skill, ok=True):
        """Reinforce (or penalise) the mapping command->skill.
        Near-duplicate of an existing node -> bump it; otherwise add a new node."""
        text = (text or "").strip()
        if not text or not skill:
            return
        vec = self._embed(text)
        # find an existing node for the SAME skill that's basically this command
        best_i, best_s = None, 0.0
        same_skill = [i for i, n in enumerate(self.nodes) if n["skill"] == skill]
        if same_skill and vec is not None and self._mat is not None \
                and self._mat.shape[0] == len(self.nodes):
            sims = _cos(self._mat[same_skill], vec)
            j = int(np.argmax(sims))
            best_i, best_s = same_skill[j], float(sims[j])
        else:
            for i in same_skill:
                s = _overlap(self.nodes[i]["text"], text)
                if s > best_s:
                    best_i, best_s = i, s
        if best_i is not None and best_s >= self.dedup:
            self.nodes[best_i]["ok" if ok else "bad"] += 1
            self.nodes[best_i]["ts"] = time.time()
        else:
            self.nodes.append({
                "id": uuid.uuid4().hex[:12], "text": text, "skill": skill,
                "ok": 1 if ok else 0, "bad": 0 if ok else 1,
                # fast vectors are recomputed from text on load — don't bloat the file
                "vec": None if self.fast else (vec.tolist() if vec is not None else None),
                "ts": time.time(),
            })
            self._rebuild_matrix()
        tally = self.skills.setdefault(skill, {"ok": 0, "bad": 0})
        tally["ok" if ok else "bad"] += 1
        self._save()

    def penalize(self, text, skill):
        self.record(text, skill, ok=False)

    # ---- for the fine-tuner / dashboard ----
    def trainset(self):
        """Confirmed (command, skill) pairs — the fine-tune / retrain material."""
        return [(n["text"], n["skill"]) for n in self.nodes if n["ok"] > n["bad"]]

    def stats(self):
        good = sum(1 for n in self.nodes if n["ok"] > n["bad"])
        return {"commands": len(self.nodes), "learned": good, "skills": len(self.skills)}
