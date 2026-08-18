"""Running code and shell commands, which is where the capability lives.

An agent that can write and run a script can do things nobody wrote a skill
for. That is most of the difference between a menu of features and something
that can be given a real task. It is also the part that can wreck a machine, so
this module is the whole safety story:

    deny     never runs, not even with a yes. Things with no undo and no
             legitimate reason to be in a chat request: formatting a disk,
             wiping shadow copies, turning off Defender, editing the boot
             record.
    confirm  runs only after the user agrees. Deletes and writes outside the
             workspace, installs, shutdowns, anything pushed to a remote.
    allow    runs unattended. Reads, computation, and anything inside the
             workspace, which the agent owns.

Be clear about what this is not. It is a policy check over the text of a
command, not a sandbox: the code runs as the user, with the user's permissions,
on the user's real filesystem. Patterns catch the destructive things a model
reaches for by accident, and they are written to survive the obvious dodges —
an aliased import, a method called off a different name — but a determined
attempt to hide an intent from a regex will succeed. The isolation that would
actually contain it is a separate account or a container, and neither is here.
What is here is a fast check on the common case, a confirmation prompt on the
irreversible one, and `audit.jsonl`, which records every run either way.

That is the trade the user asked for: maximum capability, with the genuinely
irreversible actions gated.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from vb import config, progress

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_TIMEOUT = 120
MAX_OUTPUT = 6000          # characters handed back to the model


def workspace() -> Path:
    """The agent's own folder. Scripts, downloads and scratch files land here."""
    return config.data_dir("workspace")


def audit_path() -> Path:
    return config.data_dir() / "audit.jsonl"


def inside_workspace(path) -> bool:
    """Is this path really inside the agent's own folder?

    One helper, used by everything that asks, because the obvious version is
    wrong: `str(target).startswith(str(workspace()))` says yes to
    `…/workspaceEVIL/x.txt`, which is a different directory entirely. Resolving
    first also collapses `..`, so a traversal cannot walk out and back in.
    """
    if not isinstance(path, (str, Path)) or not str(path).strip():
        # An empty path resolves to the workspace itself and would answer yes,
        # which is the wrong answer to "may I write to nowhere in particular".
        return False
    try:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = workspace() / target
        return target.resolve().is_relative_to(workspace().resolve())
    except (OSError, ValueError, TypeError):
        return False


# ------------------------------------------------------------- the classifier
# No undo, no plausible reason to be here. These are refused outright.
DENY = [
    (r"\bformat\s+[a-z]:", "formats a drive"),
    (r"\bdiskpart\b", "repartitions disks"),
    (r"\bbcdedit\b|\bbootrec\b", "edits the boot configuration"),
    (r"vssadmin\s+delete\s+shadows", "deletes the restore points"),
    (r"\bcipher\s+/w", "wipes free space irrecoverably"),
    (r"Set-MpPreference[^\n]*DisableRealtimeMonitoring\s*\$?true", "disables Defender"),
    (r"\bmpcmdrun\b[^\n]*-RemoveDefinitions", "disables Defender"),
    (r"reg(\.exe)?\s+delete\s+[\"']?HK(LM|EY_LOCAL_MACHINE)", "deletes machine registry keys"),
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+/(\s|$)", "deletes the filesystem root"),
    (r"(?i)remove-item[^\n]*\b[a-z]:\\?\s*-recurse", "deletes a whole drive"),
    (r"\bdel\s+/[sq]\b[^\n]*\b[a-z]:\\(windows|program files)", "deletes system files"),
    (r":\(\)\s*\{.*\|.*&.*\}\s*;?\s*:", "fork bomb"),
    (r"\bnetsh\s+advfirewall\s+set\s+\w+\s+state\s+off", "turns the firewall off"),
]

