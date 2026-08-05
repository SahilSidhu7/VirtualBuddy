"""Shared bits for the training bots. Local MiniLM encoder + paths."""
import os, sys
os.environ.setdefault("USE_TF", "0")

# let tools import the buddy package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MODELS = os.path.join(ROOT, "models")
CLF_PATH = os.path.join(MODELS, "intent_clf.joblib")
FAIL_PATH = os.path.join(DATA, "failures.jsonl")
SCORE_PATH = os.path.join(DATA, "score.json")
os.makedirs(DATA, exist_ok=True)

_enc = None
def encoder():
    global _enc
    if _enc is None:
        from sentence_transformers import SentenceTransformer
        _enc = SentenceTransformer("all-MiniLM-L6-v2")
    return _enc

def skill_phrases():
    """dict skill_name -> [base phrases]."""
    from buddy.skills import all_skills
    return {s["name"]: list(s["phrases"]) for s in all_skills()}
