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
ASSETS = os.path.join(ROOT, "assets", "character")
PY = sys.executable

from buddy import settings
load_cfg = settings.load
save_cfg = settings.save

class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.root = tk.Tk()
        self.root.title("VirtualBuddy Control Panel")
        self.root.geometry("560x520")
        self._procs = []
        self._theme()
        nb = ttk.Notebook(self.root); nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_settings(nb)
        self._tab_character(nb)
        self._tab_sync(nb)
        self._tab_skills(nb)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(600, self._maybe_first_run)

    # ---- duck theme (warm yellow / orange) ----
    BG = "#1c1810"; CARD = "#241e10"; FG = "#fff7e6"; MUT = "#c8b487"
    ACC = "#ffc233"; ACC_HOVER = "#ffd166"; ACC_TEXT = "#2a1e00"; EDGE = "#3a3016"

    def _theme(self):
        self.root.configure(bg=self.BG)
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=self.BG, foreground=self.FG,
                    fieldbackground=self.CARD, bordercolor=self.EDGE)
        s.configure("TFrame", background=self.BG)
        s.configure("TLabel", background=self.BG, foreground=self.FG)
        s.configure("TCheckbutton", background=self.BG, foreground=self.FG)
        s.map("TCheckbutton", background=[("active", self.BG)])
        s.configure("TSeparator", background=self.EDGE)
        s.configure("TNotebook", background=self.BG, bordercolor=self.EDGE)
        s.configure("TNotebook.Tab", background=self.CARD, foreground=self.MUT, padding=(12, 6))
        s.map("TNotebook.Tab", background=[("selected", self.ACC)],
              foreground=[("selected", self.ACC_TEXT)])
        s.configure("TButton", background=self.ACC, foreground=self.ACC_TEXT,
                    borderwidth=0, focuscolor=self.ACC)
        s.map("TButton", background=[("active", self.ACC_HOVER), ("pressed", self.ACC_HOVER)])
        s.configure("TEntry", fieldbackground=self.CARD, foreground=self.FG, insertcolor=self.FG)
        s.configure("TCombobox", fieldbackground=self.CARD, background=self.CARD, foreground=self.FG)
        s.map("TCombobox", fieldbackground=[("readonly", self.CARD)])
        s.configure("Horizontal.TScale", background=self.BG, troughcolor=self.CARD)

    def _maybe_first_run(self):
        if settings.is_first_run():                  # train automatically (offline, seconds)
            self.train_lbl.config(text="first run: training brain...")
            from buddy import trainer
            trainer.train_async(on_done=lambda: self.train_lbl.config(text="brain trained."))

    # ---- Settings tab ----
    def _tab_settings(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Settings")
        self.v_wake = tk.StringVar(value=self.cfg.get("wake_word", "buddy"))
        self.v_thr = tk.DoubleVar(value=self.cfg.get("match_threshold", 0.40))
        self.v_speak = tk.BooleanVar(value=self.cfg.get("speak_replies", True))
        self.v_power = tk.BooleanVar(value=self.cfg.get("power_save", False))
        self.v_autoupd = tk.BooleanVar(value=self.cfg.get("auto_update", False))
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
        ttk.Label(f, text="Updates").grid(row=7, column=0, sticky="w")
        ttk.Checkbutton(f, text="Auto-update on launch (git checkout only)",
                        variable=self.v_autoupd, command=self._save_autoupd).grid(
            row=8, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Button(f, text="Update now", command=self._update_now).grid(row=9, column=0, pady=4)
        self.upd_lbl = ttk.Label(f, text="")
        self.upd_lbl.grid(row=9, column=1, columnspan=2, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(row=10, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="Launch buddy").grid(row=11, column=0, sticky="w")
        ttk.Button(f, text="Text mode", command=lambda: self._launch([])).grid(row=12, column=0, pady=4)
        ttk.Button(f, text="Voice mode", command=lambda: self._launch(["--voice"])).grid(row=12, column=1, pady=4)
        ttk.Button(f, text="Character", command=lambda: self._launch(["--character"])).grid(row=12, column=2, pady=4)

    def _save_autoupd(self):
        self.cfg["auto_update"] = self.v_autoupd.get()
        save_cfg(self.cfg)

    def _update_now(self):
        self.upd_lbl.config(text="updating (pull + retrain)...")
        def work():
            try:
                import update
                changed, msg = update.pull_only()
                if changed:
                    subprocess.run([PY, "-m", "tools.loop", "0.95", "4"], cwd=ROOT)
                    msg = "updated + retrained brain."
            except Exception as e:
                msg = f"update failed: {e}"
            self.root.after(0, lambda: self.upd_lbl.config(text=msg))
        threading.Thread(target=work, daemon=True).start()

    # ---- Character tab ----
    def _tab_character(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Character")
        row = ttk.Frame(f); row.pack(pady=8)
        ttk.Label(row, text="Character:").grid(row=0, column=0, padx=4)
        chars = [d for d in os.listdir(ASSETS) if os.path.isdir(os.path.join(ASSETS, d))]
        self.v_char = tk.StringVar(value=self.cfg.get("character", "duck"))
        self.char_pick = ttk.Combobox(row, textvariable=self.v_char, values=sorted(chars),
                                      width=14, state="readonly")
        self.char_pick.grid(row=0, column=1, padx=4)
        self.char_pick.bind("<<ComboboxSelected>>", lambda e: (self._load_preview(), self._save_char()))
        self.v_roam = tk.BooleanVar(value=self.cfg.get("roam", False))
        ttk.Checkbutton(f, text="Roam — walk along the taskbar (off = sit in place)",
                        variable=self.v_roam, command=self._save_roam).pack(pady=6)
        self.preview = tk.Label(f, bg=self.BG, fg=self.MUT); self.preview.pack(pady=12)
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

    def _save_roam(self):
        self.cfg["roam"] = self.v_roam.get()
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
            try:
                from tools import make_sprites, make_pixels
                make_sprites.main(); make_pixels.main()
                msg = "Regenerated built-in sprites (duck, robot, crab, elf)."
            except Exception as e:
                msg = f"Failed: {e}"
            self.root.after(0, lambda: (self._load_preview(), messagebox.showinfo("Sprites", msg)))
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
        ttk.Label(f, text="Peer PCs (control other machines). ★ = default target").pack()
        self.peer_box = tk.Listbox(f, height=4, width=54, bg=self.CARD, fg=self.FG,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=self.EDGE,
                                   selectbackground=self.ACC, selectforeground=self.ACC_TEXT)
        self.peer_box.pack(pady=4)
        self._refresh_peers()
        row = ttk.Frame(f); row.pack()
        self.p_name = ttk.Entry(row, width=10); self.p_name.grid(row=0, column=0, padx=2)
        self.p_url = ttk.Entry(row, width=24); self.p_url.grid(row=0, column=1, padx=2)
        ttk.Button(row, text="Add", command=self._add_peer).grid(row=0, column=2, padx=2)
        self.p_name.insert(0, "laptop"); self.p_url.insert(0, "http://192.168.1.x:8770")
        row2 = ttk.Frame(f); row2.pack(pady=2)
        ttk.Label(row2, text="Nicknames (comma-sep):").grid(row=0, column=0, padx=2)
        self.p_alias = ttk.Entry(row2, width=28); self.p_alias.grid(row=0, column=1, padx=2)
        ttk.Button(f, text="Set selected as default",
                   command=self._set_default_peer).pack(pady=4)

    def _peer_names(self):
        return list((self.cfg.get("peers") or {}).keys())

    def _refresh_peers(self):
        self.peer_box.delete(0, "end")
        from buddy import peers as peer_book
        default = self.cfg.get("default_peer", "")
        for name, p in peer_book.normalize(self.cfg).items():
            mark = "★ " if name == default else "  "
            nick = f"   [{', '.join(p['aliases'])}]" if p["aliases"] else ""
            self.peer_box.insert("end", f"{mark}{name}  ->  {p['url']}{nick}")

    def _add_peer(self):
        name, url = self.p_name.get().strip(), self.p_url.get().strip()
        if not name or not url:
            return
        aliases = [a.strip() for a in self.p_alias.get().split(",") if a.strip()]
        entry = {"url": url, "aliases": aliases} if aliases else url
        peers = self.cfg.setdefault("peers", {})
        peers[name] = entry
        if not self.cfg.get("default_peer"):     # first peer becomes the default
            self.cfg["default_peer"] = name
        save_cfg(self.cfg)
        self._refresh_peers()

    def _set_default_peer(self):
        sel = self.peer_box.curselection()
        if not sel:
            return
        name = self._peer_names()[sel[0]]
        self.cfg["default_peer"] = name
        save_cfg(self.cfg)
        self._refresh_peers()

    # ---- Skills tab ----
    def _tab_skills(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Skills & Training")
        box = tk.Text(f, height=12, width=64, bg=self.CARD, fg=self.FG,
                      insertbackground=self.FG, relief="flat", highlightthickness=1,
                      highlightbackground=self.EDGE); box.pack(padx=6, pady=6)
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
        self.train_lbl.config(text="training locally (offline, seconds)...")
        from buddy import trainer
        trainer.train_async(on_done=lambda: self.root.after(
            0, lambda: self.train_lbl.config(text="brain trained.")))

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
        from buddy import launcher
        launcher.spawn(*args)

    def _close(self):
        for p in self._procs:
            try: p.terminate()
            except Exception: pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    App().run()
