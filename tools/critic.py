"""CRITIC BOT: tests the trained classifier on UNSEEN wording, logs every miss
so the builder can learn from it next round. Writes an accuracy score.

Run: python tools/critic.py
"""
import json, os, joblib
from tools import common, augment

def main():
    if not os.path.exists(common.CLF_PATH):
        print("[critic] no classifier yet - run builder first."); return
    bundle = joblib.load(common.CLF_PATH)
    clf = bundle["clf"]

    phrases = common.skill_phrases()
    tests, expected = [], []
    for name, base in phrases.items():
        for t in augment.test_set(base):
            tests.append(t); expected.append(name)

    preds = clf.predict(tests)     # pipeline vectorizes raw text

    fails = []
    for t, exp, got in zip(tests, expected, preds):
        if got != exp:
            fails.append({"text": t, "expected": exp, "got": got})
    acc = 1 - len(fails) / len(tests)

    with open(common.FAIL_PATH, "w") as f:      # overwrite: only current misses
        for d in fails:
            f.write(json.dumps(d) + "\n")
    with open(common.SCORE_PATH, "w") as f:
        json.dump({"accuracy": round(acc, 4), "tested": len(tests), "failed": len(fails)}, f)

    print(f"[critic] accuracy {acc:.2%} on {len(tests)} unseen phrasings, {len(fails)} misses")
    for d in fails[:8]:
        print(f"   MISS: '{d['text']}' -> {d['got']} (want {d['expected']})")
    return acc

if __name__ == "__main__":
    main()
