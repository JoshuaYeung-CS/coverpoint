# coverpoint: one command regenerates every number the README cites.
#
# Everything is project-local: a Python venv (.venv) for cocotb, pyuvm, Yosys, SymbiYosys
# and z3, and a conda prefix (.cenv) that holds only Verilator. Nothing is installed
# globally. The venv must come before the conda prefix on PATH.
SHELL := /bin/bash
ROOT  := $(CURDIR)
PY    := $(ROOT)/.venv/bin/python
CONDA ?= $(HOME)/miniconda3/bin/conda
export PATH := $(ROOT)/.venv/bin:$(ROOT)/.cenv/bin:$(PATH)
export YOWASP_CACHE_DIR := $(ROOT)/.cache/yowasp

.PHONY: reproduce test lint tools dev confirm clean

# Re-run the whole scored experiment from the RTL up, print the tables, and exit non-zero
# if any number differs from the committed results or from a figure quoted in the docs.
reproduce: tools
	$(PY) -m harness.run reproduce --check

test: tools
	$(PY) -m pytest tests -q

lint: tools
	verilator --lint-only -Wall rtl/cp_fifo.sv rtl/cp_uart.sv --top-module cp_uart

tools: .venv/.ok .cenv/.ok
.venv/.ok: requirements.txt
	python3 -m venv .venv
	.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
	touch $@
.cenv/.ok:
	CONDA_PKGS_DIRS=$(ROOT)/.conda-pkgs $(CONDA) create -y -q -p $(ROOT)/.cenv -c conda-forge --override-channels verilator=5.052 make
	rm -rf $(ROOT)/.conda-pkgs
	touch $@

# The development sample may be re-run and looked at freely.
dev: tools
	$(PY) -m harness.run score dev

# Draws and scores the confirmatory sample. Refused until docs/prereg.json is frozen and
# everything the score depends on is committed. Anything changed afterwards is logged in
# docs/DEVIATIONS.md.
confirm: tools
	$(PY) -m harness.run score confirmatory

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -not -path './.venv/*' -not -path './.cenv/*' -prune -exec rm -rf {} +
