# Ethics, Authorization, Governance, and AI-Assistance Disclosure

## Study boundary

This remediation is an artefact-oriented software engineering case study with
controlled offline experiments over a laboratory publication corpus. It does
not recruit participants, solicit student/supervisor ratings, or report human
usability, satisfaction, usefulness, or advisory validation. Evaluation labels
and formative judgments prepared in this work identify the reviewer as
`codex-ai-review`, set `reviewer_type=ai`, and are described as AI-assisted
silver labels or proxy review rather than human gold labels.

No research-ethics-board/REC/IRB approval or exemption record is present in the
repository. The work therefore makes no approval or exemption claim. If a later
human-participant study is proposed, recruitment, consent, data management,
sample-size rationale, reviewer training, adjudication, and institutional
approval/exemption must precede data collection.

## Project and corpus authorization

The user has stated that TTLAB explicitly authorized the project and use of the
laboratory corpus. This supports undertaking the project and processing the
corpus for the stated research-engineering purpose. It does not by itself
establish:

- copyright ownership of third-party publications;
- permission to redistribute every PDF or substantial extracted text;
- REC/IRB approval or exemption;
- institutional approval of a public deployment;
- endorsement by an author, supervisor, or The University of the West Indies;
  or
- a right to infer sensitive or current facts about an author.

The public API fails closed: technical corpus eligibility does not imply
publication eligibility. Anonymous paper, search, topic, author, snippet, and
generated-artifact projections require an explicit public publication decision
plus source-access and rights states that permit the projection. Unresolved
records remain available only to the protected technical/review workflow.

The sanitized release applies a separate tracked-file allowlist, field
sanitization, and payload scan. It excludes local PDFs, the runtime database, interface
screenshots, private histories, secrets, model caches, and unlicensed full
text. Catalogue metadata, source hashes, bounded evidence summaries, schemas,
AI-reviewed silver labels, raw experimental rankings/judgments, and aggregate
results are included only to the extent supported by the repository's release
review. That technical sanitizer does not consult the runtime publication
ledger and is not evidence of per-paper redistribution authority; release of
allowlisted titles, authors, and source URLs remains subject to RIGHTS-001 and
an accountable human rights decision.

## Responsible-AI boundaries

The platform separates four kinds of content wherever practical:

1. extracted publication evidence;
2. future work explicitly stated in a paper;
3. system inference about a gap or relationship; and
4. a newly generated suggestion.

Source-traceable means that a response retains paper, chunk, page/section,
snippet, provider, timestamp, and review-state provenance. It does not mean
that a claim is factually correct or entailed. Claim support and citation
correctness are reported only from the persisted claim-level formative review.

Topic and potential-expertise links are limited to indexed publication
evidence. They do not establish researcher availability, endorsement,
supervisory capacity, or identity equivalence beyond reviewed aliases.
Recommendation reviews are synthetic-profile, AI-assisted proxies. They do not
establish novelty, semester feasibility, student usefulness, or supervisor
approval.

## Privacy minimization

Public Ask questions and Thesis Extension Finder profiles are processed for the
current response with persistence disabled. Interests, skills, timelines, data
constraints, difficulty preferences, and avoid-topics are not written to
SQLite by default. Protected legacy histories and item routes require a
configured reviewer/admin actor. The frontend keeps a bearer token in page
memory only and does not write it to browser storage or URLs.

Operational logs are designed to retain route template, status, duration,
request ID, and actor ID/role without query strings, bodies, bearer tokens,
questions, profile fields, provider prompts, or responses. Deployment owners
must apply an institution-approved retention schedule, contact/request
procedure, proxy-log policy, access review, and incident process before public
operation. See `docs/PRIVACY.md`, `docs/SECURITY.md`, and
`docs/THREAT_MODEL.md`.

## Review and correction governance

Public read routes are separated from authenticated reviewer/admin routes.
Review events are append-only at the application/SQLite-trigger boundary and
record actor, reviewer type/role, request ID, prior/new state, diff, timestamp,
and a hash chain. This does not make the SQLite file tamper-proof against its
owner. Any content or metadata correction returns the item to `needs_review`;
approval requires a distinct subsequent, attributable human-admin decision.
AI actors may record `ai_reviewed` but cannot represent human review or approve
content. Corrections and review/publication decisions are separate operations:
a correction invalidates the prior decision and requires a new attributable
review. Publication decisions also remain independent of technical corpus
eligibility and per-source rights/access decisions.

## Codex and LLM assistance disclosure

Codex/GPT assistance was used materially in repository audit, implementation,
test preparation, source-backed label preparation, evaluation scripting,
formative output review, statistical analysis code, documentation, figure and
manuscript editing, and verification orchestration. AI-produced judgments are
identified in the datasets and limitations rather than described as independent
human assessment. Automated assistance did not supply participant data,
institutional approvals, legal opinions, funding/conflict declarations, or
rights-holder permissions.

The author and institution remain responsible for checking this disclosure
against University and target-venue policy. The external attestations that only
they can provide are listed in `docs/EXTERNAL_SUBMISSION_CHECKS.md`.
