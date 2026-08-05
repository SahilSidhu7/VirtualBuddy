"""Single entry point for VirtualBuddy (used by the installers).

  vb              -> control panel (GUI); on a headless server, text mode instead
  vb --character  -> on-screen buddy
  vb --voice      -> voice mode
  vb --server     -> LAN command server (phone / other PCs)
  vb --text       -> text mode
"""
import os, sys

def _has_display():
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

def main():
    args = set(sys.argv[1:])
    runtime = args & {"--character", "--voice", "--server", "--text"}
    if runtime:
        import run
        sys.argv = ["run.py"] + list(runtime)
        return run.main()
    # no runtime flag: GUI control panel if we have a screen, else text
    if _has_display():
        import app
        return app.App().run()
    print("No display detected - starting text mode. (use 'vb --server' for a headless host)")
    import run
    from buddy.settings import load
    from buddy.agent import Agent
    run.text_loop(Agent(load()))

if __name__ == "__main__":
    main()
