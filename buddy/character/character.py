"""The on-screen buddy. Loads sprite frames and animates them in place.

Drag it anywhere, left-click to type a command, right-click for the menu.
Commands run on a background thread so the UI never freezes.

Buddy shows what it's doing via animation STATES (dedicated sprite frames):
  idle       - waiting
  listening  - voice is active, waiting for your command
  thinking   - planner / LLM is working out what to do
  working    - a task (primitive/skill) is running
  talk       - speaking a reply  (transient, times out)
The agent drives these through set_state(); missing states fall back to idle.

If sprites/Pillow are missing it falls back to a simple drawn blob.
Regenerate sprites: python -m tools.make_sprites && python -m tools.make_pixels
"""
import os, glob, threading, tkinter as tk

KEY = "#ff00ff"   # chroma-key color -> made transparent by the window
_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "character")

# every state we know how to load, in priority order for the animation loop
_STATES = ("talk", "working", "thinking", "listening", "idle")


class Buddy:
    def __init__(self, on_command, character="duck", roam=False, roam_speed=40):
        self.on_command = on_command
        self.assets = os.path.join(_BASE, character)
        self._roam_on = bool(roam)
        self._roam_speed = roam_speed
        self._roamer = None
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY)  # Windows only
        except tk.TclError:
            pass

        self.frames = {}
        self.size = self._load_frames()
        self.active = "idle"        # sticky state driven by the agent / voice
        self.fi = 0
        self._talk_left = 0         # transient "speaking" timer (ms)
        self.dragging = False

        self.root.geometry(f"{self.size}x{self.size}+300+300")
        self.c = tk.Canvas(self.root, width=self.size, height=self.size,
                           bg=KEY, highlightthickness=0)
        self.c.pack()
        self.img_id = self.c.create_image(self.size // 2, self.size // 2, anchor="center")

        self._bind()
        self._animate()

    # ---- commands run off the UI thread so nothing freezes ----
    def _dispatch(self, cmd):
        self.set_state("thinking")
        def work():
            try:
                self.on_command(cmd)
            finally:
                self.root.after(0, self._reply_done)
        threading.Thread(target=work, daemon=True).start()

    def _reply_done(self):
        self.talk()
        self.set_state("idle")

    # ---- state control (thread-safe) ----
    def set_state(self, name):
        """Set buddy's sticky animation state. Safe to call from any thread."""
        if name not in _STATES:
            name = "idle"
        self.root.after(0, lambda: setattr(self, "active", name))

    # ---- sprites ----
    def _load_frames(self):
        try:
            from PIL import Image, ImageTk
            self._ImageTk = ImageTk
        except ImportError:
            self.frames = None
            return 96
        size = 96
        for state in _STATES:
            imgs = []
            for fp in sorted(glob.glob(os.path.join(self.assets, f"{state}_*.png"))):
                im = Image.open(fp).convert("RGBA").resize((size, size), Image.LANCZOS)
                bg = Image.new("RGB", im.size, KEY)
                bg.paste(im, mask=im.split()[3])
                imgs.append(self._ImageTk.PhotoImage(bg))
            if imgs:
                self.frames[state] = imgs
        if not self.frames:
            self.frames = None
        return size

    # ---- events ----
    def _bind(self):
        self.c.bind("<Button-1>", self._down)
        self.c.bind("<B1-Motion>", self._drag)
        self.c.bind("<ButtonRelease-1>", self._up)
        self.c.bind("<Double-Button-1>", lambda e: self._prompt())
        self.c.bind("<Button-3>", self._menu)
        self._build_menu()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Ask buddy...", command=self._prompt)
        m.add_separator()
        for label, cmd in (("What time is it", "what time is it"),
                           ("System status", "system status"),
                           ("What am I serving", "what is my pc serving"),
                           ("Take a screenshot", "take a screenshot")):
            m.add_command(label=label, command=lambda c=cmd: self._dispatch(c))
        m.add_separator()
        m.add_command(label="Open dashboard", command=self._open_dashboard)
        m.add_command(label="Quit buddy", command=self.root.destroy)
        self._m = m

    def _menu(self, e):
        try:
            self._m.tk_popup(e.x_root, e.y_root)
        finally:
            self._m.grab_release()

    def _open_dashboard(self):
        from buddy import launcher
        launcher.spawn("--dashboard")

    def _down(self, e):
        self.dragging = True
        self._ox, self._oy = e.x, e.y
        self._moved = False

    def _drag(self, e):
        self._moved = True
        x = self.root.winfo_x() + e.x - self._ox
        y = self.root.winfo_y() + e.y - self._oy
        self.root.geometry(f"+{x}+{y}")

    def _up(self, e):
        self.dragging = False
        if self._roamer is not None:
            self._roamer.resync_from_window()   # fall from wherever it was dropped
        if not self._moved:
            self._prompt()

    def _prompt(self):
        win = tk.Toplevel(self.root)
        win.attributes("-topmost", True)
        win.title("Tell buddy")
        e = tk.Entry(win, width=44); e.pack(padx=8, pady=8); e.focus_force()
        out = tk.Label(win, text="", wraplength=320, justify="left", fg="#334")
        out.pack(padx=8, pady=(0, 8))
        def go(_=None):
            cmd = e.get().strip()
            if not cmd:
                return
            out.config(text="...")
            self.set_state("thinking")
            done = {"ok": False}
            def work():
                try:
                    reply = self.on_command(cmd)
                except Exception as ex:
                    reply = f"(error: {ex})"
                done["ok"] = True
                win.after(0, lambda: out.config(text=reply or ""))
                self.root.after(0, self._reply_done)
            threading.Thread(target=work, daemon=True).start()
            # watchdog: never let the bubble sit on "..." forever if a skill stalls
            def watchdog():
                if not done["ok"]:
                    out.config(text="still working on it — taking longer than usual...")
            win.after(30000, watchdog)
        e.bind("<Return>", go)

    def talk(self, ms=1500):
        self._talk_left = ms

    # ---- animation (in place - no window moves, so no flicker) ----
    def _current(self):
        """Highest-priority state that actually has frames loaded."""
        if self._talk_left > 0 and self.frames and "talk" in self.frames:
            return "talk"
        if self.frames and self.active in self.frames:
            return self.active
        return "idle"

    def _animate(self):
        if self.frames:
            state = self._current()
            seq = self.frames.get(state) or self.frames.get("idle")
            self.fi = (self.fi + 1) % len(seq)
            self.c.itemconfig(self.img_id, image=seq[self.fi])
        else:
            self._blob()
        self._talk_left = max(0, self._talk_left - 180)
        self._roam_tick()
        self.root.after(180, self._animate)

    # ---- roaming: walk the taskbar (opt-in; window only moves in roam mode) ----
    def _roam_tick(self):
        if not self._roam_on or self.dragging:
            return
        if self._roamer is None:
            try:
                from buddy.character.roam import RoamController
                self.root.update_idletasks()
                self._roamer = RoamController(self.root, self.size, self._roam_speed)
            except Exception:
                self._roam_on = False
                return
        x, y = self._roamer.step(0.18)          # matches the 180ms tick
        self.root.geometry(f"+{x}+{y}")

    def _blob(self):
        self.c.delete("blob")
        s = self.size
        self.c.create_oval(15, 20, s-15, s-10, fill="#4aa3ff", outline="", tags="blob")
        for dx in (-12, 12):
            self.c.create_oval(s/2+dx-6, 40, s/2+dx+6, 52, fill="white", outline="", tags="blob")

    def run(self):
        self.root.mainloop()
