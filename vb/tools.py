"""Everything the loop can actually do, described in a way a model can call.

Two sources feed one list. The skills already in `vb/skills/` become tools
automatically — their signature is the schema and their docstring is the
description, so writing a skill still means writing one function and nothing
else. On top of those sit the primitives a skill cannot cover: reading and
writing files, running a script, searching what it remembers, and saying it is
done.

The primitives are the important half. A fixed menu of skills can only do the
things somebody predicted; `run_python` can do the rest, which is why the tool
list stays short instead of growing to sixty entries.
"""
from __future__ import annotations

import inspect
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vb import memory, sandbox
from vb.registry import Result, all_skills, load_all

MAX_READ = 20000
MAX_MENU = 6            # task-specific tools offered per request, before primitives
SCORE_FLOOR = 0.30      # below this the router is guessing, not matching
DANGER_FLOOR = 0.55     # irreversible skills need a clear match, not a near one

# "The user said yes to this one call." Thread-local, not a module flag: the
# panel runs a loop on a worker thread while the UI thread is still alive, and
# a permission granted in one run must never be visible to another. It is also
# cleared immediately after the call it was granted for.
_grant = threading.local()


def _approved(name: str) -> bool:
    return name in getattr(_grant, "names", ())


@dataclass
class Tool:
    name: str
    description: str
    params: dict                      # JSON schema properties
    required: list[str]
    run: Callable[..., Any]
    danger: bool = False              # always asks, whatever the mode
    tags: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                },
            },
        }


# ------------------------------------------------------- skills become tools
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}


def _param_schema(param: inspect.Parameter) -> dict:
    kind = _JSON_TYPES.get(param.annotation, "string")
    out: dict = {"type": kind}
    if param.default not in (inspect.Parameter.empty, None):
        out["description"] = f"defaults to {param.default!r}"
    return out


def _from_skill(skill) -> Tool | None:
    try:
        sig = inspect.signature(skill.run)
    except (TypeError, ValueError):
        return None
    props, required = {}, []
    for name, param in sig.parameters.items():
        if name.startswith("_") or param.kind in (param.VAR_POSITIONAL,
                                                  param.VAR_KEYWORD):
            continue
        props[name] = _param_schema(param)
        if param.default is inspect.Parameter.empty:
            required.append(name)

    def call(**kwargs):
        return skill.run(**kwargs)

    return Tool(name=skill.name, description=skill.description, params=props,
                required=required, run=call, danger=skill.danger,
                tags=list(skill.tags))


# -------------------------------------------------------------- primitives
def _tool_read_file(path: str, max_chars: int = 4000) -> Result:
    """Read a text file."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = sandbox.workspace() / target
    if not target.exists():
        return Result.fail(f"There is no file at {target}.")
    if target.is_dir():
        return Result.fail(f"{target} is a folder. Use list_dir.")
    try:
        text = target.read_text("utf-8", errors="replace")
    except OSError as exc:
        return Result.fail(f"Could not read {target}: {exc}")
    cut = int(max_chars or 4000)
    clipped = text[:cut]
    note = "" if len(text) <= cut else f"\n… [{len(text) - cut} more characters]"
    return Result(text=clipped + note, data={"path": str(target), "size": len(text)})


def _tool_write_file(path: str, content: str) -> Result:
    """Write a text file, replacing what is there."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = sandbox.workspace() / target
    if not sandbox.inside_workspace(target) and not _approved("write_file"):
        # Outside its own folder the agent is editing the user's things. The
        # loop sets this flag only after the user has said yes.
        return Result.fail(
            f"Writing to {target} is outside the workspace and needs approval.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", "utf-8")
    except OSError as exc:
        return Result.fail(f"Could not write {target}: {exc}")
    return Result(text=f"Wrote {len(content or '')} characters to {target}.")


def _tool_list_dir(path: str = "") -> Result:
    """List what is in a folder."""
    target = Path(path).expanduser() if path else sandbox.workspace()
    if not target.is_absolute():
        target = sandbox.workspace() / target
    if not target.is_dir():
        return Result.fail(f"{target} is not a folder.")
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return Result.fail(f"Could not list {target}: {exc}")
    lines = [f"{'d' if p.is_dir() else '-'} {p.name}" for p in entries[:200]]
    more = "" if len(entries) <= 200 else f"\n… and {len(entries) - 200} more"
    return Result(text=f"{target}\n" + "\n".join(lines) + more)


PYTHON_HELP = """Write and run a Python script. Use this for anything the other
tools do not cover: counting, parsing, maths, bulk file work.

The one argument is `code`, the whole script as text. Rules that matter:
- Plain Python 3 and its standard library only. The other tools are NOT Python
  functions: there is no list_dir() or read_file() inside a script. Use os,
  pathlib, json, re.
- Write real multi-line code with newlines and indentation. Do not squeeze a
  for loop and an if onto one line with semicolons; that is a syntax error.
- It runs in a scratch folder, not where your files are, so always use full
  absolute paths.
- Only what you print comes back. Print the answer.

Example of the shape:
import pathlib
root = pathlib.Path(r"C:/some/folder")
for f in sorted(root.rglob("*.py")):
    print(f.name, len(f.read_text(encoding="utf-8", errors="replace").splitlines()))"""

