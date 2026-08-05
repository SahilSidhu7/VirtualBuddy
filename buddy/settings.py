"""Settings + where buddy keeps its files.

Config and everything buddy writes (workspace, trained model, learning data)
live in a user folder, NOT next to the program. This makes the packaged app
work when installed read-only, and keeps your settings across updates.

  VB_HOME env var overrides the location. Default: ~/.virtualbuddy
"""
import os, yaml

HOME = os.environ.get("VB_HOME") or os.path.join(os.path.expanduser("~"), ".virtualbuddy")
CONFIG_PATH = os.path.join(HOME, "config.yaml")

def models_dir():
    d = os.path.join(HOME, "models"); os.makedirs(d, exist_ok=True); return d

def data_dir():
    d = os.path.join(HOME, "data"); os.makedirs(d, exist_ok=True); return d

def clf_path():
    return os.path.join(models_dir(), "intent_clf.joblib")

_DEFAULTS = {
    "wake_word": "buddy",
    "character": "robot",
    "match_threshold": 0.40,
    "speak_replies": True,
    "claude_cli": "claude",
    "workspace": os.path.join(HOME, "workspace"),
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
    os.makedirs(HOME, exist_ok=True)
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg.update(yaml.safe_load(f) or {})
    else:
        save(cfg)                    # first run: seed the user config
    os.makedirs(cfg["workspace"], exist_ok=True)
    return cfg

def save(cfg):
    os.makedirs(HOME, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

def is_first_run():
    """No trained intent model yet -> good moment to offer training."""
    return not os.path.exists(clf_path())
