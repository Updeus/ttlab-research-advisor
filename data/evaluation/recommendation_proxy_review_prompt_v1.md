# Recommendation proxy-review rubric v1

Reviewer identity: Codex AI source-audit agent. Reviewer type: `ai`.

This is a fixed, AI-assisted proxy audit. It is not a student study, human
inter-rater exercise, novelty search, feasibility guarantee, supervisor
approval, or institutional review. Inspect the exact ranked paper, cited source
passages, generated recommendation fields, student profile, and warnings. Do
not use a paper title alone when source passages are available.

For every evidence-only paper, judge `paper_relevance` and `source_fidelity`.
For every full-finder recommendation, judge all of:

1. `paper_relevance`
2. `source_fidelity`
3. `fact_future_gap_suggestion_separation`
4. `novelty_caution`
5. `skills_time_data_feasibility`
6. `mvp_scope`
7. `stretch_goal_appropriateness`
8. `risk_calibration`
9. `required_skills`
10. `evaluation_plan_quality`
11. `usefulness_as_ai_proxy`

Use `pass`, `partial`, `fail`, or `not_applicable`. A pass requires direct
support or a clearly cautious and internally consistent suggestion. Partial
means useful but materially incomplete, generic, or dependent on an unresolved
constraint. Fail means contradicted, misleading, unsupported, or unusable.
Include a concise rationale grounded in the profile/output/evidence. Never
upgrade an inferred gap to explicit future work merely because a passage uses
words such as “evaluation”, “dataset”, “challenge”, or “improvement”. Never
call an idea novel. A recommendation with a skill, data, or time mismatch may
still be candidly useful if the mismatch and scope reduction are explicit.

Run two passes in independently shuffled fixed-seed orders. The two passes use
the same frozen inputs and rubric; agreement measures repeatability of this one
AI-assisted audit procedure, not human inter-rater reliability.
