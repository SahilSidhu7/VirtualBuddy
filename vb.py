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
    # Windows consoles default to cp1252, which mangles the em dashes and arrows
    # buddy's replies are full of. UTF-8 with replacement keeps output readable.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
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

def _auto_update():
    """If enabled, pull updates in the background so the next launch runs them."""
    try:
        from buddy.settings import load
        if not load().get("auto_update"):
            return
        import threading, update
        def work():
            changed, msg = update.pull_only()
            print(f"[update] {msg}")
        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        print(f"[update] skipped: {e}")

def main():
    _setup_logging()
    _auto_update()
    args = set(sys.argv[1:])

    if "--dashboard" in args:
        from buddy import dashboard          # modern webview panel (falls back to tkinter)
        return dashboard.run()

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
        buddy = Buddy(brain.handle, cfg.get("character", "duck"),
                      roam=cfg.get("roam", False), roam_speed=cfg.get("roam_speed", 40))
        if hasattr(brain, "on_state"):
            brain.on_state = buddy.set_state
        buddy.run()
    else:
        import run
        run.text_loop(brain)

if __name__ == "__main__":
    main()
