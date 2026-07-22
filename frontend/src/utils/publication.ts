import type { Paper } from "../types/paper";

export function isSearchablePublicPaper(paper: Paper): boolean {
  return Boolean(
    paper.demo_preview
      ? paper.corpus_eligibility_status === "eligible" && paper.chunk_count > 0
      : paper.publication_status === "published"
    && paper.rights_status === "cleared"
    && paper.public_access_level === "searchable"
    && paper.corpus_eligibility_status === "eligible"
  );
}
