"""Install a community skill (local file or URL) into buddy.

Validates it defines a proper SKILLS list, then drops it into buddy/skills/.
After installing, run buddy and type !train so the brain learns its phrases.

  python -m tools.install_skill path\\to\\skill.py
  python -m tools.install_skill https://example.com/skill.py
"""
import os, sys, shutil, importlib.util, urllib.request
from tools import common

SKILLS_DIR = os.path.join(common.ROOT, "buddy", "skills")

def _fetch(src):
    """Return (local_path, cleanup?). Downloads if src is a URL."""
    if src.startswith(("http://", "https://")):
        name = os.path.basename(src.split("?")[0]) or "downloaded_skill.py"
        tmp = os.path.join(common.DATA, name)
        urllib.request.urlretrieve(src, tmp)
        return tmp, True
    return src, False

def _validate(path):
    spec = importlib.util.spec_from_file_location("_candidate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                      # runs the file
    skills = getattr(mod, "SKILLS", None)
    if not isinstance(skills, list) or not skills:
        return "no SKILLS list found"
    for s in skills:
        for key in ("name", "phrases", "run"):
            if key not in s:
                return f"a skill is missing '{key}'"
        if not callable(s["run"]):
            return "run must be a function"
    return None

def main():
    if len(sys.argv) < 2:
        print("usage: python -m tools.install_skill <file-or-url>"); return
    src = sys.argv[1]
    path, tmp = _fetch(src)
    if not path.endswith(".py"):
        print("skill must be a .py file"); return
    err = _validate(path)
    if err:
        print(f"rejected: {err}"); return
    dest = os.path.join(SKILLS_DIR, os.path.basename(path))
    shutil.copyfile(path, dest)
    if tmp:
        os.remove(path)
    print(f"installed -> {dest}")
    print("now start buddy and type  !train  to activate it.")

if __name__ == "__main__":
    main()
