# Cross-document and cross-project consistency

This audit cross-checked application behavior, API contracts, the live SQLite
snapshot, index manifests, raw experiment artifacts, generated manuscript
macros, repository documentation, rendered PDFs, screenshots, and release/
reproduction claims.

## Canonical current facts

| Fact | Audited value |
|---|---|
| Current branch / commit | main / b561fa73c1de50569d7e76261b2aa37195524c21 |
| Catalogue / local PDFs / eligible papers | 134 / 98 / 96 |
| Raw / eligible chunks | 735 / 719 |
| Corpus snapshot | corpus-04a010207327069a |
| Corpus snapshot hash | 04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5 |
| Index coverage | keyword, feature hashing, dense each 719/719 |
| Feature hashing / dense dimensions | 256 / 384 |
| Dense model/revision | all-MiniLM-L6-v2 / 826711e54e001c83835913827a843d8dd0a1def9 |
| Backend tests | 255 passed, 6 warnings |
| Frontend unit / E2E | 20 / 6 passed |
| Documentation validation after audit files were staged | 44 Markdown files, 25 links |
| Paper | 8 Letter pages, 29 cited references |
| Thesis | 74 A4 pages |
| Clean exact-HEAD reproduction | failed at performance-full; 40 failed samples; no final manifest/checksums/release |

## Consistency findings

