"""Auto skill-writer — when nothing local can do a task, Claude writes a new skill.

Only runs if the user opted in (cfg.use_claude and cfg.claude_writes_skills). Flow:

  1. Ask Claude to FIRST write a short PLAN (how the command can be run on this PC),
     THEN output the complete skill file.
  2. Parse the ```python block, validate it (SKILLS list + callable run functions).
  3. Install it into buddy/skills/, refresh the skill registry.
  4. Run the matching function on the original command and return its reply.
  5. Record command -> skill on the command graph (so it routes there next time with
     slot-extracted parameters) and retrain the classifier in the background.

The skill file is the standard contract (see docs/SKILL_AUTHORING.md): one file, a
`SKILLS` list, each mapping a name + phrases to a callable run(text, ctx). Those
callables are what the command graph maps to and buddy runs with parameters.
"""
import os, re, json, time, subprocess, importlib.util

from buddy import settings
from buddy.skills import all_skills

_GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "docs", "SKILL_AUTHORING.md")


def _guide_text():
    try:
        with open(_GUIDE, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Define SKILLS = [{'name','phrases','run'}]; run(text, ctx) returns a string."


def _build_prompt(text, existing):
    return f"""{_guide_text()}

---
You are extending VirtualBuddy, a local PC assistant. The user asked buddy to do
something it has no skill for:

    USER COMMAND: "{text}"

Existing skill names (do NOT duplicate these): {', '.join(existing)}

Do this in two parts:

PART 1 — PLAN:
Write a short numbered plan (2-5 steps) describing exactly how this command can be
carried out on the user's PC using Python (which libraries/APIs/primitives, what the
function does, what it returns). Prefer the standard library and the helpers in the
guide. Keep it realistic and safe.

PART 2 — CODE:
Then output the COMPLETE skill file as a single ```python code block, following the
contract exactly: a module-level SKILLS list whose functions are the callables buddy
will run. Give phrases that cover how the user actually phrased the command above so
it routes to this skill next time. The run functions must return a short string and
handle their own errors.
"""


def _ask_claude(cli, prompt, timeout=180):
    try:
        r = subprocess.run([cli, "-p", prompt], capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def _extract(reply):
    """Return (plan_text, code) from Claude's answer."""
    m = re.search(r"```(?:python)?\s*(.*?)```", reply, re.S)
    code = m.group(1).strip() if m else None
    plan = reply[:m.start()].strip() if m else reply.strip()
    if not code and "SKILLS" in reply:      # model forgot the fence
        code = reply.strip()
    return plan, code


def _skill_names(code):
    return re.findall(r"""["']name["']\s*:\s*["']([a-zA-Z0-9_]+)["']""", code)


def _validate(path):
    """Exec the candidate file in isolation; return (module, error)."""
    try:
        spec = importlib.util.spec_from_file_location("_authored_candidate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return None, f"import failed: {e}"
    skills = getattr(mod, "SKILLS", None)
    if not isinstance(skills, list) or not skills:
        return None, "no SKILLS list"
    for s in skills:
        if not all(k in s for k in ("name", "phrases", "run")):
            return None, "a skill is missing name/phrases/run"
        if not callable(s["run"]):
            return None, "run is not callable"
    return mod, None


def _audit(entry):
    try:
        path = os.path.join(settings.memory_dir(), "authored_skills.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


class Pending:
    """A drafted skill waiting on the user's yes/no (approval gate)."""
    _draft = None

    @classmethod
    def set(cls, draft):
        cls._draft = draft

    @classmethod
    def pop(cls):
        d = cls._draft
        cls._draft = None
        return d

    @classmethod
    def clear(cls):
        cls._draft = None

    @classmethod
    def active(cls):
        return cls._draft is not None


def is_verdict(text):
    from buddy import planner
    return planner.is_verdict(text)


def _install_and_run(draft, ctx, on_done=None):
    """Copy the drafted skill into the package, run it, remember it, retrain."""
    text, fname = draft["text"], draft["name"]
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", f"{fname}.py")
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(draft["code"])
    except Exception as e:
        _audit({"cmd": text, "ok": False, "error": f"install: {e}", "ts": time.time()})
        return f"Couldn't install the new skill: {e}"

    from buddy import skills as _skills
    _skills.reload()

    mod = draft["mod"]
    skill = next((s for s in mod.SKILLS if s["name"] == fname), mod.SKILLS[0])
    try:
        result = skill["run"](text, ctx)
    except Exception as e:
        result = f"(new skill '{fname}' installed but errored: {e})"

    graph = ctx.get("graph")
    if graph:
        graph.record(text, fname, ok=True)
    mem = ctx.get("mem")
    if mem:
        mem.note_episode(f"authored skill '{fname}' for '{text}'")
    _audit({"cmd": text, "ok": True, "skill": fname, "plan": draft["plan"][:500], "ts": time.time()})

    try:
        from buddy import trainer
        trainer.train_async(on_done=on_done)
    except Exception:
        pass

    return f"(I didn't have a skill for that, so I wrote one: {fname}) {result}"


def confirm(text, ctx, on_done=None):
    """Handle yes/no for a drafted skill awaiting approval. Returns reply or None."""
    if not Pending.active():
        return None
    from buddy import planner
    t = text.lower().strip(" .!?")
    draft = Pending.pop()
    if t in planner._NO:
        _audit({"cmd": draft["text"], "ok": False, "error": "declined by user", "ts": time.time()})
        return f"Okay, I won't add the '{draft['name']}' skill."
    return _install_and_run(draft, ctx, on_done)


def try_author(text, ctx, on_done=None):
    """Return a reply string on success, or None to let the caller fall through."""
    cfg = ctx.get("cfg", {})
    cli = cfg.get("claude_cli", "claude")
    existing = [s["name"] for s in all_skills()]

    reply = _ask_claude(cli, _build_prompt(text, existing))
    if not reply:
        return None
    plan, code = _extract(reply)
    if not code:
        return None
    names = _skill_names(code)
    names = [n for n in names if n not in existing]     # skip dupes
    if not names:
        return None
    fname = names[0]

    # validate in a scratch location before touching the skills package
    scratch = os.path.join(settings.data_dir(), f"_authored_{fname}.py")
    with open(scratch, "w", encoding="utf-8") as f:
        f.write(code)
    mod, err = _validate(scratch)
    if err:
        _audit({"cmd": text, "ok": False, "error": err, "ts": time.time()})
        return None

    draft = {"text": text, "name": fname, "code": code, "plan": plan, "mod": mod}

    # approval gate: if on, show the plan and wait for the user's yes/no
    if cfg.get("skill_approval", True):
        Pending.set(draft)
        short = "\n".join(plan.splitlines()[:6]).strip() or "(no plan given)"
        return (f"I don't have a skill for that. Claude drafted one: '{fname}'.\n"
                f"{short}\nInstall & run it? (yes/no)")

    return _install_and_run(draft, ctx, on_done)
