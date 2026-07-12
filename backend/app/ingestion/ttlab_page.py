from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

DEFAULT_URL = "https://lab.tt/index.php/category/pub/"
USER_AGENT = "TTLABResearchIntelligence/0.1 (+https://lab.tt)"
NON_AUTHOR_ACTION_LABELS = {
    "click to view",
    "click here",
    "download",
    "download pdf",
    "read more",
    "view article",
    "view paper",
}


@dataclass
class LinkCandidate:
    text: str
    url: str
    is_pdf: bool = False
    is_source: bool = False


class TTLABDiscoveryClient:
    def __init__(self, timeout: float = 15.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def get_text(self, url: str) -> str:
        response = self._request("GET", url)
        response.raise_for_status()
        return response.text

    def is_pdf_url(self, url: str) -> bool:
        try:
            response = self._request("HEAD", url, accept="application/pdf,*/*")
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code < 400 and "application/pdf" in content_type:
                return True
        except httpx.HTTPError:
            pass
        return False

    def _request(self, method: str, url: str, accept: str | None = None) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        last_error: httpx.HTTPError | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.request(method, url, headers=headers)
                if response.status_code in {429, 503} and attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def stable_paper_id(title: str, post_url: str | None = None) -> str:
    normalized = normalize_title(title)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:72]
    digest_source = f"{normalized}|{post_url or ''}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else f"paper-{digest}"


def parse_year(raw_date: str | None) -> int | None:
    if not raw_date:
        return None
    compact = re.sub(r"(?<=\d)\s+(?=\d)", "", raw_date)
    match = re.search(r"\b(19|20)\d{2}\b", compact)
    return int(match.group(0)) if match else None


def split_authors(raw_authors: str | None) -> list[str]:
    if not raw_authors:
        return []
    cleaned = re.sub(r"\s+", " ", raw_authors).strip(" ,;")
    if not cleaned:
        return []
    parts = re.split(r"\s*,\s*|\s+\band\b\s+|\s*&\s*", cleaned)
    authors = [part.strip(" ,;") for part in parts if part.strip(" ,;")]
    return [author for author in authors if not is_action_label(author)]


