import type { ExtractionDiagnostics, Paper, PaperChunk, Stats } from "../types/paper";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchPapers(): Promise<Paper[]> {
  return getJson<Paper[]>("/api/papers");
}

export function fetchStats(): Promise<Stats> {
  return getJson<Stats>("/api/stats");
}

export function fetchExtraction(paperId: string): Promise<ExtractionDiagnostics> {
  return getJson<ExtractionDiagnostics>(`/api/papers/${paperId}/extraction`);
}

export function fetchPaperChunks(paperId: string): Promise<PaperChunk[]> {
  return getJson<PaperChunk[]>(`/api/papers/${paperId}/chunks`);
}
