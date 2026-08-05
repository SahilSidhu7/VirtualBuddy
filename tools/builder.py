"""BUILDER BOT: makes training data from skills + past failures, trains the
local intent classifier, saves it.

The classifier is a TF-IDF (word + char n-grams) + logistic regression pipeline.
It runs in-process in well under a millisecond - no Ollama needed for routing,
so every command is instant. Semantic edge cases fall through to the LLM.

Run: python tools/builder.py
"""
import json, os, joblib
from tools import common, augment

def load_failures():
    pairs = []
    if os.path.exists(common.FAIL_PATH):
        with open(common.FAIL_PATH) as f:
            for line in f:
                d = json.loads(line)
                pairs.append((d["text"], d["expected"]))
    return pairs

def make_clf():
    from sklearn.pipeline import Pipeline, FeatureUnion
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    vec = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2))),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))),
    ])
    return Pipeline([("vec", vec), ("lr", LogisticRegression(max_iter=2000, C=10))])

def main():
    phrases = common.skill_phrases()
    texts, labels = [], []
    for name, base in phrases.items():
        for t in augment.build_set(base):
            texts.append(t); labels.append(name)
    extra = load_failures()
    for t, lab in extra:
        texts.append(t); labels.append(lab)

    print(f"[builder] {len(texts)} examples over {len(phrases)} skills (+{len(extra)} from failures)")
    clf = make_clf().fit(texts, labels)
    acc = clf.score(texts, labels)
    joblib.dump({"clf": clf, "labels": sorted(set(labels))}, common.CLF_PATH)
    print(f"[builder] trained. train-acc {acc:.2f}. saved {common.CLF_PATH}")

if __name__ == "__main__":
    main()
