import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { installGraphAdminFetch } from "./admin-graph-fixtures";
import type { GraphRequest } from "./admin-graph-fixtures";

describe("admin author identity governance", () => {
  afterEach(() => {
    cleanup();
    setReviewerToken("");
    vi.restoreAllMocks();
  });

  it("blocks unresolved approval and saves corrections as a separate needs-review version", async () => {
    const user = userEvent.setup();
    const requests: GraphRequest[] = [];
    installGraphAdminFetch(requests);
    setReviewerToken("a".repeat(32));

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Author Identities" }));

    expect(await screen.findByRole("heading", { name: "Pat Example" })).toBeInTheDocument();
    expect(screen.getByText(/identity is unresolved or ambiguous/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Reviewer notes")).toHaveValue("Ambiguous initials");

    await user.type(screen.getByLabelText("Canonical author name"), "Pat Example");
    await user.selectOptions(screen.getByLabelText("Identity status"), "resolved");
    await user.click(screen.getByRole("button", { name: "Save Correction (returns to needs review)" }));

    await waitFor(() => expect(requests).toContainEqual({
      path: "/api/admin/authors/7/correction",
      body: {
        canonical_name: "Pat Example",
        affiliation: null,
        email: null,
        profile_url: null,
        persistent_identifier: null,
        persistent_identifier_source: null,
        identity_status: "resolved",
        merged_into_author_id: null,
        reviewer_notes: "Ambiguous initials",
      },
    }));
    expect(requests[requests.length - 1]?.body).not.toHaveProperty("review_status");
  });
});
