"""Launcher.

    python run.py              the desktop buddy
    python run.py --cli        the terminal instead
    python run.py --once "..." do one thing, no window, result to the inbox
    python run.py --chat       answer from Telegram or Discord
    python run.py --testlog    write what you asked and what it said to a file
                               (add "bad" for the failures only)
    python run.py --selftest   load everything, print a report, exit

--selftest is what CI runs against the packaged .exe: it exercises the parts a
frozen build usually breaks (skill discovery, sprite paths, the vectoriser)
without opening a window.
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def selftest() -> int:
    from vb import __version__
    from vb.registry import load_all
    from vb.router import Router
    from vb.ui.sprite import asset_root

    from vb.web import extract

    skills = load_all()
    router = Router(skills)
    match = router.best("what's eating my disk space")
    sprites = sorted(p.name for p in (asset_root() / "duck").glob("idle_*.png"))

    # Extraction offline, on a fixed page: this is what breaks when the build
    # excludes a package the extraction stack quietly imports.
    sample = ("<html><head><title>Tide times</title></head><body><nav>menu</nav>"
              "<article><p>" + ("The tide turns at four in the afternoon. " * 20) +
              "</p></article></body></html>")
    text = extract.to_text(sample, "https://example.com/tides")

    # Pillow is what composites sprites onto the transparency key. It went
    # missing from requirements once; opening a frame here is how that gets
    # caught before anyone downloads a build with no buddy in it.
    try:
        from PIL import Image
        with Image.open(asset_root() / "duck" / "idle_0.png") as frame:
            pillow = f"{frame.width}x{frame.height} {frame.mode}"
    except Exception as exc:
        pillow = f"BROKEN ({type(exc).__name__}: {exc})"

    print(f"version   {__version__}")
    print(f"frozen    {bool(getattr(sys, 'frozen', False))}")
    print(f"skills    {len(skills)}")
    print(f"route     {match.skill.name if match else 'NONE'} "
          f"({match.score:.2f})" if match else "route     NONE")
    print(f"sprites   {asset_root()} -> {len(sprites)} duck idle frames")
    print(f"extract   {len(text.split())} words from a sample page")
    print(f"pillow    {pillow}")

    problems = []
    if len(skills) < 20:
        problems.append(f"only {len(skills)} skills registered")
    if not match or match.skill.name != "disk_hogs":
        problems.append("routing did not reach disk_hogs")
    if not sprites:
        problems.append("no sprites found")
    if "tide turns" not in text:
        problems.append("page extraction returned nothing usable")
    if "BROKEN" in pillow:
        problems.append("Pillow cannot open a sprite, so the buddy will not draw")
    for problem in problems:
        print(f"FAIL      {problem}")
    print("ok" if not problems else "FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    # What a scheduled task runs in a frozen build. Without this branch the
    # packaged .exe answered `--once` by opening the whole GUI and ignoring the
    # request, so every scheduled job on an installed copy did nothing at all.
    if "--chat" in sys.argv:
        from vb.chat import serve_forever
        raise SystemExit(serve_forever())
    if "--once" in sys.argv:
        from vb.run_once import main
        argv = sys.argv[1:]
        argv.remove("--once")
        raise SystemExit(main(argv))
    # Export the testing log without having to open a front end. A packaged
    # build has no console, so this is how someone on an installed copy gets
    # the file: run the .exe with --testlog and read where it says it went.
    if "--testlog" in sys.argv:
        from vb import testlog
        only_bad = "bad" in sys.argv or "failures" in sys.argv
        target = testlog.write(only_failures=only_bad)
        print(testlog.summary())
        print(f"written to: {target}")
        raise SystemExit(0)
    if "--cli" in sys.argv:
        from vb.cli import main
        sys.argv.remove("--cli")
        raise SystemExit(main())
    from vb.app import main
    raise SystemExit(main())
