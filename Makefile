# hackai-mpk: reproducible analysis of the AKAI MPK Mini Plus firmware.
# Run `make help` for the list of targets.

GHIDRA_INSTALL_DIR ?= /opt/ghidra_11.3.1_PUBLIC
export GHIDRA_INSTALL_DIR
RENODE ?= /opt/renode_1.17.0-portable/renode
SIM_TIME ?= 2

PYTHON  := .venv/bin/python
SVD     := build/svd/AT32F415xx_v2.svd
SVD_RENODE := build/svd/AT32F415xx_v2.renode.svd
SVD_URL := $(shell sed -n 's/^url = "\(.*\)"/\1/p' config/segments.toml)
SVD_SHA := $(shell sed -n 's/^sha256 = "\(.*\)"/\1/p' config/segments.toml)
BASEROM := baserom/firmware.bin
PROJECT := build/ghidra/hackai-mpk.gpr

.PHONY: help setup setup-gui gui matrix-sweep analog-sweep baserom check ghidra rebuild export report decompile decompile-all sim sim-debug sim-dump flash-check flash-sim flash screensaver screensaver-sim mod mod-sim clean distclean

help:
	@echo "make setup               create .venv with PyGhidra (from your Ghidra install)"
	@echo "make baserom SRC=<file>  find and verify the stock firmware (updater .exe or raw file)"
	@echo "make check               verify baserom/firmware.bin"
	@echo "make ghidra              build the Ghidra project from config/ (first time)"
	@echo "make export              write names from Ghidra back to config/symbols.csv"
	@echo "make decompile F=<fn>    print Ghidra's decompilation of functions (names or 0x addresses)"
	@echo "make decompile-all       every function into build/decompiled.c (for grep)"
	@echo "make report              generate analysis reports in build/reports/"
	@echo "make setup-gui           install the simulator GUI dependencies (PySide6) in .venv"
	@echo "make gui                 run the simulator with the MPK Mini Plus panel (PySide6)"
	@echo "make gui JACK=1          same, with the DIN MIDI on JACK ports (PipeWire, needs pw-jack)"
	@echo "make matrix-sweep        press every button matrix position, report in build/reports/"
	@echo "make analog-sweep        drive every analog input (ADC x mux), report in build/reports/"
	@echo "make sim                 run the stock firmware in Renode, with the OLED in a window"
	@echo "make sim-debug           same as sim, with all the warnings (to find missing models)"
	@echo "make sim-dump            run SIM_TIME virtual seconds headless and print the OLED as text"
	@echo "make flash-check IMAGE=… safety checks on a firmware image"
	@echo "make flash-sim IMAGE=…   flash an image into the simulator over the update protocol, verify it"
	@echo "make flash IMAGE=…       flash a real unit in update mode (SHIFT + PROG SELECT at power-up)"
	@echo "make screensaver PNG=…   build/mods/screensaver.bin: stock firmware with PNG as screensaver"
	@echo "make screensaver-sim     show the screensaver of build/mods/screensaver.bin in the simulator"
	@echo "make mod                 build/mods/hackai.bin: stock firmware + our code (firmware/)"
	@echo "make mod BASE=build/mods/screensaver.bin   same, on top of another image (screensaver)"
	@echo "make mod-sim             check the mod in the simulator (Global menu, MIDI THRU, pad channels, LED feedback)"
	@echo "make rebuild             export, then rebuild the Ghidra project from scratch"
	@echo "make clean               delete the Ghidra project (export first!)"
	@echo "make distclean           delete build/ and .venv/"

setup: $(PYTHON)

$(PYTHON):
	python3 -m venv .venv
	$(PYTHON) -m pip install --no-index \
	  -f $(GHIDRA_INSTALL_DIR)/Ghidra/Features/PyGhidra/pypkg/dist pyghidra

baserom:
	@test -n "$(SRC)" || { echo "usage: make baserom SRC=/path/to/MPK_mini_Plus_Updater_v1.13.exe"; exit 1; }
	python3 tools/baserom.py "$(SRC)"

check:
	python3 tools/baserom.py --check

$(SVD):
	mkdir -p $(dir $@)
	curl -fsSL -o $@.tmp "$(SVD_URL)"
	echo "$(SVD_SHA)  $@.tmp" | sha256sum -c --quiet
	mv $@.tmp $@

# Renode rejects the stray whitespace in some <access> fields of Artery's SVD.
$(SVD_RENODE): $(SVD)
	sed -E 's#<access>[[:space:]]*([a-zA-Z-]+)[[:space:]]*</access>#<access>\1</access>#g' $< > $@

$(PROJECT): | $(PYTHON) $(SVD)
	python3 tools/baserom.py --check
	$(PYTHON) tools/ghidra/build_project.py

