import {
  askTtlab,
  fetchAdminOverview,
  fetchPapers,
  generatePaperArtifacts,
  patchAdminPaper,
  previewBulkApproval,
  recommendExtensions,
  reviewGraphRecord,
  setReviewerToken,
} from "../api/client";
import { json } from "./fixtures";

describe("API request boundaries", () => {
  afterEach(() => {
    setReviewerToken("");
    vi.restoreAllMocks();
  });

  it("keeps reviewer credentials off public reads, Ask, and Finder requests", async () => {
    const token = "r".repeat(32);
    setReviewerToken(token);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));

    await fetchPapers();
    await askTtlab({
      question: "What is grounded?",
      mode: "hybrid",
      top_k: 3,
      audience: "general",
      max_words: 120,
      provider: "offline_extractive",
    });
    await recommendExtensions({
      interests: "retrieval",
      skills: ["Python"],
      available_time: "semester",
      project_type: "software prototype",
      data_constraints: "public data preferred",
      preferred_difficulty: "medium",
      preferred_topics: ["retrieval"],
      avoid_topics: [],
      top_k: 3,
      retrieval_mode: "hybrid",
      provider: "auto",
    });
    await fetchAdminOverview();

    for (const [, init] of fetchMock.mock.calls.slice(0, 3)) {
      expect(new Headers(init?.headers).has("Authorization")).toBe(false);
    }
    expect(new Headers(fetchMock.mock.calls[3][1]?.headers).get("Authorization")).toBe(`Bearer ${token}`);
  });

  it("formats FastAPI validation arrays into actionable field messages", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
      detail: [{ loc: ["body", "year"], msg: "Input should be less than or equal to 2200", type: "less_than_equal" }],
    }, { status: 422 }));

    await expect(patchAdminPaper("paper-1", { year: 2201 })).rejects.toThrow(
      "year: Input should be less than or equal to 2200 (422)",
    );
  });

  it("surfaces structured graph approval blockers without losing the HTTP status", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
      detail: {
        code: "approval_blocked",
        item_type: "author_topic",
        approval_blockers: ["author_identity_not_approved", "topic_not_approved"],
      },
    }, { status: 409 }));

    await expect(reviewGraphRecord("author_topic", "link-1", { review_status: "approved" })).rejects.toThrow(
      "Approval blocked: author_identity_not_approved, topic_not_approved (409)",
    );
  });

  it("distinguishes initial artifact generation from explicit regeneration", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ artifacts: [], grounding_status: "unsupported" }));

    await generatePaperArtifacts("paper-1");
    await generatePaperArtifacts("paper-1", true);

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ overwrite: false });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({ overwrite: true });
  });

  it("requests the explicit catch-all bulk approval mode", async () => {
    const token = "a".repeat(32);
    setReviewerToken(token);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
      operation_id: "catch-all-op",
      preview_hash: "a".repeat(64),
      eligible_count: 3,
      blocked_count: 2,
      approval_mode: "catch_all",
    }));

    await previewBulkApproval("catch_all");

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ approval_mode: "catch_all" });
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization")).toBe(`Bearer ${token}`);
  });
});
