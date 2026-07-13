# Data Availability and Sanitized Release Policy

The authoritative availability, rights, sanitization, and current release-state
record is [Data and Artifact Availability](DATA_AND_ARTIFACT_AVAILABILITY.md).
This compatibility page is retained because earlier documents linked to this
filename.

The essential boundary is unchanged: TTLAB authorized the project and use of
the laboratory corpus, but that does not grant blanket redistribution rights
over third-party PDFs or extracted full text. `make release` builds an
allowlist-based, scanned bundle of code and sanitized research evidence; it
excludes PDFs, runtime databases/indexes, interface screenshots, private
histories/prompts, local paths, and secrets. A final bundle must be rebuilt and
verified from the final clean commit rather than reusing an older local archive.
