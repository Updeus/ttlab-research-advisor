# Cross-document and cross-project consistency

This final cross-check compares application behavior, API/data contracts, the
frozen technical corpus, historical and prospective experiment artifacts,
generated manuscript macros, repository documentation, screenshots, and the
rendered manuscripts. It preserves revision boundaries: an older valid
measurement is not silently relabeled as a measurement of the delivery branch.

## Canonical facts

| Fact | Final audited value and boundary |
|---|---|
| Delivery branch | `codex/peer-review-remediation`; later than the v2 evaluated source. The final exact delivery commit belongs in `FINAL_READINESS_REPORT.md`, because final documentation commits follow evaluation. |
| Prospective v2 source | `0d4b9bdcb657034beab5c288ab174983eb0760e3` |
| V2 manifest / validation attestation | SHA-256 `bdc8e8b289d36834479f7bcc1c2efc9857b9812171dd3d4df7f2bff6680e18d9` / `f6d320bc246666bd19e7c6642c49e40b53d3acb3b52a789599e1eb3a290f34b7` |
| V2 package inventory | 17 versionable files. The manifest separately records and hashes three rights-sensitive full-raw files retained locally and excluded from version control/release. |
| Audit-baseline evidence | Commit `b561fa73c1de50569d7e76261b2aa37195524c21`; snapshot `corpus-04a010207327069a`, SHA-256 `04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5`; retained, not presented as current manuscript evidence |
| Post-remediation v1-form evidence | Source `73092e48f173b74f726659bd5b98224545ac23bb`; snapshot `corpus-f4638c633bea82b0`; this is the v1-form evidence consumed by the final manuscripts |
| Historical performance source | `73092e48f173b74f726659bd5b98224545ac23bb`; 17 stages, 102 samples, zero recorded failures; CPU-only, concurrency one, single WSL2 host |
| Catalogue / PDFs / eligible papers | 134 / 98 / 96; 36 catalogue records have no eligible full text |
| Raw / eligible chunks | 735 / 719; 199 eligible chunks have `Unknown` section |
| Suspected PDF/title mismatches | 2, excluded from the technical corpus |
| Corpus snapshot | `corpus-f4638c633bea82b0`; 719 eligible technical chunks |
| Index coverage | Keyword, 256-dimensional feature hashing, and pinned 384-dimensional learned dense each cover 719/719 eligible chunks |
| Public projection | Empty at the audited governance capture: zero searchable papers/chunks. V2 used technical scope and explicitly did not exercise or validate the public projection. |
| Post-remediation v1-form QA | 50 cases; strict coverage 11/81 = 0.135802; citation correctness 218/334 = 0.652695; unanswerable abstention 1/4 = 0.25 |
| Prospective v2 QA held-out | 12 cases; strict coverage 3/16 = 0.1875; exact-locator precision 1/11 = 0.090909; citation completeness 0.846154; false-positive rate 4/4 = 1.0; abstention 0 |
| Prospective v2 Finder held-out | Five profiles; evidence-only/full Hit@3 1.0/0.8 (delta -0.2, 95% cluster CI [-0.6, 0]); MRR 0.666667/0.6 (delta -0.066667) |
| Prospective v2 topics held-out | Eight positive-only cases; known-positive recall 9/12 = 0.75; case coverage 0.625; 9/18 predictions unadjudicated and not classifiable as false positives |
| Prospective v2 OCR | One deterministic synthetic raster fixture; CER/WER 0 and exact repeated output; not a TTLAB-corpus OCR estimate |
| Frontend verification | 67 tests passed; production build passed; 9 E2E scenarios passed. These are engineering evidence, not effectiveness. |
| Backend verification | 407/407 collected tests passed across 43 files in eight 60-second-bounded shards; zero failures, errors, or skips; 168.16 s summed pytest runtime. |
| IEEE paper | 6 Letter pages including references; 21 cited bibliography entries |
| Thesis | 88 A4 pages; 38 bibliography entries |
| PDF accessibility | Both rendered PDFs report `Tagged: no`; neither manuscript claims PDF/UA or WCAG conformance |

## Revision and artifact map

