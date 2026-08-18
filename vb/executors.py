"""Where code runs. Here, in a container, or on another machine.

`vb.sandbox` runs things as the user, on the user's real files, guarded by a
regex. That is the right default for a desktop assistant — the whole point is
to act on *this* machine — and it is also the reason the safety story has a
ceiling. A container has no opinion about which regex it matched; it simply
cannot reach the files it was not given.

Three backends, chosen per run:

    local    the default. Full access, policy-checked. Fast.
    docker   a throwaway container with the workspace mounted and nothing else.
             Genuine isolation, and the only mode where a bad command is
             contained rather than merely discouraged.
    ssh      another machine entirely, over the user's existing SSH config.
             For "run this on the server", which no regex can make safe here.

The interface is the one `sandbox.Run` already has, so the tools do not care
which backend answered. Configuration lives in `config.json` under
`executor` and `executor_hosts`; with nothing set, everything is local and this
module is a thin pass-through.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

from vb import config, progress, sandbox
from vb.sandbox import Run, Verdict

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_IMAGE = "python:3.12-slim"
CONTAINER_TIMEOUT = 180


def which() -> str:
    """The configured backend: local | docker | ssh."""
    choice = str(config.get("executor", "local") or "local").lower()
    return choice if choice in ("local", "docker", "ssh") else "local"


def describe() -> str:
    mode = which()
    if mode == "docker":
        return (f"docker ({config.get('docker_image') or DEFAULT_IMAGE})"
                + ("" if docker_ready() else "  — Docker is not running"))
    if mode == "ssh":
        host = config.get("ssh_host") or "(no host set)"
        return f"ssh ({host})"
    return "local (this machine, policy-checked)"


# ------------------------------------------------------------------- docker
def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        done = subprocess.run(["docker", "info"], capture_output=True,
                              text=True, timeout=15, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _docker_run(argv: list[str], timeout: int) -> Run:
    """Run a command in a throwaway container with only the workspace mounted.

    `--rm` so nothing accumulates, `--network none` unless the user turns it
    back on, and the workspace bind-mounted at /work. Nothing else on the
    machine is visible from inside, which is the entire reason to use this.
    """
    image = config.get("docker_image") or DEFAULT_IMAGE
    home = sandbox.workspace()
    home.mkdir(parents=True, exist_ok=True)
    network = "bridge" if config.get("docker_network", False) else "none"

    command = ["docker", "run", "--rm", "-i",
               "--network", network,
               "-v", f"{home}:/work", "-w", "/work",
               "--memory", str(config.get("docker_memory") or "2g"),
               image, *argv]
    started = time.time()
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8",
                              errors="replace", creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Run(ok=False, output=f"The container timed out after {timeout}s.",
                   seconds=time.time() - started)
    except OSError as exc:
        return Run(ok=False, output=f"Docker would not run: {exc}",
                   seconds=time.time() - started)
    output = (done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")
    return Run(ok=done.returncode == 0, output=output.strip(),
               exit_code=done.returncode, seconds=time.time() - started)


# ---------------------------------------------------------------------- ssh
def _ssh_run(command: str, timeout: int) -> Run:
    """Run a command on the configured host via the system ssh client.

    Keys and host aliases come from the user's own `~/.ssh/config`. Nothing
    about credentials is handled here, deliberately: an assistant that starts
    collecting SSH passwords is a worse idea than one that cannot log in.
    """
    host = config.get("ssh_host")
    if not host:
        return Run(ok=False, output="No ssh_host configured.")
    if not shutil.which("ssh"):
        return Run(ok=False, output="No ssh client on this machine.")

    started = time.time()
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
             str(host), command],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8",
            errors="replace", creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Run(ok=False, output=f"{host} did not answer in {timeout}s.",
                   seconds=time.time() - started)
    except OSError as exc:
        return Run(ok=False, output=f"ssh would not run: {exc}",
                   seconds=time.time() - started)
    output = (done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")
    if done.returncode == 255 and "Permission denied" in output:
        return Run(ok=False, seconds=time.time() - started, exit_code=255,
                   output=f"{host} refused the key. BatchMode is on, so there "
                          f"is no password prompt — set up key auth first.")
    return Run(ok=done.returncode == 0, output=output.strip(),
               exit_code=done.returncode, seconds=time.time() - started)


# ------------------------------------------------------------------ the door
@dataclass
class Where:
    mode: str
    isolated: bool          # can a bad command reach the user's files?


def target() -> Where:
    mode = which()
    return Where(mode=mode, isolated=mode in ("docker", "ssh"))


def run_shell(command: str, *, timeout: int = 120, approved: bool = False) -> Run:
    """Run a shell command wherever the executor points."""
    mode = which()
    if mode == "local":
        return sandbox.run_shell(command, timeout=timeout, approved=approved)

    # Inside a container or on another host the policy check is advice rather
    # than protection — the blast radius is already bounded by the boundary.
    # The deny list still applies, because "wipe the server" is not made
    # acceptable by the server being remote.
    verdict = sandbox.classify(command)
    if verdict.blocked:
        return Run(ok=False, verdict=verdict,
                   output=f"Refused: this {verdict.reason}.")
    if mode == "ssh" and verdict.action == "confirm" and not approved:
        return Run(ok=False, verdict=verdict,
                   output=f"Needs your approval first: this {verdict.reason}, "
                          f"on a machine that is not this one.")

    progress.say(f"Running on {describe()}: {command[:60]}")
    if mode == "docker":
        if not docker_ready():
            return Run(ok=False, output="Docker is not running.")
        return _docker_run(["sh", "-lc", command], timeout)
    return _ssh_run(command, timeout)


def run_python(code: str, *, timeout: int = 120, approved: bool = False) -> Run:
    """Run a Python snippet wherever the executor points."""
    mode = which()
    if mode == "local":
        return sandbox.run_python(code, timeout=timeout, approved=approved)

    verdict = sandbox.classify(code)
    if verdict.blocked:
        return Run(ok=False, verdict=verdict,
                   output=f"Refused: this {verdict.reason}.")

    if mode == "docker":
        if not docker_ready():
            return Run(ok=False, output="Docker is not running.")
        progress.say("Running a script in a container…")
        # Through stdin, so the script never has to be quoted into a command
        # line and a stray quote cannot end it early.
        return _docker_stdin(code, timeout)

    # Over SSH the script is sent to a remote python on stdin, same reasoning.
    return _ssh_run(f"python3 -c \"$(cat)\" <<'VBEOF'\n{code}\nVBEOF", timeout)


def _docker_stdin(code: str, timeout: int) -> Run:
    image = config.get("docker_image") or DEFAULT_IMAGE
    home = sandbox.workspace()
    home.mkdir(parents=True, exist_ok=True)
    network = "bridge" if config.get("docker_network", False) else "none"
    started = time.time()
    try:
        done = subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", network,
             "-v", f"{home}:/work", "-w", "/work",
             "--memory", str(config.get("docker_memory") or "2g"),
             image, "python", "-"],
            input=code, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Run(ok=False, output=f"The container timed out after {timeout}s.",
                   seconds=time.time() - started)
    except OSError as exc:
        return Run(ok=False, output=f"Docker would not run: {exc}",
                   seconds=time.time() - started)
    output = (done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")
    return Run(ok=done.returncode == 0, output=output.strip(),
               exit_code=done.returncode, seconds=time.time() - started)
