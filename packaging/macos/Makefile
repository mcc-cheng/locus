# Locus macOS build pipeline (Phase 7.3).
#
#   make deps   — install build tooling (PyInstaller, frontend deps, tauri-cli)
#   make icons  — generate Tauri icons from packaging/macos/icon.png
#   make dist   — freeze sidecar -> tauri build -> .app and .dmg
#
# Final artifacts:
#   src-tauri/target/aarch64-apple-darwin/release/bundle/macos/
#     Biomedical Data Aggregator.app
#     Biomedical Data Aggregator_0.1.0_aarch64.dmg

ROOT   := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)
VENV   := $(ROOT)/.venv
PY     := $(VENV)/bin/python
TARGET := aarch64-apple-darwin
BUILD  := $(ROOT)/packaging/build

.PHONY: dist deps icons sidecar app clean

deps:
	$(PY) -m pip install -e "$(ROOT)[bio,experiments,packaging]"
	npm --prefix $(ROOT)/frontend install
	cargo install tauri-cli --version "^2.0" --locked || true

icons:
	cd $(ROOT)/src-tauri && cargo tauri icon $(ROOT)/packaging/macos/icon.png

# Freeze the Python sidecar into an independent onedir bundle, then stage it
# where tauri.conf.json expects it (packaging/build/locus-sidecar).
sidecar:
	cd $(ROOT) && $(PY) -m PyInstaller packaging/locus_sidecar.spec --noconfirm \
		--distpath $(BUILD)/_dist --workpath $(BUILD)/_work
	rm -rf $(BUILD)/locus-sidecar
	cp -R $(BUILD)/_dist/locus-sidecar $(BUILD)/locus-sidecar
	@echo "Sidecar staged at $(BUILD)/locus-sidecar"

# Build the Tauri app (its beforeBuildCommand builds the frontend).
app: sidecar
	cd $(ROOT)/src-tauri && cargo tauri build --target $(TARGET)

dist: app
	@echo ""
	@echo "Done. Artifacts:"
	@ls -1 "$(ROOT)/src-tauri/target/$(TARGET)/release/bundle/macos/" 2>/dev/null || true
	@ls -1 "$(ROOT)/src-tauri/target/$(TARGET)/release/bundle/dmg/" 2>/dev/null || true

clean:
	rm -rf $(BUILD) $(ROOT)/src-tauri/target $(ROOT)/frontend/dist
