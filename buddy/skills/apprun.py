"""Run an app or server in a project. Sets the project up first if needed.

Detects the project type, installs deps if missing, then starts it in the
background. Only touches folders under config 'projects_dirs'. No tokens.
"""
import os, subprocess
from buddy import slots
from buddy.skills.projects import _git_repos

# type -> (setup marker, setup cmd, run cmd)
RECIPES = [
    ("package.json", "node_modules", "npm install", "npm run dev"),
    ("manage.py",    ".venv",        "python -m venv .venv",   "python manage.py runserver"),
    ("requirements.txt", ".venv",    "python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt", "python app.py"),
    ("docker-compose.yml", None,     None, "docker compose up -d"),
]

def _find_project(text, ctx):
    want = slots.clean(text)
    for p in _git_repos(ctx["cfg"]):
        if os.path.basename(p).lower() in want:
            return p
    return None

def _run(text, ctx):
    proj = _find_project(text, ctx)
    if not proj:
        return "Which project? Name one from 'list my projects'."
    for marker, setup_dir, setup_cmd, run_cmd in RECIPES:
        if not os.path.exists(os.path.join(proj, marker)):
            continue
        steps = []
        if setup_dir and not os.path.exists(os.path.join(proj, setup_dir)) and setup_cmd:
            r = subprocess.run(setup_cmd, cwd=proj, shell=True, capture_output=True, text=True, timeout=600)
            steps.append("setup done" if r.returncode == 0 else f"setup failed: {r.stderr[-200:]}")
            if r.returncode != 0:
                return f"{os.path.basename(proj)}: " + "; ".join(steps)
        # start server in background, log to file
        log = os.path.join(ctx["cfg"]["workspace"], f"{os.path.basename(proj)}.log")
        with open(log, "w") as lf:
            subprocess.Popen(run_cmd, cwd=proj, shell=True, stdout=lf, stderr=lf)
        steps.append(f"started: {run_cmd} (log: {log})")
        return f"{os.path.basename(proj)}: " + "; ".join(steps)
    return f"{os.path.basename(proj)}: unknown project type (no known run recipe)."

SKILLS = [
    {"name": "run_project", "desc": "set up (if needed) and run an app/server from a project folder",
     "phrases": ["run my project", "start the server for", "launch the app", "spin up",
                 "set up and run", "start the project"],
     "run": _run},
]
