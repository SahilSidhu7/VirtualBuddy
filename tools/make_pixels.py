"""Makes pixel-art buddy characters (crab, duck, elf) as PNG frames.

Each character is a 16x16 pixel map, scaled up with nearest-neighbour so it
stays crisp pixel-art. Output -> assets/character/<name>/idle_0.png etc.
Edit the maps below or drop your own PNGs to add characters.

Beyond idle/talk, each character gets dedicated STATE frames baked in so the
user can see what buddy is doing:
  listening -> sound-wave arcs (voice is active)
  thinking  -> "..." thought dots (planner / LLM running)
  working   -> spinning gear (a primitive is executing)
These are real PNG frames (not runtime overlays), so custom art can override
them by dropping <state>_<n>.png files in the character folder.

Run: python -m tools.make_pixels
"""
import os, math
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "character")
SCALE = 8   # 16px -> 128px

# palettes: letter -> RGBA ('.' = transparent)
def P(**kw):
    d = {".": (0, 0, 0, 0)}
    d.update({k: (v if len(v) == 4 else v + (255,)) for k, v in kw.items()})
    return d

CRAB = {
    "pal": P(R=(226, 75, 60), D=(143, 36, 28), W=(255, 255, 255),
             K=(20, 20, 20), C=(255, 111, 97)),
    "map": [
        "................",
        "................",
        "...W........W...",
        "...K........K...",
        "...D........D...",
        "..CDR......RDC..",
        ".CCRRRRRRRRRRCC.",
        ".CCRRRRRRRRRRCC.",
        "..CRRRRRRRRRRC..",
        "...RRRRRRRRRR...",
        "..R.RR.RR.RR.R..",
        ".R..R...R..R..R.",
        "................",
        "................",
        "................",
        "................",
    ],
}
DUCK = {
    "pal": P(Y=(255, 217, 74), O=(255, 159, 28), W=(255, 255, 255),
             K=(20, 20, 20), G=(240, 192, 32)),
    "map": [
        "................",
        "......YYYY......",
        ".....YYYYYY.....",
        ".....YWKYYY.....",
        ".....YYYYYY.....",
        "......YYYYY.....",
        "OOO..YYYYYY.....",
        ".OOOYYYYYYYY....",
        "...YYYYYYYYYY...",
        "..YYYYGGGGYYYY..",
        "..YYYYYYYYYYYY..",
        "..YYYYYYYYYYY...",
        "...YYYYYYYYY....",
        "....O....O......",
        "................",
        "................",
    ],
}
ELF = {
    "pal": P(G=(47, 168, 79), F=(255, 216, 168), K=(20, 20, 20),
             T=(31, 143, 63), B=(120, 72, 30), E=(255, 216, 168)),
    "map": [
        ".......G........",
        "......GGG.......",
        ".....GGGGG......",
        "....GGGGGGG.....",
        "...GGGGGGGGG....",
        "......FFF.......",
        ".....FFFFF......",
        "..E..FKFKF..E...",
        ".....FFFFF......",
        "......TTT.......",
        ".....TTTTT......",
        "....TTTTTTT.....",
        "....TBBBBBT.....",
        ".....T...T......",
        ".....T...T......",
        "................",
    ],
}
CHARS = {"crab": CRAB, "duck": DUCK, "elf": ELF}

def render(spec, shift=0):
    pal, m = spec["pal"], spec["map"]
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(m):
        for x, ch in enumerate(row):
            yy = y + shift
            if 0 <= yy < 16:
                px[x, yy] = pal.get(ch, pal["."])
    return img.resize((16 * SCALE, 16 * SCALE), Image.NEAREST)

# ---- state glyphs, drawn on the scaled 128px frame (crisp, baked in) ----
W = 16 * SCALE
ACCENT = (255, 209, 102, 255)
INK = (40, 48, 70, 255)

def _dots(img, lit):
    """thinking: three thought dots top-right, `lit` of them filled."""
    d = ImageDraw.Draw(img)
    r = SCALE
    for i in range(3):
        cx = int(W * 0.62) + i * SCALE * 2
        cy = int(W * 0.14)
        fill = INK if i < lit else (INK[0], INK[1], INK[2], 60)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)

def _waves(img, n):
    """listening: sound-wave arcs on the left, `n` of them."""
    d = ImageDraw.Draw(img)
    for i in range(n):
        pad = int(W * 0.06) + i * SCALE * 2
        box = [pad, int(W * 0.30), pad + SCALE * 4, int(W * 0.70)]
        d.arc(box, 110, 250, fill=ACCENT, width=max(2, SCALE // 2))

def _gear(img, angle):
    """working: a small spinning gear top-right."""
    d = ImageDraw.Draw(img)
    cx, cy, rad = int(W * 0.78), int(W * 0.18), SCALE * 2
    for k in range(8):
        a = angle + k * math.pi / 4
        x0 = cx + math.cos(a) * rad
        y0 = cy + math.sin(a) * rad
        x1 = cx + math.cos(a) * (rad + SCALE)
        y1 = cy + math.sin(a) * (rad + SCALE)
        d.line([x0, y0, x1, y1], fill=INK, width=max(2, SCALE // 2))
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=INK, width=max(2, SCALE // 2))
    d.ellipse([cx - SCALE, cy - SCALE, cx + SCALE, cy + SCALE], fill=ACCENT)

def _frame(spec, shift, glyph=None):
    img = render(spec, shift)
    if glyph:
        glyph(img)
    return img

def main():
    for name, spec in CHARS.items():
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        # base
        render(spec, 0).save(os.path.join(d, "idle_0.png"))
        render(spec, 1).save(os.path.join(d, "idle_1.png"))   # 1px bob
        render(spec, 0).save(os.path.join(d, "talk_0.png"))
        render(spec, 1).save(os.path.join(d, "talk_1.png"))
        # thinking: dots fill in over the loop
        for i, lit in enumerate((1, 2, 3)):
            _frame(spec, i % 2, lambda im, l=lit: _dots(im, l)).save(
                os.path.join(d, f"thinking_{i}.png"))
        # listening: waves grow
        for i, n in enumerate((1, 2, 3)):
            _frame(spec, 0, lambda im, k=n: _waves(im, k)).save(
                os.path.join(d, f"listening_{i}.png"))
        # working: gear rotates
        for i in range(4):
            _frame(spec, i % 2, lambda im, a=i * math.pi / 6: _gear(im, a)).save(
                os.path.join(d, f"working_{i}.png"))
        print(f"wrote {name} -> {d}  (idle/talk/thinking/listening/working)")

if __name__ == "__main__":
    main()
