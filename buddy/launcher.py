"""Launch buddy in another mode, correctly whether running from source or as the
packaged .exe. In the frozen app sys.executable IS VirtualBuddy.exe, so we pass
flags straight to it; from source we run vb.py with the interpreter.
"""
import os, sys, subprocess

def spawn(*flags):
    if getattr(sys, "frozen", False):          # packaged app
        cmd = [sys.executable, *flags]
        cwd = os.path.dirname(sys.executable)
    else:                                       # from source
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, os.path.join(root, "vb.py"), *flags]
        cwd = root
    subprocess.Popen(cmd, cwd=cwd)
