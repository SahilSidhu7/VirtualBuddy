"""Terminal front end — the same agent the desktop buddy uses.

    python -m vb.cli                 interactive
    python -m vb.cli research bees   one shot
"""
from __future__ import annotations

import sys

from vb import config, traces
from vb.agent import Agent
from vb.registry import load_all

BANNER = """VirtualBuddy — type what you want, or:
  /skills            list what I can do
  /tools             everything the agent loop can call
  /model             see what this machine can run, and pick one
  /learned           the skills it has written for itself
  /mcp               external tool servers
  /traces            what has been recorded for fine-tuning
  /good  /bad why    was the last answer right? the only label worth trusting
  /testlog [bad]     write the testing log to a file you can send on
  /auto  /manual     run matches straight away, or confirm first
  /quit
"""


def _report(message: str) -> None:
    print(f"   … {message}")


def _ellipsis(text: str, limit: int = 60) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _approve(tool: str, args: dict, reason: str) -> bool:
    """Ask before something irreversible. Defaults to no on anything unclear."""
    shown = ", ".join(f"{k}={str(v)[:120]}" for k, v in args.items())
    print(f"\n   ⚠ {tool} {reason}.")
    print(f"     {shown}")
    try:
        return input("     allow it? [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _show_task(turn, agent) -> None:
    """The agent loop path: many steps, model in the middle of each one."""
    if not turn.auto:
        print("→ I'll work through this in steps.")
        if input("   go ahead? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            print("   skipped.")
            return
    res = agent.run_task(turn, approve=_approve, on_progress=_report)
    out = turn.outcome
    if out and out.steps:
        print(f"\n   ({len(out.steps)} steps, {out.seconds:.0f}s"
              + (", asked a stronger model" if out.escalated else "") + ")")
    if out and out.verdict and not out.verdict.passed:
        print(f"   critic: {out.verdict.badge()} {out.verdict.summary}")
    if out and out.learned:
        print(f"   learned: {out.learned}")
    print(("" if res.ok else "! ") + res.text)
    if res.detail:
        print("  " + res.detail)


FIT_WORD = {"good": "✓", "tight": "~", "slow": "!", "no": "✕"}


def _choose_model() -> None:
    """Show what this machine can run, and let the user pick one."""
    from vb import llm
    kit = llm.hardware()
    print(f"  {kit['summary']}\n")
    options = llm.model_options()
    for i, opt in enumerate(options, start=1):
        marks = " ".join(x for x in (
            "recommended" if opt["recommended"] else "",
            "downloaded" if opt["installed"] else "") if x)
        print(f"  {i}. {FIT_WORD[opt['fit']]} {opt['name']:14} "
              f"{opt['size_gb']:.1f}GB  {opt['speed']}"
              + (f"  [{marks}]" if marks else ""))
        print(f"       {opt['blurb']}")
    answer = input("\n  which one? [number, or enter to keep the recommendation] ")
    answer = answer.strip()
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        chosen = options[int(answer) - 1]["name"]
    else:
        chosen = llm.recommended_model()
    config.set("llm_model", chosen)
    config.set("llm_model_pinned", True)
    print(f"  using {chosen}."
          + ("" if llm.installed(chosen) else
             "  Run `ollama pull " + chosen + "` to download it."))


def _show(turn, agent) -> None:
    if turn.task:
        return _show_task(turn, agent)
    if turn.plan:
        print(f"→ {len(turn.plan.steps)} steps:")
        for i, step in enumerate(turn.plan.steps, start=1):
            print(f"   {i}. {step.describe()}")
        if turn.plan.cannot:
            print(f"   cannot: {turn.plan.cannot}")
        if turn.plan.note:
            print(f"   {turn.plan.note}")
        if input("   run them? [Y/n] ").strip().lower() in ("", "y", "yes"):
            res = agent.run_plan(turn, on_progress=_report)
        else:
            print("   skipped.")
            return
    elif turn.auto:
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
    traces.set_source("cli")
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
        if line == "/learned":
            from vb import learning
            print(learning.summary())
            continue
        if line == "/mcp":
            from vb import mcp
            print(mcp.status())
            continue
        if line == "/traces":
            print(traces.stats().describe())
            print(f"  recorded in: {traces.path()}")
            continue
        if line in ("/good", "/bad", "/wrong") or line.startswith(
                ("/good ", "/bad ", "/wrong ")):
            word, _, why = line.partition(" ")
            verdict = "good" if word == "/good" else "bad"
            from vb import testlog
            marked = testlog.mark_last(verdict, why)
            if marked is None:
                print("  nothing to mark yet — ask something first.")
            else:
                print(f"  marked {verdict}: {_ellipsis(marked.get('question', ''))}")
                if verdict == "bad" and not why.strip():
                    print("  (a word on what was wrong makes it far more "
                          "useful: /bad it counted subfolders too)")
            continue
        if line == "/testlog" or line.startswith("/testlog "):
            from vb import testlog
            rest = line.partition(" ")[2].strip().lower()
            target = testlog.write(only_failures=rest in ("bad", "failures"))
            print(f"  {testlog.summary()}")
            print(f"  written to: {target}")
            continue
        if line == "/model":
            _choose_model()
            continue
        if line == "/tools":
            from vb import backends, tools as toolkit
            print(toolkit.catalogue())
            tiers = backends.describe_tiers()
            print(f"\n  models: fast={tiers['fast']}  work={tiers['work']}  "
                  f"hard={tiers['hard']}")
            continue
        if line in ("/auto", "/manual"):
            config.set("mode", line[1:])
            print(f"  mode: {line[1:]}")
            continue
        _show(agent.handle(line), agent)


if __name__ == "__main__":
    raise SystemExit(main())