# What a broken script usually means, said in the terms the model can act on.
SYNTAX_HINT = ("\nHint: that is a syntax error. Rewrite it as proper multi-line "
               "Python — one statement per line, real indentation under `for` "
               "and `if` — rather than statements joined with semicolons.")
NAME_HINT = ("\nHint: that name does not exist in Python. The tools are not "
             "callable from inside a script; use the standard library "
             "(os, pathlib, re, json) to do it yourself.")
WRONG_DIR_HINT = ("\nHint: those are the scratch folder's own temporary files, "
                  "not the ones you were asked about. The script runs somewhere "
                  "else entirely, so os.getcwd() is useless here — put the full "
                  "path from the request into the script.")


def _tool_run_python(code: str) -> Result:
    from vb import executors
    run = executors.run_python(code, approved=_approved("run_python"))
    text = run.as_observation()
    # Searching the scratch folder and finding only its own step files is the
    # single most common wrong answer a small model produces here. It looks
    # like a successful run, so it has to be named as a mistake.
    if run.ok and "_step_" in text and ".virtualbuddy" in text:
        text += WRONG_DIR_HINT
    if not run.ok:
        # A failed script is the most common step in a run, so the observation
        # is worth more than the traceback alone. Naming the mistake is the
        # difference between the model fixing it and retrying it verbatim.
        if "SyntaxError" in text or "invalid syntax" in text:
            text += SYNTAX_HINT
        elif "NameError" in text:
            text += NAME_HINT
    return Result(ok=run.ok, text=text, data=run)


_tool_run_python.__doc__ = PYTHON_HELP


def _tool_run_shell(command: str) -> Result:
    """Run one shell command (PowerShell on Windows)."""
    from vb import executors
    run = executors.run_shell(command, approved=_approved("run_shell"))
    return Result(ok=run.ok, text=run.as_observation(), data=run)


def _tool_remember(text: str) -> Result:
    """Store something worth knowing next time."""
    return Result(text="Noted." if memory.remember(text, "fact") else
                  "Already knew that.")


def _tool_recall(query: str) -> Result:
    """Look up what was remembered earlier."""
    notes = memory.recall(query, limit=6)
    if not notes:
        return Result(text="Nothing remembered about that.")
    return Result(text="\n".join(f"- {n.text} ({n.age()})" for n in notes))


def _tool_finish(answer: str) -> Result:
    """Give the user the final answer and stop. Call this when the task is
    done, or when you have established it cannot be."""
    return Result(text=answer or "")


PRIMITIVES = [
    Tool("run_python", _tool_run_python.__doc__ or "",
         {"code": {"type": "string", "description": "the script to run"}},
         ["code"], _tool_run_python, tags=["exec"]),
    Tool("run_shell", _tool_run_shell.__doc__ or "",
         {"command": {"type": "string", "description": "the command"}},
         ["command"], _tool_run_shell, tags=["exec"]),
    Tool("read_file", _tool_read_file.__doc__ or "",
         {"path": {"type": "string"},
          "max_chars": {"type": "integer", "description": "defaults to 4000"}},
         ["path"], _tool_read_file, tags=["files"]),
    Tool("write_file", _tool_write_file.__doc__ or "",
         {"path": {"type": "string"}, "content": {"type": "string"}},
         ["path", "content"], _tool_write_file, tags=["files"]),
    Tool("list_dir", _tool_list_dir.__doc__ or "",
         {"path": {"type": "string", "description": "defaults to the workspace"}},
         [], _tool_list_dir, tags=["files"]),
    Tool("remember", _tool_remember.__doc__ or "",
         {"text": {"type": "string"}}, ["text"], _tool_remember, tags=["memory"]),
    Tool("recall", _tool_recall.__doc__ or "",
         {"query": {"type": "string"}}, ["query"], _tool_recall, tags=["memory"]),
    Tool("finish", _tool_finish.__doc__ or "",
         {"answer": {"type": "string",
                     "description": "the complete answer for the user"}},
         ["answer"], _tool_finish, tags=["control"]),
]


# ------------------------------------------------------------------ the list
_cache: dict[str, Tool] | None = None
_shadowed: list[str] = []


def all_tools(refresh: bool = False) -> dict[str, Tool]:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    load_all()
    built: dict[str, Tool] = {}
    for name, skill in all_skills().items():
        tool = _from_skill(skill)
        if tool:
            built[name] = tool
    # Primitives win a name clash, and the clash is real: there is a
    # `read_file` skill that finds a file by name, and a `read_file` primitive
    # that takes a path. The loop wants the path one, because by the time it
    # calls it, it has the path. The displaced skill is recorded rather than
    # vanishing silently.
    global _shadowed
    _shadowed = [t.name for t in PRIMITIVES if t.name in built]
    for tool in PRIMITIVES:
        built[tool.name] = tool
    for tool in _mcp_tools():
        built.setdefault(tool.name, tool)     # never displace a local tool
    _cache = built
    return built


