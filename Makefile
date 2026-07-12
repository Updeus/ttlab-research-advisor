TECTONIC ?= $(shell command -v tectonic 2>/dev/null || { test -x "$(HOME)/.local/bin/tectonic" && printf '%s' "$(HOME)/.local/bin/tectonic"; })

.PHONY: all thesis paper evidence clean

all: thesis paper

thesis:
	@test -n "$(TECTONIC)" || { echo "tectonic is required (PATH or $$HOME/.local/bin/tectonic)"; exit 1; }
	@mkdir -p build
	cd thesis && "$(TECTONIC)" --keep-logs --keep-intermediates --outdir ../build thesis.tex
	@test -s build/thesis.pdf

paper:
	@test -n "$(TECTONIC)" || { echo "tectonic is required (PATH or $$HOME/.local/bin/tectonic)"; exit 1; }
	@mkdir -p build
	cd paper && "$(TECTONIC)" --keep-logs --keep-intermediates --outdir ../build ieee-paper.tex
	@test -s build/ieee-paper.pdf

evidence:
	PYTHONPATH=backend .venv/bin/python thesis/scripts/collect_evidence.py
	PYTHONPATH=backend .venv/bin/python thesis/scripts/runtime_probe.py

clean:
	rm -f build/thesis.aux build/thesis.bbl build/thesis.blg build/thesis.log build/thesis.out build/thesis.toc build/thesis.lof build/thesis.lot build/thesis.pdf
	rm -f build/ieee-paper.aux build/ieee-paper.bbl build/ieee-paper.blg build/ieee-paper.log build/ieee-paper.out build/ieee-paper.pdf
