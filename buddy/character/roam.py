"""Sit vs roam — give the on-screen buddy a floor to walk on.

The taskbar's top edge is the ground. In roam mode the buddy strolls left/right along
it, turns at the screen edges, and obeys gravity: drag it into the air, let go, and it
falls back to the taskbar. Sit mode (default) leaves it exactly where you drop it.

Kept as a separate controller so character.py stays simple and roam is fully opt-in —
important because moving the window every tick is what historically caused flicker, so
it only happens when the user actually turns roaming on.

Windows: the taskbar height is read from the desktop work-area (SPI_GETWORKAREA).
Other OSes / failure: falls back to a sensible default.
"""
import sys


def _screen_and_floor(root):
    """Return (screen_w, screen_h, floor_y) where floor_y is the taskbar's top edge."""
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    taskbar = 48
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030 -> usable desktop minus the taskbar
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            work_bottom = rect.bottom
            if 0 < work_bottom <= sh:
                taskbar = sh - work_bottom
        except Exception:
            pass
    return sw, sh, sh - taskbar


class RoamController:
    """Tiny (x, y, vx, vy) integrator. One .step() per animation tick moves the window."""

    def __init__(self, root, size, speed=40):
        self.root = root
        self.size = size
        self.speed = float(speed)          # px/sec horizontal walk
        self.gravity = 1400.0              # px/sec^2
        self.sw, self.sh, self.floor = _screen_and_floor(root)
        self.x = float(root.winfo_x() or 300)
        self.y = float(self.floor - size)  # stand on the floor
        self.vx = self.speed
        self.vy = 0.0
        self.facing = 1

    def resync_from_window(self):
        """After a drag, adopt the window's dropped position (so it falls from there)."""
        self.x = float(self.root.winfo_x())
        self.y = float(self.root.winfo_y())
        self.vy = 0.0

    def step(self, dt):
        """Advance physics by dt seconds; return (int_x, int_y) to place the window at."""
        ground = self.floor - self.size
        # gravity while above the floor
        if self.y < ground:
            self.vy += self.gravity * dt
            self.y += self.vy * dt
            if self.y >= ground:
                self.y, self.vy = ground, 0.0
        else:
            # on the floor -> walk
            self.y = ground
            self.x += self.vx * dt
            if self.x <= 0:
                self.x, self.vx, self.facing = 0.0, abs(self.vx), 1
            elif self.x >= self.sw - self.size:
                self.x, self.vx, self.facing = float(self.sw - self.size), -abs(self.vx), -1
        return int(self.x), int(self.y)

    def walking(self):
        return abs(self.y - (self.floor - self.size)) < 1.0
