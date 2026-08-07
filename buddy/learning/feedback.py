"""The 'am I doing this right?' loop.

New employees check their work. So does buddy: the first `ask_to_confirm_first_n`
times it runs a given skill, it asks whether it got it right. Your answer becomes a
lesson:

  - "yes"            -> reinforce (episodic memory: this routing was correct)
  - "no, it was X"   -> correction (procedural lesson + feeds the classifier retrain)

Once a skill has been confirmed enough times, buddy stops asking and just does it.
Counts live in ~/.virtualbuddy/data/skill_confidence.json.

This module is state + helpers; agent.py calls should_confirm() after a skill runs
and record_verdict() when the user replies. Pending state is per-process (the last
action awaiting a verdict).
"""
import os, json, re

from buddy import settings
from buddy.memory import memory as mem

_COUNTS = os.path.join(settings.data_dir(), "skill_confidence.json")

_YES = ("yes", "yep", "yeah", "correct", "right", "good", "perfect", "that's it", "nice")
_NO = ("no", "nope", "wrong", "not right", "incorrect", "that's wrong")
_FIX_RE = re.compile(r"(?:no|wrong|actually)[,\s]+(?:it(?:'s| was| should be)?\s+)?(.*)", re.I)


def _load():
    if os.path.exists(_COUNTS):
        try:
            return json.load(open(_COUNTS, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(d):
    json.dump(d, open(_COUNTS, "w", encoding="utf-8"), indent=2)


def confirmed_count(skill_name):
    return _load().get(skill_name, 0)


def should_confirm(skill_name, cfg):
    """True while buddy is still learning this skill and should ask."""
    if not cfg.get("learning_enabled", True):
        return False
    n = cfg.get("ask_to_confirm_first_n", 5)
    return confirmed_count(skill_name) < n


class Pending:
    """Holds the last action awaiting a yes/no verdict (per process)."""
    text = None
    skill = None

    @classmethod
    def set(cls, text, skill):
        cls.text, cls.skill = text, skill

    @classmethod
    def clear(cls):
        cls.text, cls.skill = None, None

    @classmethod
    def active(cls):
        return cls.skill is not None


def ask_line(skill_name):
    return f"(still learning '{skill_name}') — did I get that right? say yes, or 'no, it was <skill>'."


def is_verdict(text):
    low = (text or "").lower().strip()
    return low.startswith(_YES) or low.startswith(_NO)


def record_verdict(text, cfg):
    """Consume a yes/no reply for the pending action. Returns a short reply or None."""
    if not Pending.active():
        return None
    low = (text or "").lower().strip()
    skill, cmd = Pending.skill, Pending.text
    counts = _load()

    if low.startswith(_YES):
        counts[skill] = counts.get(skill, 0) + 1
        _save(counts)
        mem.get(cfg).note_episode(f"'{cmd}' -> {skill} (confirmed correct)")
        Pending.clear()
        left = max(0, cfg.get("ask_to_confirm_first_n", 5) - counts[skill])
        tail = "" if left else " I've got this one now — won't ask again."
        return "Great, noted." + tail

    if low.startswith(_NO):
        fix = _FIX_RE.match(text or "")
        correct = (fix.group(1).strip() if fix else "").strip(" .")
        mem.get(cfg).learn_procedure(
            f"'{cmd}' should be handled by '{correct or 'a different skill'}', not '{skill}'")
        if correct:
            try:
                from buddy.corrections import log_correction
                log_correction(cmd, correct)          # feeds the 2-bot classifier retrain
            except Exception:
                pass
        Pending.clear()
        return (f"Sorry — logged that '{cmd}' should be '{correct}'. "
                f"Run !train to bake it in." if correct
                else "Logged as wrong. What should it have been?")
    return None
