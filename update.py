"""Update VirtualBuddy to the latest version. Cross-platform.

  python update.py       # git pull + refresh packages + retrain brain

Keeps your config.yaml and installed skills.
"""
import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))

def sh(*args):
    print("  $", " ".join(args))
    return subprocess.run(args, cwd=ROOT).returncode

def is_git_checkout():
    return os.path.isdir(os.path.join(ROOT, ".git"))

def pull_only():
    """Lightweight auto-update: git pull + quiet dep refresh, NO retrain.
    Returns (changed: bool, message: str). Safe to call on launch in the background."""
    if not is_git_checkout():
        return False, "not a git checkout"
    try:
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
    except Exception as e:
        return False, f"update check failed: {e}"
    if before == after:
        return False, "already up to date"
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
                   cwd=ROOT)
    return True, f"updated {before[:7]} -> {after[:7]} (run !train or the Update button to retrain)"

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
