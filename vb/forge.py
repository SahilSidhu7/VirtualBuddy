"""Tools the buddy writes for itself, so the second time is fast.

`learning.py` already keeps notes: after a good run it writes down how the job
was done, and the next similar request gets that note in its prompt. That
helps the model choose, but the model still runs the whole loop — five or ten
API calls and a few scripts — every single time.

This is the next step up. After a run that worked and survived the critic,
the work model turns what the loop did into one Python function with named
arguments. The function is **run before it is kept**, on the same request the
loop just answered, and kept only if it gives the same answer. From then on
the router can send a matching request straight to it: one fast-model call to
fill in the arguments, one script, no loop.

On disk, one folder per tool in `~/.virtualbuddy/tools/<name>/`:

    tool.json   name, description, phrases, params, counters
    tool.py     `def run(...) -> str`, the code itself

Plain files on purpose. They can be read, edited or deleted by hand, and a tool
that turns out wrong is quarantined after three failures rather than trusted
forever.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from vb import config, progress, sandbox

MAX_FAILS = 3
MAX_TOOLS = 150
SCRIPT_TIMEOUT = 120

# Steps that mean the loop did real work a function could repeat. A run that
# only called one built-in skill is already a fast path and needs no tool.
WORK_STEPS = {"run_python", "run_shell"}
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
_lock = threading.Lock()


@dataclass
class Forged:
    name: str
    description: str
    phrases: list[str]
    params: dict                    # name -> {"type", "description"}
    required: list[str]
    code: str
    danger: bool = False
    created: float = 0.0
    uses: int = 0
    fails: int = 0
    quarantined: bool = False
    source: str = ""                # the request it was learned from
    extra: dict = field(default_factory=dict)

    @property
    def folder(self) -> Path:
        return tools_dir() / self.name

    def meta(self) -> dict:
        return {k: getattr(self, k) for k in (
            "name", "description", "phrases", "params", "required", "danger",
            "created", "uses", "fails", "quarantined", "source")}


def tools_dir() -> Path:
    return config.data_dir("tools")


# ---------------------------------------------------------------- storage
def load(name: str) -> Forged | None:
    folder = tools_dir() / name
    try:
        meta = json.loads((folder / "tool.json").read_text("utf-8"))
        code = (folder / "tool.py").read_text("utf-8")
    except (OSError, json.JSONDecodeError):
        return None
    known = {k: meta[k] for k in Forged.__dataclass_fields__ if k in meta
             and k not in ("code", "extra")}
    return Forged(code=code, **known)


def all_forged(include_quarantined: bool = False) -> list[Forged]:
    out = []
    for folder in sorted(tools_dir().iterdir()) if tools_dir().exists() else []:
        if folder.is_dir():
            tool = load(folder.name)
            if tool and (include_quarantined or not tool.quarantined):
                out.append(tool)
    return out


def save(tool: Forged) -> None:
    with _lock:
        tool.folder.mkdir(parents=True, exist_ok=True)
        (tool.folder / "tool.py").write_text(tool.code, "utf-8")
        (tool.folder / "tool.json").write_text(
            json.dumps(tool.meta(), indent=2), "utf-8")


def forget(name: str) -> bool:
    folder = tools_dir() / name
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    _reregister()
    return True


def _bump(tool: Forged, ok: bool) -> None:
    fresh = load(tool.name) or tool
    if ok:
        fresh.uses += 1
    else:
        fresh.fails += 1
        if fresh.fails >= MAX_FAILS and fresh.fails > fresh.uses:
            fresh.quarantined = True
    save(fresh)
    if fresh.quarantined:
        _reregister()


# -------------------------------------------------------------- execution
def execute(tool: Forged, args: dict, *, approved: bool = False) -> tuple[bool, str]:
    """Run a forged tool in the sandbox. (ok, output)."""
    call = {k: v for k, v in args.items() if k in tool.params}
    script = (f"{tool.code}\n\n"
              f"if __name__ == '__main__':\n"
              f"    import json as _json\n"
              f"    _out = run(**_json.loads({json.dumps(json.dumps(call))}))\n"
              f"    print('' if _out is None else _out)\n")
    done = sandbox.run_python(script, timeout=SCRIPT_TIMEOUT, approved=approved)
    text = (done.output or "").strip()
    return done.ok and bool(text), text or done.as_observation()


def fill_args(tool: Forged, prompt: str) -> dict | None:
    """The tool's arguments, read out of a request by the fast model."""
    if not tool.params:
        return {}
    from vb import backends
    spec = "\n".join(f"- {k} ({v.get('type', 'string')}): {v.get('description', '')}"
                     + (" [required]" if k in tool.required else "")
                     for k, v in tool.params.items())
    raw = backends.ask_text(
        f"Request: {prompt}\n\nTool: {tool.name} — {tool.description}\n"
        f"Arguments:\n{spec}\n\nReply with only a JSON object of argument "
        f"values taken from the request. Use full Windows paths. Leave out an "
        f"optional argument the request does not mention.",
        system="You extract function arguments. Reply with JSON only.",
        tier="fast", timeout=40, max_tokens=300)
    args = _json_object(raw or "")
    if args is None:
        return None
    if any(k not in args or args[k] in ("", None) for k in tool.required):
        return None
    return args


