"""The local model, spoken to over Ollama's HTTP API.

VirtualBuddy needs a model. Without one the web skills can only hand back the
text they scraped, which is what a page looks like, not an answer.

Two rules learned the hard way:

* Match model names exactly. A prefix match once made `qwen3:4b` "installed"
  because `qwen3:1.7b` was present. The app reported itself ready, every
  request 404ed, and every skill quietly fell back to raw text.
* Never fail silently. `ask()` records why it failed so the UI can say so.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from vb import config

HOST = "http://127.0.0.1:11434"
TIMEOUT = 180
KEEP_ALIVE = "30m"          # keep the model resident between questions

# Best model per graphics card, largest first. Sizes are the download; a Q4
# model needs roughly its file size in VRAM plus a little for context.
LADDER = [
    (13000, "qwen2.5:14b", "14B, for cards with 14GB or more"),
    (7000, "llama3.1:8b", "8B, the sweet spot on an 8GB card"),
    (5000, "qwen2.5:7b", "7B, comfortable on 6GB"),
    (3500, "qwen3:4b", "4B, fits a 4GB card"),
    (0, "qwen3:1.7b", "1.7B, for CPU or a very small card"),
]

# What each one costs to download, and what the user gets for it. Sizes are the
# Q4 quantisation Ollama serves by default.
CATALOGUE = {
    "qwen2.5:14b": (9.0, "Best answers. Wants a 14GB card."),
    "llama3.1:8b": (4.9, "Strong all-rounder, good at using tools."),
    # The agent loop spends most of its turns writing small scripts, and a
    # coding model is markedly better at that than a general one the same size.
    "qwen2.5-coder:7b": (4.7, "Best at writing the scripts the agent runs."),
    "qwen2.5:7b": (4.7, "Nearly as good, a gigabyte lighter."),
    "qwen3:4b": (2.6, "Quick and small. Fine for most tasks."),
    "qwen3:1.7b": (1.4, "Runs on anything. Simple jobs only."),
}

_state: dict = {}
_last_error: str | None = None


def num_ctx() -> int:
    """Context window to request. Kept in step with `backends.NUM_CTX`."""
    return int(config.get("num_ctx", 8192) or 8192)


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


def recommended_model() -> str:
    """The best model this machine should run."""
    chosen = config.get("llm_model")
    if chosen and config.get("llm_model_pinned"):
        return chosen
    have = vram_mb()
    for need, name, _blurb in LADDER:
        if have >= need:
            return name
    return LADDER[-1][1]


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


def model_options() -> list[dict]:
    """Every model, with an honest word about how it will run here.

    The ladder already picks one automatically. This exists so the user can
    overrule it during setup — someone who does not mind waiting may want the
    14B on an 8GB card, and someone on battery may want the 1.7B on a 16GB one.
    Both are reasonable, and only they know which.
    """
    vram, ram = vram_mb(), ram_mb()
    best = recommended_model()
    out = []
    for name, (size_gb, blurb) in CATALOGUE.items():
        need = size_gb * 1024 * 1.2          # weights plus room for context
        if vram >= need:
            fit, speed = "good", "runs on the graphics card"
        elif vram >= need * 0.65:
            fit, speed = "tight", "mostly on the card, some spill to RAM"
        elif ram >= need * 1.5:
            fit, speed = "slow", "on the processor — several times slower"
        else:
            fit, speed = "no", "too big for this machine"
        out.append({
            "name": name, "size_gb": size_gb, "blurb": blurb,
            "fit": fit, "speed": speed,
            "installed": installed(name),
            "recommended": name == best,
        })
    return out


# ------------------------------------------------------------------ server
def _get(path: str, timeout: float = 2.0):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return json.loads(r.read())


def running() -> bool:
    try:
        _state["models"] = [m["name"] for m in _get("/api/tags").get("models", [])]
        return True
    except Exception:
        _state.pop("models", None)
        return False


def models() -> list[str]:
    if "models" not in _state:
        running()
    return _state.get("models", [])


def installed(model: str) -> bool:
    """Exact match, or the same model with the default :latest tag."""
    have = models()
    return model in have or (":" not in model and f"{model}:latest" in have)


def ollama_installed() -> bool:
    from shutil import which
    if which("ollama"):
        return True
    from pathlib import Path
    return (Path.home() / "AppData/Local/Programs/Ollama/ollama.exe").exists()


def start_server() -> bool:
    """Launch `ollama serve` if it is installed but not answering."""
    if running():
        return True
    if not ollama_installed():
        return False
    try:
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    import time
    for _ in range(20):
        time.sleep(0.5)
        if running():
            return True
    return False


def enabled() -> bool:
    return running() and installed(config.get("llm_model") or recommended_model())


def status() -> dict:
    model = config.get("llm_model") or recommended_model()
    if not ollama_installed():
        return {"state": "no_ollama", "model": model,
                "message": "Ollama is not installed.", "fix": "install_ollama"}
    if not running():
        return {"state": "no_server", "model": model,
                "message": "Ollama is installed but not running.", "fix": "start_server"}
    if not installed(model):
        return {"state": "no_model", "model": model,
                "message": f"{model} is not downloaded yet.", "fix": "pull_model"}
    return {"state": "ready", "model": model, "message": f"Ready ({model})."}


# -------------------------------------------------------------- generation
def last_error() -> str | None:
    return _last_error


def _post(path: str, payload: dict, timeout: int) -> dict | None:
    global _last_error
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _last_error = None
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        _last_error = f"Ollama said {exc.code}: {body}"
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
    return None


def ask(prompt: str, system: str = "", *, json_mode: bool = False,
        max_tokens: int = 900, timeout: int = TIMEOUT,
        temperature: float = 0.2) -> str | None:
    """One-shot completion. None means it failed; last_error() says why."""
    model = config.get("llm_model") or recommended_model()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        # Reasoning models (hermes-agent, qwen3) put their chain of thought in
        # a separate `thinking` field and leave `response` **empty**. Nothing
        # here reads `thinking`, so every call returned None and the model
        # looked broken — the same silent-failure shape as the prefix-match bug
        # above. `think` is ignored by models without the capability, so it is
        # safe to send unconditionally.
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": temperature,
                    # Without this the model's *own* declared context wins, and
                    # some declare a very large one: hermes-agent asks for
                    # 262144 tokens, whose KV cache does not fit an 8GB card.
                    # Ollama then answers 500 "llama-server startup failed
                    # before projector CPU offload retry: ... cudaMalloc failed:
                    # out of memory" and every call through here returns None.
                    # /api/chat already pins it; this path never did.
                    "num_ctx": num_ctx()},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    out = _post("/api/generate", payload, timeout)
    if not out:
        return None
    text = (out.get("response") or "").strip()
    if not text:
        # A model that ignored `think: false` and spent the whole budget
        # reasoning. Its thoughts are better than nothing.
        text = (out.get("thinking") or "").strip()
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


# ----------------------------------------------------------------- setup
def pull(model: str | None = None, on_progress=None) -> bool:
    """Download a model, reporting percent complete. Blocking."""
    model = model or config.get("llm_model") or recommended_model()
    req = urllib.request.Request(
        HOST + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=None) as r:
            for line in r:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if on_progress:
                    if msg.get("total"):
                        percent = int(100 * msg.get("completed", 0) / msg["total"])
                        on_progress(percent, msg.get("status", ""))
                    else:
                        on_progress(None, msg.get("status", ""))
                if msg.get("status") == "success":
                    _state.pop("models", None)
                    return True
    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return False
    return False


def warm_up(on_progress=None) -> bool:
    """Load the model into VRAM so the first real question is not the slow one.

    A cold 8B model takes several seconds to load. Doing it during the splash
    means the first thing the user asks feels instant.
    """
    if on_progress:
        on_progress("Warming the model up…")
    reply = ask("Reply with the single word: ready", max_tokens=8, timeout=180)
    return bool(reply)


def install_ollama(on_progress=None) -> bool:
    """Install Ollama itself, via winget. Windows only."""
    if sys.platform != "win32":
        return False
    if on_progress:
        on_progress("Installing Ollama…")
    try:
        done = subprocess.run(
            ["winget", "install", "--id", "Ollama.Ollama", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and ollama_installed()