| Artifact or claim surface | Bound revision | Relationship to delivery branch |
|---|---|---|
| Audit-baseline Phase 1--4 evidence | `b561fa73...`; `corpus-04a...` | Preserved in the audit and dated evidence log; its old QA/Finder values are not presented as current manuscript measurements |
| Post-remediation v1-form evidence | `73092e48...`; `corpus-f463...` | Historical relative to delivery/v2, but the exact v1-form artifact layer consumed by the final manuscripts |
| Historical full performance profile | `73092e48...` | Valid historical engineering profile only |
| Prospective v2 QA/Finder/topic/OCR package | `0d4b9bd...` | Prospectively evaluated implementation source; later delivery edits are packaging, manuscript, validation, and reporting work unless a new evaluation says otherwise |
| V2 final package | Manifest `bdc8e8b...`; attestation `f6d320bc...` | Frozen validated package; packaging recovery did not reexecute cases, alter labels, or rescore metrics |
| Governance screenshots | Clean commit `9a274b82...`; manifest tree `11cd8c5f...` | Historical/delimited implementation captures. `finder-public-projection-empty.png` and `admin-governance-shell-current.png` must not be described as current-delivery captures |
| Final PDFs and validation | Delivery branch after `0d4b9bd...` | Current presentation/verification artifacts; they consume frozen generated evidence without changing its evaluated source identity |

The screenshot boundary is especially important. The governance manifest records
zero searchable papers and chunks, zero mutation requests, empty browser
storage, and aggregate-only Admin content at commit `9a274b82...`. Other older
route screenshots remain historical/manual captures unless a separate manifest
proves otherwise. Screenshots are implementation evidence, not user-study,
evaluation, human-review, or public-approval evidence.

## Consistency findings

| Area | Application/raw evidence | Documentation and manuscripts | Final consistency conclusion |
|---|---|---|---|
| Product identity | Dashboard, papers, search, Ask, Finder, explorer, evaluation, and review surfaces exist | README, thesis, and paper consistently call it a research-intelligence platform | Consistent; the project is not reduced to a chatbot |
| Central feature | Finder ranks evidence-bearing papers and separates fact, stated future work, inferred gap, and suggestion | Both manuscripts foreground Finder and retain its limitations | Consistent implementation boundary; no validated-advisor claim |
| Technical versus public scope | 96 papers/719 chunks are technically eligible; public projection is empty | Thesis/paper explicitly state that technical eligibility is not publication approval and v2 is not public behavior | Consistent fail-closed boundary; human approval and rights clearance remain external |
| Corpus counts | 134 records, 98 PDFs, 96 eligible papers, 735 raw/719 eligible chunks, two mismatches, 199 unknown sections | Generated macros populate both manuscripts from repository evidence | Numerically consistent; negative data-quality counts are retained |
| Index terminology | 256-dimensional feature hashing is lexical; 384-dimensional MiniLM is learned dense | Code/UI/docs/manuscripts distinguish the two | Consistent; feature hashing is not mislabeled as learned semantic retrieval |
| Index integrity | Authoritative indexes cover 719/719 and validate snapshot/configuration/source identity | Both manuscripts describe fail-loud stale/partial/mismatch behavior | Consistent technical invariant; it does not establish retrieval effectiveness |
| Audit-baseline revision | Snapshot `corpus-04a...` recorded 400 QA claims, correctness 0.625, utilisation 0.592, 0/4 abstention, and an 84/84 conditional Finder comparison | Audit files retain these values; current-facing documents identify them as superseded audit-baseline evidence | Consistent historical preservation; these values are not silently substituted for the later reexecution |
| Post-remediation v1-form retrieval | Keyword has highest test point estimates; no corrected tuned-hybrid superiority; all modes answer one unanswerable query | Negative/null result retained in thesis and paper | Consistent and appropriately bounded to the small AI-silver set and source `73092e48...` |
| Post-remediation v1-form QA | Coverage 0.135802 (11/81), citation correctness 0.652695, unanswerable abstention 1/4 | Both manuscripts use generated macros and distinguish support, correctness, completeness, and abstention | Consistent negative/mixed result on `corpus-f463...` |
| Prospective QA | Held-out coverage 0.1875, locator precision 0.090909, completeness 0.846154, false-positive rate 1.0, abstention 0 | Both manuscripts label v1/v2 comparison descriptive and non-paired | Consistent. It is permissible to say 0.1875 is numerically higher; it is not permissible to claim a demonstrated improvement over 0.135802 |
| Citation meaning | Exact locator metric checks frozen source identity; historical correctness is an AI-silver claim-to-link judgment | Both manuscripts state that locator presence does not establish entailment/factual correctness | Consistent calibrated boundary |
| Finder | Evidence-only test Hit@3 1.0; full Finder 0.8; delta -0.2 with interval ending at zero | Paper/thesis report the sign and retain negative/null evidence | Consistent negative result; no usefulness, novelty, feasibility, or supervisor-fit inference |
| Topics | V2 labels are known-positive and non-exhaustive; half of predictions are unadjudicated | Manuscripts report recall/coverage, not v2 precision/F1 | Consistent. Unadjudicated predictions are not false positives |
| OCR | CER/WER 0 comes from one generated raster fixture with exact repeatability | Manuscripts call it a fixture/pipeline exercise | Consistent; no scanned-corpus prevalence or corpus OCR-quality claim |
| Authors | Identity links are publication-derived; possible merges remain unresolved | Manuscripts deny expertise, endorsement, availability, and author validation | Consistent conservative identity boundary |
| Generated review | AI events are attributed, append-only, hash chained, and cannot create human approval | Both manuscripts say AI review is not human review | Consistent governance boundary |
| Student-profile privacy | Public Ask/Finder profiles are transient/non-persistent by default | Docs and manuscripts state minimization | Consistent engineering control; not a formal privacy certification |
| Provider/model provenance | Dense revision is pinned; v2 provider boundary is recorded | Manuscripts disclose model/provider/revision limits | Consistent; optional provider availability is not invented |
| Performance | Historical source `73092e48...` records 17 stages/102 successful samples on CPU | Paper/thesis explicitly call it historical, single-host, concurrency-one evidence | Consistent; no production capacity or GPU claim |
| Public screenshot | Manifested at `9a274b82...`, public projection empty | Thesis evidence text discloses the historical capture boundary | Consistent only when caption/prose retains that commit boundary |
| Engineering verification | Frontend 67 tests/build/9 E2E; backend 407/407 across eight bounded shards | Manuscripts do not turn counts into scientific effectiveness | Consistent engineering evidence; no effectiveness claim follows |
| Paper length/references | Built PDF is 6 Letter pages; BBL has 21 entries | Paper validator and final report use the same counts | Meets the stated at-most-six-page and approximate-20-reference constraints without a quality inference |
| Thesis length/references | Built PDF is 88 A4 pages; BBL has 38 entries | Thesis validator/final report use the same counts | Meets the at-least-75-page constraint; page count alone is not substantive-quality evidence |
| PDF metadata/accessibility | Titles/authors/subjects/keywords are populated; both PDFs are untagged | Sources include figure descriptions and explicitly deny PDF/UA/WCAG conformance | Consistent limitation; venue-specific tagged-PDF remediation remains external/toolchain-dependent |
| V2 package/reproduction | 17 versionable files validate against manifest/attestation; three rights-sensitive full-raw files remain restricted | Availability text excludes restricted content and requires lawful local access for exact full-corpus reruns | Consistent reproducibility/rights boundary |
| TTLAB authorization | Project/corpus use is authorized; no participants or institution approval record exists | Both manuscripts deny ethics approval/exemption and blanket redistribution rights | Consistent conservative wording; submission/rights decisions remain human-required |
| Security/deployment | Local guards and authenticated mutation boundaries exist; rate, operational, and public-deployment controls remain external | Manuscripts narrow deployment claims | Consistent; no production/security certification |

