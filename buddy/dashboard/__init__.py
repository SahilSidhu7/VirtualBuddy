"""Modern dashboard — HTML/CSS in a native window via pywebview.

Replaces the boxy tkinter control panel. Logic stays in Python (the Api class,
exposed to the page as window.pywebview.api.*); the look lives in index.html.

If the webview runtime isn't available we fall back to the old tkinter panel so
the app still opens everywhere.

  from buddy import dashboard; dashboard.run()
"""
import os, sys, glob, base64, subprocess, threading

from buddy import settings

_HERE = os.path.dirname(os.path.abspath(__file__))                 # buddy/dashboard
_ROOT = os.path.dirname(os.path.dirname(_HERE))                    # project root
HTML = os.path.join(_HERE, "index.html")
ASSETS = os.path.join(_ROOT, "assets", "character")


VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

# progress of the one-off speech-model download, polled by the page
_voice_setup = {"running": False, "percent": 0, "error": ""}


def _download_voice_model():
    """Fetch + unzip the Vosk model into ~/.virtualbuddy/models/vosk."""
    import urllib.request, zipfile, tempfile, shutil
    _voice_setup.update({"running": True, "percent": 0, "error": ""})
    try:
        models = os.path.join(settings.HOME, "models")
        os.makedirs(models, exist_ok=True)
        dest = os.path.join(models, "vosk")
        if os.path.isdir(dest):
            _voice_setup.update({"running": False, "percent": 100})
            return

        def hook(blocks, block_size, total):
            if total > 0:
                _voice_setup["percent"] = min(99, int(blocks * block_size * 100 / total))

        zip_path = os.path.join(tempfile.gettempdir(), "vb_vosk.zip")
        urllib.request.urlretrieve(VOSK_URL, zip_path, reporthook=hook)
        staging = os.path.join(models, "_vosk_unzip")
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(staging)
        inner = [n for n in os.listdir(staging) if n.startswith("vosk-model")]
        # the zip holds one vosk-model-* folder; move it into place as "vosk"
        shutil.move(os.path.join(staging, inner[0]) if inner else staging, dest)
        shutil.rmtree(staging, ignore_errors=True)
        os.remove(zip_path)
        _voice_setup.update({"running": False, "percent": 100})
    except Exception as e:
        _voice_setup.update({"running": False, "percent": 0, "error": str(e)})


