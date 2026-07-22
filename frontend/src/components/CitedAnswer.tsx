import type { ReactNode } from "react";

import type { AskCitation, AskRetrievedChunk } from "../types/paper";

type CitedAnswerProps = {
  answer: string;
  citations: AskCitation[];
  retrievedChunks: AskRetrievedChunk[];
};

export function CitedAnswer({ answer, citations, retrievedChunks }: CitedAnswerProps) {
  const citedChunkIds = new Set(citations.map((citation) => citation.chunk_id));
  const lines = answer.trim().split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let bulletItems: string[] = [];

  const flushBullets = () => {
    if (!bulletItems.length) return;
    const items = bulletItems;
    bulletItems = [];
    blocks.push(
      <ul key={`list-${blocks.length}`}>
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>
            {renderInline(item, retrievedChunks, citedChunkIds, `bullet-${index}`)}
          </li>
        ))}
      </ul>,
    );
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushBullets();
      continue;
    }
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      bulletItems.push(bullet[1]);
      continue;
    }
    flushBullets();
    blocks.push(
      <p key={`paragraph-${blocks.length}`}>
        {renderInline(line, retrievedChunks, citedChunkIds, `paragraph-${blocks.length}`)}
      </p>,
    );
  }
  flushBullets();

  return <div className="cited-answer">{blocks}</div>;
}

export function askSourceAnchor(chunkId: string): string {
  return `ask-source-${chunkId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export function askSourceNumber(retrievedChunks: AskRetrievedChunk[], chunkId: string): number | null {
  const index = retrievedChunks.findIndex((chunk) => chunk.chunk_id === chunkId);
  return index >= 0 ? index + 1 : null;
}

function renderInline(
  text: string,
  retrievedChunks: AskRetrievedChunk[],
  citedChunkIds: Set<string>,
  keyPrefix: string,
): ReactNode[] {
  const normalized = text.replace(/\*\*(\[S\d+\])\*\*/gi, "$1");
  return normalized
    .split(/(\[S\d+\]|\*\*[^*]+\*\*)/gi)
    .filter(Boolean)
    .map((part, index) => {
      const sourceMatch = part.match(/^\[S(\d+)\]$/i);
      if (sourceMatch) {
        const sourceNumber = Number(sourceMatch[1]);
        const source = retrievedChunks[sourceNumber - 1];
        if (!source) {
          return <span key={`${keyPrefix}-${index}`} className="inline-citation inline-citation--unresolved">[source unavailable]</span>;
        }
        const label = sourceLabel(source);
        const fullLabel = `Source: ${source.title}${source.section ? `, ${source.section}` : ""}${pageLabel(source.page_start, source.page_end)}`;
        if (!citedChunkIds.has(source.chunk_id)) {
          return (
            <span
              key={`${keyPrefix}-${index}`}
              className="inline-citation inline-citation--unverified"
              title={`${fullLabel}. This retrieved source was not structurally verified for the claim.`}
            >
              [Retrieved: {label}]
            </span>
          );
        }
        return (
          <a
            key={`${keyPrefix}-${index}`}
            className="inline-citation"
            href={`#${askSourceAnchor(source.chunk_id)}`}
            title={fullLabel}
            aria-label={fullLabel}
          >
            [{label}]
          </a>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
}

function sourceLabel(source: AskRetrievedChunk): string {
  const title = source.title.length > 46 ? `${source.title.slice(0, 43).trimEnd()}…` : source.title;
  return `${title}${pageLabel(source.page_start, source.page_end)}`;
}

function pageLabel(start: number | null, end: number | null): string {
  if (start === null && end === null) return "";
  if (start !== null && end !== null && start !== end) return `, pp. ${start}–${end}`;
  return `, p. ${start ?? end}`;
}
