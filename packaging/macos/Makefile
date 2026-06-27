# Annulus macOS build pipeline (verified working).
#
#   make deps   — install build tooling (PyInstaller, frontend deps + Tauri CLI)
#   make icons  — generate the app icon set from packaging/macos/icon.png
#   make dist   — freeze sidecar -> build the .app -> package a .dmg
#
# Final artifacts:
#   src-tauri/target/release/bundle/macos/Biomedical Data Aggregator.app
#   packaging/build/Biomedical Data Aggregator.dmg

ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)
PY    := $(ROOT)/.venv/bin/python
TAURI := $(ROOT)/frontend/node_modules/.bin/tauri
BUILD := $(ROOT)/packaging/build
APP   := $(ROOT)/src-tauri/target/release/bundle/macos/Biomedical Data Aggregator.app
DMG   := $(BUILD)/Biomedical Data Aggregator.dmg

.PHONY: dist deps icons sidecar app dmg clean

deps:
	$(PY) -m pip install -e "$(ROOT)[bio,experiments,packaging]"
	npm --prefix $(ROOT)/frontend install

icons:
	cd $(ROOT) && $(TAURI) icon packaging/macos/icon.png

# Freeze the Python sidecar into a self-contained onedir bundle, then stage it
# where tauri.conf.json expects it (packaging/build/annulus-sidecar).
sidecar:
	cd $(ROOT) && $(PY) -m PyInstaller packaging/annulus_sidecar.spec --noconfirm \
		--distpath $(BUILD)/_dist --workpath $(BUILD)/_work
	rm -rf $(BUILD)/annulus-sidecar
	cp -R $(BUILD)/_dist/annulus-sidecar $(BUILD)/annulus-sidecar
	@echo "Sidecar staged at $(BUILD)/annulus-sidecar"

# Build the .app (the Tauri CLI builds the frontend via beforeBuildCommand).
app: sidecar
	cd $(ROOT)/src-tauri && $(TAURI) build

# Package the .app into a drag-to-Applications .dmg (hdiutil — no Finder needed).
dmg:
	@stage=$$(mktemp -d); \
	cp -R "$(APP)" "$$stage/"; \
	ln -s /Applications "$$stage/Applications"; \
	rm -f "$(DMG)"; \
	hdiutil create -volname "Biomedical Data Aggregator" -srcfolder "$$stage" \
		-ov -format UDZO "$(DMG)"; \
	rm -rf "$$stage"

dist: app dmg
	@echo ""
	@echo "Done."
	@echo "  App: $(APP)"
	@echo "  DMG: $(DMG)"

clean:
	rm -rf $(BUILD) $(ROOT)/src-tauri/target $(ROOT)/frontend/dist
