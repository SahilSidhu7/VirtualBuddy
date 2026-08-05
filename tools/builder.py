"""BUILDER BOT: makes training data from skills + past failures, trains the
local intent classifier (logistic head on MiniLM embeddings), saves it.

Run: python tools/builder.py
"""
import json, os, joblib
from tools import common, augment

def load_failures():
    """Critic's misses: reuse them as extra training examples with correct label."""
    pairs = []
    if os.path.exists(common.FAIL_PATH):
        with open(common.FAIL_PATH) as f:
            for line in f:
                d = json.loads(line)
                pairs.append((d["text"], d["expected"]))
    return pairs

def main():
    phrases = common.skill_phrases()
    texts, labels = [], []
    for name, base in phrases.items():
        for t in augment.build_set(base):
            texts.append(t); labels.append(name)

    extra = load_failures()
    for t, lab in extra:
        texts.append(t); labels.append(lab)

    print(f"[builder] {len(texts)} examples over {len(phrases)} skills "
          f"(+{len(extra)} from failures)")

    from sklearn.linear_model import LogisticRegression
    X = common.embed(texts)
    clf = LogisticRegression(max_iter=1000, C=8.0)
    clf.fit(X, labels)
    acc = clf.score(X, labels)
    joblib.dump({"clf": clf, "labels": sorted(set(labels))}, common.CLF_PATH)
    print(f"[builder] trained. train-acc {acc:.2f}. saved {common.CLF_PATH}")

if __name__ == "__main__":
    main()
