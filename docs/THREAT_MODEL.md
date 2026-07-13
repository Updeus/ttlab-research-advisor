# Threat Model

## Scope and security objective

This threat model covers the FastAPI service, SQLite database, local corpus and
derived files, PDF acquisition and parsing, local/optional model providers, and
the browser-to-API boundary. It describes the controls in this repository; it
does not claim that a public production deployment has been completed or
penetration-tested.

The objective is to keep publication discovery publicly readable while
preventing anonymous mutation, minimizing collection of student/profile data,
preserving attributable review decisions, and preventing untrusted URLs or
files from reaching local-network services or unbounded parser resources.

## Assets

- Publication metadata, extracted full text, chunks, indexes, and generated
  research-intelligence outputs.
- Student interests, skills, constraints, timelines, and Ask questions. These
  can reveal educational plans or interests even though the application does
  not treat them as special-category data.
- Reviewer corrections, notes, identities, roles, and audit events.
- Bearer tokens, provider/API credentials, local database files, backups, and
  restricted third-party PDFs.
- Availability and integrity of the search, recommendation, and review service.

## Trust boundaries and data flows

1. **Public browser to FastAPI.** Public metadata/search/read routes and the
   transient Ask/Finder computations cross an untrusted network boundary.
2. **Reviewer browser to FastAPI.** A bearer token authorizes protected history,
   generation, review, and admin routes. The application uses no authentication
   cookie or server-side browser session.
3. **FastAPI to SQLite/local files.** The process can read corpus files and
   mutate application state. Filesystem and database ownership are therefore a
   privileged operator boundary.
4. **Downloader to the public network.** A publication URL is hostile until its
   scheme, host, port, resolved addresses, redirect destinations, response type,
   signature, and size are checked.
5. **PDF parser/OCR boundary.** PDFs may be malformed, compressed, or expensive
   to render. PyMuPDF and optional OCR run in the application environment.
6. **Model-provider boundary.** Offline extraction and local Ollama stay within
   the configured host. An external provider is disabled by the default
   allowlist and must be an explicit operator/privacy decision.

## Threats and implemented controls

| Threat | Implemented control | Residual risk |
|---|---|---|
| Anonymous metadata/review mutation | Reviewer/admin bearer dependencies protect all `/api/admin/*` routes. Persisted artifact generation is protected; batch generation requires `admin`. | Token distribution and identity lifecycle are operator responsibilities. |
| Credential disclosure | No default/raw token is in source. Configuration stores only SHA-256 digests; comparisons are constant-time; access logs omit headers and bodies. | SHA-256 is safe here only because tokens must be random 256-bit values. Weak human passwords would be vulnerable to offline guessing. |
| Privilege escalation or false approval | Reviewer and admin roles are distinct. Reviewers cannot approve/reject. AI reviewers must use `ai_reviewed` and cannot grant `reviewed`/`approved`. Same-status requests still enforce actor rules, and every content/metadata correction is forced to `needs_review` before a separate decision. | A compromised human-admin token has application-level approval authority. |
| Audit-event tampering through the application/database connection | Events contain actor ID/type/role, request ID, diff, previous hash, and event hash. SQLite triggers reject `UPDATE` and `DELETE`. | The SQLite file owner can remove triggers or rewrite the file; external append-only/WORM logging is not bundled. Legacy pre-control rows may be unattributed/unhashed. |
| Student/profile over-collection | Public Ask and Finder calls pass `persist=False`; their history/item routes are protected. No public opt-in persistence endpoint exists. | Operator/proxy logs and legacy local-demo rows still require lifecycle controls. |
| Review-workspace or uncleared-source disclosure | Public artifacts omit reviewer notes/IDs and unapproved corrections. Public chunk/artifact evidence is limited to papers whose corpus status is exactly `eligible`; authenticated reviewers can inspect non-eligible material. Local-model status omits the internal provider URL and raw connection errors. | Approved corrected content and eligible source snippets remain intentionally public and require corpus-rights review. |
| SSRF, redirect pivot, or local metadata-service access | PDF URLs require `http(s)`, no embedded credentials, ports 80/443, an explicit host allowlist, and only globally routable resolved IPs. Every redirect is validated before the next request. | DNS can theoretically change between validation and connection. A permitted public host can be compromised. Use egress filtering for a higher-assurance deployment. |
| Oversized/mislabelled download or partial-file corruption | Downloads stream with a byte cap, validate Content-Type and `%PDF` signature, use a redirect cap, and atomically replace the destination only after validation. | A small PDF can still expand heavily during parsing. |
| Path traversal | Derived PDF/extraction filenames are sanitized, collision-suffixed, and checked against the configured output directory. Admin API users cannot set local filesystem paths. | Command-line operators retain filesystem authority and must protect configuration/working directories. |
| PDF bomb or parser exploit | Downloader/parser byte caps and a parser page cap reject obvious resource bombs; non-PDF suffixes are rejected. | PyMuPDF/OCR still parse in process. Public production should isolate ingestion in a low-privilege, resource-limited worker/container with no secrets. |
| Oversized or abusive API input | ASGI middleware enforces a one-MiB default cap, including chunked bodies. Pydantic fields/list sizes and result limits are bounded. Public Ask/Finder have a conservative single-process rate limiter. | The limiter is not shared across processes and is not a DDoS control; proxy/WAF limits remain necessary. |
| SQL/command injection | SQLModel/SQLAlchemy parameterize application queries. User inputs are not interpolated into shell commands. | Future raw SQL or subprocess additions require renewed review. |
| Stored/reflected XSS | The API returns JSON, not server-rendered HTML; API responses receive restrictive CSP/nosniff/frame headers. Frontend code must render text as text rather than unsanitized HTML. | CSP on API responses does not replace frontend encoding. Generated Markdown/HTML libraries require separate sanitization. |
| Cross-site request forgery and cross-origin misuse | Authentication uses an `Authorization: Bearer` header, not cookies, so ambient browser credentials are absent. CORS uses exact origins, no wildcard, and `allow_credentials=False`. | XSS or a malicious browser extension can still steal a token kept in browser-accessible storage; avoid persistent browser storage. |
| Host-header/TLS downgrade | Trusted-host middleware uses an explicit allowlist. Production startup requires an HTTPS public URL; HSTS is emitted in production. | TLS termination and correct forwarded-header trust are external deployment duties. |
| Sensitive logging | Application completion logs contain method, route template, status, duration, request ID, and authenticated actor ID/role only—never query string, body, token, question, or profile. | Uvicorn/reverse-proxy defaults may log raw request targets; configure them as described in `DEPLOYMENT.md`. |

## Abuse cases to retain in regression tests

- No token, a short/invalid token, reviewer token, AI-reviewer token, and admin
  token against protected routes and state transitions.
- Attempts to update/delete `reviewevent` rows.
- Private/loopback DNS resolution; a public URL redirecting to loopback; an
  unapproved host; an oversized or invalid-signature response.
- `../`/absolute-like paper IDs, excessive request bodies/fields/lists, full
  chunk requests without authentication, and CORS from an unapproved origin.

The targeted implementation tests are in
`backend/tests/test_security_privacy.py` and
`backend/tests/test_pdf_downloader.py`.
