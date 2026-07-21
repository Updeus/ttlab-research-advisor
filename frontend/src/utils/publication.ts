import type { Paper } from "../types/paper";

export function isSearchablePublicPaper(paper: Paper): boolean {
  return paper.publication_status === "published"
    && paper.rights_status === "cleared"
    && paper.public_access_level === "searchable"
    && paper.corpus_eligibility_status === "eligible";
}
