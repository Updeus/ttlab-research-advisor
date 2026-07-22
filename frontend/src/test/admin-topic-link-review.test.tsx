import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { installGraphAdminFetch } from "./admin-graph-fixtures";
import type { GraphRequest } from "./admin-graph-fixtures";

describe("admin topic-link governance", () => {
  afterEach(() => {
    cleanup();
    setReviewerToken("");
    vi.restoreAllMocks();
  });

  it("reaches every topic-link queue directly and gates approval on dependency evidence", async () => {
    const user = userEvent.setup();
    const requests: GraphRequest[] = [];
    const requestedQueues: string[] = [];
    installGraphAdminFetch(requests, requestedQueues, { total: 51 });
    setReviewerToken("a".repeat(32));

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Topics & Links" }));
    expect(await screen.findByRole("heading", { name: "RAG" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Paper-topic evidence links" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Author-topic evidence links" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Record type"), "author_topic");
    expect(await screen.findByRole("heading", { name: "Pat Example -> RAG" })).toBeInTheDocument();
    expect(screen.getByLabelText("Supporting paper count")).toHaveValue(2);
    const pagination = screen.getByRole("navigation", { name: "topics queue pagination" });
    await user.click(within(pagination).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(requestedQueues.some((url) => url.includes("item_type=author_topic") && url.includes("offset=50"))).toBe(true));
  });
});
