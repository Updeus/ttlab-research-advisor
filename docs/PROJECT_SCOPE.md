# Project Scope

## Product and research scope

The TTLAB Research Intelligence Platform is a bounded, local-first MSc research
artefact for a single laboratory publication corpus. It supports full-text
discovery, source-traceable question answering, publication-derived topic/
author exploration, structured extension suggestions, generated paper-
intelligence drafts, administrative review, and offline evaluation.

The executed study evaluates the artefact as an engineering case study. It does
not claim human advisory effectiveness, a novel retrieval algorithm, exhaustive
archive coverage, general scholarly-search performance, or production-scale
deployment.

## Included capabilities

- archive discovery and idempotent seed import;
- allowlisted PDF acquisition, identity checks, page extraction, scan
  diagnostics, optional OCR, and conservative section-aware chunking;
- explicit corpus eligibility and authoritative keyword/feature-hashing/dense
  index manifests;
- keyword, deterministic feature-hashing, pinned learned-dense, and hybrid
  retrieval;
- Search and transient Ask TTLAB with paper/chunk/page evidence;
- evidence-only and full Thesis Extension Finder modes with fact, gap, and
  suggestion separation;
- cited public/technical summaries, methods, contributions, limitations, future
  work, extension/skills/evaluation-plan bundles, and text-only podcast scripts;
- controlled Topic/Author Explorer and explainable related-paper links;
- route-based responsive frontend and evidence/freshness/error/review states;
- role-protected admin review and attributable append-only audit events;
- AI-reviewed silver/proxy evaluations for sections, retrieval, QA,
  recommendations, topics/authors, and stored generated outputs; and
- performance/reproduction/release, security/privacy, and document-build
  tooling.

The frozen experimental boundary contains 96 eligible papers and 719 eligible
chunks from 134 catalogue records. Thirty-six no-text records and two
metadata/PDF mismatches are visible but excluded from corpus-dependent
experiments.

## Deliberate design boundaries

- Public Ask questions and student profiles are transient by default; there is
  no public opt-in history endpoint.
- Local/offline providers are supported. External providers are an explicit
  allowlist/privacy decision and are not required for the artefact.
- The product offers a loopback-only insecure demo bypass, but production
  requires explicit bearer actors and fail-closed security configuration.
- Topic/author evidence is limited to eligible indexed publications and does
  not claim availability, endorsement, supervision, or expertise outside the
  corpus.
- A podcast is a cited text script. Audio generation is not included.
- Related-paper and thesis-extension outputs are navigation/suggestion aids,
  not novelty or feasibility guarantees.
- OCR is optional; the frozen corpus records no OCR-processed pages, so OCR
  quality/performance is not evaluated.
- The sanitized release excludes PDFs, substantial extracted text, SQLite
  databases, runtime indexes, private prompts/histories, and secrets.

## Research evaluation boundary

The study uses one AI reviewer in two-pass source-inspection procedures and
labels the resulting data silver/proxy evidence. It includes development/test
separation, correct retrieval metrics, confidence intervals, paired tests,
ablations, sensitivity, and failure taxonomies. It does not recruit
participants or report human usability, satisfaction, usefulness, or
supervisor approval.

## Remaining work versus future work

Remaining local remediation gates are part of the current delivery: full
performance execution, full reproduction, final current-commit release/tag,
paper/thesis synchronization, and complete PDF/route verification.

Potential future extensions outside the current evidence include:

- an institutionally approved human study;
- institution-managed identity, retention, monitoring, correction, and incident
  processes for public deployment;
- broader multi-laboratory/cross-domain evaluation;
- OCR accuracy evaluation on a licensed scanned-document set;
- audio/TTS generation after script review; and
- production load/capacity testing.

See `docs/METHODOLOGY.md` and `docs/FINAL_STATUS.md` for the executed study and
current closure state.
