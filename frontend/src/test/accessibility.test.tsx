import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock } from "./fixtures";

describe("automated accessibility smoke", () => {
  beforeEach(() => installBaseFetchMock());

  it.each(["/", "/papers", "/admin"])("has no detectable axe violations on %s", async (route) => {
    const { container } = render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    await screen.findByRole("main");
    if (route === "/papers") await screen.findByRole("heading", { name: "Paper Browser" });
    if (route === "/admin") await screen.findByRole("heading", { name: "Reviewer authentication required" });
    if (route === "/") await screen.findByRole("heading", { name: "Research intelligence dashboard" });
    expect(await axe(container)).toHaveNoViolations();
  });
});
