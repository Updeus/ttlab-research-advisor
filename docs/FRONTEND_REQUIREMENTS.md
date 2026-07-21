# Frontend Requirements and Verification

## Purpose

The React/Vite client is a core research-intelligence layer. It must make the
corpus boundary, retrieval method, source evidence, generation provenance,
review state, evaluation state, and security mode visible. A polished screen is
not sufficient if it hides that a result is unreviewed, unsupported, stale, or
unavailable.

## Route contract

The public route map is reproducible and supports reload, browser history, and
direct linking:

| Route | Surface | Data boundary |
|---|---|---|
| `/` | Dashboard | Public aggregate/corpus state |
| `/papers` | Paper Browser | Public publication metadata |
| `/papers/:paperId` | Paper Detail | Public metadata, snippets, citations, and published artifacts |
| `/search` | Search | Public eligible-corpus retrieval |
| `/ask` | Ask TTLAB | Transient public question |
| `/ask/:paperId` | Paper-scoped Ask | Transient public question and URL-safe paper ID only |
| `/extensions` | Thesis Extension Finder | Transient public student/project profile |
| `/explorer` | Topic/Author overview | Public source-derived relationships |
| `/explorer/topics` | Topic list | Public deterministic topic index |
| `/explorer/topics/:topicId` | Topic detail | Public evidence and linked papers/authors |
| `/explorer/authors` | Author list | Public source-derived author index |
| `/explorer/authors/:authorId` | Author detail | Public source-derived expertise evidence |
| `/evaluation` | Evaluation Dashboard | Public result availability and validated metrics |
| `/admin` | Admin Review | Authenticated reviewer/admin operations |

Unknown routes render an application 404. The deployment host must serve
`index.html` for unknown non-asset paths so BrowserRouter deep links reach this
route table. Vite's development server supplies this fallback; production
hosting must configure it explicitly.

Questions, profile fields, reviewer tokens, and generated answers must never be
placed in route paths or query parameters. Entity IDs and non-sensitive public
filters may be URL-addressable.

## Navigation and accessibility

The target is WCAG 2.2 AA where practical. Required behavior includes:

- one site header, primary navigation landmark, main landmark, and footer;
- a first-focusable skip link targeting `#main-content`;
- real route links with `aria-current="page"`;
- a route-specific document title and polite route announcement;
- focus restoration to the main landmark on route changes;
- logical page headings, labelled forms, persistent inline errors, and retry
  controls;
- WAI-ARIA tabs with `ArrowLeft`, `ArrowRight`, `Home`, and `End` support where
  a local tab panel remains preferable to a route;
- a solid high-contrast visible focus indicator;
- text in addition to colour for status and grounding;
- reduced-motion handling for transitions, spinners, and skeletons;
- no horizontal document overflow at 360, 768, 1024, or 1440 CSS pixels.

Automated axe, keyboard, and viewport checks are regression evidence, not proof
of accessibility conformance. Manual screen-reader, platform-specific
zoom/reflow, and contrast sampling remain pre-deployment external validation;
they are not represented as completed local release gates.

## Retrieval terminology and freshness

The interface must keep these modes distinct:

- **Keyword**: lexical full-text retrieval.
- **Feature-hashing baseline**: deterministic lexical feature hashing. It is
  not a learned semantic embedding model.
- **Dense semantic (learned model)**: the pinned learned embedding provider,
  when its complete index is available.
- **Hybrid**: the backend-defined combination, including any explicit fallback
  warning returned by the API.

The ambiguous legacy API value `semantic` is rejected. Callers must select
`keyword`, `feature_hashing`, `dense`, or `hybrid` explicitly. Search
diagnostics must show eligible/searchable counts, per-index status, and the
latest available snapshot timestamp. Missing, invalid, partial, or stale
indexes are states, not zero-valued success.

## Evidence and generated-content contract

Search results expose paper, chunk ID, page range, section, snippet, and score.
Ask answers expose provider/model, generation timestamp, transient/unreviewed
state, grounding, unsupported claims, citations, and retrieved chunks. Paper
artifacts expose provider/model, generation time, grounding, review state, and
source citations when the backend provides them.

Finder output must distinguish:

- paper/source-supported facts;
- an explicitly paper-stated gap or future-work item;
- an inference from retrieved paper evidence;
- a system-suggested extension;
- a potential researcher-fit discovery hint, which is not a supervisor
  assignment.

The Finder echoes the submitted profile from client memory and offers a
non-generative evidence-only alternative that returns ranked papers/passages
without inventing an extension or feasibility judgement. Full advisor output
must show fit rationale, paper focus, gap status, extension, MVP, stretch goals,
risk, skills, data needs, evaluation plan, related work, researcher-fit hints,
and citations.