| Area | Application / raw evidence | README/docs | Thesis | IEEE paper | Audit conclusion / issue |
|---|---|---|---|---|---|
| Product identity | Multiple discovery, evaluation, review and Finder routes exist | Consistently calls it a research-intelligence platform | Consistent | Consistent | No chatbot-only scope contradiction |
| Central feature | Finder is a deterministic heuristic/template system; outputs separate facts, gap and suggestion | Finder is presented as a major student workflow | Important in aim/RQ4, but receives little interface discussion | Included but compressed into RQ4 | Centrality is consistent; validation and thesis treatment are not. FINDER-001/002, THESIS-004 |
| Evaluated revision | Current HEAD adds scheduled ingestion and UI/API work; its clean full reproduction fails | Exact-final gate is described as future acceptance | Generated base f4abb767; performance 5ccf22e; index manifests 166c6fc | Uses frozen artifacts without one paper-wide evaluated commit | Current product and evaluated artifact are not one revision. PROVENANCE-001, REPRO-003 |
| Corpus counts | Live DB and evidence snapshot agree on 134/98/96 and 719 eligible chunks | Main docs use same frozen counts | Same generated macros | Same generated macros | Numerically consistent for the frozen snapshot |
| Eligibility versus approval | 96 papers are technically eligible, but all 134 papers and all 39 topics are needs_review | Docs distinguish some review states but public API examples imply catalogue availability | Describes review boundary | Calls interface public-facing | Technical eligibility is being used as public visibility despite absent editorial approval. PUBLIC-001 |
| Missing/mismatched documents | 36 no eligible text; two suspected title/PDF mismatches; 199 Unknown sections; no corpus OCR | Limitations disclose these | Disclosed | Disclosed | Negative data-quality facts are consistent and must be retained. PDF-001 |
| Index terminology | Feature hashing is a lexical signed hashing baseline, but semantic alias maps to it | Docs generally make correct distinction | Correct distinction | Correct distinction | API terminology contradicts manuscripts. INDEX-002 |
| Retrieval values | Keyword MRR 0.947; dense 0.939; tuned hybrid 0.860; no corrected superiority | Same | Same | Same | Metrics consistent, but product defaults Search/Ask/Finder to heuristic hybrid. RAG-003 |
| Retrieval sample size | 30 development, 20 test; test includes 19 answerable and one unanswerable | Protocol explains split | Usually explicit | Dense abstract compresses denominator detail | Values are consistent; the single unanswerable is not a stable rate. EVAL-002, THESIS-005 |
| QA quality | 400 claims; support 0.995; citation correctness 0.625; coverage 0.135802; 0/4 abstention | Negative result disclosed | Disclosed | Disclosed | Numeric claims are consistent |
| Runtime grounding label | Citation verifier checks fields and aggregate lexical overlap | Docs warn that grounded is structural | Explicitly separates traceability and entailment | Explicitly separates traceability and entailment | API/UI grounded badge remains materially more affirmative than the documented construct. RAG-002 |
| QA retriever | Evaluated QA uses untuned heuristic hybrid | Evaluation docs say so | Methodology states this | Methodology states this | Consistent but explains weak end-to-end result; not evidence for best retrieval/answer pairing |
| Finder effect | Delta 0.0238, CI crosses zero; 84/84 feasibility partial | Disclosed as proxy/uncertain | Disclosed | Disclosed | Numeric interpretation is consistent |
| Finder personalization | Timeline/data/difficulty fields largely echo profile and project-type templates | User-facing docs describe tailored recommendations | Calls output evidence-calibrated | Calls it a prototype | Personalization wording is stronger than independent feasibility evidence. FINDER-001 |
| Topic results | Lexical F1 0.556, dense F1 0.521; sparse support; production topics unreviewed | Metrics/limits documented | Documented | Documented | Experimental values consistent; public editorial status is not |
| Authors | 136 rows; identity audit has unresolved/malformed entries | Identity limits documented | 13 possible pairs highlighted | 13 possible pairs highlighted | The narrow pair metric does not mean 133 other identities are approved. META-001 |
| Review events | 48 events; 21 AI-reviewed and 27 needs-reprocess | AI review explicitly distinguished | Same | Same | Counts consistent; end-to-end UI transition and effective-content contracts are not. REVIEW-001/002 |
| Student-profile persistence | Public Ask/Finder calls use persist=false; frontend keeps inputs in memory | Privacy docs claim minimization | Same | Same | Confirmed consistent positive control |
| Provider default | auto resolves to offline_extractive unless configured | Local LLM docs distinguish availability | Evaluated offline provider disclosed | Evaluated offline provider disclosed | Diagnostics hard-code Ollama as default. API-001 |
| Provider/model identity | Dense model is pinned; Ollama request model can be arbitrary mutable tag | Docs stress provenance | Model boundary discussed | Model boundary discussed | Runtime generative-provider reproducibility is weaker than index provenance. LLM-001 |
| Performance | 17 stages, 102 samples, zero failures at 5ccf22e; clean b561fa7 run records 40 database/index-status failures | Correctly says not scale evidence | Reports the old run | Reports the old run | Old result is internally consistent but stale; exact-current closure fails. REPRO-003 |
| External sanity | Three CC BY JATS/XML articles, three fixed lexical top-one checks | Clearly scoped | Same | Same | Consistent; not PDF/cross-domain effectiveness |
| Test counts | Live: backend 255; frontend 20/6 | docs/FINAL_STATUS.md says 249 and 19/6; docs count 37/23 | Refers readers to status | Does not rely on exact current test count | Documentation is stale. DOC-001 |
| Engineering versus effectiveness | Tests/builds pass | Docs usually state distinction | Explicit | Explicit | Consistent positive control; do not turn test counts into scientific claims |
| Paper page count | PDF has 8 pages | README and reproducibility docs candidly say 8 | Not material | Validator accepts 6-8 | Hard requirement is at most 6; local PASS is false assurance. PAPER-001, VALIDATE-001 |
| Paper references | 29 cited entries; shared bibliography has 32 | No approximate-20 gate | Shared 32-entry bibliography is appropriate for thesis | Page 8 is mostly references | Fails requested paper target; thesis bibliography need not be reduced. PAPER-001 |
| Thesis page count | PDF has 74 pages | README/repro docs say 74 | Validator accepts 40-500 | Not material | Hard requirement is at least 75 substantive pages; local PASS is false assurance. THESIS-001, VALIDATE-001 |
| PDF accessibility | Both PDFs untagged | Thesis evidence discloses untagged status | Does not claim PDF/UA | Does not claim PDF/UA | Consistent limitation; rendered screenshot legibility still weak. PDFDOC-001 |
| IEEE PDF profile | Paper has outlines and link annotations | External venue check remains open | Not material | Generic IEEEtran build | Current generic IEEE Xplore guidance expects no bookmarks/links; target venue remains human decision. PAPER-003, SUBMISSION-001 |
| Reproduction completion | Clean exact-HEAD attempt reaches performance-full, then 40 probes fail because both index builds suppress DB status updates; no final manifest/checksums follow | Docs explicitly require exact-candidate output | Appendix cites reproduction manifest and conclusion says reproducible | Says clean-commit full reproduction passed | Current execution contradicts completion claims. REPRO-001, REPRO-003 |
| Release | Old bundle/release validation exists for d0d84aa | Final exact release described as gate | Claims sanitized release | Claims sanitized release | A verified old bundle is not the current release candidate. REPRO-001 |
| Database hash | Raw live DB SHA-256 dc33ad9c...; canonical SQLite backup can hash differently; Phase 1 records an earlier stage hash | Multiple stages documented | Snapshot ID/hash is the scientific identity | Snapshot ID/hash is used | Different file hashes are not automatically contradictions; stage and canonicalization must be stated |
| Rights/authorization | Source PDFs excluded from release; public API can expose metadata/snippets | Correctly denies blanket rights | Correctly denies ethics/blanket rights | Correctly denies ethics/blanket rights | Wording is cautious, but formal rights/controller decisions remain absent. RIGHTS-001 |
| Human review | No recruited participants or independent human assessors | Correctly disclosed | Correctly disclosed | Correctly disclosed | Consistent; AI-assisted audit/review must not be called human peer review |
| Security/deployment | Strong local guards; remaining DNS/parser/concurrency/rate risks | Docs call production controls external | Bounded claims | Bounded claims | Manuscript wording is mostly consistent; public deployment is not approved. SECURITY-001, OPS-001, RATE-001 |

