"""The on-screen buddy. Loads real sprite frames from assets/character/ and
animates them. Drag it anywhere, click to type a command.

If sprites or Pillow are missing, falls back to a simple drawn blob so it
always runs. Regenerate/edit sprites with:  python -m tools.make_sprites
"""
import os, glob, tkinter as tk

KEY = "#ff00ff"   # chroma-key color -> made transparent by the window
_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "character")

class Buddy:
    def __init__(self, on_command, character="robot"):
        self.on_command = on_command
        self.assets = os.path.join(_BASE, character)
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY)  # Windows only
        except tk.TclError:
            pass  # mac/linux: shows on a solid square instead

        self.frames = {}         # state -> [PhotoImage]
        self.size = self._load_frames()
        self.state = "idle"
        self.fi = 0

        self.root.geometry(f"{self.size}x{self.size}+300+300")
        self.c = tk.Canvas(self.root, width=self.size, height=self.size,
                           bg=KEY, highlightthickness=0)
        self.c.pack()
        self.img_id = self.c.create_image(self.size // 2, self.size // 2, anchor="center")

        self.vx, self.vy = 2, 1
        self.dragging = False
        self._talk_left = 0
        self._bind()
        self._animate()
        self._wander()

    # ---- sprites ----
    def _load_frames(self):
        try:
            from PIL import Image, ImageTk
            self._ImageTk = ImageTk
        except ImportError:
            self.frames = None
            return 90
        size = 96
        for state in ("idle", "talk"):
            files = sorted(glob.glob(os.path.join(self.assets, f"{state}_*.png")))
            imgs = []
            for fp in files:
                im = Image.open(fp).convert("RGBA").resize((size, size), Image.LANCZOS)
                bg = Image.new("RGB", im.size, KEY)     # flatten onto key color
                bg.paste(im, mask=im.split()[3])
                imgs.append(self._ImageTk.PhotoImage(bg))
            if imgs:
                self.frames[state] = imgs
        if not self.frames:
            self.frames = None                          # nothing loaded -> blob mode
        return size

    # ---- events ----
    def _bind(self):
        self.c.bind("<Button-1>", self._down)
        self.c.bind("<B1-Motion>", self._drag)
        self.c.bind("<ButtonRelease-1>", self._up)
        self.c.bind("<Double-Button-1>", lambda e: self._prompt())
        self.c.bind("<Button-3>", self._menu)        # right-click = quick options
        self._build_menu()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Ask buddy...", command=self._prompt)
        m.add_separator()
        for label, cmd in (("What time is it", "what time is it"),
                           ("Take a screenshot", "take a screenshot"),
                           ("System status", "system status"),
                           ("Lock PC", "lock my pc")):
            m.add_command(label=label, command=lambda c=cmd: (self.talk(), self.on_command(c)))
        m.add_separator()
        m.add_command(label="Settings", command=self._open_settings)
        m.add_command(label="Quit", command=self.root.destroy)
        self._m = m

    def _menu(self, e):
        try:
            self._m.tk_popup(e.x_root, e.y_root)
        finally:
            self._m.grab_release()

    def _open_settings(self):
        import subprocess, sys, os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        subprocess.Popen([sys.executable, "app.py"], cwd=root)

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
        if not self._moved:
            self._prompt()

    def _prompt(self):
        win = tk.Toplevel(self.root)
        win.attributes("-topmost", True)
        win.title("Tell buddy")
        e = tk.Entry(win, width=44); e.pack(padx=8, pady=8); e.focus()
        def go(_=None):
            cmd = e.get().strip(); win.destroy()
            if cmd:
                self.talk()                     # react while it answers
                self.on_command(cmd)
        e.bind("<Return>", go)

    def talk(self, ms=1500):
        self._talk_left = ms

    # ---- animation ----
    def _animate(self):
        state = "talk" if (self._talk_left > 0 and self.frames and "talk" in self.frames) else "idle"
        if self.frames:
            seq = self.frames.get(state) or self.frames.get("idle")
            self.fi = (self.fi + 1) % len(seq)
            self.c.itemconfig(self.img_id, image=seq[self.fi])
        else:
            self._blob()                        # fallback drawing
        self._talk_left = max(0, self._talk_left - 120)
        self.root.after(120, self._animate)

    def _blob(self):
        self.c.delete("blob")
        s = self.size
        self.c.create_oval(15, 20, s-15, s-10, fill="#4aa3ff", outline="", tags="blob")
        for dx in (-12, 12):
            self.c.create_oval(s/2+dx-6, 40, s/2+dx+6, 52, fill="white", outline="", tags="blob")

    def _wander(self):
        if not self.dragging:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x += self.vx; y += self.vy
            if x < 0 or x > sw - self.size: self.vx *= -1
            if y < 0 or y > sh - self.size: self.vy *= -1
            self.root.geometry(f"+{x}+{y}")
        self.root.after(40, self._wander)

    def run(self):
        self.root.mainloop()
