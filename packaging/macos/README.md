# Building the macOS app

Annulus ships as a double-click macOS app: a Tauri shell wrapping a frozen Python
sidecar (PyInstaller) and the built React frontend.

## Prerequisites

- macOS (Apple Silicon), Xcode command-line tools
- Rust (`rustup`), Node.js, and the project's `.venv` (Python 3.12)
- An app icon at `packaging/macos/icon.png` (1024×1024 PNG)

## One-time setup

```bash
make -C packaging/macos deps     # PyInstaller, frontend deps + Tauri CLI (npm)
make -C packaging/macos icons    # generate src-tauri/icons/* from icon.png
```

## Build

```bash
make -C packaging/macos dist
```

This runs (all verified working on Apple Silicon):
1. **PyInstaller** freezes `src/api/sidecar.py` + every package and the
   bio/experiment stacks into a ~454 MB onedir bundle, staged at
   `packaging/build/locus-sidecar/`.
2. **Tauri build** builds the frontend and links the Rust shell, bundling the
   frozen sidecar as a resource → a self-contained `.app` (~530 MB).
3. **hdiutil** packages the `.app` into a drag-to-Applications `.dmg`.

> The Tauri config targets `app` only; the `.dmg` is made with `hdiutil` because
> Tauri's built-in DMG step uses Finder/AppleScript and fails in headless builds.

### Output

```
src-tauri/target/release/bundle/macos/Biomedical Data Aggregator.app   (~530 MB)
packaging/build/Biomedical Data Aggregator.dmg                          (~246 MB)
```

## Opening the unsigned app (Gatekeeper)

The app is **unsigned**, so macOS Gatekeeper will block it on first launch.
Either:

- **Right-click → Open**, then confirm "Open" in the dialog; or
- Clear the quarantine attribute:

  ```bash
  xattr -cr "/Applications/Biomedical Data Aggregator.app"
  ```

(Code signing + notarization can be added later via Tauri's `signingIdentity`.)

## How startup works

The Tauri shell shows a splash window, spawns the sidecar (which picks a free
port, writes it to `sidecar.port` in the app data dir, and serves on
`127.0.0.1`), polls `GET /health` for up to 15 seconds, then opens the main
window with the sidecar URL injected as `window.__ANNULUS_API__`. On failure the
splash shows the sidecar log and a **Retry** button. The sidecar is terminated
when the main window closes.
