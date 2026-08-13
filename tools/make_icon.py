"""Build the Windows .ico from a character sprite.

    python tools/make_icon.py [duck|elf|crab]

Kept as a script rather than a committed binary blob nobody can regenerate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main(avatar: str = "duck") -> int:
    from PIL import Image

    source = ROOT / "assets" / "character" / avatar / "idle_0.png"
    if not source.exists():
        print(f"No sprite at {source}")
        return 1

    art = Image.open(source).convert("RGBA")
    # Trim the transparent margin so the glyph fills the icon at 16px.
    box = art.getbbox()
    if box:
        art = art.crop(box)
    side = max(art.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(art, ((side - art.width) // 2, (side - art.height) // 2))

    frames = [square.resize((n, n), Image.NEAREST) for n in SIZES]
    out = ROOT / "packaging" / "windows" / "virtualbuddy.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    print(f"wrote {out} ({out.stat().st_size:,} bytes) from {avatar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "duck"))
