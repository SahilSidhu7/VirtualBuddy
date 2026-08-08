"""Planner — turn an unknown command into a plan of primitives, run it, remember it.

This is v3 step 5 (see docs/ARCHITECTURE_V3.md). It runs only when the classifier
and command graph both miss, i.e. from agent._fallback. Flow:

  build plan (small local LLM, JSON) -> validate against the primitive catalog
  -> if any step is risk:confirm, hold the plan and ask the user (yes/no)
  -> execute -> on success, save as a learned skill so next time it's instant.

No code generation: the model only *chooses* primitives + fills their args.
"""
import json, os, re

from buddy import llm, primitives, settings


def _store_path():
    return os.path.join(settings.memory_dir(), "plans.json")


def _load_store():
    try:
        with open(_store_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(store):
    tmp = _store_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _store_path())

_PLAN_SYS = (
    "You are Buddy's planner. Turn the user's request into a short plan using ONLY "
    "these primitives:\n{catalog}\n\n"
    "Reply with ONLY a JSON array of steps, each {{\"primitive\": name, \"args\": {{...}}}}. "
    "Use the fewest steps. If the request cannot be done with these primitives, reply []."
)


class Pending:
    """A plan waiting on the user's yes/no (because it has a confirm-risk step)."""
    _text = None
    _plan = None

    @classmethod
    def set(cls, text, plan):
        cls._text, cls._plan = text, plan

    @classmethod
    def clear(cls):
        cls._text = cls._plan = None

    @classmethod
    def active(cls):
        return cls._plan is not None


_YES = {"yes", "y", "yeah", "yep", "do it", "go", "sure", "ok", "okay", "run it"}
_NO = {"no", "n", "nope", "cancel", "stop", "don't", "dont"}


def is_verdict(text):
    t = text.lower().strip(" .!?")
    return t in _YES or t in _NO


def _parse_plan(raw):
    """Pull the JSON array out of the model's reply; keep only valid primitive steps."""
    m = re.search(r"\[.*\]", raw or "", re.S)
    if not m:
        return []
    try:
        steps = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for s in steps if isinstance(steps, list) else []:
        name = (s or {}).get("primitive")
        if name in primitives.PRIMITIVES:
            out.append({"primitive": name, "args": s.get("args") or {}})
    return out


def _preview(plan):
    return "\n".join(
        f"  {i+1}. {s['primitive']}({', '.join(f'{k}={v!r}' for k, v in s['args'].items())})"
        for i, s in enumerate(plan))


def build_plan(text, cfg):
    catalog = primitives.catalog(cfg)
    msg = llm.chat([{"role": "system", "content": _PLAN_SYS.format(catalog=catalog)},
                    {"role": "user", "content": text}], cfg)
    return _parse_plan(msg.get("content", ""))


def _execute(text, plan, ctx):
    cfg = ctx.get("cfg", {})
    results = []
    for s in plan:
        results.append(primitives.run(s["primitive"], s["args"]))
    reply = " ".join(r for r in results if r) or "Done."
    _remember(text, plan, ctx)
    return reply


def _remember(text, plan, ctx):
    """Save the working plan so the same command is instant next time (no LLM)."""
    mem = ctx.get("mem")
    names = "+".join(s["primitive"] for s in plan)
    if mem:
        mem.note_episode(f"planned '{text}' -> [{names}]")
    store = _load_store()
    store[text.lower().strip()] = plan
    _save_store(store)


def recall(text):
    """Exact-match a previously-saved plan so a learned command skips the LLM."""
    return _load_store().get(text.lower().strip())


def run(text, ctx):
    """Entry from agent fallback. Returns a reply string."""
    cfg = ctx.get("cfg", {})
    if not cfg.get("planner_enabled", True):
        return None
    saved = recall(text)                  # learned this exact command before? skip the LLM
    if saved:
        return _execute(text, saved, ctx)
    plan = build_plan(text, cfg)
    if not plan:
        return None                       # planner can't help -> caller tries web/Claude
    if any(primitives.needs_confirm(s["primitive"]) for s in plan):
        Pending.set(text, plan)
        return f"Here's my plan:\n{_preview(plan)}\nRun it? (yes/no)"
    return _execute(text, plan, ctx)      # all-safe plan -> just do it


def confirm(text, ctx):
    """Handle the user's yes/no to a pending plan. Returns reply or None."""
    if not Pending.active():
        return None
    t = text.lower().strip(" .!?")
    plan, cmd = Pending._plan, Pending._text
    Pending.clear()
    if t in _NO:
        return "Cancelled."
    return _execute(cmd, plan, ctx)
