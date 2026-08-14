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
    hiddenimports=[
        "vb.skills.apps", "vb.skills.filework", "vb.skills.pcgraph",
        "vb.skills.procs", "vb.skills.todo", "vb.skills.websearch",
        "vb.planner", "vb.progress", "vb.ui.splash",
        "PIL.ImageTk", "PIL._tkinter_finder",
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
