"""The window you see while the buddy wakes up.

The model lives on NVIDIA's free API, so waking up is one call to check the key
works. When there is no key yet, this is where the user pastes one — it is
saved to `.env` in the data folder, never into the install directory.

Everything slow runs on a worker thread; Tk is only touched through `after`.
"""
from __future__ import annotations

import threading
import tkinter as tk

from vb import config, llm, provider
from vb.ui import theme as themes
from vb.ui.sprite import asset_root
from vb.ui.widgets import Button, font, round_rect

W, H = 430, 280
CHOOSER_H = 300


class Splash(tk.Toplevel):
    def __init__(self, master: tk.Tk, on_done, on_skip=None):
        super().__init__(master)
        self.on_done, self.on_skip = on_done, on_skip
        self.theme = themes.get(config.get("avatar"))
        self.cancelled = False
        self._frames = []
        self._frame_index = 0
        self._anim_job = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.theme.base, highlightthickness=1,
                       highlightbackground=self.theme.line)
        self._centre()

        # No key yet: ask for one. After that it is stored and asking again
        # every launch would be a nuisance rather than a courtesy.
        if provider.api_key():
            self._build()
            threading.Thread(target=self._work, daemon=True).start()
        else:
            self._build_chooser()

    def _centre(self, height: int = H):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - W) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{W}x{height}+{x}+{y}")

    # -- asking for a key -------------------------------------------------
    def _build_chooser(self):
        t = self.theme
        self._centre(CHOOSER_H)
        wrap = tk.Frame(self, bg=t.base)
        wrap.pack(fill="both", expand=True, padx=26, pady=22)

        tk.Label(wrap, text="Paste your NVIDIA API key", bg=t.base, fg=t.text,
                 font=font(t, 14, "bold")).pack(anchor="w")
        tk.Label(wrap, text="Free at build.nvidia.com → Get API Key. It starts "
                            "with nvapi- and is saved only on this PC.",
                 bg=t.base, fg=t.text_dim, font=(t.mono, 8), wraplength=W - 60,
                 justify="left").pack(anchor="w", pady=(2, 12))

        self._key = tk.Entry(wrap, bg=t.base, fg=t.text, insertbackground=t.text,
                             relief="flat", highlightthickness=1,
                             highlightbackground=t.line, font=(t.mono, 9),
                             show="•")
        self._key.pack(fill="x", ipady=6)
        self._key.focus_set()
        self._key.bind("<Return>", lambda _e: self._accept_choice())

        self._chooser_note = tk.Label(wrap, text="", bg=t.base, fg=t.bad,
                                      font=(t.mono, 8), wraplength=W - 60,
                                      justify="left")
        self._chooser_note.pack(anchor="w", pady=(8, 0))

        Button(wrap, "Save and start", self._accept_choice, t,
               width=W - 52, height=30, size=10).pack(pady=(12, 0))
        Button(wrap, "Continue without it", self._skip, t,
               width=150, height=26, size=9).pack(pady=(8, 0))

    def _accept_choice(self):
        key = self._key.get().strip()
        if not key.startswith("nvapi-"):
            self._chooser_note.configure(text="That does not look like an "
                                              "NVIDIA key (nvapi-…).")
            return
        config.HOME.mkdir(parents=True, exist_ok=True)
        env = config.HOME / ".env"
        lines = [line for line in (env.read_text("utf-8").splitlines()
                                   if env.exists() else [])
                 if not line.startswith("NVIDIA_API_KEY=")]
        env.write_text("\n".join(lines + [f"NVIDIA_API_KEY={key}"]) + "\n",
                       "utf-8")
        for child in self.winfo_children():
            child.destroy()
        self._centre(H)
        self._build()
        threading.Thread(target=self._work, daemon=True).start()

    def _build(self):
        t = self.theme
        wrap = tk.Frame(self, bg=t.base)
        wrap.pack(fill="both", expand=True, padx=26, pady=24)

        self.sprite = tk.Label(wrap, bg=t.base, bd=0)
        self.sprite.pack()
        self._load_frames()

        self.title_lbl = tk.Label(wrap, text="VirtualBuddy", bg=t.base, fg=t.text,
                                  font=font(t, 15, "bold"))
        self.title_lbl.pack(pady=(10, 2))

        self.status = tk.Label(wrap, text="Waking up…", bg=t.base, fg=t.text_dim,
                               font=font(t, 10), wraplength=W - 70, justify="center")
        self.status.pack(pady=(0, 12))

        self.bar = tk.Canvas(wrap, width=W - 52, height=6, bg=t.base,
                             highlightthickness=0, bd=0)
        self.bar.pack()
        self._percent: float | None = 0.0
        self._sweep = 0.0
        self._draw_bar()

        self.detail = tk.Label(wrap, text="", bg=t.base, fg=t.text_faint,
                               font=(t.mono, 8))
        self.detail.pack(pady=(8, 0))

        self.skip_btn = Button(wrap, "Continue without it", self._skip, t,
                               width=150, height=26, size=9)

    def _load_frames(self):
        try:
            from PIL import Image, ImageTk
            folder = asset_root() / config.get("avatar")
            # This is an ordinary window, so the sprite is composited onto the
            # background colour. The magenta colour key only works on the pet
            # window, which asks Windows to treat that colour as see-through.
            behind = tuple(int(self.theme.base[i:i + 2], 16) for i in (1, 3, 5))
            for path in sorted(folder.glob("thinking_*.png")) or \
                    sorted(folder.glob("idle_*.png")):
                img = Image.open(path).convert("RGBA").resize((84, 84), Image.NEAREST)
                flat = Image.new("RGB", img.size, behind)
                flat.paste(img, mask=img.split()[3])
                self._frames.append(ImageTk.PhotoImage(flat))
        except Exception:
            self._frames = []
        if self._frames:
            self.sprite.configure(image=self._frames[0], bg=self.theme.base)
            self._animate()

    def _animate(self):
        if not self._frames:
            return
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self.sprite.configure(image=self._frames[self._frame_index])
        self._anim_job = self.after(320, self._animate)

    # -- the bar ---------------------------------------------------------
    def _draw_bar(self):
        t = self.theme
        width = int(self.bar["width"])
        self.bar.delete("all")
        round_rect(self.bar, 0, 1, width, 5, r=3, fill=t.line, outline=t.line)
        if self._percent is None:
            # Unknown length: a shuttle, so it still reads as "working".
            span = width * 0.28
            x = (width + span) * self._sweep - span
            round_rect(self.bar, max(0, x), 1, min(width, x + span), 5,
                       r=3, fill=t.accent, outline=t.accent)
            self._sweep = (self._sweep + 0.02) % 1.0
            self.after(40, self._draw_bar)
        elif self._percent > 0:
            round_rect(self.bar, 0, 1, max(4, width * self._percent / 100), 5,
                       r=3, fill=t.accent, outline=t.accent)

    def set_progress(self, percent: float | None, message: str = "",
                     detail: str = ""):
        was_indeterminate = self._percent is None
        self._percent = percent
        if message:
            self.status.configure(text=message)
        self.detail.configure(text=detail[:58])
        if percent is None and not was_indeterminate:
            self._draw_bar()          # start the shuttle
        elif percent is not None:
            self._draw_bar()

    # -- the work --------------------------------------------------------
    def _work(self):
        """Check the API answers. Runs off the UI thread."""
        def report(percent, message="", detail=""):
            self.after(0, self.set_progress, percent, message, detail)

        model = llm.recommended_model()
        report(None, "Checking the connection…", model)
        if not llm.warm_up():
            return self.after(0, self._failed, "The NVIDIA API would not answer.",
                              llm.last_error() or "Check your key and connection.")

        report(100, "Ready.", model)
        self.after(450, self._finish)

    def _finish(self):
        if self.cancelled:
            return
        self.cancelled = True
        if self._anim_job:
            self.after_cancel(self._anim_job)
        self.destroy()
        self.on_done()

    def _failed(self, message: str, detail: str):
        self._percent = 0
        self.status.configure(text=message, fg=self.theme.bad)
        self.detail.configure(text=detail[:70])
        self._draw_bar()
        self.skip_btn.pack(pady=(14, 0))

    def _skip(self):
        if self.cancelled:
            return
        self.cancelled = True
        if self._anim_job:
            self.after_cancel(self._anim_job)
        self.destroy()
        (self.on_skip or self.on_done)()
