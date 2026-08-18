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
    # The model is not optional any more: without one, web answers are just
    # scraped text. Empty means "pick the best one this machine can run", which
    # llm.recommended_model() decides from the amount of video memory.
    "llm_model": "",
    "llm_model_pinned": False,   # True once the user chooses one by hand
    "skip_splash": False,        # set once a model is known good
    "browser_tier": "auto",    # auto = fall back to Playwright when HTTP fails
    # The agent loop. Local models do the work; the Claude Code CLI is only
    # reached for after the local one has failed twice, and only if the user
    # already has it installed — it costs them nothing extra per call.
    # Off by default. This was added on the understanding that the Claude Code
    # CLI came out of a flat-rate subscription and so cost nothing per call;
    # it does not — it reports a per-token cost like any API, and it refuses
    # programmatic driving anyway. The stated goal was zero cost per task, so
    # the tier that breaks that promise is opt-in.
    "use_claude_code": False,
    "agent_max_steps": 12,
    # After a task the buddy writes itself a note on how it did it, and reads
    # it back next time. "auto" writes them, "off" does not. The notes are
    # plain markdown in the data folder — readable, editable, deletable.
    "learn_skills": "auto",
    "mcp_servers": {},         # name -> {"command": [...], "env": {...}}
    # Every run is written to traces.jsonl, which is what a fine-tune is made
    # from. Local file, never uploaded; `python -m vb.cli` then /traces shows
    # what is there and how to wipe it.
    "collect_traces": True,
    # Where code runs: local | docker | ssh. See vb/executors.py. Docker is the
    # only mode where a bad command is contained rather than discouraged.
    "executor": "local",
    "docker_image": "",        # empty = python:3.12-slim
    "docker_network": False,   # containers get no network unless asked
    "docker_memory": "2g",
    "ssh_host": "",            # an alias from the user's own ~/.ssh/config
    # Chat frontends. Nothing starts unless a token is set. chat_allow is a
    # list of usernames; empty means anyone who can reach the bot.
    "telegram_token": "",
    "discord_token": "",
    "discord_channel": "",
    "chat_allow": [],
    "vision_model": "",        # empty = the best one installed
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
