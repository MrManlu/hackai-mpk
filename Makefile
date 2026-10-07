# hackai-mpk: reproducible analysis of the AKAI MPK Mini Plus firmware.
# Run `make help` for the list of targets.

GHIDRA_INSTALL_DIR ?= /opt/ghidra_11.3.1_PUBLIC
export GHIDRA_INSTALL_DIR

PYTHON  := .venv/bin/python
SVD     := build/svd/AT32F415xx_v2.svd
SVD_URL := $(shell sed -n 's/^url = "\(.*\)"/\1/p' config/segments.toml)
SVD_SHA := $(shell sed -n 's/^sha256 = "\(.*\)"/\1/p' config/segments.toml)
BASEROM := baserom/firmware.bin
PROJECT := build/ghidra/hackai-mpk.gpr

.PHONY: help setup baserom check ghidra rebuild export clean distclean

help:
	@echo "make setup               create .venv with PyGhidra (from your Ghidra install)"
	@echo "make baserom SRC=<file>  find and verify the stock firmware (updater .exe or raw file)"
	@echo "make check               verify baserom/firmware.bin"
	@echo "make ghidra              build the Ghidra project from config/ (first time)"
	@echo "make export              write names from Ghidra back to config/symbols.csv"
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

$(PROJECT): | $(PYTHON) $(SVD)
	python3 tools/baserom.py --check
	$(PYTHON) tools/ghidra/build_project.py

ghidra: $(PROJECT)

export: | $(PYTHON)
	$(PYTHON) tools/ghidra/export_symbols.py

rebuild: export | $(PYTHON) $(SVD)
	python3 tools/baserom.py --check
	$(PYTHON) tools/ghidra/build_project.py --force

clean:
	rm -rf build/ghidra

distclean:
	rm -rf build .venv