# Reversible only with effort, or reaches outside this machine. Ask first.
CONFIRM = [
    (r"\b(shutdown|restart-computer|stop-computer)\b", "shuts the computer down"),
    (r"\b(rmdir|rd)\s+/s|\bremove-item\b[^\n]*-recurse|\brm\s+-[a-z]*r", "deletes a folder tree"),
    # `del` as a shell verb takes something that looks like a file: a switch, a
    # path separator, a wildcard or an extension. The Python keyword takes a
    # variable name. Without the distinction, `del old_var` raised a dialog on
    # perfectly ordinary code — and a user asked to approve harmless things
    # learns to approve everything, which costs more than it saves.
    (r"\b(del|erase)\s+(?:/[a-z]+\s+)*[\"']?[^\s\"']*"
     r"(?:[\\/*?]|\.[A-Za-z0-9]{1,4}\b)", "deletes files"),
    (r"\b(remove-item|rm|unlink)\b", "deletes files"),
    # The same intent written in Python. These are anchored to the modules that
    # actually delete things, not to the method name alone. The looser version
    # matched `my_list.remove(x)`, `text.replace("a","b")` and `df.rename(...)`
    # — ordinary lines in almost every generated script — and asking the user
    # to approve those, with a wrong reason attached, is how consent becomes a
    # reflex. `rmtree(` stays unanchored because it is unambiguous and it is
    # how an aliased import shows up.
    (r"\brmtree\s*\(|\bos\.(remove|unlink|rmdir|removedirs)\s*\(|"
     r"\bsend2trash\b|\bPath\([^)]*\)\.unlink\s*\(", "deletes files"),
    (r"\b(os|shutil)\.(rename|replace|move|copytree)\s*\(",
     "moves or renames files"),
    (r"\bos\.system\s*\(|\bos\.popen\s*\(|\bsubprocess\.\w+\s*\(|"
     r"\bPopen\s*\(|\bcheck_output\s*\(", "shells out to another command"),
    # Dynamic execution defeats every pattern above by construction: the string
    # being run is not in the source. `compile` is required to be a bare call —
    # `re.compile(...)` is in half the scripts written here and is not this.
    (r"\bexec\s*\(|\beval\s*\(|(?<![\w.])compile\s*\(|\b__import__\s*\(",
     "builds and runs code at runtime"),
    (r"\bctypes\b|\bwinreg\b|\bpywin32\b|\bwin32api\b",
     "reaches into Windows internals"),
    (r"\bgit\s+(push|reset\s+--hard|clean\s+-[a-z]*f)", "rewrites or publishes a repo"),
    (r"\b(pip|pip3|npm|winget|choco|scoop|apt|apt-get)\s+(install|uninstall|remove)",
     "installs or removes software"),
    (r"\bcurl\b[^\n]*\|\s*(sh|bash|powershell)|\biwr\b[^\n]*\|\s*iex", "runs a script off the internet"),
    (r"\bschtasks\b|\bnew-scheduledtask\b|\bsc(\.exe)?\s+(create|delete|config)\b",
     "changes what runs on this machine"),
    (r"\bnet\s+user\b|\bnew-localuser\b", "changes user accounts"),
    (r"\btaskkill\b|\bstop-process\b|\bkill\b", "kills running processes"),
    (r"reg(\.exe)?\s+(add|delete)\b|\bset-itemproperty[^\n]*hk(lm|cu):", "edits the registry"),
    (r"\b(move-item|mv|move|rename-item|ren)\b", "moves or renames files"),
    (r"\b(smtplib|sendmail|send-mailmessage)\b", "sends mail"),
    (r"requests\.(post|put|delete|patch)|urlopen\([^)]*data=", "sends data somewhere"),
]

# Writes are fine in the agent's own folder and worth a question outside it.
WRITE_HINT = re.compile(
    r"\bopen\([^)]*['\"][wax]b?['\"]|>\s*\S|\bout-file\b|\bset-content\b|"
    r"\badd-content\b|\bwrite_text\b|\bwrite_bytes\b|\bmkdir\b|\bnew-item\b", re.I)


@dataclass
class Verdict:
    action: str            # allow | confirm | deny
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.action == "deny"


def classify(command: str, *, cwd: str | None = None) -> Verdict:
    """Decide what this command is allowed to do, before running any of it."""
    text = command or ""
    for pattern, why in DENY:
        if re.search(pattern, text, re.I):
            return Verdict("deny", why)
    for pattern, why in CONFIRM:
        if re.search(pattern, text, re.I):
            return Verdict("confirm", why)
    if WRITE_HINT.search(text) and not _writes_only_inside(text, cwd):
        return Verdict("confirm", "writes outside its own workspace")
    return Verdict("allow")


def _writes_only_inside(text: str, cwd: str | None) -> bool:
    """True when no absolute path outside the workspace is mentioned.

    Relative paths resolve against the workspace, so a command with no absolute
    path in it cannot escape. Anything naming a path elsewhere is treated as
    writing there, even if it is only reading it — over-asking is the cheap
    mistake here.
    """
    try:
        if cwd and Path(cwd).resolve() != workspace().resolve():
            return False
    except (OSError, ValueError):
        return False
    for hit in re.findall(r"[a-zA-Z]:[\\/][^\s\"'<>|]*|/[^\s\"'<>|:]{3,}", text):
        if not inside_workspace(hit.strip("\"'")):
            return False
    return True


# -------------------------------------------------------------------- audit
def _log(kind: str, command: str, verdict: Verdict, code: int | None,
         seconds: float) -> None:
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "verdict": verdict.action,
        "reason": verdict.reason,
        "exit": code,
        "seconds": round(seconds, 2),
        "command": command[:2000],
    }
    try:
        with audit_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass          # never let logging be the thing that fails a run