class Api:
    """Everything the page can call. All returns are JSON-serializable."""

    def __init__(self):
        self.cfg = settings.load()
        self._brain = None                  # built on first command, so the window opens fast

    # ---- talking to buddy ----
    def _agent(self):
        if self._brain is None:
            from buddy.agent import make_brain
            self._brain = make_brain(self.cfg)
        return self._brain

    def ask(self, text):
        """Run a command and return buddy's reply. This is the dashboard's chat box."""
        text = (text or "").strip()
        if not text:
            return {"ok": False, "reply": ""}
        try:
            return {"ok": True, "reply": str(self._agent().handle(text))}
        except Exception as e:
            return {"ok": False, "reply": f"That went wrong: {e}"}

    def voice_status(self):
        from buddy import listener
        state = dict(_voice_setup)                 # progress of a download, if one is running
        state.update({"ok": listener.available(),
                      "why": listener.why_unavailable() or ""})
        return state

    def setup_voice(self):
        """Download the offline speech model (~40MB) into the user folder.

        The installed app can't run install.py --voice, so without this every
        packaged user was stuck with text only.
        """
        from buddy import listener
        if listener.available():
            return {"ok": True, "msg": "Voice is already set up."}
        if _voice_setup.get("running"):
            return {"ok": True, "msg": "Already downloading…"}
        threading.Thread(target=_download_voice_model, daemon=True).start()
        return {"ok": True, "msg": "Downloading the speech model (~40MB)…"}

    def listen(self, seconds=6):
        """Record one spoken command and return the transcript (does not run it)."""
        from buddy import listener
        try:
            heard = listener.listen_once(self.cfg, seconds)
        except Exception as e:
            return {"ok": False, "text": "", "why": f"Microphone failed: {e}"}
        if not heard:
            return {"ok": False, "text": "", "why": "I didn't catch that."}
        return {"ok": True, "text": heard, "why": ""}

    # ---- config ----
    def get_config(self):
        self.cfg = settings.load()
        return {
            "wake_word": self.cfg.get("wake_word", "buddy"),
            "character": self.cfg.get("character", "duck"),
            "speak_replies": self.cfg.get("speak_replies", True),
            "power_save": self.cfg.get("power_save", False),
            "planner_enabled": self.cfg.get("planner_enabled", True),
            "match_threshold": self.cfg.get("match_threshold", 0.45),
            "claude_cli": self.cfg.get("claude_cli", "claude"),
            "auto_update": self.cfg.get("auto_update", False),
            "roam": self.cfg.get("roam", False),
            "use_claude": self.cfg.get("use_claude", False),
            "claude_writes_skills": self.cfg.get("claude_writes_skills", False),
            "skill_approval": self.cfg.get("skill_approval", True),
            "web_automation": self.cfg.get("web_automation", True),
            "claude_available": self._claude_available(),
        }

    def _claude_available(self):
        import shutil, os
        cli = self.cfg.get("claude_cli", "claude")
        if shutil.which(cli):
            return True
        return os.path.exists(os.path.expanduser(r"~/.local/bin/claude.exe"))

    def save_settings(self, patch):
        self.cfg.update(patch or {})
        settings.save(self.cfg)
        return {"ok": True}

    # ---- characters ----
    def list_characters(self):
        out = []
        for d in sorted(os.listdir(ASSETS)):
            p = os.path.join(ASSETS, d)
            if not os.path.isdir(p):
                continue
            out.append({"name": d, "preview": self._first_frame(p)})
        return out

    def _first_frame(self, folder):
        frames = sorted(glob.glob(os.path.join(folder, "idle_*.png")))
        if not frames:
            return ""
        with open(frames[0], "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()

    def set_character(self, name):
        self.cfg["character"] = name
        settings.save(self.cfg)
        return {"ok": True}

    def set_character_and_restart(self, name):
        self.set_character(name)
        killed = self._kill_character()
        self._spawn("--character")
        return {"ok": True, "restarted": killed}

    # ---- launching ----
    def start_buddy(self, voice=False):
        flags = ["--character"] + (["--voice"] if voice else [])
        self._spawn(*flags)
        return {"ok": True}

    def open_text_console(self):
        self._spawn("--text")
        return {"ok": True}

    def _spawn(self, *flags):
        from buddy import launcher
        launcher.spawn(*flags)

    def _kill_character(self):
        """Terminate any running on-screen buddy so a new one can take its place."""
        killed = 0
        try:
            import psutil
        except Exception:
            return killed
        me = os.getpid()
        for pr in psutil.process_iter(["pid", "cmdline"]):
            try:
                if pr.info["pid"] == me:
                    continue
                cl = " ".join(pr.info.get("cmdline") or [])
                if "--character" in cl and ("vb" in cl or "run.py" in cl
                                            or "VirtualBuddy" in cl):
                    pr.terminate()
                    killed += 1
            except Exception:
                continue
        return killed

    # ---- sync ----
    def get_sync(self):
        from buddy.server import lan_ip
        from buddy import peers as peer_book
        url = f"http://{lan_ip()}:{self.cfg.get('server_port', 8770)}"
        default = self.cfg.get("default_peer", "")
        peers = []
        for name, p in peer_book.normalize(self.cfg).items():
            peers.append({"name": name, "url": p["url"],
                          "aliases": p["aliases"], "default": name == default})
        return {"url": url, "token": self.cfg.get("server_token", "changeme"),
                "peers": peers}

    def start_server(self):
        self._spawn("--server")
        return {"ok": True}

    def add_peer(self, name, url, aliases=""):
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url:
            return {"ok": False, "error": "name and url required"}
        al = [a.strip() for a in (aliases or "").split(",") if a.strip()]
        peers = self.cfg.setdefault("peers", {})
        peers[name] = {"url": url, "aliases": al} if al else url
        if not self.cfg.get("default_peer"):
            self.cfg["default_peer"] = name
        settings.save(self.cfg)
        return {"ok": True}

    def set_default_peer(self, name):
        self.cfg["default_peer"] = name
        settings.save(self.cfg)
        return {"ok": True}

    # ---- advanced (dev tools, hidden by default) ----
    def list_skills(self):
        try:
            from buddy.skills import all_skills
            return [{"name": s["name"], "example": s["phrases"][0]} for s in all_skills()]
        except Exception as e:
            return [{"name": "(error)", "example": str(e)}]

    def train(self):
        def work():
            try:
                from buddy import trainer
                trainer.train_async()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def regenerate_sprites(self):
        def work():
            try:
                from tools import make_sprites, make_pixels
                make_sprites.main(); make_pixels.main()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def install_skill(self, src):
        """Add a shared skill from a local .py path or URL. Validates, installs, retrains."""
        src = (src or "").strip()
        if not src:
            return {"ok": False, "msg": "give a .py path or URL"}
        try:
            import shutil, urllib.request, importlib.util
            from buddy import settings as _s, skills as _skills
            path = src
            if src.startswith(("http://", "https://")):
                path = os.path.join(_s.data_dir(), os.path.basename(src.split("?")[0]) or "skill.py")
                urllib.request.urlretrieve(src, path)
            if not path.endswith(".py"):
                return {"ok": False, "msg": "skill must be a .py file"}
            spec = importlib.util.spec_from_file_location("_incoming", path)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            sk = getattr(mod, "SKILLS", None)
            if not isinstance(sk, list) or not sk or not all(
                    all(k in s for k in ("name", "phrases", "run")) and callable(s["run"]) for s in sk):
                return {"ok": False, "msg": "invalid skill file (needs SKILLS list with name/phrases/run)"}
            dest = os.path.join(os.path.dirname(_HERE), "skills", os.path.basename(path))
            shutil.copyfile(path, dest)
            _skills.reload()
            self.train()
            return {"ok": True, "msg": f"installed {', '.join(s['name'] for s in sk)} — retraining."}
        except Exception as e:
            return {"ok": False, "msg": f"failed: {e}"}

    def update_now(self):
        def work():
            try:
                import update
                update.pull_only()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}


def _html_path():
    """Where index.html actually is. Frozen builds unpack it under _MEIPASS."""
    for p in (HTML,
              os.path.join(getattr(sys, "_MEIPASS", ""), "buddy", "dashboard", "index.html"),
              os.path.join(_ROOT, "buddy", "dashboard", "index.html")):
        if p and os.path.exists(p):
            return p
    return None


def _fallback(reason):
    print(f"[dashboard] {reason} — using the basic panel.")
    import app
    return app.App().run()


def run():
    """Open the dashboard. Falls back to the tkinter panel if the webview can't run."""
    try:
        import webview
    except Exception as e:
        return _fallback(f"pywebview unavailable ({e})")
    page = _html_path()
    if not page:
        # a packaged build that forgot to ship index.html would otherwise show a blank window
        return _fallback("dashboard page missing from this build")
    api = Api()
    try:
        webview.create_window("VirtualBuddy", url=page, js_api=api,
                              width=980, height=760, min_size=(820, 620),
                              background_color="#1c1810")
        webview.start()
    except Exception as e:
        return _fallback(f"webview failed to start ({e})")