## Current-versus-frozen provenance map

| Artifact | Revision recorded | Relationship to current HEAD |
|---|---|---|
| Current checkout | b561fa73c1de50569d7e76261b2aa37195524c21 | source of truth for this audit |
| Thesis generated evidence base | f4abb767018f9db13a2a9ac5bee1e6f6fca3428e | older |
| Performance artifact | 5ccf22ec39cb33bf179cdff6954bfc9e0ce8dbc4 | older |
| Tracked feature-hashing/dense manifests | 166c6fc45befa0a2847b320328042ab861a34e9d | older |
| Phase 1 evidence execution | 1f31dc16879df4c03dbe7e8ae82159d731af1b35 plus dirty tree | older and not clean |
| QA feature-hashing run | d7a4764... plus working_tree_dirty=true | older and dirty |
| QA heuristic-hybrid run | 7cd80c0... plus working_tree_dirty=true | older and dirty |
| Existing baseline release | d0d84aa... | older |
| Audit clean full run | b561fa73c1de50569d7e76261b2aa37195524c21, clean | current, but failed at performance-full before final provenance/release |

File-level hashes preserve valuable provenance even when the worktree was dirty,
but they do not by themselves reconstruct every untracked dependency or establish
that current HEAD is the evaluated artifact.

## Statements that are consistent and should be protected

- Feature hashing is not learned semantic retrieval.
- Source traceability is not factual correctness or entailment.
- AI-reviewed silver/proxy evidence is not human review.
- The negative hybrid, citation, coverage, abstention, and Finder results are
  genuine findings, not defects to hide from the manuscripts.
- TTLAB authorization is not university ethics approval and not blanket
  third-party redistribution permission.
- Build/test counts are engineering evidence, not effectiveness evidence.
- The current system is a recommendation prototype, not a validated academic
  advisor.
