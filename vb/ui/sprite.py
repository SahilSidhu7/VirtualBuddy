"""Loading and animating the pixel avatars.

Windows gives a Tk window per-pixel transparency only through a colour key, so
each frame is composited onto that key colour and the window is told to treat it
as see-through. Pixel art has hard alpha edges, which is exactly the case where
a colour key looks clean.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

KEY = "#FE00FE"          # colour key: a magenta no sprite contains
STATES = ("idle", "listening", "thinking", "working", "talk")


def asset_root() -> Path:
    """Where the character folders live, in a checkout or inside a bundle."""
    import sys
    here = Path(__file__).resolve().parents[2]
    candidates = [here / "assets" / "character"]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "assets" / "character")
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[-1]


class Frames:
    """Every state's frames for one avatar, as Tk images ready to blit."""

    def __init__(self, avatar: str, size: int = 128):
        self.avatar, self.size = avatar, size
        self.by_state: dict[str, list[tk.PhotoImage]] = {}
        self._load()

    def _load(self):
        from PIL import Image, ImageTk
        folder = asset_root() / self.avatar
        key_rgb = tuple(int(KEY[i:i + 2], 16) for i in (1, 3, 5))
        for state in STATES:
            frames = []
            for path in sorted(folder.glob(f"{state}_*.png")):
                img = Image.open(path).convert("RGBA")
                if img.size != (self.size, self.size):
                    img = img.resize((self.size, self.size), Image.NEAREST)
                flat = Image.new("RGB", img.size, key_rgb)
                flat.paste(img, mask=img.split()[3])
                frames.append(ImageTk.PhotoImage(flat))
            if frames:
                self.by_state[state] = frames
        if "idle" not in self.by_state:
            raise FileNotFoundError(f"No sprites for avatar “{self.avatar}” in {folder}")

    def get(self, state: str) -> list[tk.PhotoImage]:
        return self.by_state.get(state) or self.by_state["idle"]


# Frame dwell time per state: idle breathes slowly, working is busy.
PACE = {"idle": 620, "listening": 260, "thinking": 300, "working": 180, "talk": 220}
