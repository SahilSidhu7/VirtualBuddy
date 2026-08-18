"""Run a built VirtualBuddy.exe and check it came out working.

    python tools/smoketest.py dist/VirtualBuddy/VirtualBuddy.exe

A packaged build fails in ways a source checkout never does: skills that are
imported by name go missing, sprites are not bundled, tkinter loses its DLLs.
This asks the binary itself, rather than trusting that the build printed no
errors.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REQUIRED = ("version", "skills", "sprites", "extract", "pillow", "ok")


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: smoketest.py <path to VirtualBuddy.exe>")
        return 2
    exe = Path(argv[0])
    if not exe.exists():
        print(f"No executable at {exe}")
        return 1

    # A GUI build has no console attached, so it cannot print. --selftest is a
    # normal exit path that writes to stdout when one is redirected.
    done = subprocess.run([str(exe), "--selftest"], capture_output=True,
                          text=True, timeout=180)
    output = (done.stdout or "") + (done.stderr or "")
    print(output.strip() or "(no output)")

    if done.returncode != 0:
        print(f"FAILED exit code {done.returncode}")
        return 1
    missing = [key for key in REQUIRED if key not in output]
    if missing:
        print(f"FAILED missing from the report: {', '.join(missing)}")
        return 1

    # The count, not just the word. A skill module left out of the spec's
    # hiddenimports is not an error at runtime — `registry.load_all` catches the
    # ImportError and carries on — so the packaged app simply has fewer skills
    # than the checkout it was built from and says nothing about it. Checking
    # only that "skills" appeared in the report would pass that build, and
    # three modules were in exactly that state before 0.8.0. selftest's own
    # floor of 20 is too low to notice losing a module or two.
    expected = _source_skill_count()
    got = _reported_skill_count(output)
    if expected and got is not None and got < expected:
        print(f"FAILED the build registered {got} skills, "
              f"the source tree has {expected} — a skill module is probably "
              f"missing from hiddenimports in the .spec")
        return 1

    print(f"smoke test passed: {exe}" + (f" ({got} skills)" if got else ""))
    return 0


def _source_skill_count() -> int:
    """How many skills this checkout registers. 0 if it cannot be worked out."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from vb.registry import load_all
        return len(load_all())
    except Exception:
        return 0


def _reported_skill_count(output: str) -> int | None:
    for line in output.splitlines():
        if line.startswith("skills"):
            rest = line.split(maxsplit=1)
            if len(rest) == 2 and rest[1].strip().isdigit():
                return int(rest[1].strip())
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
