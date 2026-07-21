import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock } from "./fixtures";

describe("automated accessibility smoke", () => {
  beforeEach(() => installBaseFetchMock());

  it.each([
    ["/", "Research intelligence dashboard"],
    ["/papers", "Paper Browser"],
    ["/papers/paper-1", "Grounded Research Discovery"],
    ["/search", "Search Source Chunks"],
    ["/ask", "Ask TTLAB"],
    ["/extensions", "Thesis Extension Finder"],
    ["/explorer", "Topic and author explorer"],
    ["/evaluation", "Evaluation dashboard"],
    ["/admin", "Reviewer authentication required"],
  ])("has no detectable axe violations on %s", async (route, heading) => {
    const { container } = render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: heading });
    expect(await axe(container)).toHaveNoViolations();
  });
});
