# Human-required items

This list is intentionally narrow. It excludes work Codex can safely implement,
test, calculate, rebuild, or rewrite conservatively. Time-consuming engineering
is not classified as human-required.

## 1. University submission identity and attestations

Related issue: SUBMISSION-001.

Why Codex cannot resolve it:

- the repository does not establish the approved degree nomenclature or formal
  title-page formula;
- supervisor/co-supervisor names and permitted attribution require the relevant
  people;
- submission month/year, declarations, copyright/originality language, and
  acknowledgements are institution-specific;
- the official expansion/capitalization of TTLAB is not established;
- institutional rules must determine whether the implementation, commit history,
  and disclosed Codex/LLM assistance may be represented as the student's work;
- funding and conflict-of-interest declarations cannot be inferred from silence.

Minimum human input:

1. Approved thesis template or exact required title-page/declaration text.
2. Confirmed supervisor/co-supervisor names, submission date, and official TTLAB
   name.
3. Author-approved funding/COI statement.
4. Written confirmation that the AI-assistance disclosure and authorship
   representation comply with current University policy.

Codex can then apply and cross-check those supplied facts, but must not invent
them.

## 2. Target paper venue and submission profile

Related issues: SUBMISSION-001, PAPER-001, PAPER-003.

Why Codex cannot resolve it:

- the target conference or journal has not been selected;
- anonymity, author order, page size, copyright/footer notice, metadata profile,
  and exact camera-ready/review rules depend on that venue;
- IEEE PDF eXpress/Checker access uses venue credentials;
- final title, author block, and submission approval are author/supervisor
  decisions.

Minimum human input:

1. Target venue and whether the build is for blind review or camera-ready use.
2. Venue instructions or conference code/profile.
3. Approved title, author order, affiliation, and copyright notice.
4. A PDF eXpress/Checker report produced with authorized credentials after Codex
   completes local preflight.

Codex can create the venue-specific build and eliminate bookmarks/links once the
profile is selected.

## 3. Rights and public-operation authority

Related issues: RIGHTS-001, PUBLIC-001, PDF-001.

Why Codex cannot resolve it:

- TTLAB authorization to undertake the project and use the laboratory corpus is
  an explicit project fact, but it is not a blanket third-party redistribution
  license;
- rights to expose each PDF, substantial extracted text, or public snippet
  require source- or rights-holder-specific decisions;
- an institutional controller/contact must own retention, correction/appeal,
  access, incident, backup, and privacy-request procedures;
- Codex cannot sign legal or institutional attestations.

Minimum human input:

1. Dated TTLAB/author confirmation of the authorized project and public-use
   boundary.
2. Per-paper decision for public metadata, snippets/extracted text, PDF links,
   and any redistribution.
3. Named institutional controller/contact and approved retention, correction,
   incident, backup, and privacy-request rules.

Codex can implement a fail-closed rights matrix and enforcement after those
decisions are supplied.

## 4. Editorial approval of public corpus facts

Related issues: PUBLIC-001, META-001, TOPIC-001.

Why Codex cannot completely resolve it:

- Codex can normalize obvious parser artifacts, preserve aliases, and hide every
  unapproved record;
- ambiguous person merges, official author spellings, final topic labels, and
  permission to publish a corrected record require an accountable reviewer;
- the current database has every paper and topic at needs_review.

Minimum human input:

1. A named reviewer/administrator and permitted role.
2. Approval or correction decisions for records intended to become public,
   beginning with the small demo corpus.
3. Explicit decisions for unresolved identity pairs and the two suspected
   title/PDF mismatches.

Human adjudication is not needed for Codex to implement the fail-closed gate; it
is needed to populate that gate with approved public content.

## 5. Optional future human validation

This is not required to preserve the manuscripts' current bounded negative
claims. It becomes required only if the author wants to claim student usefulness,
supervisor fit, practical feasibility, usability, trust, accessibility with
assistive technology, or human-quality topic/recommendation judgments.

Minimum human input before such a study:

1. Institutional determination on whether ethics/REC/IRB review is required.
2. Approved protocol, recruitment/consent, sample-size rationale, reviewer
   training, adjudication, privacy, and retention plan.
3. Actual participant/reviewer records and versioned results.

Do **not** add an ethics approval/exemption number unless a real record exists.
The present no-participant study does not justify inventing one, and AI review
must never be described as human review.
