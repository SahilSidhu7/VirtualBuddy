"""File tasks: create a file, run a script. Stays inside workspace for safety."""
import os, subprocess
from buddy import slots

def _create(text, ctx):
    ws = ctx["cfg"]["workspace"]
    name = slots.filename(text) or "new.txt"
    path = os.path.join(ws, name)
    open(path, "a").close()
    return f"Created {path}."

def _run(text, ctx):
    ws = ctx["cfg"]["workspace"]
    name = slots.filename(text)
    if not name:
        return "Which file to run?"
    path = os.path.join(ws, name)
    if not os.path.exists(path):
        return f"{name} not found in workspace."
    try:
        cmd = ["python", path] if name.endswith(".py") else [path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr or "Done.").strip()[:500]
    except Exception as e:
        return f"Run failed: {e}"

SKILLS = [
    {"name": "create_file", "phrases": ["create a file", "make a new file", "new document"], "run": _create},
    {"name": "run_file", "phrases": ["run the script", "execute this file", "run my python file"], "run": _run},
]
