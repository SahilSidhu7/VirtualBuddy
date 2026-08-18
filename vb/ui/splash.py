"""The window you see while the buddy wakes up.

VirtualBuddy needs a local model, and getting one ready can mean installing
Ollama, downloading several gigabytes and loading it into the graphics card.
That is minutes on a first run, so it happens behind a progress bar that says
which of those things is going on, rather than a frozen sprite.

Everything slow runs on a worker thread; Tk is only touched through `after`.
"""
from __future__ import annotations

import threading
import tkinter as tk

from vb import config, llm
from vb.ui import theme as themes
from vb.ui.sprite import asset_root
from vb.ui.widgets import Button, font, round_rect

W, H = 430, 280
CHOOSER_H = 430          # taller: the model list needs the room

FIT_WORD = {"good": "✓", "tight": "~", "slow": "!", "no": "✕"}


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

        # First run gets a choice. After that the answer is already stored and
        # asking again every launch would be a nuisance rather than a courtesy.
        if config.get("llm_model_pinned") or config.get("llm_model"):
            self._build()
            threading.Thread(target=self._work, daemon=True).start()
        else:
            self._build_chooser()

    def _centre(self, height: int = H):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - W) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{W}x{height}+{x}+{y}")

    # -- choosing a model -------------------------------------------------
    def _build_chooser(self):
        """Measure the machine, then let the user pick.

        The ladder's pick is pre-selected and marked, so doing nothing but
        pressing the button is the same as letting it decide. Everything else
        is offered with a plain word about what it will cost: a 14B on an 8GB
        card is allowed, it is just labelled as slow rather than hidden.
        """
        t = self.theme
        self._centre(CHOOSER_H)
        wrap = tk.Frame(self, bg=t.base)
        wrap.pack(fill="both", expand=True, padx=26, pady=22)

        tk.Label(wrap, text="Which model should I use?", bg=t.base, fg=t.text,
                 font=font(t, 14, "bold")).pack(anchor="w")

        kit = llm.hardware()
        tk.Label(wrap, text=kit["summary"], bg=t.base, fg=t.text_dim,
                 font=(t.mono, 8), wraplength=W - 60, justify="left"
                 ).pack(anchor="w", pady=(2, 12))

        self._picked = tk.StringVar(value=llm.recommended_model())
        for opt in llm.model_options():
            self._option_row(wrap, opt)

        note = tk.Label(wrap, text="", bg=t.base, fg=t.text_faint,
                        font=(t.mono, 8), wraplength=W - 60, justify="left")
        note.pack(anchor="w", pady=(10, 0))
        self._chooser_note = note
        self._describe_pick()

        Button(wrap, "Set it up", self._accept_choice, t,
               width=W - 52, height=30, size=10).pack(pady=(12, 0))

    def _option_row(self, parent, opt: dict):
        t = self.theme
        row = tk.Frame(parent, bg=t.base)
        row.pack(fill="x", pady=1)

        label = f"{opt['name']}"
        if opt["recommended"]:
            label += "  — recommended"
        if opt["installed"]:
            label += "  (already downloaded)"
        colour = {"good": t.text, "tight": t.text, "slow": t.text_dim,
                  "no": t.text_faint}[opt["fit"]]

        radio = tk.Radiobutton(
            row, text=f"{FIT_WORD[opt['fit']]}  {label}", value=opt["name"],
            variable=self._picked, command=self._describe_pick,
            bg=t.base, fg=colour, selectcolor=t.base, activebackground=t.base,
            activeforeground=t.text, font=font(t, 10), anchor="w",
            highlightthickness=0, bd=0, takefocus=False,
            state="disabled" if opt["fit"] == "no" and not opt["installed"] else "normal")
        radio.pack(fill="x")
        tk.Label(row, text=f"     {opt['size_gb']:.1f}GB · {opt['speed']}",
                 bg=t.base, fg=t.text_faint, font=(t.mono, 8), anchor="w"
                 ).pack(fill="x")

    def _describe_pick(self):
        chosen = self._picked.get()
        for opt in llm.model_options():
            if opt["name"] == chosen:
                first = ("Already downloaded — this will take a moment."
                         if opt["installed"] else
                         f"{opt['size_gb']:.1f}GB to download, once.")
                self._chooser_note.configure(text=f"{first}  {opt['blurb']}")
                return

    def _accept_choice(self):
        chosen = self._picked.get()
        config.set("llm_model", chosen)
        config.set("llm_model_pinned", True)
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
        """Get a model ready. Runs off the UI thread."""
        def report(percent, message="", detail=""):
            self.after(0, self.set_progress, percent, message, detail)

        model = config.get("llm_model") or llm.recommended_model()
        if not config.get("llm_model"):
            config.set("llm_model", model)

        if not llm.ollama_installed():
            report(None, "Installing Ollama, the bit that runs the model…",
                   "one time, a few minutes")
            if not llm.install_ollama():
                return self.after(0, self._failed,
                                  "Ollama could not be installed automatically.",
                                  "Install it from ollama.com, then restart me.")

        if not llm.running():
            report(None, "Starting Ollama…")
            if not llm.start_server():
                return self.after(0, self._failed, "Ollama would not start.",
                                  "Try running “ollama serve” in a terminal.")

        if not llm.installed(model):
            report(0, f"Downloading {model}. This happens once.",
                   "several gigabytes")
            ok = llm.pull(model, on_progress=lambda p, s: report(
                p, f"Downloading {model}. This happens once.", s))
            if not ok:
                return self.after(0, self._failed,
                                  f"{model} could not be downloaded.",
                                  llm.last_error() or "Check your connection.")

        report(None, "Warming the model up…", f"{model} into the graphics card")
        if not llm.warm_up():
            return self.after(0, self._failed, "The model would not answer.",
                              llm.last_error() or "")

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
