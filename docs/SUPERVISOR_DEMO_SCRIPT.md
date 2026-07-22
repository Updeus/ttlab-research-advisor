# Supervisor Demo Script

Use the current evidence-calibrated sequence in
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). The recommended framing is:

> This artefact makes eligible TTLAB full-paper evidence searchable and
> source-traceable, then exposes clearly labeled generated suggestions and
> review state. Offline evaluation found useful engineering properties and
> important failures; it did not conduct a human advisory study.

Suggested demonstrations are full-paper evidence, keyword/dense comparison,
Ask citations and limitations, evidence-only versus full Extension Finder,
controlled topic/author links, executed Evaluation Dashboard results, and the
protected review/audit workflow.

The most important empirical talking points are:

- 96 eligible papers and 719/719 indexed chunks;
- in the exact post-remediation v1-form re-execution, keyword held-out MRR was
  0.947368 versus learned dense 0.938596 and tuned hybrid 0.912281; hybrid
  superiority was not demonstrated;
- AI-assisted QA produced 334 checkable claims (331 supported, three partial,
  none unsupported), citation correctness 0.652695, returned-citation utilization
  1.000000, strict answer-point coverage 11/81 = 0.135802, and 1/4
  unanswerable abstentions;
- the recommendation comparison returned 84 evidence-only items but only 67
  full-Finder items; the zero-filled relevance difference was -0.035714 (95%
  CI -0.119048 to 0.047619), while feasibility and usefulness failed for all 67
  returned full-Finder items; and
- topic/author and generated-output evidence clearly labeled as AI silver/proxy
  review rather than human approval.

These talking points are bound to commit
`73092e48f173b74f726659bd5b98224545ac23bb` and technical snapshot
`corpus-f4638c633bea82b0`. The older
`b561fa73...`/`corpus-04a010207327069a` values remain audit-baseline evidence,
not current presentation numbers. Do not frame the two runs as a paired
before/after experiment.

Do not present the project as a proven advisor, production deployment, or novel
retrieval algorithm. External supervisor/institutional sign-off remains separate
from repository evidence.
