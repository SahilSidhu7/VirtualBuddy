"""Learn from mistakes. When buddy picks the wrong skill, log the fix here.
The 2-bot builder reads these on its next run and trains on them -> buddy
stops making that mistake. All local, no tokens.
"""
import os, json
from buddy.skills import all_skills

_FAIL = os.path.join(os.path.dirname(__file__), "..", "data", "failures.jsonl")

def skill_names():
    return [s["name"] for s in all_skills()]

def log_correction(text, correct_skill):
    if correct_skill not in skill_names():
        return f"Unknown skill '{correct_skill}'. Options: {', '.join(skill_names())}"
    os.makedirs(os.path.dirname(_FAIL), exist_ok=True)
    with open(_FAIL, "a") as f:
        f.write(json.dumps({"text": text, "expected": correct_skill}) + "\n")
    return f"Got it - '{text}' should be {correct_skill}. Run !train to bake it in."