def _mcp_tools() -> list[Tool]:
    """Tools borrowed from configured MCP servers.

    Prefixed with the server name, because two servers offering `search` is
    normal and a collision would silently route to whichever loaded second.
    Failures here are swallowed: a misconfigured server in someone's config
    must not be the reason the buddy has no tools at all.
    """
    from vb import mcp
    out = []
    try:
        found = mcp.discover()
    except Exception:
        return out
    for server, schema in found:
        params = schema.get("inputSchema") or {}
        name = f"{server.name}_{schema['name']}"

        def call(_server=server, _tool=schema["name"], **kwargs):
            ok, text = _server.call(_tool, kwargs)
            return Result(ok=ok, text=text)

        out.append(Tool(
            name=name,
            description=schema.get("description", "")[:400] or name,
            params=params.get("properties") or {},
            required=list(params.get("required") or []),
            run=call, tags=["mcp", server.name]))
    return out


def shadowed() -> list[str]:
    """Skills hidden by a primitive of the same name."""
    all_tools()
    return list(_shadowed)


def get(name: str) -> Tool | None:
    return all_tools().get(name)


_router_cache = None


def _router():
    """One Router, reused. Building it re-encodes every skill phrase, and
    doing that per request throws away the reason the router is cheap."""
    global _router_cache
    if _router_cache is None:
        from vb.router import Router
        _router_cache = Router()
    return _router_cache


def relevant(request: str, top: int = 6) -> list[str]:
    """The tools worth offering for this request.

    Handing a small model all thirty-odd tools is the single biggest cause of
    it wandering: asked to count files it will reach for disk_hogs, then
    list_tasks, because they are there and they sound vaguely related. The
    router already scores every skill against the request in under a
    millisecond, so the menu is cut to the ones that scored, plus the
    primitives, which are always on.

    Cheap in every sense — no model call, and a shorter tool list is fewer
    tokens in every turn of the loop.
    """
    always = [t.name for t in PRIMITIVES]
    try:
        ranked = _router().rank(request, top=top)
    except Exception:
        # Scoring failed, so fall back to the primitives alone. Offering
        # everything instead would be the opposite of what this is for: the
        # long menu is the problem, and a broken router is no reason to hand
        # the model all thirty-three.
        return always
    # A score floor, not just a ranking. `rank(top=6)` always returns six, so
    # a request that matches nothing well still got six confident-looking
    # suggestions — which is how counting files came to be offered `disk_hogs`
    # and `pc_health`, and how "save a summary to a file" was offered
    # `delete_file`. Below the floor the primitives are a better answer than
    # the nearest skill, and irreversible skills have to clear a higher bar
    # before being put in front of a model that is guessing.
    known = all_tools()
    picked = []
    for match in ranked:
        name = match.skill.name
        if name not in known:
            continue
        floor = DANGER_FLOOR if known[name].danger else SCORE_FLOOR
        if match.score >= floor:
            picked.append(name)
    # Capped, not just filtered. With MCP servers attached the scored list can
    # grow back to the length the narrowing exists to prevent — a filesystem
    # server alone adds fourteen tools, four of which will match any request
    # mentioning a file. The primitives are never cut; they are what the model
    # falls back to when nothing specific fits.
    chosen = list(dict.fromkeys(picked + _matching_mcp(request)))[:MAX_MENU]
    return list(dict.fromkeys(chosen + always))


_WORDS = re.compile(r"[a-z0-9]{4,}")


def _matching_mcp(request: str, limit: int = 4) -> list[str]:
    """MCP tools whose name or description overlaps the request.

    The router only knows about skills, so borrowed tools would never be
    offered at all without this. Word overlap is crude, but the alternative is
    either offering every remote tool — the long-menu problem again — or paying
    a model call to choose, on every request.
    """
    words = set(_WORDS.findall((request or "").lower()))
    if not words:
        return []
    scored = []
    for tool in all_tools().values():
        if "mcp" not in tool.tags:
            continue
        text = f"{tool.name} {tool.description}".lower()
        hits = len(words & set(_WORDS.findall(text)))
        if hits:
            scored.append((hits, tool.name))
    scored.sort(reverse=True)
    return [name for _hits, name in scored[:limit]]


def schemas(names: list[str] | None = None) -> list[dict]:
    tools = all_tools()
    chosen = [tools[n] for n in names if n in tools] if names else list(tools.values())
    return [t.schema() for t in chosen]


def catalogue(names: list[str] | None = None) -> str:
    """The tool list as text, for backends that cannot take a schema."""
    tools = all_tools()
    chosen = [tools[n] for n in names if n in tools] if names else list(tools.values())
    lines = []
    for t in sorted(chosen, key=lambda x: x.name):
        args = ", ".join(t.params) or "no arguments"
        flag = "  [asks first]" if t.danger else ""
        lines.append(f"- {t.name}({args}): {t.description.strip().splitlines()[0]}{flag}")
    return "\n".join(lines)


def set_approved(name: str, approved: bool) -> None:
    """Record that the user said yes to this one call, on this thread."""
    names = set(getattr(_grant, "names", ()))
    names.add(name) if approved else names.discard(name)
    _grant.names = names
