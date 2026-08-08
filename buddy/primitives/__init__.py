"""Primitives — the ONLY ways buddy touches the machine.

The planner (buddy/planner.py) composes these into a plan; it never writes code.
Each primitive is small, reviewed, and tagged with a risk level:
  safe    -> may run without asking
  confirm -> user must approve before it runs (destructive / arbitrary)

Add a capability = add one primitive here, rarely. See docs/ARCHITECTURE_V3.md.
"""
import os, subprocess, datetime

from buddy import slots

# verbs that make any shell command dangerous regardless of allowlist
_DANGER = ("del ", "rm ", "remove-item", "rmdir", "format ", "rd ", "kill",
           "stop-process", "shutdown", "diskpart", "reg delete", "> ")


def launch_app(target):
    """Start an app cross-platform. On Windows go through `start` so PATH-independent
    apps (chrome, code, spotify) resolve via the App Paths registry instead of failing
    with 'not recognized'. A target already prefixed with 'start ' is a protocol
    (e.g. 'start ms-settings:') and is passed straight through."""
    if os.name != "nt":
        subprocess.Popen([target])
    elif target.startswith("start "):
        subprocess.Popen(target, shell=True)
    else:
        subprocess.Popen(f'start "" "{target}"', shell=True)


def _open_app(name):
    target = slots.app(name) or name
    if not target:
        return "Which app?"
    launch_app(target)
    return f"Opening {target}."


def _run_shell(cmd):
    if any(d in cmd.lower() for d in _DANGER):
        return f"(refused — destructive shell command: {cmd})"
    exe = ["powershell", "-NoProfile", "-Command", cmd] if os.name == "nt" else ["bash", "-lc", cmd]
    out = subprocess.run(exe, capture_output=True, text=True, timeout=60)
    return (out.stdout or out.stderr or "(no output)").strip()[:2000]


def _write_file(path, text=""):
    path = os.path.abspath(os.path.expanduser(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    return f"Wrote {path}."


def _read_file(path):
    path = os.path.abspath(os.path.expanduser(path))
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()[:2000]


def _list_dir(path="."):
    path = os.path.abspath(os.path.expanduser(path))
    return ", ".join(sorted(os.listdir(path))[:100]) or "(empty)"


def _screenshot(path=None):
    from PIL import ImageGrab
    out = os.path.abspath(os.path.expanduser(path or "shot.png"))
    ImageGrab.grab().save(out)
    return f"Saved screenshot to {out}."


def _time(_=None):
    return "It is " + datetime.datetime.now().strftime("%I:%M %p, %A")


# ---- web-automation primitives (Playwright); thin wrappers over primitives/web.py ----
def _web_open(url):        from buddy.primitives import web; return web.web_open(url)
def _web_read(url=None):   from buddy.primitives import web; return web.web_read(url)
def _web_click(target):    from buddy.primitives import web; return web.web_click(target)
def _web_fill(selector, text=""): from buddy.primitives import web; return web.web_fill(selector, text)
def _web_shot(path=None):  from buddy.primitives import web; return web.web_screenshot(path)


# name -> {fn, risk, args(ordered), desc, group?}
PRIMITIVES = {
    "open_app":    {"fn": _open_app,   "risk": "safe",    "args": ["name"],        "desc": "launch an application by name (chrome, notepad, code...)"},
    "run_shell":   {"fn": _run_shell,  "risk": "confirm", "args": ["cmd"],         "desc": "run a PowerShell/bash command and return its output"},
    "write_file":  {"fn": _write_file, "risk": "confirm", "args": ["path", "text"],"desc": "create/overwrite a text file"},
    "read_file":   {"fn": _read_file,  "risk": "safe",    "args": ["path"],        "desc": "read a text file's contents"},
    "list_dir":    {"fn": _list_dir,   "risk": "safe",    "args": ["path"],        "desc": "list files in a folder"},
    "screenshot":  {"fn": _screenshot, "risk": "safe",    "args": ["path"],        "desc": "capture the screen to a PNG"},
    "time":        {"fn": _time,       "risk": "safe",    "args": [],              "desc": "current time and day"},
    # web automation (only offered when cfg.web_automation and Playwright are available)
    "web_open":    {"fn": _web_open,   "risk": "safe",    "args": ["url"],             "desc": "open a URL in a real browser", "group": "web"},
    "web_read":    {"fn": _web_read,   "risk": "safe",    "args": ["url"],             "desc": "read the visible text of a page (optionally navigate to url first)", "group": "web"},
    "web_click":   {"fn": _web_click,  "risk": "confirm", "args": ["target"],          "desc": "click an element by CSS selector or visible text", "group": "web"},
    "web_fill":    {"fn": _web_fill,   "risk": "confirm", "args": ["selector", "text"],"desc": "type text into a form field (CSS selector)", "group": "web"},
    "web_screenshot":{"fn": _web_shot, "risk": "safe",    "args": ["path"],            "desc": "screenshot the current web page", "group": "web"},
}


def _web_enabled(cfg):
    if not (cfg or {}).get("web_automation", False):
        return False
    from buddy.primitives import web
    return web.available()


def catalog(cfg=None):
    """Human/LLM-readable list of primitives for the planner prompt.
    Web primitives are hidden unless cfg.web_automation is on and Playwright is installed."""
    web_on = _web_enabled(cfg)
    lines = []
    for name, p in PRIMITIVES.items():
        if p.get("group") == "web" and not web_on:
            continue
        args = ", ".join(p["args"]) or "(none)"
        lines.append(f"- {name}({args}) [{p['risk']}]: {p['desc']}")
    return "\n".join(lines)


def run(name, args):
    """Execute one primitive. args is a dict; extra keys ignored, missing use defaults."""
    p = PRIMITIVES.get(name)
    if not p:
        return f"(unknown primitive {name})"
    kwargs = {k: v for k, v in (args or {}).items() if k in p["args"]}
    try:
        return str(p["fn"](**kwargs))
    except TypeError:
        # positional fallback for primitives that take one required arg
        vals = [args.get(a) for a in p["args"] if a in (args or {})]
        return str(p["fn"](*vals)) if vals else "(bad arguments)"
    except Exception as e:
        return f"({name} failed: {e})"


def needs_confirm(name):
    return PRIMITIVES.get(name, {}).get("risk") == "confirm"
