# Data Availability and Sanitized Release Policy

## Authorization and rights boundary

TTLAB authorized this project and its use of the laboratory corpus. That fact
does not establish research-ethics-board approval, copyright ownership, or a
right to redistribute every third-party publication. Publication PDFs, local
database rows containing full extracted text, chunks, and indexes therefore
remain local inputs. Recipients must obtain them through a permitted source or
receive separate authorization.

The application and research artifacts are prepared as a versioned sanitized
bundle by:

```bash
make release
```

The command does not publish a repository, push a tag, or alter repository
visibility. It prepares the tag name `v0.1.0-remediation` in the manifest for a
maintainer to create after final verification.

## Included material

The allowlist includes:

- backend/frontend source and tests;
- exact dependency requirements and frontend lock file;
- data/evaluation schemas, acquisition/review scripts, prompts, cases, labels,
  and sanitized result records;
- redistributable publication metadata fields from seed files;
- aggregate and sanitized raw experiment outputs, configurations, manifests,
  hashes, and figure sources;
- LaTeX/BibTeX sources and build instructions;
- security, ethics, methodology, and reproduction documentation.

JSON/JSONL fields containing source passages, generated answers that may quote
sources, local paths, raw scrape payloads, or private prompt content are
replaced by a record containing the original SHA-256 and character count.
Judgment labels, IDs, numeric metrics, configurations, and provenance hashes
remain available. This preserves audit linkage without silently redistributing
publication text.

## Mandatory exclusions

The builder and its post-build scanner reject:

- every PDF, including corpus and compiled-document PDFs;
- SQLite databases and runtime indexes;
- downloaded, extracted, and chunked publication text;
- `.env` files, credentials, private keys, and detected bearer/API tokens;
- absolute local user paths;
- private AI-review prompts/inputs and raw Europe PMC XML;
- files outside the explicit source allowlist.

Compiled paper/thesis PDFs are distributed separately only after the author
and venue confirm that doing so is appropriate; they are not required to
reproduce the editable manuscripts.

## Integrity and inspection

The deterministic tarball uses the source commit timestamp, sorted paths, zero
UID/GID, normalized modes, and gzip timestamp zero. Each release contains:

- `RELEASE_MANIFEST.json`, with source/released hashes and sanitization counts;
- `SHA256SUMS`, covering every payload file before the manifest;
- `REPRODUCE.md`, with the rights boundary and commands.

An adjacent `.sha256` file covers the archive itself. The verifier scans each
archive member for unsafe paths, PDF magic bytes, forbidden extensions,
absolute local paths, and secret patterns. Build failure is mandatory if a scan
finding remains.

## Reproduction levels

`make reproduce-quick` verifies distributable code, tests, evidence manifests,
the frontend, manuscripts, PDF preflight, external acquisition, a bounded
engineering benchmark, and release construction. It does not claim to recreate
corpus-dependent experiments.

`make reproduce` is the authoritative full path. It requires an authorized
local `data/papers.db`, referenced local PDFs, and the pinned dense model. It
uses an isolated `tmp/reproduce/full` workspace to import/repair metadata,
extract, chunk, index, rerun evaluations, benchmark, test, build, preflight, and
hash results. Restricted workspace files are never copied into the sanitized
release.

The release can therefore reproduce code-level and sanitized analytical
artifacts openly, while exact full-corpus reruns remain conditional on lawful
access to the underlying papers. That is a reproducibility limitation, not an
invitation to bypass source terms.
