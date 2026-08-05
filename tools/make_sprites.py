"""Makes the default buddy sprite frames as PNGs. Local, editable, free.

Draws a cute robot mascot at 4x then shrinks -> smooth edges.
Output -> assets/character/<state>_<n>.png  (RGBA, transparent).
Swap these PNGs with your own art any time (keep the names).

Run: python -m tools.make_sprites
"""
import os, math
from PIL import Image, ImageDraw

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
    print(f"wrote {len(idle)} idle + {len(talk)} talk frames to {OUT}")

if __name__ == "__main__":
    main()