ghidra: $(PROJECT)

export: | $(PYTHON)
	$(PYTHON) tools/ghidra/export_symbols.py

decompile: | $(PYTHON)
	@$(PYTHON) tools/ghidra/decompile.py $(F) 2>/dev/null | grep -v '^INFO'

decompile-all: | $(PYTHON)
	$(PYTHON) tools/ghidra/decompile.py --all 2>/dev/null | grep -v '^INFO' > build/decompiled.c
	@grep -c '^// ' build/decompiled.c | xargs echo "functions:"

report: | $(PYTHON)
	$(PYTHON) tools/ghidra/report_peripherals.py

setup-gui: | $(PYTHON)
	$(PYTHON) -m pip install -r sim/gui/requirements.txt

gui: $(SVD_RENODE) | $(PYTHON)
	python3 tools/baserom.py --check
	RENODE=$(RENODE) $(if $(JACK),pw-jack) $(PYTHON) sim/gui/mpk_panel.py $(if $(JACK),--jack)

matrix-sweep: $(SVD_RENODE)
	python3 tools/baserom.py --check
	RENODE=$(RENODE) python3 sim/scripts/matrix_sweep.py

analog-sweep: $(SVD_RENODE)
	python3 tools/baserom.py --check
	RENODE=$(RENODE) python3 sim/scripts/analog_sweep.py

sim: $(SVD_RENODE)
	python3 tools/baserom.py --check
	$(RENODE) -e 'include @sim/mpk.resc; include @sim/quiet.resc; showAnalyzer spi2.oled; start'

sim-debug: $(SVD_RENODE)
	python3 tools/baserom.py --check
	$(RENODE) -e 'include @sim/mpk.resc; showAnalyzer spi2.oled; start'

sim-dump: $(SVD_RENODE)
	python3 tools/baserom.py --check
	$(RENODE) --disable-gui --console --plain \
	  -e 'include @sim/mpk.resc; emulation RunFor "$(SIM_TIME)"; cpu PC; spi2.oled AsciiArt; quit' \
	  </dev/null 2>&1 | tr -d '\r' | grep -E '^(0x|[.#]+$$)'

flash-check:
	@test -n "$(IMAGE)" || { echo "usage: make flash-check IMAGE=<file>"; exit 1; }
	python3 tools/mpkflash.py check "$(IMAGE)"

flash-sim: $(SVD_RENODE)
	@test -n "$(IMAGE)" || { echo "usage: make flash-sim IMAGE=<file>"; exit 1; }
	RENODE=$(RENODE) python3 -u tools/mpkflash.py flash "$(IMAGE)" --sim

flash:
	@test -n "$(IMAGE)" || { echo "usage: make flash IMAGE=<file>"; exit 1; }
	python3 tools/mpkflash.py flash "$(IMAGE)" --hid

SCREENSAVER := build/mods/screensaver.bin

screensaver:
	@test -n "$(PNG)" || { echo "usage: make screensaver PNG=<image> [OPTS=--dither]"; exit 1; }
	python3 tools/baserom.py --check
	python3 tools/screensaver.py patch "$(PNG)" $(SCREENSAVER) $(OPTS)

screensaver-sim: $(SVD_RENODE)
	@test -f $(SCREENSAVER) || { echo "run make screensaver PNG=<image> first"; exit 1; }
	RENODE=$(RENODE) python3 -u sim/scripts/screensaver_check.py $(SCREENSAVER)

MOD := build/mods/hackai.bin
BASE ?= $(BASEROM)

mod:
	python3 tools/baserom.py --check
	python3 tools/build_mod.py --firmware $(BASE) --out $(MOD)

mod-sim: mod $(SVD_RENODE)
	RENODE=$(RENODE) python3 -u sim/scripts/menu_check.py $(MOD) --compare $(BASEROM) | grep -E 'PASS|FAIL|checks'
	RENODE=$(RENODE) python3 -u sim/scripts/thru_check.py $(MOD) --stock $(BASEROM) | grep -E 'PASS|FAIL|checks'
	RENODE=$(RENODE) python3 -u sim/scripts/pad_check.py $(MOD) --compare $(BASEROM) | grep -E 'PASS|FAIL|checks'
	RENODE=$(RENODE) python3 -u sim/scripts/feedback_check.py $(MOD) --stock $(BASEROM) | grep -E 'PASS|FAIL|checks'

rebuild: export | $(PYTHON) $(SVD)
	python3 tools/baserom.py --check
	$(PYTHON) tools/ghidra/build_project.py --force

clean:
	rm -rf build/ghidra

distclean:
	rm -rf build .venv
