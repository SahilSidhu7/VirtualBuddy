"""Makes pixel-art buddy characters (crab, duck, elf) as PNG frames.

Each character is a 16x16 pixel map, scaled up with nearest-neighbour so it
stays crisp pixel-art. Output -> assets/character/<name>/idle_0.png etc.
Edit the maps below or drop your own PNGs to add characters.

Run: python -m tools.make_pixels
"""
import os
from PIL import Image

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

def main():
    for name, spec in CHARS.items():
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        render(spec, 0).save(os.path.join(d, "idle_0.png"))
        render(spec, 1).save(os.path.join(d, "idle_1.png"))   # 1px bob
        render(spec, 0).save(os.path.join(d, "talk_0.png"))
        print(f"wrote {name} -> {d}")

if __name__ == "__main__":
    main()
