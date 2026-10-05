import { render, screen } from "@testing-library/react";
import { CitedAnswer } from "../components/CitedAnswer";
import type { AskCitation, AskRetrievedChunk } from "../types/paper";

const chunks: AskRetrievedChunk[] = Array.from({ length: 5 }, (_, index) => ({
  chunk_id: `chunk-${index + 1}`, paper_id: "paper", title: "Recommendation System",
  authors: [], year: 2025, page_start: index + 1, page_end: index + 1,
  section: "Methodology", snippet: "Weighted eligibility recommendations.",
  scores: { keyword: 1, vector: 0, vector_provider: null, metadata: 0, section_boost: 0,
    evidence_quality: 0, topical_alignment: 0, diversity_penalty: 0, combined: 1 },
  source: { pdf_url: null, post_url: null },
}));
const citations: AskCitation[] = [chunks[2], chunks[4]].map((chunk) => ({
  ...chunk, score: 1, source_url: null, pdf_url: null,
}));

describe("grouped Ask citations", () => {
  it.each(["[S3, S5]", "**[S3, S5]**", "[s3; s5]"])("links %s to the original sources even with filtered citations", (marker) => {
    render(<CitedAnswer answer={`Weighted eligibility ${marker}.`} citations={citations} retrievedChunks={chunks} />);
    expect(screen.getByRole("link", { name: "Source: Recommendation System, Methodology, p. 3" }))
      .toHaveAttribute("href", "#ask-source-chunk-3");
    expect(screen.getByRole("link", { name: "Source: Recommendation System, Methodology, p. 5" }))
      .toHaveAttribute("href", "#ask-source-chunk-5");
    expect(screen.queryByText(/\[S\d/i)).not.toBeInTheDocument();
  });

  it("labels unavailable and unverified sources without inventing links", () => {
    render(<CitedAnswer answer="Eligibility [S1, S99]." citations={citations} retrievedChunks={chunks} />);
    expect(screen.getByText("[source unavailable]")).toBeInTheDocument();
    expect(screen.getByText("[Retrieved: Recommendation System, p. 1]")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