def is_action_label(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    return normalized in NON_AUTHOR_ACTION_LABELS or normalized.startswith("click to ")


def is_internal_lab_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("lab.tt")


def classify_link(
    link_text: str,
    href: str,
    page_url: str,
    client: TTLABDiscoveryClient | None = None,
    check_content_type: bool = False,
) -> LinkCandidate:
    absolute_url = urljoin(page_url, href)
    text = re.sub(r"\s+", " ", link_text).strip()
    lowered_text = text.lower()
    lowered_path = urlparse(absolute_url).path.lower()
    is_pdf = "download" in lowered_text or lowered_path.endswith(".pdf")
    if not is_pdf and check_content_type and client is not None and should_probe_pdf_content_type(absolute_url):
        is_pdf = client.is_pdf_url(absolute_url)

    is_source = False
    if not is_pdf:
        if "click to view" in lowered_text:
            is_source = True
        elif not is_internal_lab_url(absolute_url):
            is_source = True

    return LinkCandidate(text=text, url=absolute_url, is_pdf=is_pdf, is_source=is_source)


def should_probe_pdf_content_type(url: str) -> bool:
    parsed = urlparse(url)
    if not is_internal_lab_url(url):
        return False
    path = parsed.path.lower()
    if "/author/" in path or "/category/" in path or re.search(r"/20\d{2}/", path):
        return False
    return "/wp-content/" in path or path.endswith((".ashx", ".download", "/download"))


def parse_publications_from_html(
    html: str,
    page_url: str,
    client: TTLABDiscoveryClient | None = None,
    check_content_type: bool = False,
) -> tuple[list[dict[str, object]], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()

    for article in soup.select("article"):
        record = parse_article(article, page_url, client=client, check_content_type=check_content_type)
        if record is None:
            continue
        title_key = normalize_title(str(record["title"]))
        url_keys = {url for url in [record.get("post_url"), record.get("source_url"), record.get("pdf_url")] if url}
        if title_key in seen_titles or seen_urls.intersection(url_keys):
            continue
        seen_titles.add(title_key)
        seen_urls.update(url_keys)
        records.append(record)

    return records, find_next_page_url(soup, page_url)


def parse_article(
    article: Tag,
    page_url: str,
    client: TTLABDiscoveryClient | None = None,
    check_content_type: bool = False,
) -> dict[str, object] | None:
    content = article.select_one(".entry-content") or article
    paragraphs = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip() for p in content.select("p")]
    paragraphs = [text for text in paragraphs if text]

    title = extract_title(article, content, paragraphs)
    if not title:
        return None

    authors_raw, venue, publication_date_raw = extract_bibliographic_fields(paragraphs, title)
    links = [
        classify_link(a.get_text(" ", strip=True), a.get("href", ""), page_url, client, check_content_type)
        for a in article.select("a[href]")
    ]
    all_urls = sorted({candidate.url for candidate in links})
    post_url = extract_post_url(article, links)
    pdf_url = next((candidate.url for candidate in links if candidate.is_pdf), None)
    source_url = next(
        (candidate.url for candidate in links if candidate.is_source and candidate.url != post_url),
        None,
    )

    authors = split_authors(authors_raw)
    year = parse_year(publication_date_raw)
    paper_id = stable_paper_id(title, post_url)
    pdf_text_status = "not_extracted" if pdf_url else "missing_pdf"
    record: dict[str, object] = {
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "year": year,
        "publication_date_raw": publication_date_raw,
        "venue": venue,
        "source_url": source_url,
        "post_url": post_url,
        "pdf_url": pdf_url,
        "local_pdf_path": None,
        "topics": [],
        "all_urls": all_urls,
        "ingestion_status": "discovered",
        "pdf_text_status": pdf_text_status,
        "review_status": "needs_review",
        "raw_scraped": {
            "authors_raw": authors_raw,
            "paragraphs": paragraphs,
            "links": [candidate.__dict__ for candidate in links],
        },
    }
    return record


def extract_title(article: Tag, content: Tag, paragraphs: list[str]) -> str | None:
    strong = content.select_one("p strong")
    if strong:
        title = re.sub(r"\s+", " ", strong.get_text(" ", strip=True)).strip()
        if title:
            return title
    heading = article.select_one(".entry-title a, h1 a, h2 a, h3 a, .entry-title, h1, h2, h3")
    if heading:
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
        if title:
            return title
    return paragraphs[0] if paragraphs else None


def extract_bibliographic_fields(paragraphs: list[str], title: str) -> tuple[str | None, str | None, str | None]:
    useful = [
        text
        for text in paragraphs
        if normalize_title(text) != normalize_title(title) and not is_action_label(text)
    ]
    authors_raw: str | None = None
    venue: str | None = None
    publication_date_raw: str | None = None

    for text in useful:
        if authors_raw is None and looks_like_author_line(text):
            authors_raw = text
            continue
        if authors_raw is not None and venue is None and not parse_year(text):
            venue = text
            continue
        if parse_year(text):
            publication_date_raw = text
            break

    return authors_raw, venue, publication_date_raw


def looks_like_author_line(text: str) -> bool:
    if is_action_label(text):
        return False
    if parse_year(text):
        return False
    lowered = text.lower()
    venue_words = ["conference", "journal", "chapter", "proceedings", "transactions", "symposium"]
    if any(word in lowered for word in venue_words):
        return False
    return bool(re.search(r"\b(and|&)\b|,", text)) or len(text.split()) <= 8


def extract_post_url(article: Tag, links: Iterable[LinkCandidate]) -> str | None:
    for selector in [".entry-title a", ".posted-by a[href*='/20']", "a[href*='/20']"]:
        found = article.select_one(selector)
        if found and found.get("href"):
            return found["href"]
    for candidate in links:
        if is_internal_lab_url(candidate.url) and "/index.php/" in candidate.url and "/author/" not in candidate.url:
            return candidate.url
    article_id = article.get("id", "")
    match = re.search(r"post-(\d+)", article_id)
    return None if not match else None


def find_next_page_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for link in soup.select("a.next, .nav-links a, nav a"):
        text = link.get_text(" ", strip=True).lower()
        rel = " ".join(link.get("rel", [])).lower() if link.get("rel") else ""
        href = link.get("href")
        if href and ("next" in text or "next" in rel):
            return urljoin(page_url, href)
    return None


def discover_publications(start_url: str, max_pages: int, check_content_type: bool = True) -> list[dict[str, object]]:
    client = TTLABDiscoveryClient()
    records: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    current_url: str | None = start_url
    try:
        for _page_number in range(max_pages):
            if current_url is None:
                break
            try:
                html = client.get_text(current_url)
            except httpx.HTTPStatusError as exc:
                if records:
                    print(f"warning=page_fetch_failed url={current_url} status={exc.response.status_code}")
                    break
                raise
            page_records, next_url = parse_publications_from_html(
                html,
                current_url,
                client=client,
                check_content_type=check_content_type,
            )
            for record in page_records:
                title_key = normalize_title(str(record["title"]))
                url_keys = {url for url in [record.get("post_url"), record.get("source_url"), record.get("pdf_url")] if url}
                if title_key in seen_titles or seen_urls.intersection(url_keys):
                    continue
                seen_titles.add(title_key)
                seen_urls.update(url_keys)
                records.append(record)
            current_url = next_url
    finally:
        client.close()
    return records


def write_seed(records: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_papers_seed_copy(records: list[dict[str, object]], output_path: Path) -> None:
    papers_path = output_path.parent / "papers.json"
    write_seed(records, papers_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover TTLAB publication metadata from the WordPress archive.")
    subparsers = parser.add_subparsers(dest="command")
    discover = subparsers.add_parser("discover", help="Fetch and parse TTLAB publication archive pages.")
    discover.add_argument("--url", default=DEFAULT_URL)
    discover.add_argument("--max-pages", type=int, default=2)
    discover.add_argument("--out", default="data/seed/ttlab_publications_discovered.json")
    discover.add_argument("--skip-content-type-check", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "discover":
        parser.print_help()
        return
    records = discover_publications(
        args.url,
        max_pages=max(args.max_pages, 1),
        check_content_type=not args.skip_content_type_check,
    )
    output_path = Path(args.out)
    write_seed(records, output_path)
    write_papers_seed_copy(records, output_path)
    direct_pdf_count = sum(1 for record in records if record.get("pdf_url"))
    print(
        f"discovered={len(records)} direct_pdf={direct_pdf_count} "
        f"missing_pdf={len(records) - direct_pdf_count} out={output_path}"
    )


if __name__ == "__main__":
    main()
