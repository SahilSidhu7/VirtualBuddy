"""Shut down, restart, sleep, sign out — all behind a yes/no gate.

Nothing here runs on the first ask. Buddy states what it's about to do and waits
for confirmation (buddy/confirm.py), because a misheard voice command should
never cost someone their unsaved work.
"""
import os, sys, subprocess

from buddy import confirm, slots

_ACTIONS = {
    "shutdown": {
        "words": ("shut down", "shutdown", "power off", "power down", "turn off"),
        "question": "Shut down the PC?",
        "nt": ["shutdown", "/s", "/t", "0"],
        "darwin": ["osascript", "-e", 'tell app "System Events" to shut down'],
        "linux": ["systemctl", "poweroff"],
        "done": "Shutting down.",
    },
    "restart": {
        "words": ("restart", "reboot", "reset my pc", "start it up again"),
        "question": "Restart the PC?",
        "nt": ["shutdown", "/r", "/t", "0"],
        "darwin": ["osascript", "-e", 'tell app "System Events" to restart'],
        "linux": ["systemctl", "reboot"],
        "done": "Restarting.",
    },
    "sleep": {
        "words": ("sleep", "suspend", "hibernate", "standby"),
        "question": "Put the PC to sleep?",
        "nt": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "darwin": ["pmset", "sleepnow"],
        "linux": ["systemctl", "suspend"],
        "done": "Going to sleep.",
    },
    "signout": {
        "words": ("sign out", "sign me out", "log out", "log me out", "log off",
                  "log me off", "logout", "signout"),
        "question": "Sign out of Windows?",
        "nt": ["shutdown", "/l"],
        "darwin": ["osascript", "-e", 'tell app "System Events" to log out'],
        "linux": ["loginctl", "terminate-user", os.environ.get("USER", "")],
        "done": "Signing out.",
    },
}


def _platform_key():
    if os.name == "nt":
        return "nt"
    return "darwin" if sys.platform == "darwin" else "linux"


def _pick(text):
    t = slots.clean(text)
    # longest phrase first so "shut down" beats a stray "down"
    for name, spec in sorted(_ACTIONS.items(), key=lambda kv: -max(len(w) for w in kv[1]["words"])):
        if any(w in t for w in spec["words"]):
            return name, spec
    return None, None


def _runner(spec):
    cmd = spec[_platform_key()]

    def do():
        try:
            subprocess.Popen(cmd)
            return spec["done"]
        except Exception as e:
            return f"Couldn't do that: {e}"
    return do


def power(text, ctx):
    name, spec = _pick(text)
    if not spec:
        return "I can shut down, restart, sleep or sign out — which one?"
    delay = slots.duration_seconds(text)
    if delay:
        def later(_spec=spec, _delay=delay):
            import threading
            threading.Timer(_delay, _runner(_spec)).start()
            return f"{_spec['question'][:-1]} in {_delay} seconds — scheduled."
        return confirm.ask(f"{spec['question'][:-1]} in {delay} seconds?", later)
    return confirm.ask(spec["question"], _runner(spec))


SKILLS = [
    {"name": "power", "desc": "shut down, restart, sleep or sign out (asks first)",
     "phrases": ["shut down my pc", "turn off the computer", "restart my computer",
                 "reboot the pc", "put the pc to sleep", "sleep my computer",
                 "sign me out", "log off windows", "shutdown in 10 minutes",
                 "hibernate the machine"],
     "run": power},
]
