import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock, json } from "./fixtures";

describe("GCP managed provider profile", () => {
  it("hides public model controls and discloses Vertex processing", async () => {
    const fetchMock = installBaseFetchMock();
    const base = fetchMock.getMockImplementation();
    expect(base).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/llms/status") return json({
        runtime_profile: "gcp",
        provider: "vertex_gemini",
        display_name: "Google Gemini on Vertex AI",
        configured: true,
        location: "global",
        model: "gemini-3.5-flash",
        model_selection_enabled: false,
        external_processing: true,
        privacy_notice: "The question and retrieved TTLAB passages are processed by Google Vertex AI.",
      });
      return base!(input, init);
    });

    render(<MemoryRouter initialEntries={["/ask"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Ask TTLAB" })).toBeInTheDocument();
    expect(await screen.findByText("Google Gemini on Vertex AI")).toBeInTheDocument();
    expect(screen.getByText(/processed by Google Vertex AI/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Answer provider")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Local Ollama model")).not.toBeInTheDocument();
  });
});

function requestUrl(input: RequestInfo | URL | undefined): URL {
  if (!input) return new URL("/__missing_request__", "http://127.0.0.1:8000");
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return new URL(raw, "http://127.0.0.1:8000");
}