def answer(tool: Forged, prompt: str, *, approved: bool = False) -> tuple[bool, str]:
    """The fast path: fill the arguments, run, count the outcome.

    (ok, text). Not ok means the caller should fall back to the full loop.
    """
    args = fill_args(tool, prompt)
    if args is None:
        return False, "Could not read the arguments for that out of the request."
    progress.say(f"Using a tool I made earlier: {tool.name}")
    ok, text = execute(tool, args, approved=approved)
    _bump(tool, ok)
    return ok, text


# ---------------------------------------------------------------- forging
FORGE_SYSTEM = """You turn one successful agent run into a reusable Python tool.

Write a single function `run(...)` with keyword arguments for every part of the
request that would change next time (paths, names, numbers, search terms). It
must return a short human-readable answer as a string — the same kind of
answer the run gave. Standard library first; `psutil` is also available.
Imports go inside the function. No input(), no GUI, no network unless the task
needed it. Never delete or overwrite files unless that was the task.

Reply with one JSON object only:
{"name": "snake_case_verb_noun", "description": "one sentence: what it does",
 "phrases": ["5-8 varied ways a user would ask for this, generalised, no specific paths"],
 "params": {"arg": {"type": "string|integer|number|boolean", "description": "..."}},
 "required": ["arg"],
 "example_args": {"arg": "the value from THIS request"},
 "code": "def run(arg: str) -> str:\\n    ..."}

If the run cannot be generalised into a function (pure conversation, a one-off
judgement), reply {"skip": "why"}."""


def worth_forging(outcome) -> bool:
    if not (outcome.ok and outcome.answer) or getattr(outcome, "rescued", False):
        return False
    if outcome.verdict is not None and not outcome.verdict.passed:
        return False
    if config.get("learn_skills", "auto") == "off":
        return False
    tools_used = {s.tool for s in outcome.steps if s.ok}
    return bool(tools_used & WORK_STEPS) or len(outcome.steps) >= 2


