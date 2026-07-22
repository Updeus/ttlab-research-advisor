from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.config import Settings, get_settings
from app.models import Paper
from app.security import require_offline_pdf_worker

USER_AGENT = "TTLABResearchIntelligence/0.1 (+https://lab.tt)"
PDF_UNAVAILABILITY_REASONS = {
    "no_pdf_url",
    "forbidden",
    "not_found",
    "timeout",
    "invalid_pdf",
    "scanned_pdf",
    "extraction_failure",
    "permission_restricted",
    "network_error",
    "security_blocked",
    "file_too_large",
    "redirect_error",
}


class DownloadSecurityError(ValueError):
    pass


class DownloadTooLargeError(ValueError):
    pass


class InvalidPDFError(ValueError):
    pass


@dataclass
class DownloadRecord:
    paper_id: str
    pdf_url: str | None
    local_pdf_path: str | None = None
    pdf_text_status: str | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_direct_pdf_candidate(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.path.lower().endswith(".pdf")


def has_acceptable_pdf_content_type(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower().split(";")[0].strip()
    if not content_type:
        return True
    return content_type in {"application/pdf", "application/octet-stream", "binary/octet-stream"}


def has_pdf_signature(content: bytes) -> bool:
    return content.startswith(b"%PDF")


def verify_pdf_response(response: httpx.Response) -> bool:
    return has_acceptable_pdf_content_type(response) and has_pdf_signature(response.content[:1024])


def deterministic_pdf_path(output_dir: Path, paper_id: str) -> Path:
    if not paper_id or len(paper_id) > 200:
        raise ValueError("paper_id must contain between 1 and 200 characters")
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in paper_id).strip("-")
    if not safe_name:
        raise ValueError("paper_id does not contain any safe filename characters")
    if safe_name != paper_id:
        safe_name = f"{safe_name[:160]}-{hashlib.sha256(paper_id.encode('utf-8')).hexdigest()[:12]}"
    target = output_dir / f"{safe_name}.pdf"
    if target.resolve().parent != output_dir.resolve():
        raise ValueError("Resolved PDF target escaped the configured output directory")
    return target


def host_matches_allowlist(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    normalized = hostname.rstrip(".").lower()
    for allowed in allowed_hosts:
        pattern = allowed.strip().rstrip(".").lower()
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if normalized.endswith(suffix) and normalized != suffix[1:]:
                return True
        elif hmac_hostname_equal(normalized, pattern):
            return True
    return False


def hmac_hostname_equal(left: str, right: str) -> bool:
    # Hostnames are not secrets; compare through a separate helper to keep all
    # allowlist matching exact and auditable.
    return left == right


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


def resolve_host_addresses(
    hostname: str,
    resolver: Callable[..., Any] | None = None,
) -> set[str]:
    resolve = resolver or socket.getaddrinfo
    try:
        raw_results = resolve(hostname, None, type=socket.SOCK_STREAM)
    except TypeError:
        raw_results = resolve(hostname)
    except OSError as exc:
        raise DownloadSecurityError("PDF host could not be resolved") from exc
    addresses: set[str] = set()
    for result in raw_results:
        if isinstance(result, str):
            addresses.add(result)
        elif isinstance(result, tuple) and len(result) >= 5 and isinstance(result[4], tuple):
            addresses.add(str(result[4][0]))
    if not addresses:
        raise DownloadSecurityError("PDF host did not resolve to an address")
    return addresses


def validate_remote_pdf_url(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    resolver: Callable[..., Any] | None = None,
    resolve_dns: bool = True,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadSecurityError("Only absolute http(s) PDF URLs are permitted")
    if parsed.username or parsed.password:
        raise DownloadSecurityError("Embedded URL credentials are not permitted")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DownloadSecurityError("PDF URL contains an invalid port") from exc
    if port is not None and port not in {80, 443}:
        raise DownloadSecurityError("Non-standard PDF URL ports are not permitted")
    hostname = parsed.hostname.rstrip(".").lower()
    if not host_matches_allowlist(hostname, allowed_hosts):
        raise DownloadSecurityError("PDF URL host is not on the configured allowlist")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise DownloadSecurityError("Private, loopback, link-local, and reserved IP destinations are blocked")
    if resolve_dns:
        addresses = resolve_host_addresses(hostname, resolver)
        if any(not is_public_ip(address) for address in addresses):
            raise DownloadSecurityError("PDF host resolved to a non-public IP address")
    return url


def stream_pdf_to_path(
    client: httpx.Client,
    url: str,
    target: Path,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int,
    max_redirects: int,
    resolver: Callable[..., Any] | None = None,
) -> None:
    current_url = url
    redirects = 0
    while True:
        validate_remote_pdf_url(
            current_url,
            allowed_hosts=allowed_hosts,
            resolver=resolver,
            resolve_dns=True,
        )
        with client.stream("GET", current_url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise DownloadSecurityError("PDF redirect omitted a Location header")
                redirects += 1
                if redirects > max_redirects:
                    raise DownloadSecurityError("PDF redirect limit exceeded")
                current_url = urljoin(current_url, location)
                # Validate before the next request, so redirects cannot pivot to
                # loopback/private/unapproved hosts.
                validate_remote_pdf_url(
                    current_url,
                    allowed_hosts=allowed_hosts,
                    resolver=resolver,
                    resolve_dns=True,
                )
                continue
            response.raise_for_status()
            if not has_acceptable_pdf_content_type(response):
                raise InvalidPDFError("Response Content-Type is not a supported PDF type")
            raw_length = response.headers.get("content-length")
            if raw_length:
                try:
                    content_length = int(raw_length)
                except ValueError as exc:
                    raise InvalidPDFError("Invalid Content-Length response header") from exc
                if content_length > max_bytes:
                    raise DownloadTooLargeError(f"PDF exceeds the configured {max_bytes}-byte limit")

            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
            temporary_path = Path(temporary_name)
            total = 0
            prefix = bytearray()
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise DownloadTooLargeError(f"PDF exceeds the configured {max_bytes}-byte limit")
                        if len(prefix) < 1024:
                            prefix.extend(chunk[: 1024 - len(prefix)])
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                if not has_pdf_signature(bytes(prefix)):
                    raise InvalidPDFError("Response did not contain a PDF signature")
                os.replace(temporary_path, target)
            finally:
                temporary_path.unlink(missing_ok=True)
            return


def load_records_from_seed(seed_path: Path) -> list[DownloadRecord]:
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Seed file must contain a JSON array.")
    loaded: list[DownloadRecord] = []
    for record in records:
        if not isinstance(record, dict) or not record.get("paper_id"):
            continue
        loaded.append(
            DownloadRecord(
                paper_id=str(record["paper_id"]),
                pdf_url=str(record["pdf_url"]) if record.get("pdf_url") else None,
                local_pdf_path=str(record["local_pdf_path"]) if record.get("local_pdf_path") else None,
                pdf_text_status=str(record["pdf_text_status"]) if record.get("pdf_text_status") else None,
            )
        )
    return loaded


def load_records_from_db(session: Session) -> list[DownloadRecord]:
    papers = session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all()
    return [
        DownloadRecord(
            paper_id=paper.paper_id,
            pdf_url=paper.pdf_url,
            local_pdf_path=paper.local_pdf_path,
            pdf_text_status=paper.pdf_text_status,
        )
        for paper in papers
    ]


def filter_records(
    records: list[DownloadRecord],
    paper_ids: list[str] | None,
    only_missing: bool,
    output_dir: Path,
) -> list[DownloadRecord]:
    allowed = set(paper_ids or [])
    filtered: list[DownloadRecord] = []
    for record in records:
        if allowed and record.paper_id not in allowed:
            continue
        if only_missing:
            target = deterministic_pdf_path(output_dir, record.paper_id)
            if record.local_pdf_path or target.exists():
                continue
        filtered.append(record)
    return filtered


def update_paper_download_status(
    session: Session | None,
    paper_id: str,
    *,
    local_pdf_path: str | None = None,
    ingestion_status: str | None = None,
    pdf_text_status: str | None = None,
    unavailability_reason: str | None = None,
    unavailability_detail: str | None = None,
    clear_unavailability: bool = False,
) -> None:
    if session is None:
        return
    paper = session.get(Paper, paper_id)
    if paper is None:
        return
    if local_pdf_path is not None:
        paper.local_pdf_path = local_pdf_path
    if ingestion_status is not None:
        paper.ingestion_status = ingestion_status
    if pdf_text_status is not None:
        paper.pdf_text_status = pdf_text_status
    if clear_unavailability:
        paper.pdf_unavailability_reason = None
        paper.pdf_unavailability_detail = None
    elif unavailability_reason is not None:
        if unavailability_reason not in PDF_UNAVAILABILITY_REASONS:
            raise ValueError(f"Unsupported PDF unavailability reason: {unavailability_reason}")
        paper.pdf_unavailability_reason = unavailability_reason
        paper.pdf_unavailability_detail = unavailability_detail
    paper.updated_at = utc_now()
    session.add(paper)


def download_pdfs(
    records: list[DownloadRecord],
    output_dir: Path,
    *,
    limit: int | None = None,
    download: bool = False,
    overwrite: bool = False,
    timeout: float = 30.0,
    session: Session | None = None,
    client: httpx.Client | None = None,
    allowed_hosts: Iterable[str] | None = None,
    max_bytes: int | None = None,
    max_redirects: int | None = None,
    resolver: Callable[..., Any] | None = None,
    settings_override: Settings | None = None,
) -> dict[str, int]:
    settings = settings_override or get_settings()
    if download:
        require_offline_pdf_worker(settings, "Live PDF acquisition")
    allowed_hosts = tuple(allowed_hosts or settings.allowed_pdf_hosts)
    max_bytes = max_bytes or settings.max_pdf_download_bytes
    max_redirects = settings.max_pdf_redirects if max_redirects is None else max_redirects
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "attempted": 0,
        "downloaded": 0,
        "skipped_existing": 0,
        "failed": 0,
        "invalid_pdf": 0,
        "missing_pdf_url": 0,
        "forbidden": 0,
        "not_found": 0,
        "timeout": 0,
        "permission_restricted": 0,
        "network_error": 0,
        "blocked_url": 0,
        "oversize": 0,
        "redirect_error": 0,
    }
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
    try:
        for record in records:
            if limit is not None and summary["attempted"] >= limit:
                break
            if not is_direct_pdf_candidate(record.pdf_url):
                summary["missing_pdf_url"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="missing_pdf",
                    pdf_text_status="missing_pdf",
                    unavailability_reason="no_pdf_url",
                    unavailability_detail="No permitted direct PDF URL was available.",
                )
                continue

            try:
                validate_remote_pdf_url(
                    str(record.pdf_url),
                    allowed_hosts=allowed_hosts,
                    resolver=resolver,
                    resolve_dns=False,
                )
            except DownloadSecurityError as exc:
                summary["blocked_url"] += 1
                summary["failed"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_blocked",
                    pdf_text_status="download_failed",
                    unavailability_reason="security_blocked",
                    unavailability_detail=str(exc),
                )
                continue

            target = deterministic_pdf_path(output_dir, record.paper_id)
            if target.exists() and not overwrite:
                summary["skipped_existing"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    local_pdf_path=str(target),
                    ingestion_status="pdf_downloaded",
                    pdf_text_status="downloaded",
                    clear_unavailability=True,
                )
                continue

            summary["attempted"] += 1
            if not download:
                print(f"dry-run would_download paper_id={record.paper_id} target={target}")
                continue

            try:
                stream_pdf_to_path(
                    client,
                    str(record.pdf_url),
                    target,
                    allowed_hosts=allowed_hosts,
                    max_bytes=max_bytes,
                    max_redirects=max_redirects,
                    resolver=resolver,
                )
            except httpx.TimeoutException as exc:
                reason = "timeout"
                summary[reason] += 1
                summary["failed"] += 1
                detail = f"{type(exc).__name__}: remote PDF request timed out"
                print(f"failed paper_id={record.paper_id} reason={reason}")
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_failed",
                    pdf_text_status="download_failed",
                    unavailability_reason=reason,
                    unavailability_detail=detail,
                )
                continue
            except DownloadTooLargeError as exc:
                summary["oversize"] += 1
                summary["failed"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_failed",
                    pdf_text_status="download_failed",
                    unavailability_reason="file_too_large",
                    unavailability_detail=str(exc),
                )
                continue
            except DownloadSecurityError as exc:
                reason = "redirect_error" if "redirect" in str(exc).lower() else "security_blocked"
                summary["redirect_error" if reason == "redirect_error" else "blocked_url"] += 1
                summary["failed"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_blocked",
                    pdf_text_status="download_failed",
                    unavailability_reason=reason,
                    unavailability_detail=str(exc),
                )
                continue
            except InvalidPDFError as exc:
                summary["invalid_pdf"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="invalid_pdf",
                    pdf_text_status="invalid_pdf",
                    unavailability_reason="invalid_pdf",
                    unavailability_detail=str(exc),
                )
                continue
            except httpx.HTTPStatusError as exc:
                reason = classify_http_unavailability(exc.response.status_code)
                summary[reason] += 1
                summary["failed"] += 1
                print(f"failed paper_id={record.paper_id} reason={reason} status={exc.response.status_code}")
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_failed",
                    pdf_text_status="download_failed",
                    unavailability_reason=reason,
                    unavailability_detail=f"HTTP {exc.response.status_code}",
                )
                continue
            except httpx.RequestError as exc:
                reason = "network_error"
                summary[reason] += 1
                detail = f"{type(exc).__name__}: remote PDF request failed"
                print(f"failed paper_id={record.paper_id} reason={reason}")
                summary["failed"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_failed",
                    pdf_text_status="download_failed",
                    unavailability_reason=reason,
                    unavailability_detail=detail,
                )
                continue

            update_paper_download_status(
                session,
                record.paper_id,
                local_pdf_path=str(target),
                ingestion_status="pdf_downloaded",
                pdf_text_status="downloaded",
                clear_unavailability=True,
            )
            print(f"downloaded paper_id={record.paper_id} target={target}")
            summary["downloaded"] += 1
    finally:
        if owns_client:
            client.close()
    if session is not None:
        session.commit()
    return summary


def classify_http_unavailability(status_code: int) -> str:
    if status_code == 403:
        return "forbidden"
    if status_code in {404, 410}:
        return "not_found"
    if status_code in {401, 451}:
        return "permission_restricted"
    return "network_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely download direct TTLAB PDF URLs.")
    parser.add_argument("--seed", default="data/seed/ttlab_publications_discovered.json")
    parser.add_argument("--from-db", action="store_true", help="Read paper URLs from SQLite instead of seed JSON.")
    parser.add_argument("--out-dir", default="data/pdfs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--paper-id", action="append", default=None)
    parser.add_argument("--download", action="store_true", help="Actually save PDFs. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly keep dry-run behavior.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only-missing", dest="only_missing", action="store_true", default=True)
    parser.add_argument("--include-existing", dest="only_missing", action="store_false")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    output_dir = Path(args.out_dir)
    with Session(engine) as session:
        records = load_records_from_db(session) if args.from_db else load_records_from_seed(Path(args.seed))
        records = filter_records(records, args.paper_id, args.only_missing, output_dir)
        summary = download_pdfs(
            records,
            output_dir,
            limit=args.limit,
            download=bool(args.download and not args.dry_run),
            overwrite=args.overwrite,
            timeout=args.timeout,
            session=session if args.from_db else None,
        )
    print(
        "attempted={attempted} downloaded={downloaded} skipped_existing={skipped_existing} "
        "failed={failed} invalid_pdf={invalid_pdf} missing_pdf_url={missing_pdf_url}".format(**summary)
    )


if __name__ == "__main__":
    main()
