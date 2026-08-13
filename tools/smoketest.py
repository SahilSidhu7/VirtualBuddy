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

REQUIRED = ("version", "skills", "sprites", "extract", "ok")


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
    print(f"smoke test passed: {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
