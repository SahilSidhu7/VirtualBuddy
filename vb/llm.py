"""The model, reached through `vb.provider` (NVIDIA's free API).

This used to drive a local Ollama: pick a model by video memory, install the
server, pull the weights, warm them up. All of that is gone — the card was the
ceiling on how good the buddy could be. What is left is the small one-shot
surface the planner, the web skills and the UI were already written against,
so none of them had to change.

One rule survives from the Ollama days: never fail silently. `ask()` records
why it failed so the UI can say so.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from vb import config, provider

TIMEOUT = 120

_state: dict = {}
_last_error: str | None = None
STATUS_TTL = 60.0


def num_ctx() -> int:
    return int(config.get("num_ctx", 32768) or 32768)


# ---------------------------------------------------------------- hardware
def vram_mb() -> int:
    """Usable video memory in MB. 0 when there is no usable GPU.

    nvidia-smi is asked first because Windows reports AdapterRAM as a 32 bit
    value: an 8GB RTX 4060 shows up as 4GB, which would pick a needlessly
    small model.
    """
    if "vram" in _state:
        return _state["vram"]
    total = 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            total = max(int(line) for line in out.stdout.split() if line.isdigit())
    except (OSError, ValueError, subprocess.SubprocessError):
        total = 0
    if not total and sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | "
                 "Measure-Object AdapterRAM -Maximum).Maximum"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            total = int(out.stdout.strip()) // (1024 * 1024)
        except (OSError, ValueError, subprocess.SubprocessError):
            total = 0
    _state["vram"] = total
    return total


def gpu_name() -> str:
    if "gpu" in _state:
        return _state["gpu"]
    name = ""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            name = out.stdout.strip().splitlines()[0].strip()
    except (OSError, IndexError, subprocess.SubprocessError):
        name = ""
    _state["gpu"] = name
    return name


def ram_mb() -> int:
    """System memory. Matters because a model too big for the card can still
    run on the processor, just slowly."""
    if "ram" in _state:
        return _state["ram"]
    total = 0
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        if sys.platform == "win32":
            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            total = status.ullTotalPhys // (1024 * 1024)
        else:
            total = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                     // (1024 * 1024))
    except Exception:
        total = 0
    _state["ram"] = total
    return total


def hardware() -> dict:
    """What this machine has, in the terms that decide which model to run."""
    vram = vram_mb()
    return {
        "gpu": gpu_name(),
        "vram_mb": vram,
        "ram_mb": ram_mb(),
        "cores": os.cpu_count() or 1,
        "summary": (f"{gpu_name() or 'no GPU'}"
                    + (f", {vram / 1024:.0f}GB video memory" if vram else "")
                    + f", {ram_mb() / 1024:.0f}GB RAM"),
    }


def recommended_model() -> str:
    """The first model the work tier will try."""
    return provider.chain("work")[0]


# ------------------------------------------------------------------ status
def status() -> dict:
    """Is the API usable? Cached for a minute — the loop asks every turn."""
    now = time.time()
    cached = _state.get("status")
    if cached and now - cached[0] < STATUS_TTL:
        return cached[1]
    ok, message = provider.ping()
    out = {"state": "ready" if ok else ("no_key" if not provider.api_key()
                                        else "no_api"),
           "model": recommended_model(), "message": message}
    _state["status"] = (now if ok else now - STATUS_TTL + 5, out)
    return out


def enabled() -> bool:
    return status()["state"] == "ready"


def running() -> bool:
    return enabled()


def models() -> list[str]:
    return provider.models()


def installed(model: str) -> bool:
    """Hosted models need no download; "installed" means the key can see it."""
    have = provider.models()
    return not have or model in have


# -------------------------------------------------------------- generation
def last_error() -> str | None:
    return _last_error or provider.last_error()


def ask(prompt: str, system: str = "", *, json_mode: bool = False,
        max_tokens: int = 900, timeout: int = TIMEOUT,
        temperature: float = 0.2, tier: str = "work") -> str | None:
    """One-shot completion. None means it failed; last_error() says why."""
    global _last_error
    messages = ([{"role": "system", "content": system}] if system else []) +                [{"role": "user", "content": prompt}]
    try:
        # No reasoning pass for one-shot writing: it is a summary or a JSON
        # object, not a decision, and the reasoning tokens come out of the same
        # budget — a research write-up was cut off mid-sentence by them.
        msg, _model = provider.chat(messages, tier=tier, json_mode=json_mode,
                                    max_tokens=max_tokens, timeout=timeout,
                                    temperature=temperature, think=False)
    except provider.ProviderError as exc:
        _last_error = str(exc)
        return None
    _last_error = None
    text = (msg.get("content") or "").strip()
    if not text:
        # Reasoning models put their thoughts in a separate field and, with a
        # tight budget, leave the answer empty. Their thoughts beat nothing.
        text = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    return strip_thinking(text) or None


def ask_json(prompt: str, system: str = "", timeout: int = TIMEOUT) -> dict | None:
    raw = ask(prompt, system, json_mode=True, timeout=timeout, temperature=0.1)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def strip_thinking(text: str) -> str:
    """Reasoning models emit <think> blocks. Nobody wants those in an answer."""
    import re
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S | re.I).strip()


def warm_up(on_progress=None) -> bool:
    """One tiny call, so a bad key shows up on the splash and not mid-task."""
    if on_progress:
        on_progress("Checking the connection…")
    return bool(ask("Reply with the single word: ready", max_tokens=8, timeout=60,
                    tier="fast"))
