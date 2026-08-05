"""Your current working projects, and a status summary of any one of them.

Scans the folders in config 'projects_dirs' for git repos, ranks by recent
activity. Summary reads git log/status locally, then the local LLM writes it
up (no Claude tokens). Great for "what was the agent doing here".
"""
import os, subprocess, time
from buddy import slots

def _roots(cfg):
    dirs = cfg.get("projects_dirs") or []
    if not dirs:
        home = os.path.expanduser("~")
        dirs = ["C:/Projects", os.path.join(home, "Projects"), os.path.join(home, "dev")]
    return [d for d in dirs if os.path.isdir(d)]

def _git_repos(cfg):
    repos = []
    for root in _roots(cfg):
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(os.path.join(path, ".git")):
                repos.append(path)
    return repos

def _git(path, *args):
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""

def _list(text, ctx):
    repos = _git_repos(ctx["cfg"])
    if not repos:
        return "No git projects found. Set 'projects_dirs' in config.yaml."
    scored = []
    for p in repos:
        last = _git(p, "log", "-1", "--format=%ct")
        ts = int(last) if last.isdigit() else int(os.path.getmtime(p))
        scored.append((ts, p))
    scored.sort(reverse=True)
    rows = []
    for ts, p in scored[:10]:
        days = int((time.time() - ts) / 86400)
        dirty = "*" if _git(p, "status", "--porcelain") else " "
        rows.append(f" {dirty} {os.path.basename(p):<28} {days}d ago")
    return "Current projects (* = uncommitted):\n" + "\n".join(rows)

def _status(text, ctx):
    repos = _git_repos(ctx["cfg"])
    want = slots.clean(text)
    match = next((p for p in repos if os.path.basename(p).lower() in want), None)
    if not match:
        return "Which project? Try 'list my projects' first."
    log = _git(match, "log", "-8", "--format=%h %s (%cr)")
    status = _git(match, "status", "--porcelain") or "clean"
    facts = f"Project: {os.path.basename(match)}\nRecent commits:\n{log}\n\nWorking tree:\n{status}"
    from buddy import llm
    if ctx["cfg"].get("llm_enabled") and not ctx["cfg"].get("power_save") and llm.is_up(ctx["cfg"]):
        try:
            return llm.ask("Summarize this project's recent state in 3-4 lines:\n" + facts, ctx["cfg"])
        except Exception:
            pass
    return facts[:700]

SKILLS = [
    {"name": "list_projects", "desc": "list current working projects (git repos) by recent activity",
     "phrases": ["list my projects", "what am i working on", "my current projects",
                 "show my working projects", "recent projects"],
     "run": _list},
    {"name": "project_status", "desc": "summarize the status of one project and what was done recently",
     "phrases": ["status of project", "what was done in", "summarize project",
                 "what happened in the project", "where did the agent leave off"],
     "run": _status},
]
