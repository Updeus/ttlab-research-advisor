TECTONIC ?= $(shell command -v tectonic 2>/dev/null || { test -x "$(HOME)/.local/bin/tectonic" && printf '%s' "$(HOME)/.local/bin/tectonic"; })
PYTHON ?= .venv/bin/python
PERFORMANCE_ARTIFACT ?= artifacts/phase6/performance/performance_full_results.json
PERFORMANCE_VALIDATION ?= artifacts/phase6/performance/performance_validation.json
V2_DIR := artifacts/peer_review_remediation/v2
V2_VALIDATOR := data/evaluation/validate_peer_review_remediation_v2.py

.PHONY: all thesis thesis-assets thesis-assets-frozen thesis-assets-layout thesis-layout thesis-compile thesis-word thesis-word-validate paper paper-assets paper-assets-layout paper-layout paper-compile peer-review-v2-validate evidence docs-validate benchmark benchmark-resume performance-validate reproduce reproduce-quick release clean

all: thesis paper

peer-review-v2-validate:
	@test -s "$(V2_DIR)/freeze_receipt_v2.json"
	@test -s "$(V2_DIR)/manifest_v2.json"
	@test -s "$(V2_DIR)/validation_attestation_v2.json"
	@test -s "$(V2_DIR)/manuscript_macros_v2.tex"
	PYTHONPATH=backend "$(PYTHON)" "$(V2_VALIDATOR)" --versionable-only

thesis-assets: evidence peer-review-v2-validate
	PYTHONPATH=backend "$(PYTHON)" thesis/scripts/generate_manuscript_assets.py

thesis-assets-frozen: peer-review-v2-validate
	@test -s thesis/generated/evidence_snapshot.json
	@test -s artifacts/phase1/phase1_evidence.json
	@test -s artifacts/phase2/retrieval/summary.json
	@test -s artifacts/phase3/qa/qa_faithfulness_metrics_v1.json
	@test -s artifacts/phase4/recommendation_proxy_v1/aggregate_results.json
	@test -s artifacts/phase6/performance/performance_full_results.json
	@test -s artifacts/phase6/performance/performance_validation.json
	PYTHONPATH=backend "$(PYTHON)" thesis/scripts/generate_manuscript_assets.py

thesis-assets-layout:
	PYTHONPATH=backend "$(PYTHON)" thesis/scripts/generate_manuscript_assets.py --allow-v2-not-run

thesis-layout: thesis-assets-layout thesis-compile

thesis-compile:
	@test -n "$(TECTONIC)" || { echo "tectonic is required (PATH or $$HOME/.local/bin/tectonic)"; exit 1; }
	@mkdir -p build
	cd thesis && "$(TECTONIC)" --keep-logs --keep-intermediates --outdir ../build thesis.tex
	@test -s build/thesis.pdf

thesis: thesis-assets thesis-compile

thesis-word: thesis
	"$(PYTHON)" thesis/scripts/build_word.py
	"$(PYTHON)" thesis/scripts/validate_word.py build/thesis-editable.docx

thesis-word-validate: thesis-word
	"$(PYTHON)" thesis/scripts/validate_word.py build/thesis-editable.docx --render --render-dir tmp/pdfs/thesis-word-validation

paper-assets: peer-review-v2-validate
	PYTHONPATH=backend "$(PYTHON)" paper/scripts/generate_paper_assets.py

paper-assets-layout:
	PAPER_ALLOW_MISSING_PERFORMANCE=1 PYTHONPATH=backend "$(PYTHON)" paper/scripts/generate_paper_assets.py --allow-v2-not-run

paper-layout: paper-assets-layout paper-compile

paper-compile:
	@test -n "$(TECTONIC)" || { echo "tectonic is required (PATH or $$HOME/.local/bin/tectonic)"; exit 1; }
	@mkdir -p build
	cd paper && "$(TECTONIC)" --keep-logs --keep-intermediates --outdir ../build ieee-paper.tex
	@test -s build/ieee-paper.pdf

paper: paper-assets paper-compile

evidence:
	PYTHONPATH=backend "$(PYTHON)" thesis/scripts/collect_evidence.py
	PYTHONPATH=backend "$(PYTHON)" thesis/scripts/runtime_probe.py

docs-validate:
	"$(PYTHON)" scripts/validate_documentation.py

benchmark:
	PYTHONPATH=backend "$(PYTHON)" -m app.evaluation.performance_benchmark --profile full --repetitions 3 --database data/papers.db --runtime-root . --out "$(PERFORMANCE_ARTIFACT)"
	$(MAKE) performance-validate PERFORMANCE_ARTIFACT="$(PERFORMANCE_ARTIFACT)" PYTHON="$(PYTHON)"

benchmark-resume:
	PYTHONPATH=backend "$(PYTHON)" -m app.evaluation.performance_benchmark --profile full --repetitions 3 --database data/papers.db --runtime-root . --out "$(PERFORMANCE_ARTIFACT)" --resume
	$(MAKE) performance-validate PERFORMANCE_ARTIFACT="$(PERFORMANCE_ARTIFACT)" PYTHON="$(PYTHON)"

performance-validate:
	PYTHONPATH=backend "$(PYTHON)" -m app.evaluation.performance_validator "$(PERFORMANCE_ARTIFACT)" --expected-profile full --expected-repetitions 3 --out "$(PERFORMANCE_VALIDATION)"

reproduce:
	./scripts/reproduce_all.sh --mode full

reproduce-quick:
	./scripts/reproduce_all.sh --mode quick

release:
	PYTHONPATH=backend "$(PYTHON)" -m app.reproducibility.release build --version 0.1.0-remediation

clean:
	rm -f build/thesis.aux build/thesis.bbl build/thesis.blg build/thesis.log build/thesis.out build/thesis.toc build/thesis.lof build/thesis.lot build/thesis.pdf build/thesis-editable.docx
	rm -f build/ieee-paper.aux build/ieee-paper.bbl build/ieee-paper.blg build/ieee-paper.log build/ieee-paper.out build/ieee-paper.pdf