def forge(outcome, *, quiet: bool = False) -> tuple[Forged | None, str]:
    """Try to make a tool from a run. (tool or None, what happened)."""
    from vb import backends, learning

    if len(all_forged(include_quarantined=True)) >= MAX_TOOLS:
        return None, "Tool shelf is full."
    transcript = outcome.transcript(width=1500, output=800)
    raw = backends.ask_text(
        f"Request: {outcome.request}\n\nSteps the agent ran:\n{transcript}\n\n"
        f"Final answer it gave:\n{outcome.answer[:1200]}",
        system=FORGE_SYSTEM, tier="work", timeout=120, max_tokens=2500)
    spec = _json_object(raw or "")
    if not spec:
        return None, "The model did not write a tool."
    if spec.get("skip"):
        return None, f"Not a reusable job: {spec['skip']}"

    name = str(spec.get("name", "")).strip().lower()
    code = str(spec.get("code", ""))
    if not _NAME.match(name) or "def run(" not in code:
        return None, "The tool came back malformed."
    try:
        compile(code, f"{name}.py", "exec")
    except SyntaxError as exc:
        return None, f"The tool did not compile: {exc}"

    shape = learning._shape(name)
    for other in all_forged(include_quarantined=True):
        if other.name == name or learning._shape(other.name) == shape:
            _widen(other, spec.get("phrases") or [], outcome.request)
            return None, f"Already have {other.name}."

    verdict = sandbox.classify(code, python=True)
    if verdict.blocked:
        return None, f"Refused to keep it: it {verdict.reason}."
    params = {k: dict(v) if isinstance(v, dict) else {"type": "string"}
              for k, v in (spec.get("params") or {}).items()}
    tool = Forged(
        name=name, description=str(spec.get("description", ""))[:200],
        phrases=[str(p) for p in (spec.get("phrases") or [])][:10],
        params=params,
        required=[r for r in (spec.get("required") or []) if r in params],
        code=code, danger=verdict.action == "confirm", created=time.time(),
        source=outcome.request[:300])

    # Run it before keeping it. A tool that does not reproduce the answer the
    # loop just gave is a wrong tool, and a wrong tool on the fast path is
    # worse than no tool: it answers instantly and confidently.
    if not quiet:
        progress.say(f"Testing a new tool: {name}…")
    ok, output = execute(tool, dict(spec.get("example_args") or {}),
                         approved=False)
    if not ok:
        return None, f"The tool failed its test run: {output[:200]}"
    if not _same_answer(outcome.request, outcome.answer, output):
        return None, "The tool ran but did not match the original answer."
    save(tool)
    _reregister()
    return tool, f"Made a new tool: {name}"


def forge_later(outcome) -> None:
    """Forge in the background, so the answer is never kept waiting for it."""
    if not worth_forging(outcome):
        return

    def work():
        try:
            forge(outcome, quiet=True)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True, name="forge").start()


def _same_answer(request: str, expected: str, got: str) -> bool:
    from vb import backends
    verdict = backends.ask_text(
        f"Question: {request}\n\nAnswer A:\n{expected[:1500]}\n\n"
        f"Answer B:\n{got[:1500]}\n\nDo A and B give the same facts (same "
        f"numbers, names, results)? Wording and formatting do not matter. "
        f"Reply with only YES or NO.",
        tier="fast", timeout=40, max_tokens=5)
    return bool(verdict) and verdict.strip().upper().startswith("Y")


def _widen(tool: Forged, phrases: list[str], request: str) -> None:
    """A second run of a job we already have a tool for: learn its phrasing."""
    merged = list(tool.phrases)
    for p in [*phrases, request]:
        p = str(p).strip()
        if p and p not in merged:
            merged.append(p)
    if merged != tool.phrases:
        tool.phrases = merged[:16]
        save(tool)


def _json_object(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                out = json.loads(text[start:end + 1])
                return out if isinstance(out, dict) else None
            except json.JSONDecodeError:
                return None
    return None


# ----------------------------------------------------------- registration
def as_skill(tool: Forged):
    """The tool as a router skill, so it is found like any built-in one."""
    from vb.registry import Result, Skill

    # A dangerous tool only reaches here after someone said yes: the panel asks
    # before running a `danger` skill, and so does the loop.
    def run(_prompt: str = "", **args):
        if _prompt and not args:
            ok, text = answer(tool, _prompt, approved=tool.danger)
        else:
            ok, text = execute(tool, args, approved=tool.danger)
            _bump(tool, ok)
        return Result(ok=ok, text=text if ok else f"{tool.name} failed.",
                      detail="" if ok else text[:400])

    return Skill(
        name=tool.name, description=tool.description,
        phrases=list(tool.phrases), run=run,
        slots=lambda text: {"_prompt": text},
        danger=tool.danger, slow=True, tags=["learned"],
        schema={"params": tool.params, "required": tool.required})


def register_all(registry: dict) -> int:
    """Put every live forged tool in the skill registry. Returns how many."""
    for name in [n for n, s in registry.items() if "learned" in s.tags]:
        registry.pop(name, None)
    count = 0
    for tool in all_forged():
        if tool.name not in registry:
            registry[tool.name] = as_skill(tool)
            count += 1
    return count


_listeners: list = []


def on_change(fn) -> None:
    """Called after the shelf changes, so routers can rebuild."""
    _listeners.append(fn)


def _reregister() -> None:
    from vb import registry, tools
    register_all(registry._REGISTRY)
    tools.all_tools(refresh=True)
    tools._router_cache = None
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass
