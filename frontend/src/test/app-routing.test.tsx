import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock } from "./fixtures";

describe("route-based application shell", () => {
  beforeEach(() => {
    installBaseFetchMock();
  });

  it("deep-links, updates title, exposes current navigation, and restores focus", async () => {
    render(<MemoryRouter initialEntries={["/papers"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Paper Browser" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Papers/ })).toHaveAttribute("aria-current", "page");
    expect(document.title).toBe("Paper Browser | TTLAB Research Intelligence");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("id", "main-content"));
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main-content");
  });

  it("loads a paper detail route without prior in-app selection", async () => {
    render(<MemoryRouter initialEntries={["/papers/paper-1"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Grounded Research Discovery" })).toBeInTheDocument();
    expect(await screen.findByText("A source-grounded passage.")).toBeInTheDocument();
    expect(screen.getByText("Generation requires a reviewer credential.")).toBeInTheDocument();
  });

  it("protects administration and keeps credentials out of web storage", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/admin"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Reviewer authentication required" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Reviewer bearer token"), "a".repeat(32));
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("provides a deterministic 404 route", async () => {
    render(<MemoryRouter initialEntries={["/does-not-exist"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(document.title).toBe("Page Not Found | TTLAB Research Intelligence");
  });
});
