import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";

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

  it("restores year, author, topic, and venue facets from the URL and keeps history navigable", async () => {
    const user = userEvent.setup();
    const papers = [
      paper,
      {
        ...paper,
        paper_id: "paper-2",
        title: "Climate Network Planning",
        authors: ["B. Analyst"],
        year: 2024,
        venue: "Climate Systems",
        topics: ["climate", "networks"],
      },
    ];

    render(
      <MemoryRouter initialEntries={["/papers?year=2024&author=B.%20Analyst&topic=climate&venue=Climate%20Systems"]}>
        <PaperBrowser papers={papers as never[]} />
        <LocationHarness />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Climate Network Planning" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: paper.title })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Filter by year")).toHaveValue("2024");
    expect(screen.getByLabelText("Filter by author")).toHaveValue("B. Analyst");
    expect(screen.getByLabelText("Filter by topic")).toHaveValue("climate");
    expect(screen.getByLabelText("Filter by venue")).toHaveValue("Climate Systems");

    await user.click(screen.getByRole("button", { name: "Clear paper filters" }));
    expect(screen.getByTestId("location-search")).toHaveTextContent("");
    expect(screen.getByRole("heading", { name: paper.title })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by topic"), "retrieval");
    expect(screen.getByTestId("location-search")).toHaveTextContent("topic=retrieval");
    expect(screen.getByRole("heading", { name: paper.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Climate Network Planning" })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by topic"), "climate");
    expect(screen.getByTestId("location-search")).toHaveTextContent("topic=climate");
    await user.click(screen.getByRole("button", { name: "Back in filter history" }));
    expect(screen.getByLabelText("Filter by topic")).toHaveValue("retrieval");
  });

  it("includes paper topics in free-text matching", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><PaperBrowser papers={[paper] as never[]} /></MemoryRouter>);
    await user.type(screen.getByLabelText("Search papers"), "retrieval");
    expect(screen.getByRole("heading", { name: paper.title })).toBeInTheDocument();
  });

  it("treats an empty public catalogue as a governed state", () => {
    render(<MemoryRouter><PaperBrowser papers={[]} /></MemoryRouter>);
    expect(screen.getByText("No papers are approved for public display yet")).toBeInTheDocument();
    expect(screen.getByText(/publication and rights settings/)).toBeInTheDocument();
  });

  it("distinguishes metadata catalogue records from the searchable corpus", () => {
    const metadataOnly = {
      ...paper,
      paper_id: "paper-metadata-only",
      title: "Metadata-only Publication",
      public_access_level: "metadata_only",
      chunk_count: 0,
    };
    render(<MemoryRouter><PaperBrowser papers={[paper, metadataOnly] as never[]} /></MemoryRouter>);

    expect(screen.getByText(/1 of 2 papers are also in the searchable full-text corpus/)).toBeInTheDocument();
    const metadataHeading = screen.getByRole("heading", { name: "Metadata-only Publication" });
    expect(metadataHeading).toBeInTheDocument();
    expect(metadataHeading.closest("article")).toHaveTextContent("not in the searchable corpus");
  });
});

function LocationHarness() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location-search">{location.search}</output>
      <button type="button" onClick={() => navigate(-1)}>Back in filter history</button>
    </>
  );
}
