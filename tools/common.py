"""Shared bits for the training bots. Local MiniLM encoder + paths."""
import os, sys
os.environ.setdefault("USE_TF", "0")

# let tools import the buddy package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from buddy import settings                       # user-dir paths (survive updates)
DATA = settings.data_dir()
MODELS = settings.models_dir()
CLF_PATH = settings.clf_path()
FAIL_PATH = os.path.join(DATA, "failures.jsonl")
SCORE_PATH = os.path.join(DATA, "score.json")

_cfg = None
def cfg():
    global _cfg
    if _cfg is None:
        from buddy.settings import load
        _cfg = load()
    return _cfg

def embed(texts):
    """Same embedder the runtime brain uses, so training + inference match."""
    from buddy import embedder
    return embedder.embed(texts, cfg())

def skill_phrases():
    """dict skill_name -> [base phrases]."""
    from buddy.skills import all_skills
    return {s["name"]: list(s["phrases"]) for s in all_skills()}
