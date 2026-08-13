"""User settings, stored next to the user's data — never inside the install dir,
so an update or a reinstall can't wipe them."""
from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("VB_HOME") or (Path.home() / ".virtualbuddy"))
CONFIG_PATH = HOME / "config.json"

DEFAULTS = {
    "mode": "manual",          # manual = confirm the match, auto = just run it
    "avatar": "duck",          # duck | elf | crab
    "voice_input": False,      # vosk wake-word listening
    "speak": False,            # read replies aloud
    "llm": "auto",             # auto = use Ollama if it's running, off = never
    "llm_model": "qwen3:4b",
    "browser_tier": "auto",    # auto = fall back to Playwright when HTTP fails
}


def _read() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    except Exception:
        return {}


_cache: dict | None = None


def all() -> dict:
    global _cache
    if _cache is None:
        _cache = {**DEFAULTS, **_read()}
    return _cache


def get(key: str, default=None):
    return all().get(key, DEFAULTS.get(key, default))


def set(key: str, value) -> dict:
    cfg = all()
    cfg[key] = value
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), "utf-8")
    return cfg


def data_dir(*parts: str) -> Path:
    p = HOME.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
