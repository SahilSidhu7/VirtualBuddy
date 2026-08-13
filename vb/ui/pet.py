"""The buddy itself: a frameless, always-on-top sprite that lives on the desktop.

Left click opens the command panel, drag moves it, right click is the menu.
The sprite's state is the app's only ambient status display, so it changes only
when something real happens: listening, thinking, working, talking.
"""
from __future__ import annotations

import tkinter as tk

from vb import config
from vb.ui import sprite
from vb.ui.sprite import KEY, PACE, Frames

SIZE = 128


class Pet(tk.Toplevel):
    def __init__(self, master: tk.Tk, on_click, on_menu=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", KEY)
        self.configure(bg=KEY)

        self.canvas = tk.Canvas(self, width=SIZE, height=SIZE, bg=KEY,
                                highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack()
        self.item = self.canvas.create_image(SIZE // 2, SIZE // 2)

        self.frames = Frames(config.get("avatar"), SIZE)
        self.state_name = "idle"
        self._index = 0
        self._tick_id = None
        self._drag = {}
        self._on_click = on_click

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        if on_menu:
            self.canvas.bind("<Button-3>", on_menu)

        self.place_default()
        self._tick()

    # -- placement -------------------------------------------------------
    def place_default(self):
        saved = config.get("pet_pos")
        if saved:
            self.geometry(f"+{saved[0]}+{saved[1]}")
            return
        self.update_idletasks()
        x = self.winfo_screenwidth() - SIZE - 48
        y = self.winfo_screenheight() - SIZE - 120
        self.geometry(f"+{x}+{y}")

    def anchor(self) -> tuple[int, int]:
        """Top-left the panel should sit at: beside the pet, on-screen."""
        px, py = self.winfo_x(), self.winfo_y()
        panel_w, panel_h = 420, 460
        x = px - panel_w - 12 if px > panel_w + 24 else px + SIZE + 12
        y = min(max(py + SIZE - panel_h, 12), self.winfo_screenheight() - panel_h - 60)
        return x, y

    # -- animation -------------------------------------------------------
    def set_state(self, name: str):
        if name == self.state_name:
            return
        self.state_name = name if name in sprite.STATES else "idle"
        self._index = 0

    def _tick(self):
        frames = self.frames.get(self.state_name)
        self._index = (self._index + 1) % len(frames)
        self.canvas.itemconfigure(self.item, image=frames[self._index])
        self._tick_id = self.after(PACE.get(self.state_name, 400), self._tick)

    def set_avatar(self, avatar: str):
        self.frames = Frames(avatar, SIZE)
        self._index = 0

    # -- pointer ---------------------------------------------------------
    def _press(self, event):
        self._drag = {"x": event.x_root, "y": event.y_root,
                      "wx": self.winfo_x(), "wy": self.winfo_y(), "moved": False}

    def _move(self, event):
        if not self._drag:
            return
        dx, dy = event.x_root - self._drag["x"], event.y_root - self._drag["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag["moved"] = True
        self.geometry(f"+{self._drag['wx'] + dx}+{self._drag['wy'] + dy}")

    def _release(self, _event):
        moved = self._drag.get("moved")
        self._drag = {}
        if moved:
            config.set("pet_pos", [self.winfo_x(), self.winfo_y()])
        else:
            self._on_click()

    def destroy(self):
        if self._tick_id:
            self.after_cancel(self._tick_id)
        super().destroy()
