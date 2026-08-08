"""Makes the default buddy sprite frames as PNGs. Local, editable, free.

Draws a cute robot mascot at 4x then shrinks -> smooth edges.
Output -> assets/character/<state>_<n>.png  (RGBA, transparent).
Swap these PNGs with your own art any time (keep the names).

Run: python -m tools.make_sprites
"""
import os, math
from PIL import Image, ImageDraw

ACCENT = (255, 209, 102, 255)
INK = (30, 40, 60, 255)


def _dots(img, lit):
    d = ImageDraw.Draw(img); r = S // 22
    for i in range(3):
        cx, cy = int(S * 0.66) + i * S // 12, int(S * 0.16)
        fill = INK if i < lit else (INK[0], INK[1], INK[2], 70)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _waves(img, n):
    d = ImageDraw.Draw(img)
    for i in range(n):
        pad = int(S * 0.05) + i * S // 14
        d.arc([pad, int(S * 0.32), pad + S // 5, int(S * 0.68)], 110, 250,
              fill=ACCENT, width=max(2, S // 40))


def _gear(img, angle):
    d = ImageDraw.Draw(img); cx, cy, rad = int(S * 0.80), int(S * 0.18), S // 12
    for k in range(8):
        a = angle + k * math.pi / 4
        d.line([cx + math.cos(a) * rad, cy + math.sin(a) * rad,
                cx + math.cos(a) * (rad + S // 24), cy + math.sin(a) * (rad + S // 24)],
               fill=INK, width=max(2, S // 40))
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=INK, width=max(2, S // 40))
    d.ellipse([cx - S // 24, cy - S // 24, cx + S // 24, cy + S // 24], fill=ACCENT)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "character", "robot")
S = 128          # final size
SS = 4           # supersample factor

def _canvas():
    return Image.new("RGBA", (S * SS, S * SS), (0, 0, 0, 0))

def _draw(bob=0.0, blink=False, mouth="smile"):
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = S * SS
    yb = int(bob * SS)                       # vertical bob offset

    # soft shadow on the floor
    d.ellipse([c*0.28, c*0.86, c*0.72, c*0.94], fill=(0, 0, 0, 60))

    # body (rounded), blue with lighter belly
    body = [c*0.20, c*0.22 + yb, c*0.80, c*0.82 + yb]
    d.rounded_rectangle(body, radius=c*0.28, fill=(74, 163, 255, 255))
    d.ellipse([c*0.34, c*0.46 + yb, c*0.66, c*0.78 + yb], fill=(225, 240, 255, 255))

    # antenna
    d.line([c*0.5, c*0.22 + yb, c*0.5, c*0.10 + yb], fill=(74, 163, 255, 255), width=int(c*0.02))
    d.ellipse([c*0.46, c*0.05 + yb, c*0.54, c*0.13 + yb], fill=(255, 209, 102, 255))

    # eyes
    ey = c*0.40 + yb
    for ex in (c*0.40, c*0.60):
        if blink:
            d.line([ex - c*0.06, ey, ex + c*0.06, ey], fill=(30, 40, 60, 255), width=int(c*0.02))
        else:
            d.ellipse([ex - c*0.07, ey - c*0.07, ex + c*0.07, ey + c*0.07], fill=(255, 255, 255, 255))
            d.ellipse([ex - c*0.035, ey - c*0.02, ex + c*0.035, ey + c*0.05], fill=(30, 40, 60, 255))

    # mouth
    my = c*0.62 + yb
    if mouth == "open":
        d.ellipse([c*0.45, my, c*0.55, my + c*0.06], fill=(30, 40, 60, 255))
    else:  # smile
        d.arc([c*0.44, my - c*0.03, c*0.56, my + c*0.05], 20, 160, fill=(30, 40, 60, 255), width=int(c*0.018))

    return img.resize((S, S), Image.LANCZOS)

def main():
    os.makedirs(OUT, exist_ok=True)
    # idle: gentle bob + one blink frame
    idle = [
        _draw(bob=0),  _draw(bob=-3), _draw(bob=-4, blink=True),
        _draw(bob=-3), _draw(bob=0),  _draw(bob=2),
    ]
    for i, im in enumerate(idle):
        im.save(os.path.join(OUT, f"idle_{i}.png"))
    # talk: mouth open/closed while buddy speaks
    talk = [_draw(bob=-1, mouth="open"), _draw(bob=-1, mouth="smile")]
    for i, im in enumerate(talk):
        im.save(os.path.join(OUT, f"talk_{i}.png"))
    # thinking: eyes up + thought dots filling in
    for i, lit in enumerate((1, 2, 3)):
        im = _draw(bob=-2 if i % 2 else 0); _dots(im, lit)
        im.save(os.path.join(OUT, f"thinking_{i}.png"))
    # listening: alert + sound waves
    for i, n in enumerate((1, 2, 3)):
        im = _draw(bob=0); _waves(im, n)
        im.save(os.path.join(OUT, f"listening_{i}.png"))
    # working: gear spins
    for i in range(4):
        im = _draw(bob=-1 if i % 2 else 1, mouth="open"); _gear(im, i * math.pi / 6)
        im.save(os.path.join(OUT, f"working_{i}.png"))
    print(f"wrote idle/talk/thinking/listening/working frames to {OUT}")

if __name__ == "__main__":
    main()
