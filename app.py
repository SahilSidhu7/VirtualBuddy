"""VirtualBuddy control panel. One window to:
  - edit settings (wake word, sensitivity, voice on/off)
  - preview / regenerate the character
  - launch buddy (text / voice / character)
  - run the local training loop
  - see the skills buddy knows

Run: python app.py
"""
import os, sys, glob, subprocess, threading, tkinter as tk
from tkinter import ttk, messagebox
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(ROOT, "config.yaml")
ASSETS = os.path.join(ROOT, "assets", "character")
PY = sys.executable

def load_cfg():
    with open(CFG) as f:
        return yaml.safe_load(f) or {}

def save_cfg(cfg):
    with open(CFG, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.root = tk.Tk()
        self.root.title("VirtualBuddy Control Panel")
        self.root.geometry("560x520")
        self._procs = []
        nb = ttk.Notebook(self.root); nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_settings(nb)
        self._tab_character(nb)
        self._tab_sync(nb)
        self._tab_skills(nb)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    # ---- Settings tab ----
    def _tab_settings(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Settings")
        self.v_wake = tk.StringVar(value=self.cfg.get("wake_word", "buddy"))
        self.v_thr = tk.DoubleVar(value=self.cfg.get("match_threshold", 0.40))
        self.v_speak = tk.BooleanVar(value=self.cfg.get("speak_replies", True))
        self.v_power = tk.BooleanVar(value=self.cfg.get("power_save", False))
        self.v_cli = tk.StringVar(value=self.cfg.get("claude_cli", "claude"))

        ttk.Label(f, text="Wake word").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.v_wake, width=24).grid(row=0, column=1, sticky="w")

        ttk.Label(f, text="Match sensitivity").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Scale(f, from_=0.2, to=0.8, variable=self.v_thr, length=200).grid(row=1, column=1, sticky="w")
        self.lbl_thr = ttk.Label(f, text=""); self.lbl_thr.grid(row=1, column=2)
        self.v_thr.trace_add("write", lambda *_: self.lbl_thr.config(text=f"{self.v_thr.get():.2f}"))
        self.lbl_thr.config(text=f"{self.v_thr.get():.2f}")

        ttk.Checkbutton(f, text="Buddy talks back", variable=self.v_speak).grid(
            row=2, column=1, sticky="w", pady=6)
        ttk.Checkbutton(f, text="Power-saving (no LLM, frees RAM)", variable=self.v_power).grid(
            row=3, column=1, sticky="w", pady=6)

        ttk.Label(f, text="Claude command").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.v_cli, width=24).grid(row=4, column=1, sticky="w")

        ttk.Button(f, text="Save settings", command=self._save).grid(row=5, column=1, sticky="w", pady=12)

        ttk.Separator(f, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="Launch buddy").grid(row=7, column=0, sticky="w")
        ttk.Button(f, text="Text mode", command=lambda: self._launch([])).grid(row=8, column=0, pady=4)
        ttk.Button(f, text="Voice mode", command=lambda: self._launch(["--voice"])).grid(row=8, column=1, pady=4)
        ttk.Button(f, text="Character", command=lambda: self._launch(["--character"])).grid(row=8, column=2, pady=4)

    # ---- Character tab ----
    def _tab_character(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Character")
        row = ttk.Frame(f); row.pack(pady=8)
        ttk.Label(row, text="Character:").grid(row=0, column=0, padx=4)
        chars = [d for d in os.listdir(ASSETS) if os.path.isdir(os.path.join(ASSETS, d))]
        self.v_char = tk.StringVar(value=self.cfg.get("character", "robot"))
        self.char_pick = ttk.Combobox(row, textvariable=self.v_char, values=sorted(chars),
                                      width=14, state="readonly")
        self.char_pick.grid(row=0, column=1, padx=4)
        self.char_pick.bind("<<ComboboxSelected>>", lambda e: (self._load_preview(), self._save_char()))
        self.preview = tk.Label(f); self.preview.pack(pady=12)
        self._pv_frames = []; self._pv_i = 0
        self._load_preview()
        ttk.Button(f, text="Regenerate default sprites",
                   command=self._regen_sprites).pack(pady=4)
        ttk.Label(f, text="Add your own: make a folder in assets/character/<name>/\n"
                          "with idle_0.png, idle_1.png, talk_0.png", justify="center").pack(pady=8)
        self._anim_preview()

    def _save_char(self):
        self.cfg["character"] = self.v_char.get()
        save_cfg(self.cfg)

    def _load_preview(self):
        self._pv_frames = []
        try:
            from PIL import Image, ImageTk
            d = os.path.join(ASSETS, self.v_char.get())
            for fp in sorted(glob.glob(os.path.join(d, "idle_*.png"))):
                im = Image.open(fp).convert("RGBA").resize((120, 120), Image.NEAREST)
                self._pv_frames.append(ImageTk.PhotoImage(im))
        except Exception:
            pass

    def _anim_preview(self):
        if self._pv_frames:
            self._pv_i = (self._pv_i + 1) % len(self._pv_frames)
            self.preview.config(image=self._pv_frames[self._pv_i])
        else:
            self.preview.config(text="(no sprites yet - click regenerate)")
        self.root.after(140, self._anim_preview)

    def _regen_sprites(self):
        def work():
            for mod in ("tools.make_sprites", "tools.make_pixels"):
                subprocess.run([PY, "-m", mod], cwd=ROOT, capture_output=True, text=True)
            self.root.after(0, lambda: (self._load_preview(),
                messagebox.showinfo("Sprites", "Regenerated robot + pixel characters.")))
        threading.Thread(target=work, daemon=True).start()

    # ---- Sync tab (phone + other PCs) ----
    def _tab_sync(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Sync")
        from buddy.server import lan_ip
        url = f"http://{lan_ip()}:{self.cfg.get('server_port', 8770)}"
        ttk.Label(f, text="Command buddy from your phone / other PCs on the same WiFi",
                  wraplength=500).pack(pady=6)
        ttk.Label(f, text=f"Phone URL:  {url}", font=("", 11, "bold")).pack(pady=2)
        ttk.Label(f, text=f"Token:  {self.cfg.get('server_token','changeme')}").pack(pady=2)
        ttk.Button(f, text="Start server", command=lambda: self._launch(["--server"])).pack(pady=8)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(f, text="Peer PCs (control other machines)").pack()
        peers = self.cfg.get("peers") or {}
        self.peer_box = tk.Listbox(f, height=4, width=54)
        for k, v in peers.items():
            self.peer_box.insert("end", f"{k}  ->  {v}")
        self.peer_box.pack(pady=4)
        row = ttk.Frame(f); row.pack()
        self.p_name = ttk.Entry(row, width=12); self.p_name.grid(row=0, column=0, padx=2)
        self.p_url = ttk.Entry(row, width=30); self.p_url.grid(row=0, column=1, padx=2)
        self.p_name.insert(0, "pc2"); self.p_url.insert(0, "http://192.168.1.x:8770")
        ttk.Button(row, text="Add peer", command=self._add_peer).grid(row=0, column=2, padx=2)

    def _add_peer(self):
        name, url = self.p_name.get().strip(), self.p_url.get().strip()
        if not name or not url:
            return
        self.cfg.setdefault("peers", {})[name] = url
        save_cfg(self.cfg)
        self.peer_box.insert("end", f"{name}  ->  {url}")

    # ---- Skills tab ----
    def _tab_skills(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Skills & Training")
        box = tk.Text(f, height=12, width=64); box.pack(padx=6, pady=6)
        try:
            sys.path.insert(0, ROOT)
            from buddy.skills import all_skills
            for s in all_skills():
                box.insert("end", f"- {s['name']}: {s['phrases'][0]} ...\n")
        except Exception as e:
            box.insert("end", f"(could not list skills: {e})")
        box.config(state="disabled")
        self.train_lbl = ttk.Label(f, text="Train the local brain (no internet, no tokens)")
        self.train_lbl.pack(pady=4)
        ttk.Button(f, text="Run 2-bot training loop", command=self._train).pack(pady=4)

    def _train(self):
        self.train_lbl.config(text="training... (first run downloads model)")
        def work():
            r = subprocess.run([PY, "-m", "tools.loop", "0.95", "5"], cwd=ROOT,
                               capture_output=True, text=True)
            tail = (r.stdout or r.stderr).strip().splitlines()[-3:]
            self.root.after(0, lambda: self.train_lbl.config(text=" | ".join(tail)))
        threading.Thread(target=work, daemon=True).start()

    # ---- actions ----
    def _save(self):
        self.cfg.update({
            "wake_word": self.v_wake.get().strip() or "buddy",
            "match_threshold": round(self.v_thr.get(), 2),
            "speak_replies": self.v_speak.get(),
            "power_save": self.v_power.get(),
            "claude_cli": self.v_cli.get().strip() or "claude",
        })
        save_cfg(self.cfg)
        messagebox.showinfo("Saved", "Settings saved to config.yaml")

    def _launch(self, args):
        p = subprocess.Popen([PY, "run.py", *args], cwd=ROOT)
        self._procs.append(p)

    def _close(self):
        for p in self._procs:
            try: p.terminate()
            except Exception: pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    App().run()
