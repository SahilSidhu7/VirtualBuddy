# PyInstaller build for the Windows app.
#
#     pyinstaller packaging/windows/virtualbuddy.spec --noconfirm
#
# One directory rather than one file: the installer hides the folder anyway, and
# a one-file build unpacks itself to a temp directory on every launch, which is
# exactly the wrong trade for something that starts with Windows.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets" / "character"), "assets/character")],
    # The skill modules are imported by name at runtime, so the analyser cannot
    # see them from the import graph alone.
    #
    # This list has to be kept in step with `vb.skills.MODULES`, and the way it
    # fails when it is not is silent: `registry.load_all` catches the
    # ImportError and moves on, so an unlisted skill is simply absent from the
    # packaged app with nothing said. agenda, browsing and seeing were added to
    # MODULES and missed here, which would have shipped a build with no
    # calendar, no browser control and no eyes.
    hiddenimports=[
        "vb.skills.agenda", "vb.skills.apps", "vb.skills.browsing",
        "vb.skills.filework", "vb.skills.pcgraph", "vb.skills.procs",
        "vb.skills.seeing", "vb.skills.todo", "vb.skills.websearch",
        "vb.planner", "vb.progress", "vb.ui.splash",
        # Reached only through function-level imports, and cheap insurance
        # against the analyser missing one: an absent module here is another
        # silent loss of a whole feature rather than a build error.
        "vb.chat", "vb.executors", "vb.mcp", "vb.run_once", "vb.schedule",
        "vb.vision",
        # The screenshot grabber, imported inside `vision.screenshot`.
        "PIL.ImageGrab", "PIL.ImageTk", "PIL._tkinter_finder",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Optional at runtime and downloaded on demand; bundling them would triple
    # the installer for features most people never turn on.
    #
    # torch and friends are here because they are installed on some build
    # machines and the analyser follows them through optional imports in other
    # libraries. Nothing in VirtualBuddy imports torch: verified with
    # `import vb.app; 'torch' in sys.modules` -> False. Leaving it in added
    # gigabytes and roughly an hour to the build.
    excludes=["torch", "torchvision", "torchaudio", "transformers",
              "sentence_transformers", "tensorflow", "jax", "triton",
              "sklearn", "scipy", "pandas",
              # Reached through optional imports in the extraction stack, and
              # 40MB between them. selftest exercises extraction, so a wrong
              # guess here fails the build rather than shipping.
              "babel", "pytz", "pythonnet", "clr", "Pythonwin", "win32com",
              "playwright", "vosk", "sounddevice", "matplotlib",
              "pytest", "IPython", "notebook", "pygments"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VirtualBuddy",
    debug=False,
    strip=False,
    upx=False,
    console=False,                       # no console window at login
    icon=str(ROOT / "packaging" / "windows" / "virtualbuddy.ico"),
    version=str(ROOT / "packaging" / "windows" / "version.txt"),
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="VirtualBuddy",
)
