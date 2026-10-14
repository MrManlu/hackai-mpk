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

.PHONY: help setup baserom check ghidra rebuild export report sim sim-dump clean distclean

help:
	@echo "make setup               create .venv with PyGhidra (from your Ghidra install)"
	@echo "make baserom SRC=<file>  find and verify the stock firmware (updater .exe or raw file)"
	@echo "make check               verify baserom/firmware.bin"
	@echo "make ghidra              build the Ghidra project from config/ (first time)"
	@echo "make export              write names from Ghidra back to config/symbols.csv"
	@echo "make report              generate analysis reports in build/reports/"
	@echo "make sim                 run the stock firmware in Renode, with the OLED in a window"
	@echo "make sim-dump            run SIM_TIME virtual seconds headless and print the OLED as text"
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

report: | $(PYTHON)
	$(PYTHON) tools/ghidra/report_peripherals.py

sim: $(SVD_RENODE)
	python3 tools/baserom.py --check
	$(RENODE) -e 'include @sim/mpk.resc; showAnalyzer spi2.oled; start'

sim-dump: $(SVD_RENODE)
	python3 tools/baserom.py --check
	$(RENODE) --disable-gui --console --plain \
	  -e 'include @sim/mpk.resc; emulation RunFor "$(SIM_TIME)"; cpu PC; spi2.oled AsciiArt; quit' \
	  </dev/null 2>&1 | tr -d '\r' | grep -E '^(0x|[.#]+$$)'

rebuild: export | $(PYTHON) $(SVD)
	python3 tools/baserom.py --check
	$(PYTHON) tools/ghidra/build_project.py --force

clean:
	rm -rf build/ghidra

distclean:
	rm -rf build .venv
