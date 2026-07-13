import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { PaperBrowser } from "../pages/PaperBrowser";
import { paper } from "./fixtures";


describe("paper browser pagination", () => {
  it("limits rendered cards, navigates pages, and resets after filtering", async () => {
    const user = userEvent.setup();
    const papers = Array.from({ length: 45 }, (_, index) => ({
      ...paper,
      paper_id: `paper-${index + 1}`,
      title: `Research Paper ${String(index + 1).padStart(2, "0")}`,
    }));

    render(<MemoryRouter><PaperBrowser papers={papers as never[]} /></MemoryRouter>);

    expect(screen.getAllByRole("article")).toHaveLength(20);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Research Paper 01" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Research Paper 21" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Research Paper 21" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search papers"), "Research Paper 45");
    expect(screen.queryByText(/Page 2 of/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Research Paper 45" })).toBeInTheDocument();
  });
});
