"""Skill modules. Every module here is imported at startup by registry.load_all.

MODULES is a fallback for the packaged app: PyInstaller freezes the package, and
directory scanning cannot be relied on to find modules that nothing imports by
name. Add new skill modules here as well as dropping the file in.
"""

MODULES = (
    "agenda",
    "apps",
    "browsing",
    "claudework",
    "filework",
    "pcgraph",
    "procs",
    "seeing",
    "todo",
    "websearch",
    "work",
)
