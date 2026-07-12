# Author Review Checklist

This checklist identifies every important item that cannot be established from the repository. Replace the corresponding `AUTHOR INPUT REQUIRED` text in the LaTeX sources only after confirmation. Do not treat an unchecked item as approved.

## Submission and authorship

- [x] Student name confirmed as Jarod Esareesingh.
- [ ] Confirm student ID.
- [x] Department confirmed as Department of Computing & Information Technology.
- [x] University confirmed as The University of the West Indies.
- [x] Country confirmed as Trinidad and Tobago; no city is included.
- [x] Email confirmed as `jarod.esareesingh@my.uwi.edu`.
- [ ] Confirm degree/programme title, supervisor, and submission month/year.
- [ ] Supply the university-approved declaration, copyright wording, and acknowledgements.
- [ ] Confirm the official laboratory name and the expansion/capitalization of TTLAB. The request says “Light Hitty Lab/TTLab,” while the repository consistently uses TTLAB; the thesis does not resolve this discrepancy.
- [ ] Confirm that the repository implementation and commit history may be presented as the student's MSc work.
- [ ] Supply the required disclosure of Codex/LLM-assisted coding, analysis, figure preparation, literature discovery, and writing under university policy.

## Research framing

- [ ] Confirm the title and subtitle in `thesis/metadata.tex`.
- [ ] Confirm the artefact-oriented engineering case-study/design-science methodology wording.
- [ ] Confirm the aim, six objectives, and five research questions in Chapters 1 and 3.
- [ ] Decide whether any untested propositions should become formal hypotheses. They cannot be reported as tested in the present snapshot.
- [ ] Confirm that the contribution is integration, traceability, and reproducible characterization—not a novel retrieval algorithm or demonstrated effectiveness.

## Corpus and permissions

- [ ] Confirm the discovery/collection date and whether 134 records form an exhaustive, date-bounded TTLAB archive snapshot.
- [ ] Confirm authorization and copyright/licensing basis for downloading, retaining, processing, and showing snippets from the 98 PDFs.
- [ ] Decide whether the thesis/release may include the ignored database and derived corpus files or only their hashes and aggregate evidence.
- [ ] Confirm whether malformed author records, including `Click to View`, should be corrected before submission and regenerate all affected evidence if so.

## Evaluation and claims

- [ ] Approve and populate gold retrieval questions and relevant paper IDs.
- [ ] Approve QA answer points and claim–citation correctness labels.
- [ ] Approve topic and author identity/expertise review samples.
- [ ] Approve recommendation review criteria: relevance, novelty, feasibility, source fidelity, usefulness, risk, and evaluation-plan quality.
- [ ] Approve summary/podcast-script review criteria.
- [ ] Define assessors/participants, sample-size rationale, recruitment, consent, training, anonymity, adjudication, and statistical analysis.
- [ ] Decide whether empirical experiments will be completed before submission. If not, retain the thesis's current technical-characterization claims and do not add effectiveness language.
- [ ] Do not claim Recall@3, Recall@5, MRR, faithfulness, usefulness, recommendation accuracy, topic quality, or user satisfaction from the current placeholder/not-run files.
- [ ] Do not interpret database `grounded` as factual correctness; it is a structural and lexical citation check.
- [ ] Do not describe the 256-dimensional feature-hashing index as a learned semantic embedding.
- [ ] Do not claim current Ollama benchmark performance; the service was unavailable and no benchmark result file exists.

## Ethics, privacy, and responsible AI

- [ ] State ethics approval number, approval date, or formal exemption and issuing body.
- [ ] Supply participant information/consent materials if a human study is approved.
- [ ] Define retention, deletion, access, and lawful-basis decisions for student interests, skills, and constraints.
- [ ] Define public correction/appeal procedures for author identities, expertise links, summaries, and recommendations.
- [ ] Confirm whether public deployment is in scope. If yes, specify authentication, authorization, security, privacy, accessibility, logging, and incident-response requirements.

## Final factual review

- [ ] Review every highlighted `AUTHOR INPUT REQUIRED` occurrence in the compiled thesis and paper.
- [ ] Verify the baseline paper title, authors, venue, page range, year, and DOI in `thesis/references.bib`.
- [ ] Review all figures and screenshots for sensitive information and accuracy.
- [ ] Re-run `thesis/scripts/collect_evidence.py` and both builds after any database, corpus, index, or application change; update all affected counts and hashes.
- [ ] Proofread institution-specific spelling conventions and obtain supervisor approval for the final claims.
