import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { installGraphAdminFetch } from "./admin-graph-fixtures";
import type { GraphRequest } from "./admin-graph-fixtures";

describe("admin paper-topic governance", () => {
  afterEach(() => {
    cleanup();
    setReviewerToken("");
    vi.restoreAllMocks();
  });

  it("shows source evidence, blocks unsafe approval, and saves a correction separately", async () => {
    const user = userEvent.setup();
    const requests: GraphRequest[] = [];
    installGraphAdminFetch(requests);
    setReviewerToken("a".repeat(32));

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Topics & Links" }));
    await user.selectOptions(screen.getByLabelText("Record type"), "paper_topic");

    expect(await screen.findByRole("heading", { name: "Paper -> RAG" })).toBeInTheDocument();
    expect(screen.getByText(/linked paper metadata has not received human approval/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText("Source evidence locators").parentElement).toHaveTextContent("paper_metadata");

    await user.clear(screen.getByLabelText("Evidence score"));
    await user.type(screen.getByLabelText("Evidence score"), "0.75");
    await user.click(screen.getByRole("button", { name: "Save Correction (returns to needs review)" }));
    await waitFor(() => expect(requests).toContainEqual({
      path: "/api/admin/paper-topics/pt-1/correction",
      body: {
        score: 0.75,
        evidence_json: [{ source: "paper_metadata", field: "topics", value: "RAG" }],
      },
    }));
  });
});
