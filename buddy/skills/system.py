"""PC tasks: open apps, screenshot, lock, time. Uses slots for reliable details."""
import os, subprocess, datetime, threading
from buddy import slots
from buddy.primitives import launch_app

def _open_app(text, ctx):
    name = slots.app(text)
    if not name:
        return "Which app?"
    try:
        launch_app(name)                        # `start` on Windows -> App Paths resolves chrome/code/...
        return f"Opening {name}."
    except Exception as e:
        return f"Could not open {name}: {e}"

def _time(text, ctx):
    return "It is " + datetime.datetime.now().strftime("%I:%M %p, %A")

def _lock(text, ctx):
    if os.name != "nt":
        return "Lock only wired for Windows."
    delay = slots.duration_seconds(text)
    def do():
        os.system("rundll32.exe user32.dll,LockWorkStation")
    if delay:
        threading.Timer(delay, do).start()
        return f"Locking in {delay} seconds."
    do()
    return "Locking."

def _screenshot(text, ctx):
    out = os.path.join(ctx["cfg"]["workspace"], "shot.png")
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Need Pillow for screenshots (pip install pillow)."
    try:
        ImageGrab.grab().save(out)
        return f"Saved screenshot to {out}."
    except Exception as e:
        return f"Screenshot failed: {e}"

SKILLS = [
    {"name": "open_app", "phrases": ["open notepad", "launch chrome", "start an app", "open calculator",
                                     "start spotify", "fire up vs code", "boot up discord",
                                     "run the calculator app", "get me notepad open",
                                     "launch the file explorer", "open steam", "open discord",
                                     "open word", "open excel", "open outlook", "open obs",
                                     "open telegram", "open whatsapp", "open figma",
                                     "open slack"], "run": _open_app},
    {"name": "time", "phrases": ["what time is it", "tell me the time", "current time", "what is the date"], "run": _time},
    {"name": "lock", "phrases": ["lock my pc", "lock the screen", "lock computer", "lock in 5 minutes"], "run": _lock},
    {"name": "screenshot", "phrases": ["take a screenshot", "capture the screen", "grab screen"], "run": _screenshot},
]
