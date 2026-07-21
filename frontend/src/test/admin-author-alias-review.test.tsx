import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { installGraphAdminFetch } from "./admin-graph-fixtures";
import type { GraphRequest } from "./admin-graph-fixtures";

describe("admin author-alias governance", () => {
  afterEach(() => {
    cleanup();
    setReviewerToken("");
    vi.restoreAllMocks();
  });

  it("loads the alias queue directly and permits human approval only when dependencies are clear", async () => {
    const user = userEvent.setup();
    const requests: GraphRequest[] = [];
    installGraphAdminFetch(requests);
    setReviewerToken("a".repeat(32));

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Author Identities" }));
    await user.selectOptions(screen.getByLabelText("Record type"), "author_alias");

    expect(await screen.findByRole("heading", { name: "P Example" })).toBeInTheDocument();
    expect(screen.getByText("Approval dependency state").parentElement).toHaveTextContent("identity_status");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(requests).toContainEqual({
      path: "/api/admin/author-aliases/alias-1/review",
      body: { review_status: "approved" },
    }));
  });
});
