"""Start VirtualBuddy.

  python run.py               text mode (type commands)
  python run.py --voice       add voice input
  python run.py --character   show the on-screen buddy (runs in its own thread)
"""
import sys, threading
from buddy.settings import load
from buddy.agent import Agent

def main():
    cfg = load()
    agent = Agent(cfg)
    args = sys.argv[1:]

    if "--server" in args:
        from buddy.server import serve
        serve(agent, cfg, block=False)      # phone/other PCs can command buddy

    if "--voice" in args:
        from buddy.listener import listen_loop
        threading.Thread(target=listen_loop, args=(cfg, agent.handle), daemon=True).start()

    if "--character" in args:
        from buddy.character.character import Buddy
        # only run the typing loop if we actually have a console
        if sys.stdin and sys.stdin.isatty():
            threading.Thread(target=text_loop, args=(agent,), daemon=True).start()
        Buddy(agent.handle, cfg.get("character", "robot")).run()
        return

    text_loop(agent)

def text_loop(agent):
    from buddy import settings
    if settings.is_first_run():
        print("Tip: buddy isn't trained yet — it works now (cosine), but !train makes it sharper.")
    print("VirtualBuddy ready. Commands: quit | !skills | !fix <skill> | !train | !power on|off")
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd.lower() in ("quit", "exit"):
            break
        if cmd.startswith("!"):
            _repl_command(agent, cmd)
        elif cmd:
            agent.handle(cmd)

def _repl_command(agent, cmd):
    from buddy import corrections
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()
    if name == "!skills":
        print(" ", ", ".join(corrections.skill_names()))
    elif name == "!fix":
        if not agent.last or len(parts) < 2:
            print("  usage: !fix <skill>   (fixes your last command)")
        else:
            print(" ", corrections.log_correction(agent.last[0], parts[1].strip()))
    elif name == "!train":
        print("  training locally...")
        from tools import loop
        loop.main()
        agent.reload_brain()
        print("  done. brain reloaded.")
    elif name == "!power":
        on = len(parts) > 1 and parts[1].strip().lower() in ("on", "1", "true")
        print(" ", agent.set_power_save(on))
    else:
        print("  unknown command")

if __name__ == "__main__":
    main()
