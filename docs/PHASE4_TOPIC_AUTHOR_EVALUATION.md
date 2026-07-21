# Phase 4.2 Topic and Author Evaluation

> **Archived Phase 4 execution record.** This report remains bound to the
> original Phase 1 snapshot `corpus-04a010207327069a`. Its labels and metrics
> are preserved rather than silently relabelled as current. Post-remediation
> manuscript evidence uses the separately executed v1-form artifacts at commit
> `73092e48f173b74f726659bd5b98224545ac23bb` and snapshot
> `corpus-f4638c633bea82b0`; see
> `docs/peer_review_readiness/FINAL_READINESS_REPORT.md`.

## Evidence boundary

This report evaluates the controlled topic vocabulary and publication-derived
author-topic links on the frozen Phase 1 corpus: 96 eligible papers and 719
eligible chunks (`corpus-04a010207327069a`). It does not evaluate the 36
catalogue-only records or the two excluded PDF/metadata mismatches. The run was
performed on a disposable byte copy of SQLite; the live database was not
changed while the recommendation experiment was active.

The labels are an **AI-reviewed silver set**, not human gold labels. One Codex
AI reviewer inspected title and source passages in two fixed-seed shuffled
passes. The passes agreed exactly on 50/60 cases (0.8333); this is a
same-reviewer consistency diagnostic, not inter-rater reliability. No author,
student, supervisor, or independent human validated these judgments.

## Silver design

The 60 unique eligible papers comprise 36 development and 24 held-out test
cases: 51 multi-label, five single-label, and four `other/unknown`. Every one of
the 39 controlled labels has at least one source-backed case, although many rare
labels have support of one and therefore very wide uncertainty intervals.
Persisted source snippets are at most 483 characters and retain paper, chunk,
page, section, and source-hash locators. Generated summaries and recommendations
are not label evidence.

The operational rule is conservative: a label denotes a principal problem,
method, or application supported by the title or primary publication passage.
Incidental background, terms in references, and cited-work vocabulary do not
qualify. `other/unknown` is a valid outcome when the vocabulary does not cover
the principal subject.

## Executed comparison

The fixed lexical system was compared with a reproducible learned alternative.
The alternative averages the pinned `all-MiniLM-L6-v2` vectors for bounded
primary-source chunks and compares that centroid with embeddings of the fixed
label prototypes. It uses model revision
`826711e54e001c83835913827a843d8dd0a1def9` and the checksummed Phase 1 dense
index. A cosine threshold of 0.20 and cap of six labels were selected only by
development-set micro-F1; test labels were not used for selection.

Held-out results are:

| Method | Micro precision | Micro recall | Micro F1 | Macro F1* | Coverage | Exact match |
|---|---:|---:|---:|---:|---:|---:|
| Controlled lexical | 0.6522 | 0.4839 | 0.5556 | 0.5928 | 0.8750 | 0.0833 |
| Dense prototype | 0.4175 | 0.6935 | 0.5212 | 0.5812 | 0.9583 | 0.0833 |

\* Macro metrics average the 26 labels supported in the held-out split; the
machine-readable output also reports all-vocabulary macro metrics and every
per-label confusion count.

Fixed-seed, 2,000-resample paper-level bootstrap 95% intervals were:

| Method | Micro precision | Micro recall | Micro F1 | Macro F1 | Coverage |
|---|---|---|---|---|---|
| Controlled lexical | [0.4894, 0.8108] | [0.3559, 0.6140] | [0.4200, 0.6852] | [0.4452, 0.6743] | [0.7490, 1.0000] |
| Dense prototype | [0.3069, 0.5455] | [0.5373, 0.8406] | [0.3926, 0.6375] | [0.4858, 0.7271] | [0.8750, 1.0000] |

The dense alternative improves recall and coverage but produces substantially
lower precision. The controlled lexical vocabulary therefore remains the
public author-topic evidence path: its links are directly inspectable and its
held-out precision is higher. The dense method may be useful later as a
review-candidate generator, but these results do not justify publishing its
labels automatically. Neither method supports a claim of comprehensive or
human-validated topic classification.

The retained error taxonomy distinguishes lexical gaps or insufficient repeat
evidence, ambiguous lexemes/incidental primary-section matches, controlled-
vocabulary boundaries, dense prototype semantic overreach, and dense threshold
or rank-cap misses. The held-out lexical system is notably weak on `ai`,
`natural language processing`, `networks`, and `other/unknown`; these outputs
must continue to display review state rather than imply completeness.

## Author identity and publication-topic audit

The disposable rebuild created 170 eligible paper-topic links and 313
publication-derived author-topic links. The all-record audit found:

- 133 active canonical rows, of which 109 have at least one eligible indexed
  publication;
- zero normalized-alias collisions;
- zero topic links or author evidence passages from excluded/non-eligible
  papers;
- zero author-topic evidence links that conflict with canonical authorship;
- zero positive availability, endorsement, supervisor-suitability, or broad
  expertise claims in the audited author output wording; and
- 13 possible same-person name pairs retained for external identity review
  rather than guessed merges.

All 133 active identities remain `unresolved` in institutional-review terms.
Examples needing authoritative confirmation include `Patrick Hosein` versus
`P. Hosein`, `Inzamam Rahaman` versus `I.Rahaman`, and several initial/full-name
variants. Consequently, canonicalization here means safe exact-normalized
identity routing, not externally verified identity resolution.

Author summaries now state only that a person is listed on eligible
publications whose controlled labels include particular topics. They explicitly
state that this bibliographic evidence does not establish broader expertise,
current availability, endorsement, or suitability for supervision or
collaboration.

## Reproduction

```bash
PYTHONPATH=backend .venv/bin/python \
  data/evaluation/build_topic_author_silver_v1.py
PYTHONPATH=backend .venv/bin/python \
  data/evaluation/validate_topic_author_silver_v1.py
PYTHONPATH=backend .venv/bin/python \
  -m app.evaluation.topic_author_eval
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_topic_explorer.py \
  backend/tests/test_topic_author_eval.py -q
```

Raw labels, source locators, both review passes, predictions, scores, per-label
metrics, confidence intervals, error records, author audit records, runtime
versions, model/index hashes, code hashes, and corpus hash are stored under
`data/evaluation/topic_author_silver_v1*` and
`artifacts/phase4/topic_author/`.
