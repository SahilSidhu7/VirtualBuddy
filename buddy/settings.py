"""Loads config.yaml. Falls back to defaults if missing."""
import os, yaml

_DEFAULTS = {
    "wake_word": "buddy",
    "character": "robot",
    "match_threshold": 0.45,
    "speak_replies": True,
    "claude_cli": "claude",
    "workspace": "./workspace",
    "llm_enabled": True,
    "llm_model": "qwen2.5:latest",
    "ollama_url": "http://localhost:11434",
    "embed_model": "nomic-embed-text",
    "power_save": False,
    "server_port": 8770,
    "server_token": "changeme",
    "peers": {},
    "projects_dirs": [],
    "notion_token": "",
    "notion_db": "",
}

def load():
    path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    cfg = dict(_DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(yaml.safe_load(f) or {})
    os.makedirs(cfg["workspace"], exist_ok=True)
    return cfg
