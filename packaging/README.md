# Packaging

Users should **download a built installer** from the Releases page — they never
run scripts. Installers are built automatically by CI.

## How a release is made
1. Bump the version, commit.
2. Tag it: `git tag v0.1.0 && git push origin v0.1.0`
3. GitHub Actions (`.github/workflows/release.yml`) builds:
   - **Windows:** PyInstaller bundle → Inno Setup → `VirtualBuddy-Setup.exe`
     (Start-menu + desktop shortcut, uninstaller).
   - **Linux:** PyInstaller bundle → `VirtualBuddy-linux.tar.gz`
     (unpack, run `./VirtualBuddy`; GUI on desktops, CLI on servers).
4. Both are attached to the GitHub Release automatically.

## Linux: server vs desktop
Same build works for both. The app checks for a display:
- Desktop (has `$DISPLAY`) → GUI control panel.
- Server (headless) → text/CLI mode (`VirtualBuddy --server` for the host).
For a system service, drop `VirtualBuddy.desktop` in `~/.local/share/applications/`.

## Note on the brain
The bundle contains the app + intent training code, but **not** a pre-trained
model or the Ollama model. On first use the app routes with cosine similarity
(works out of the box). For the accuracy boost, train the classifier on-device
(control panel button or `VirtualBuddy --text` then `!train`) — it uses the
user's local Ollama, so it never needs to ship model weights.
