"""Small Tk building blocks.

Tk has no rounded corners and no hover states, so the few we need are drawn on
a Canvas. Everything here takes a Theme and reads its tokens rather than
hard-coding colour, so an avatar switch re-skins the whole window.
"""
from __future__ import annotations

import tkinter as tk

from vb.ui.theme import RADIUS, RADIUS_SM, Theme


def font(theme: Theme, size: int = 10, weight: str = "normal") -> tuple:
    return (theme.font, size, weight)


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r=RADIUS, **kw):
    """A rounded rectangle as a smoothed polygon — Tk's only route to soft corners."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Button(tk.Canvas):
    """Flat pill button with a real pressed state (the push is the feedback)."""

    def __init__(self, master, text: str, command, theme: Theme, *,
                 primary: bool = False, width: int = 96, height: int = 30,
                 radius: int = RADIUS_SM, size: int = 10):
        bg = master.cget("background")
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.theme, self.primary, self.command = theme, primary, command
        self._radius, self._size = radius, size
        self._text = text
        self._draw(state="rest")
        self.bind("<Enter>", lambda _e: self._draw("hover"))
        self.bind("<Leave>", lambda _e: self._draw("rest"))
        self.bind("<ButtonPress-1>", lambda _e: self._draw("down"))
        self.bind("<ButtonRelease-1>", self._release)

    def _colours(self, state: str) -> tuple[str, str, str]:
        t = self.theme
        if self.primary:
            fill = {"rest": t.accent, "hover": t.accent, "down": t.accent_dim}[state]
            return fill, t.base, fill
        fill = {"rest": t.surface_hi, "hover": t.line, "down": t.surface}[state]
        return fill, t.text_dim if state == "rest" else t.text, t.line

    def _draw(self, state: str):
        fill, fg, outline = self._colours(state)
        dy = 1 if state == "down" else 0
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        round_rect(self, 1, 1 + dy, w - 1, h - 1 + dy, r=self._radius,
                   fill=fill, outline=outline)
        self.create_text(w / 2, h / 2 + dy, text=self._text, fill=fg,
                         font=font(self.theme, self._size, "normal"))

    def _release(self, _event):
        self._draw("hover")
        if self.command:
            self.command()

    def set_text(self, text: str):
        self._text = text
        self._draw("rest")

    def restyle(self, theme: Theme):
        self.theme = theme
        self.configure(bg=self.master.cget("background"))
        self._draw("rest")


class Card(tk.Frame):
    """A surface panel. Square-cornered by design: Tk cannot clip child widgets
    to a rounded parent, and a fake rounded backdrop behind square children
    looks worse than an honest rectangle with a hairline."""

    def __init__(self, master, theme: Theme, **kw):
        super().__init__(master, bg=theme.surface, highlightthickness=1,
                         highlightbackground=theme.line,
                         highlightcolor=theme.line, **kw)
        self.theme = theme

    def restyle(self, theme: Theme):
        self.theme = theme
        self.configure(bg=theme.surface, highlightbackground=theme.line,
                       highlightcolor=theme.line)


class Meter(tk.Canvas):
    """Confidence readout: a number plus a hairline bar. No filled track — the
    bar is the value, not a container for it."""

    def __init__(self, master, theme: Theme, width: int = 84, height: int = 16):
        super().__init__(master, width=width, height=height,
                         bg=master.cget("background"), highlightthickness=0, bd=0)
        self.theme = theme
        self._value = 0.0
        self.draw()

    def set(self, value: float):
        self._value = max(0.0, min(1.0, value))
        self.draw()

    def draw(self):
        t, w, h = self.theme, int(self["width"]), int(self["height"])
        self.delete("all")
        bar_w = w - 34
        y = h / 2
        self.create_line(0, y, bar_w, y, fill=t.line, width=2, capstyle="round")
        if self._value > 0:
            self.create_line(0, y, max(2, bar_w * self._value), y,
                             fill=t.accent, width=2, capstyle="round")
        self.create_text(w, y, anchor="e", text=f"{self._value:.2f}",
                         fill=t.text_faint, font=(t.mono, 8))

    def restyle(self, theme: Theme):
        self.theme = theme
        self.configure(bg=self.master.cget("background"))
        self.draw()


def drag_by(widget: tk.Misc, window: tk.Misc):
    """Let a frameless window be dragged by `widget`."""
    state = {}

    def press(e):
        state["x"], state["y"] = e.x_root, e.y_root
        state["wx"], state["wy"] = window.winfo_x(), window.winfo_y()

    def move(e):
        if "x" not in state:
            return
        window.geometry(f"+{state['wx'] + e.x_root - state['x']}"
                        f"+{state['wy'] + e.y_root - state['y']}")

    widget.bind("<ButtonPress-1>", press, add="+")
    widget.bind("<B1-Motion>", move, add="+")