# ------------------------------------------------------------------ running
@dataclass
class Run:
    ok: bool
    output: str
    exit_code: int | None = None
    verdict: Verdict | None = None
    seconds: float = 0.0

    @property
    def silent(self) -> bool:
        """Ran fine and told us nothing. Not the same as having worked."""
        return self.ok and not self.output.strip()

    def as_observation(self) -> str:
        """What the model is shown. Truncated from the middle: an error is
        usually at the end, and the command that caused it at the start."""
        if self.silent:
            # Exit code zero on a silent script is the easiest thing in this
            # whole system to mistake for success. It has to read as a warning,
            # or the model calls finish on the strength of nothing at all.
            return (f"[ran in {self.seconds:.1f}s but printed nothing]\n"
                    f"That tells you nothing about whether it worked. Print the "
                    f"result, or read back what you wrote, before you finish.")
        text = self.output.strip() or "(no output)"
        if len(text) > MAX_OUTPUT:
            head, tail = text[:MAX_OUTPUT // 2], text[-MAX_OUTPUT // 2:]
            cut = len(text) - MAX_OUTPUT
            text = f"{head}\n… [{cut} characters cut] …\n{tail}"
        status = "ok" if self.ok else f"failed (exit {self.exit_code})"
        return f"[{status} in {self.seconds:.1f}s]\n{text}"


def _finish(proc: subprocess.CompletedProcess) -> str:
    return ((proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")).strip()


def run_shell(command: str, *, cwd: str | None = None,
              timeout: int = DEFAULT_TIMEOUT, approved: bool = False) -> Run:
    """Run a shell command. PowerShell on Windows, sh elsewhere."""
    verdict = classify(command, cwd=cwd)
    if verdict.blocked or (verdict.action == "confirm" and not approved):
        _log("shell", command, verdict, None, 0.0)
        note = ("Refused: this " + verdict.reason + "."
                if verdict.blocked else
                "Needs your approval first: this " + verdict.reason + ".")
        return Run(ok=False, output=note, verdict=verdict)

    where = str(cwd or workspace())
    Path(where).mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["/bin/sh", "-c", command]

    progress.say(f"Running: {command[:70]}")
    started = time.time()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=where,
                              timeout=timeout, encoding="utf-8", errors="replace",
                              creationflags=NO_WINDOW,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired as exc:
        took = time.time() - started
        _log("shell", command, verdict, None, took)
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return Run(ok=False, output=f"Timed out after {timeout}s.\n{partial}",
                   verdict=verdict, seconds=took)
    except OSError as exc:
        took = time.time() - started
        _log("shell", command, verdict, None, took)
        return Run(ok=False, output=f"Could not start: {exc}", verdict=verdict,
                   seconds=took)
    took = time.time() - started
    _log("shell", command, verdict, proc.returncode, took)
    return Run(ok=proc.returncode == 0, output=_finish(proc),
               exit_code=proc.returncode, verdict=verdict, seconds=took)


def run_python(code: str, *, timeout: int = DEFAULT_TIMEOUT,
               approved: bool = False) -> Run:
    """Run a Python snippet in its own process, inside the workspace.

    A separate process, not exec() in ours: a script with an infinite loop or a
    segfault then costs a timeout instead of the whole app.
    """
    verdict = classify(code)
    if verdict.blocked or (verdict.action == "confirm" and not approved):
        _log("python", code, verdict, None, 0.0)
        note = ("Refused: this " + verdict.reason + "."
                if verdict.blocked else
                "Needs your approval first: this " + verdict.reason + ".")
        return Run(ok=False, output=note, verdict=verdict)

    home = workspace()
    home.mkdir(parents=True, exist_ok=True)
    script = home / f"_step_{int(time.time() * 1000)}.py"
    try:
        script.write_text(code, "utf-8")
    except OSError as exc:
        return Run(ok=False, output=f"Could not write the script: {exc}",
                   verdict=verdict)

    progress.say("Running a script…")
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                              text=True, cwd=str(home), timeout=timeout,
                              encoding="utf-8", errors="replace",
                              creationflags=NO_WINDOW,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        took = time.time() - started
        _log("python", code, verdict, None, took)
        return Run(ok=False, output=f"Timed out after {timeout}s.",
                   verdict=verdict, seconds=took)
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    took = time.time() - started
    _log("python", code, verdict, proc.returncode, took)
    return Run(ok=proc.returncode == 0, output=_finish(proc),
               exit_code=proc.returncode, verdict=verdict, seconds=took)


def recent_audit(limit: int = 20) -> list[dict]:
    try:
        lines = audit_path().read_text("utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
