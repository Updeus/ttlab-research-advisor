# Privacy Notice and Data Handling

## Plain-language notice

The platform searches TTLAB publications and generates source-linked answers
and project/thesis suggestions. A public Ask question or Extension Finder
profile is processed for that response but is **not stored in SQLite by
default**. Do not submit secrets, medical/financial information, private client
data, unpublished research, or information about another person.

Generated answers and recommendations are research-assistance outputs, not
supervisor assignment, academic approval, or proof of novelty/feasibility.

## Data categories and purpose

| Data | Purpose | Default storage |
|---|---|---|
| Publication metadata, extracted text, chunks, citations | Protected technical search, discovery, grounding, and evaluation; anonymous projection only after explicit publication/rights/access decisions | Local corpus/database according to corpus authorization and source rights |
| Ask question | Produce one source-grounded response | In-request only on the public endpoint |
| Interests, skills, timeline, project type, constraints, preferences | Rank papers and construct extension suggestions | In-request only on the public endpoint |
| Reviewer identity/role, corrections, notes, request ID | Accountability and correction history | SQLite append-only review events/application records |
| Operational metadata (route template, status, duration, request ID, actor ID/role) | Security, availability, incident investigation | Operator-configured logs |

The API does not expose a public opt-in persistence path. Existing stored
answers/recommendations from earlier local-demo/evaluation runs are treated as
legacy protected data: their history and item routes require reviewer/admin
authentication.

## Minimization and disclosure

- Public responses echo profile inputs only so the user can interpret that
  response; the backend uses `persist=False`.
- Public paper/extraction/search payloads omit local filesystem paths, raw seed
  records, extraction error details, and reviewer notes/identifiers.
- Anonymous routes fail closed when publication, source-access, or rights state
  is absent or unresolved. Technical corpus eligibility alone never makes a
  record public.
- Public artifact payloads likewise omit reviewer notes/identifiers. Draft
  corrected text/JSON stays protected until a separate human-admin approval;
  artifacts and source snippets for `needs_review` or otherwise non-eligible
  papers require reviewer/admin authentication.
- Full extracted chunks require reviewer/admin authentication; public source
  displays are bounded snippets and must still respect publication rights.
- Default providers are offline extractive and local Ollama. External-provider
  use is disabled unless the operator explicitly changes the provider allowlist.
- Application completion logs omit query strings, request/response bodies,
  bearer tokens, Ask text, and profile fields.

TTLAB authorization to undertake the project and use the laboratory corpus is
not equivalent to research-ethics-board approval, ownership of third-party
papers, or permission to redistribute every PDF. Restricted PDFs, secrets,
private database snapshots, and user-input histories must not enter a public
release bundle.

## Retention, access, export, deletion, and correction

No universal institutional retention period is evidenced in the repository.
Before public deployment, the University/TTLAB data owner must set documented
periods for protected legacy inputs, review records, backups, and operational
logs. Until then, minimize retention and do not claim a legal basis or fixed
period that has not been approved.

- **Access:** reviewer/admin bearer roles can access protected history and
  review data; database/server operators have infrastructure-level access.
- **Export:** no end-user export API is implemented because public inputs are
  not persisted. An authorized operator can export a subject/item-specific
  protected record from SQLite after verifying the requester and institutional
  procedure.
- **Deletion:** no end-user deletion API is implemented for the same reason.
  For a verified legacy-data request, an authorized database operator may
  remove the underlying answer/recommendation according to institutional policy
  and record the correction/incident separately. Review events themselves are
  append-only and are corrected by a new event, not erased through the app.
- **Correction:** publication/generated-output corrections use protected,
  attributable review routes. A correction does not rewrite prior review events
  and automatically returns the changed item to `needs_review`; approval is a
  separate subsequent event.

Requests should be directed through the approved University/TTLAB contact
channel established for deployment. The repository does not invent a privacy
officer, legal basis, or response deadline.

## Operator obligations before public deployment

1. Publish the approved owner/contact, purpose, jurisdictional legal basis,
   retention schedule, and request procedure.
2. Purge or separately protect legacy demo questions/profiles and backups.
3. Confirm proxy/application logs do not capture bodies, query strings, tokens,
   or provider prompts.
4. Document any external model provider, data destination, retention/training
   terms, and user notice/choice.
5. Apply access reviews, token rotation, backup encryption, incident response,
   and corpus redistribution restrictions from `SECURITY.md` and
   `DEPLOYMENT.md`.
