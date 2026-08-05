"""Cross-platform installer for VirtualBuddy. Works on Windows, macOS, Linux.

  python install.py            # core + brain deps
  python install.py --voice    # also set up offline voice (Vosk model ~40MB)

Safe to re-run. For updates use update.py (git pull + deps).
"""
import os, sys, subprocess, urllib.request, zipfile, platform

ROOT = os.path.dirname(os.path.abspath(__file__))
VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

def sh(*args):
    print("  $", " ".join(args))
    return subprocess.run(args, cwd=ROOT).returncode

def pip_install():
    print("[1/3] installing Python packages...")
    sh(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q")

def check_ollama():
    print("[2/3] checking local brain (Ollama)...")
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).read()
        print("      Ollama running. Good.")
    except Exception:
        print("      Ollama not found. Install from https://ollama.com  then:")
        print("        ollama pull qwen2.5   (or any model; set it in config.yaml)")

def get_voice():
    print("[3/3] downloading offline voice model (~40MB)...")
    models = os.path.join(ROOT, "models")
    os.makedirs(models, exist_ok=True)
    if os.path.isdir(os.path.join(models, "vosk")):
        print("      already present."); return
    zp = os.path.join(models, "m.zip")
    urllib.request.urlretrieve(VOSK_URL, zp)
    with zipfile.ZipFile(zp) as z:
        z.extractall(models)
    os.remove(zp)
    for n in os.listdir(models):
        if n.startswith("vosk-model"):
            os.rename(os.path.join(models, n), os.path.join(models, "vosk"))
    print("      voice ready.")

def train_brain():
    print("[3/4] training the local intent model (uses Ollama embeddings)...")
    r = subprocess.run([sys.executable, "-m", "tools.loop", "0.95", "4"], cwd=ROOT)
    if r.returncode != 0:
        print("      skipped (start Ollama, then run: python -m tools.loop)")

def main():
    print(f"VirtualBuddy install on {platform.system()} (python {sys.version.split()[0]})")
    pip_install()
    check_ollama()
    train_brain()
    if "--voice" in sys.argv:
        get_voice()
    else:
        print("[4/4] skipping voice (run with --voice to add it).")
    print("\nDone. Start with:")
    print("  python app.py        (control panel)")
    print("  python run.py        (text mode)")
    if platform.system() != "Windows":
        print("Note: the on-screen character + lock/open-app work best on Windows.")

if __name__ == "__main__":
    main()