## Cross-document statements that must remain identical

- Feature hashing is a lexical signed-hashing baseline, not learned semantic
  retrieval.
- Source traceability is not factual correctness or entailment.
- AI-reviewed silver/proxy evidence is not human review or human gold labels.
- Historical QA coverage is 11/81 (0.135802), citation correctness is 0.652695,
  and unanswerable abstention is 1/4.
- Prospective held-out coverage is 3/16 (0.1875) on distinct, non-paired cases;
  no improvement claim follows.
- Prospective exact-locator precision is 0.090909, citation completeness is
  0.846154, false-positive rate is 1.0, and abstention is zero.
- The prospective Finder comparison is adverse to full mode, not evidence that
  suggestions improve ranking.
- Positive-only topic labels do not support precision/F1; the OCR result is
  fixture-only.
- Technical evaluation did not exercise the empty public projection.
- TTLAB authorization is not university ethics approval and not blanket
  third-party redistribution permission.
- Build/test/page/count evidence is engineering evidence, not scientific
  effectiveness.
- The system is a research-intelligence and recommendation prototype, not a
  validated academic advisor.

## Remaining external boundaries

The repository cannot resolve final third-party rights decisions, author/identity
confirmation, institutional/venue approval, human usefulness, supervisor fit,
production deployment approval, or tagged-PDF/venue acceptance. Those limits
must remain visible rather than being converted into unsupported claims.
