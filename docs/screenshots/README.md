# Screenshots Checklist

Current implementation screenshots are committed under
`thesis/figures/screenshots/`. The reproducible browser-capture script
`thesis/scripts/capture_interface_screenshots.mjs` refreshes the current
Evaluation Dashboard and Ask TTLAB evidence images; the other committed images
are dated manual captures and must not be described as automatically refreshed.
Use this checklist when updating thesis slides, supervisor material, or README
evidence:

- Dashboard with paper/chunk/topic/artifact/review/evaluation counts.
- Paper Browser with TTLAB paper cards.
- Paper Detail with metadata, extraction status, chunks, and related papers.
- Paper Intelligence with summaries, limitations/future work, citations, and podcast script.
- Search page with keyword, feature-hashing, learned-dense, and hybrid results.
  The legacy `semantic` request value is retained only as a documented
  compatibility alias and must not be displayed as the name of feature hashing.
- Ask TTLAB answer with citations and page ranges.
- Thesis Extension Finder recommendations.
- Topic/Author Explorer overview.
- Topic detail page.
- Author detail page.
- Admin Review queue and audit trail.
- Evaluation Dashboard.

Before sharing screenshots publicly, ensure generated outputs have been reviewed or clearly marked as unreviewed demo content.

All files in this screenshot directory are excluded from the sanitized
reproducibility tarball. Raster captures can contain rendered paper passages,
answers, or contact data and cannot be field-redacted safely; the Git/manuscript
distribution boundary must therefore be reviewed separately.
