# Author Review Checklist

This checklist contains only decisions or attestations that cannot legitimately
be resolved from repository evidence. Completed engineering and offline-
evaluation work is not returned to the author for routine re-review. Detailed
institution/venue items are maintained in
[`docs/EXTERNAL_SUBMISSION_CHECKS.md`](docs/EXTERNAL_SUBMISSION_CHECKS.md).

## Confirmed author information

- [x] Author: Jarod Esareesingh.
- [x] Department: Department of Computing & Information Technology.
- [x] University: The University of the West Indies.
- [x] Email: `jarod.esareesingh@my.uwi.edu`.
- [x] Country: Trinidad and Tobago.
- [x] City omitted at the author's request.

## Institution and submission fields

- [ ] Supply a student ID only if the approved thesis template requires it.
- [ ] Confirm the exact MSc degree/programme title.
- [ ] Confirm supervisor/co-supervisor names and permitted attribution.
- [ ] Confirm the required submission month/year.
- [ ] Supply the approved University declaration, copyright/originality wording,
  and acknowledgements if required.
- [ ] Confirm the official name and capitalization/expansion of TTLAB. The
  repository does not resolve the earlier “Light Hitty Lab/TTLab” wording.
- [ ] Confirm that the implementation and commit history may be represented as
  the student's MSc work under University policy.
- [ ] Check that the explicit Codex/LLM-assistance disclosure satisfies current
  University and target-venue requirements.

## Rights, governance, and public operation

- [x] User-provided fact: TTLAB authorized the project and use of the laboratory
  corpus.
- [ ] Confirm rights-holder permission before redistributing any third-party PDF
  or substantial extracted text. Project authorization is not blanket
  copyright permission.
- [ ] Provide a REC/IRB approval or exemption record only if one actually exists.
  The present work reports no recruited human participants and makes no ethics-
  approval/exemption claim.
- [ ] Before public deployment, designate the institutional controller/contact
  and approve retention, access, correction/appeal, incident, backup, and
  privacy-request procedures.
- [ ] Supply funding and conflict-of-interest declarations only after an author
  confirms them; none is inferred from repository silence.

## Manuscript and venue decisions

- [ ] Approve the evidence-calibrated title and final author order.
- [ ] Select the target venue and apply its exact page limit, anonymization,
  copyright, author-block, and PDF-profile rules.
- [ ] Run IEEE PDF eXpress/Checker using venue credentials after local preflight.
- [ ] Obtain the author/supervisor approval required by the University before
  submission.

## Evidence-backed statements that should not be weakened or overstated

The repository now supports an executed artefact-oriented engineering case
study with AI-reviewed silver/proxy evaluation. The author does not need to
populate the earlier placeholder question/score files to support the recorded
results. The current claim boundary is:

- 134 catalogue records, 96 eligible papers, and 719 eligible chunks in frozen
  snapshot `corpus-04a010207327069a`;
- complete 719/719 feature-hashing and learned-dense index coverage;
- keyword held-out MRR 0.9474, dense 0.9386, tuned hybrid 0.8596, with no
  tuned-vs-baseline family-corrected rejection;
- AI-assisted QA supported-claim rate 0.995, citation correctness 0.625,
  answer-point coverage 0.1358, and zero abstentions on four unanswerable cases;
- recommendation full-minus-evidence-only relevance 0.0238 with 95% CI crossing
  zero;
- AI-reviewed topic/recommendation/generated-output results, not human ratings;
  and
- no committed full performance result at this documentation snapshot.

Do not reinterpret runtime `grounded` as factual correctness, feature hashing
as learned semantic retrieval, AI proxy usefulness as student usefulness, author
publication links as current availability/endorsement, or the three-document
Europe PMC check as broad external validation.

## Optional later human validation

A later human study could assess usefulness, readability, feasibility,
supervisor fit, topic validity, and user experience. It is not required to make
the current bounded offline claims, and it must not be backfilled informally.
If pursued, create a new approved protocol with participant records, recruitment
and consent, sample-size rationale, reviewer training, independent adjudication,
privacy/retention controls, and newly versioned results.

## Final factual sign-off

- [ ] Confirm the precursor paper's final bibliographic record against its
  primary source.
- [ ] Review the final title, abstract, contributions, limitations, and
  availability statement for institutional accuracy.
- [ ] Confirm final screenshots contain no sensitive/private data and show the
  final authoritative evaluation state.
- [ ] Confirm the sanitized release boundary and any separately distributed
  compiled PDFs.
- [ ] Proofread the final paper/thesis under required institutional spelling and
  formatting conventions.

These sign-offs do not replace automated evidence generation, validators,
builds, PDF preflight, or the issue-remediation matrix.
