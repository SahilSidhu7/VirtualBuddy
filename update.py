"""Update VirtualBuddy to the latest version. Cross-platform.

  python update.py       # git pull + refresh packages + retrain brain

Keeps your config.yaml and installed skills.
"""
import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))

def sh(*args):
    print("  $", " ".join(args))
    return subprocess.run(args, cwd=ROOT).returncode

def main():
    print("Updating VirtualBuddy...")
    if os.path.isdir(os.path.join(ROOT, ".git")):
        sh("git", "pull", "--ff-only")
    else:
        print("  (not a git checkout - skipping git pull)")
    sh(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q")
    print("  retraining brain (local, no tokens)...")
    subprocess.run([sys.executable, "-m", "tools.loop", "0.95", "4"], cwd=ROOT)
    print("Done.")

if __name__ == "__main__":
    main()
