"""Teaching — buddy 'goes to school' and bakes lessons into the brain.

This is the SLOW, HEAVY half of learning, and it runs ONLY on the server role
(the 1050ti). It batches procedural lessons and fine-tunes a small model with
QLoRA into a LoRA adapter, so the brain itself learns the job instead of leaning
on a lookup every time.

Design decisions (from research):
  * 4GB VRAM is below the comfortable QLoRA floor, so we target a *small* base
    model (0.5B-1.5B) via Unsloth's memory optimizations, and we BATCH lessons
    (teach_after_n_lessons) instead of training per-lesson.
  * To add knowledge without erasing old skills (catastrophic forgetting), we keep
    ONE adapter PER domain and train new ones orthogonally (O-LoRA style), rather
    than continually overwriting a single adapter.

This file is a real interface with a guarded body: without torch/unsloth installed
(the light client), every entry point no-ops with a clear message instead of crashing.
The training body is marked TODO and lands when requirements-server.txt is installed.
"""
import os, json, time

from buddy import settings
from buddy.memory.memory import TIERS  # noqa: F401  (procedural tier holds lessons)

_PROC = lambda: os.path.join(settings.memory_dir(), "procedural.jsonl")
_STATE = lambda: os.path.join(settings.data_dir(), "teach_state.json")


def _load_state():
    p = _STATE()
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {"last_taught_ts": 0.0, "runs": []}


def _save_state(s):
    json.dump(s, open(_STATE(), "w", encoding="utf-8"), indent=2)


def _new_lessons_since(ts):
    p = _PROC()
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ts", 0) > ts:
                out.append(r)
    return out


def pending_lesson_count(cfg=None):
    st = _load_state()
    return len(_new_lessons_since(st.get("last_taught_ts", 0)))


def should_teach(cfg):
    if cfg.get("role") != "server":
        return False
    if not cfg.get("learning_enabled", True):
        return False
    return pending_lesson_count(cfg) >= cfg.get("teach_after_n_lessons", 25)


def _gpu_stack_available():
    try:
        import torch  # noqa: F401
        import unsloth  # noqa: F401
        return True
    except Exception:
        return False


def teach(cfg, force=False):
    """Run one teaching cycle. Returns a status string; never raises for a missing GPU stack."""
    if cfg.get("role") != "server" and not force:
        return "teach: skipped (not the server role — teaching runs on the 1050ti host)."
    st = _load_state()
    lessons = _new_lessons_since(st.get("last_taught_ts", 0))
    if not lessons and not force:
        return "teach: nothing new to learn."
    if not _gpu_stack_available():
        return (f"teach: {len(lessons)} lesson(s) queued, but the training stack isn't installed. "
                f"On the server run:  pip install -r requirements-server.txt")

    # ---- TODO(phase 3): real QLoRA run ----
    # base = cfg.get("teach_base_model", "qwen2.5:0.5b")
    # 1. build SFT pairs from `lessons` (command -> correct skill/action, with memory context)
    # 2. FastLanguageModel.from_pretrained(base, load_in_4bit=True); add LoRA (r=8..16)
    #    gradient_checkpointing="unsloth", per_device_train_batch_size=1
    # 3. train a few hundred steps; save adapter -> settings.adapters_dir()/<domain>-<ts>/
    # 4. register the adapter so Ollama/brain loads it
    # Until that body is filled in, mark the batch consumed so we don't spin.
    adapter = os.path.join(settings.adapters_dir(), f"lessons-{int(time.time())}")
    os.makedirs(adapter, exist_ok=True)
    # confirmed command->skill pairs buddy learned from use are training data too
    try:
        from buddy.memory.graph import CommandGraph
        routes = [{"command": c, "skill": s} for c, s in CommandGraph(cfg).trainset()]
    except Exception:
        routes = []
    json.dump({"lessons": lessons, "routes": routes, "base": cfg.get("teach_base_model")},
              open(os.path.join(adapter, "trainset.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    st["last_taught_ts"] = time.time()
    st["runs"].append({"ts": st["last_taught_ts"], "n": len(lessons), "adapter": adapter})
    _save_state(st)
    return (f"teach: prepared {len(lessons)} lesson(s) at {adapter}. "
            f"QLoRA body is a TODO (phase 3) — trainset written, ready to train.")
