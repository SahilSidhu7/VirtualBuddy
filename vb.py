"""Single entry point for VirtualBuddy (used by the installers).

  vb              -> the on-screen buddy (GUI). Headless server -> text mode.
  vb --dashboard  -> control panel
  vb --character  -> on-screen buddy
  vb --voice      -> voice mode
  vb --server     -> LAN command server (phone / other PCs)
  vb --text       -> text mode in this terminal
"""
import os, sys

def _setup_logging():
    # windowed .exe has no console -> stdout/stderr are None; print() would crash.
    if sys.stdout is None or sys.stderr is None:
        from buddy import settings
        os.makedirs(settings.HOME, exist_ok=True)
        log = open(os.path.join(settings.HOME, "buddy.log"), "a", buffering=1)
        sys.stdout = sys.stderr = log

def _has_display():
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

def main():
    _setup_logging()
    args = set(sys.argv[1:])

    if "--dashboard" in args:
        import app
        return app.App().run()

    runtime = args & {"--character", "--voice", "--server", "--text"}
    if runtime:
        import run
        sys.argv = ["run.py"] + list(runtime)
        return run.main()

    # no flag: show the character on a desktop, else text mode (headless)
    from buddy.settings import load
    from buddy.agent import make_brain
    cfg = load()
    brain = make_brain(cfg)              # local Agent, or remote brain client (role: client)
    if _has_display():
        from buddy.character.character import Buddy
        Buddy(brain.handle, cfg.get("character", "duck"),
              roam=cfg.get("roam", False), roam_speed=cfg.get("roam_speed", 40)).run()
    else:
        import run
        run.text_loop(brain)

if __name__ == "__main__":
    main()
