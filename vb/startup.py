"""Starting with Windows.

A shortcut in the user's Startup folder, not a registry Run key: it needs no
admin rights, the user can see it and delete it in Explorer, and removing the
app removes nothing they can't find. The same toggle works whether VirtualBuddy
is a packaged .exe or a checkout being run with Python.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

NAME = "VirtualBuddy"


def supported() -> bool:
    return sys.platform == "win32"


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) \
        / "Microsoft/Windows/Start Menu/Programs/Startup"


def shortcut_path() -> Path:
    return startup_dir() / f"{NAME}.lnk"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_target() -> tuple[str, str, str]:
    """(target, arguments, working directory) for the shortcut."""
    if frozen():
        exe = Path(sys.executable).resolve()
        return str(exe), "", str(exe.parent)
    project = Path(__file__).resolve().parents[1]
    # pythonw keeps a console window from flashing up at every login.
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return str(quiet if quiet.exists() else exe), str(project / "run.py"), str(project)


def enabled() -> bool:
    return shortcut_path().exists()


def _powershell(script: str) -> bool:
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enable() -> tuple[bool, str]:
    """Create the Startup shortcut. Returns (ok, message for the user)."""
    if not supported():
        return False, "Starting with the system is Windows only for now."
    target, args, workdir = launch_target()
    link = shortcut_path()
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, str(exc)

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"'{link}'); $s.TargetPath = '{target}'; "
        f"$s.Arguments = '{args}'; $s.WorkingDirectory = '{workdir}'; "
        f"$s.Description = 'Start {NAME} when you sign in'; $s.Save()"
    )
    if not _powershell(script) or not link.exists():
        return False, "Windows would not let me create the shortcut."
    return True, "VirtualBuddy will start when you sign in."


def disable() -> tuple[bool, str]:
    link = shortcut_path()
    try:
        link.unlink(missing_ok=True)
    except OSError as exc:
        return False, str(exc)
    return True, "VirtualBuddy will no longer start on its own."


def toggle() -> tuple[bool, str]:
    return disable() if enabled() else enable()
