"""Optional local LLM, spoken to over Ollama's HTTP API.

Nothing in the app requires this. Skills call `ask()` and get None when no
model is available, then fall back to their extractive path. The default model
is chosen to fit a 4GB card: qwen3:4b at Q4 is ~2.6GB of VRAM.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from vb import config

HOST = "http://127.0.0.1:11434"
TIMEOUT = 120

_state: dict = {}


def _post(path: str, payload: dict, timeout: int = TIMEOUT) -> dict | None:
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def running() -> bool:
    """Is an Ollama server up? Cached per process after the first success."""
    if _state.get("running"):
        return True
    try:
        with urllib.request.urlopen(HOST + "/api/tags", timeout=1.5) as r:
            _state["models"] = [m["name"] for m in json.loads(r.read()).get("models", [])]
            _state["running"] = True
            return True
    except Exception:
        return False


def models() -> list[str]:
    return _state.get("models", []) if running() else []


def has_model() -> bool:
    want = config.get("llm_model")
    return any(m == want or m.startswith(want.split(":")[0]) for m in models())


def enabled() -> bool:
    """True when a skill may actually use the LLM."""
    return config.get("llm") != "off" and running() and has_model()


def status() -> dict:
    """For the settings UI: what's missing, if anything."""
    if config.get("llm") == "off":
        return {"state": "off", "message": "Smart mode disabled in settings."}
    if not running():
        return {"state": "no_server", "message": "Ollama isn't running.",
                "fix": "install_ollama"}
    if not has_model():
        return {"state": "no_model",
                "message": f"Model {config.get('llm_model')} not downloaded.",
                "fix": "pull_model"}
    return {"state": "ready", "message": f"Smart mode on ({config.get('llm_model')})."}


def ask(prompt: str, system: str = "", *, json_mode: bool = False,
        max_tokens: int = 800, timeout: int = TIMEOUT) -> str | None:
    """One-shot completion. Returns None whenever the LLM isn't usable."""
    if not enabled():
        return None
    payload = {
        "model": config.get("llm_model"),
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.2},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    out = _post("/api/generate", payload, timeout)
    if not out:
        return None
    text = (out.get("response") or "").strip()
    return text or None


def ask_json(prompt: str, system: str = "", timeout: int = TIMEOUT) -> dict | None:
    raw = ask(prompt, system, json_mode=True, timeout=timeout)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def pull(model: str | None = None, on_progress=None) -> bool:
    """Download a model, reporting percent complete. Blocking; call off-thread."""
    model = model or config.get("llm_model")
    req = urllib.request.Request(
        HOST + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=None) as r:
            for line in r:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if on_progress and msg.get("total"):
                    on_progress(int(100 * msg.get("completed", 0) / msg["total"]),
                                msg.get("status", ""))
                if msg.get("status") == "success":
                    _state.pop("models", None)
                    _state.pop("running", None)
                    return True
    except Exception:
        return False
    return False