## Privacy and authentication

Public Ask and Finder requests are transient. The client does not opt into
history persistence and does not place questions or profiles in Web Storage or
the URL. Concise notices tell users not to submit confidential or personal
data. The backend and reverse proxy must also keep content out of routine logs.

The admin route is protected. A reviewer/admin bearer token is accepted only
into module/page memory and attached to protected requests; it is not written
to `localStorage`, `sessionStorage`, the URL, or committed configuration. A
reload clears it. The header and admin route visibly distinguish an insecure
loopback-only demo bypass from protected operation. Production must never
enable the bypass.

Public users can read only artifacts whose paper publication decision, source
access class, rights state, and artifact review state are all public-eligible.
Authenticated reviewers can preview non-public states, while artifact
generation, correction, publication decisions, and review transitions require
the capability enforced by the API. The UI is not the security boundary.

Admin Review provides independently pageable queues for author identities,
author aliases, topics, paper-topic links, and author-topic links. Each record
shows its source/evidence locators, dependency states, unresolved or ambiguous
identity state, and stable approval-blocker codes. Correction forms call a
separate endpoint and always return changed records to `needs_review`; a
correction control never doubles as approval. Approval actions are shown only
when the actor capability is a human administrator and the record has no
dependency blocker. The API rechecks both conditions to prevent an AI or
service actor from impersonating human approval.
All decision and correction controls for one review item are disabled while any
mutation for that item is pending. This prevents concurrent review/correction
requests from racing; the API remains responsible for authoritative transition
and version checks.

Keyword retrieval is the user-facing default for Search, Ask, and Finder
because it is the supported baseline in the current evidence snapshot. Hybrid
remains selectable but is explicitly labelled experimental and not validated
as better. Finder renders an `unknown` difficulty as unverified feasibility,
not as an easy/medium/hard estimate.

Paper-detail deep links use the public per-paper endpoint when the shared
catalogue snapshot is absent or failed. The route has its own loading,
not-found, retryable-error, and success states; a catalogue outage is not
treated as proof that the paper ID is missing.

## Required state model

Every networked surface must represent applicable states explicitly:

| State | Required presentation |
|---|---|
| Initial loading | Named skeleton or progress region with `aria-busy` |
| Refreshing | Existing evidence remains visible with a progress message |
| Empty corpus/result | Specific explanation, not a blank panel |
| Request error | Persistent `role="alert"`, useful detail, and retry |
| Diagnostic error | State that freshness cannot be verified and offer retry |
| Stale/partial/invalid index | Warning; do not imply search readiness |
| Provider unavailable | Disable/fall back from the provider and explain it |
| No evaluation | “Not run”; never display zero as a measured metric |
| Invalid evaluation | Parse/schema failure; never display invalid metrics |
| Unauthorized/forbidden | Authentication or role-required state, not generic empty data |
| Unsupported/partial generation | Prominent warning plus available citations |

## Verification commands

From `frontend/`:

```bash
npm ci
npm run build
npm run test:unit
npm run test:a11y
npx playwright install chromium
npm run test:e2e
npm audit --audit-level=high
# With the real backend/frontend already running:
npm run capture:routes
```

Vitest, React Testing Library, user-event, jest-axe, and jsdom cover route,
focus, current-link, privacy, evidence, terminology, status, and accessible-name
regressions. Playwright covers primary-route deep links, reload/history, 404,
keyboard skip navigation, anonymous admin protection, source citation display,
and overflow assertions at 360/768/1024/1440. API responses in frontend tests
are explicit deterministic fixtures; those tests do not claim that a mocked
metric was measured. Backend contract and persistence/security tests remain
separate gates. The live route capture records desktop/mobile screenshots,
SHA-256 hashes, response/title data, console/page errors, and horizontal-
overflow status for every primary route plus discovered paper/topic/author
detail routes. Visual inspection remains required after that machine gate.

## Known residual limitations

- The automated browser matrix is Chromium-only; Firefox, WebKit, mobile
  assistive technologies, and multiple screen readers need manual/external
  validation.
- Browser focus and announcement behavior differs by assistive technology;
  automated DOM assertions cannot prove a usable spoken experience.
- Existing API evidence sometimes lacks a page or section. The UI displays an
  unknown marker and must not fabricate one.
- Explorer provenance remains limited to approved fields returned by the
  public API. The protected admin workflow exposes identity disambiguation and
  graph-link evidence, but final identity approval still requires a human
  administrator and source checking.
- Static-host SPA fallback and production TLS/security headers are deployment
  responsibilities and must be verified in the deployed environment.
- Final manuscript screenshots must be captured only after the authoritative
  corpus, indexes, and evaluation results are frozen; test fixtures are not
  screenshot evidence.
