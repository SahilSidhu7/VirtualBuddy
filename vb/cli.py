"""Terminal front end — the same agent the desktop buddy uses.

    python -m vb.cli                 interactive
    python -m vb.cli research bees   one shot
"""
from __future__ import annotations

import sys

from vb import config
from vb.agent import Agent
from vb.registry import load_all

BANNER = """VirtualBuddy — type what you want, or:
  /skills            list what I can do
  /auto  /manual     run matches straight away, or confirm first
  /quit
"""


def _report(message: str) -> None:
    print(f"   … {message}")


def _show(turn, agent) -> None:
    if turn.auto:
        res = agent.confirm(turn, on_progress=_report)
    elif turn.needs_confirm:
        alts = "".join(
            f"\n   {i}. {m.skill.name}  ({m.score:.2f})"
            for i, m in enumerate(turn.matches[1:], start=1))
        print(f"→ {turn.describe()}   [{turn.matches[0].score:.2f}]")
        if alts:
            print(f"   others:{alts}")
        answer = input("   run it? [Y/n/number] ").strip().lower()
        if answer in ("", "y", "yes"):
            res = agent.confirm(turn, on_progress=_report)
        elif answer.isdigit():
            res = agent.confirm(turn, choice=int(answer), on_progress=_report)
        else:
            print("   skipped.")
            return
    else:
        res = turn.result
    print(("" if res.ok else "! ") + res.text)
    if res.detail:
        print("  " + res.detail)


def _readable_console() -> None:
    """Stop the Windows console from killing us over a curly quote.

    cmd.exe defaults to cp1252, and anything the web or a language model hands
    back is full of characters it cannot encode. Printing one raised
    UnicodeEncodeError and took the whole answer with it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _readable_console()
    argv = argv if argv is not None else sys.argv[1:]
    skills = load_all()
    agent = Agent()

    if argv:
        _show(agent.handle(" ".join(argv)), agent)
        return 0

    print(BANNER)
    print(f"({len(skills)} skills, mode: {config.get('mode')})\n")
    while True:
        try:
            line = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line == "/skills":
            for name, sk in sorted(skills.items()):
                print(f"  {name:16} {sk.description}")
            continue
        if line in ("/auto", "/manual"):
            config.set("mode", line[1:])
            print(f"  mode: {line[1:]}")
            continue
        _show(agent.handle(line), agent)


if __name__ == "__main__":
    raise SystemExit(main())
