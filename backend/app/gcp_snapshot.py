from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, inspect, select

from app.db import engine, verify_database_revision
from app.indexing.keyword_search import rebuild_keyword_index
from app.models import ReviewChainHead, ReviewEvent
from app.models.paper import JSONEncodedValue
from app.storage import GCSObjectStore
from sqlmodel import SQLModel, Session

SNAPSHOT_SCHEMA_VERSION = 1
DURABLE_TABLES = (
    "adminuser",
    "bulkoperation",
    "paper",
    "author",
    "topic",
    "authoralias",
    "papertopic",
    "authortopic",
    "chunk",
    "raganswer",
    "thesisrecommendation",
    "paperartifact",
    "reviewevent",
    "featuresetting",
    "ingestionrun",
    "ingestioncandidate",
    "ingestionsyncstate",
)
OMITTED_TABLES = {
    "adminsession": "active administrator sessions are not portable",
    "ollamamodelpolicy": "local Ollama policy is not part of managed runtime",
    "chunk_fts": "SQLite FTS data is rebuilt as PostgreSQL full-text metadata",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def export_snapshot(database: Path, output: Path, project_root: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    table_names = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    relational_violations = list(connection.execute("PRAGMA foreign_key_check"))
    if relational_violations:
        raise ValueError(
            f"SQLite source has {len(relational_violations)} foreign-key violations"
        )
    exports: dict[str, Any] = {}
    for table_name in DURABLE_TABLES:
        if table_name not in table_names:
            continue
        query = (
            "SELECT * FROM bulkoperation WHERE status='executed'"
            if table_name == "bulkoperation"
            else f'SELECT * FROM "{table_name}"'
        )
        rows = [dict(row) for row in connection.execute(query)]
        if table_name == "bulkoperation":
            for row in rows:
                row["preview_json"] = None
        if table_name == "ingestionsyncstate":
            for row in rows:
                for field in (
                    "lock_owner",
                    "locked_until",
                    "manual_requested_at",
                    "manual_requested_by",
                    "next_scheduled_at",
                ):
                    row[field] = None
        payload = b"".join(
            (json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")
            for row in rows
        )
        target = output / f"{table_name}.jsonl"
        target.write_bytes(payload)
        exports[table_name] = {
            "file": target.name,
            "row_count": len(rows),
            "sha256": sha256(payload),
        }
    chain = verify_exported_review_chain(connection)
    files = build_file_inventory(connection, project_root)
    omissions = []
    for table_name, reason in OMITTED_TABLES.items():
        if table_name in table_names:
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
            omissions.append({"table": table_name, "row_count": count, "reason": reason})
    if "bulkoperation" in table_names:
        omitted = int(
            connection.execute("SELECT COUNT(*) FROM bulkoperation WHERE status!='executed'").fetchone()[0]
        )
    if "ingestionsyncstate" in table_names:
        omissions.append(
            {
                "table": "ingestionsyncstate",
                "row_count": int(
                    connection.execute("SELECT COUNT(*) FROM ingestionsyncstate").fetchone()[0]
                ),
                "reason": "lease ownership, lock expiry, manual request, and next-schedule fields are reset; durable run history is retained",
            }
        )
        omissions.append(
            {
                "table": "bulkoperation",
                "row_count": omitted,
                "reason": "pending and expired bulk previews are transient; executed rows are exported without preview payloads",
            }
        )
    manifest = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_schema": "sqlite",
        "source_database_sha256": sha256(database.read_bytes()),
        "tables": exports,
        "review_chain": chain,
        "files": files,
        "omissions": omissions,
    }
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (output / "manifest.json").write_bytes(encoded)
    connection.close()
    return manifest


def verify_exported_review_chain(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = list(
        connection.execute(
            "SELECT * FROM reviewevent ORDER BY created_at, review_event_id"
        )
    )
    previous: str | None = None
    verified = 0
    for row in rows:
        value = dict(row)
        event_hash = value.get("event_hash")
        if not event_hash:
            continue
        if value.get("previous_event_hash") != previous:
            raise ValueError("Review event chain link mismatch")
        diff = json.loads(value.get("diff_json") or "{}")
        created_at = datetime.fromisoformat(str(value["created_at"]))
        calculated = ReviewEvent.calculate_hash(
            review_event_id=value["review_event_id"],
            previous_event_hash=previous,
            item_type=value["item_type"],
            item_id=value["item_id"],
            action=value["action"],
            previous_status=value.get("previous_status"),
            new_status=value.get("new_status"),
            reviewer_id=value["reviewer_id"],
            reviewer_name=value["reviewer_name"],
            reviewer_type=value["reviewer_type"],
            reviewer_role=value["reviewer_role"],
            request_id=value["request_id"],
            reviewer_notes=value.get("reviewer_notes"),
            diff_json=diff,
            created_at=created_at,
        )
        if calculated != event_hash:
            raise ValueError("Review event hash mismatch")
        previous = event_hash
        verified += 1
    return {"verified_hashed_events": verified, "head_hash": previous}


def build_file_inventory(connection: sqlite3.Connection, project_root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    columns = ("local_pdf_path", "extracted_json_path", "extracted_text_path")
    for row in connection.execute(
        "SELECT paper_id, local_pdf_path, extracted_json_path, extracted_text_path FROM paper"
    ):
        values = dict(row)
        for column in columns:
            raw = values.get(column)
            if not raw:
                continue
            path = Path(str(raw))
            resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
            try:
                relative = resolved.relative_to(project_root.resolve())
            except ValueError as exc:
                raise ValueError(f"Paper {values['paper_id']} has a storage path outside the project root") from exc
            if not resolved.is_file():
                raise FileNotFoundError(f"Inventory object is missing: {relative.as_posix()}")
            payload = resolved.read_bytes()
            inventory.append(
                {
                    "paper_id": values["paper_id"],
                    "source_column": column,
                    "path": relative.as_posix(),
                    "size": len(payload),
                    "sha256": sha256(payload),
                }
            )
    return inventory


def import_snapshot(snapshot: Path, *, gcs_prefix: str) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema version")
    verify_snapshot_objects(manifest, gcs_prefix)
    verify_database_revision(engine, "20260810_01")
    metadata = SQLModel.metadata
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name in DURABLE_TABLES:
            record = (manifest.get("tables") or {}).get(table_name)
            if not record:
                continue
            path = snapshot / str(record["file"])
            payload = path.read_bytes()
            if sha256(payload) != record["sha256"]:
                raise ValueError(f"Snapshot checksum mismatch for {table_name}")
            rows = [json.loads(line) for line in payload.splitlines() if line]
            if len(rows) != int(record["row_count"]):
                raise ValueError(f"Snapshot row-count mismatch for {table_name}")
            if table_name not in metadata.tables or not inspector.has_table(table_name):
                raise ValueError(f"Target table is missing: {table_name}")
            table = metadata.tables[table_name]
            if connection.execute(select(table).limit(1)).first() is not None:
                raise ValueError(f"Target table is not empty: {table_name}")
            prepared = [prepare_row(table_name, table, row, gcs_prefix) for row in rows]
            if prepared:
                connection.execute(table.insert(), prepared)
        head_hash = (manifest.get("review_chain") or {}).get("head_hash")
        head_event = None
        if head_hash:
            head_event = connection.execute(
                select(ReviewEvent.review_event_id).where(ReviewEvent.event_hash == head_hash)
            ).scalar_one()
        connection.execute(
            ReviewChainHead.__table__.update().where(ReviewChainHead.chain_id == 1).values(
                review_event_id=head_event,
                event_hash=head_hash,
            )
        )
    with Session(engine) as session:
        rebuilt = rebuild_keyword_index(session)
        if rebuilt.get("completeness_status") != "complete":
            raise RuntimeError("PostgreSQL keyword manifest rebuild was incomplete")


def prepare_row(table_name: str, table: Any, row: dict[str, Any], gcs_prefix: str) -> dict[str, Any]:
    prepared = {key: value for key, value in row.items() if key in table.c}
    for column in table.columns:
        if column.name not in prepared or prepared[column.name] is None:
            continue
        if isinstance(column.type, JSONEncodedValue) and isinstance(prepared[column.name], str):
            prepared[column.name] = json.loads(prepared[column.name])
        elif isinstance(column.type, DateTime) and isinstance(prepared[column.name], str):
            prepared[column.name] = datetime.fromisoformat(prepared[column.name])
        elif isinstance(column.type, Boolean):
            prepared[column.name] = bool(prepared[column.name])
    if table_name == "paper":
        mapping = {
            "local_pdf_path": "pdf_storage_uri",
            "extracted_json_path": "extracted_json_storage_uri",
            "extracted_text_path": "extracted_text_storage_uri",
        }
        for local_column, uri_column in mapping.items():
            value = prepared.get(local_column)
            if value:
                prepared[uri_column] = f"{gcs_prefix.rstrip('/')}/{str(value).lstrip('/')}"
                prepared[local_column] = None
    return prepared


def upload_snapshot_objects(manifest_path: Path, project_root: Path, gcs_prefix: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    store = GCSObjectStore()
    for item in manifest.get("files") or []:
        relative = str(item["path"])
        payload = (project_root / relative).read_bytes()
        if sha256(payload) != item["sha256"]:
            raise ValueError(f"Local object checksum changed after export: {relative}")
        uri = f"{gcs_prefix.rstrip('/')}/{relative.lstrip('/')}"
        store.write_bytes(uri, payload)


def verify_snapshot_objects(manifest: dict[str, Any], gcs_prefix: str) -> None:
    store = GCSObjectStore()
    for item in manifest.get("files") or []:
        uri = f"{gcs_prefix.rstrip('/')}/{str(item['path']).lstrip('/')}"
        if not store.exists(uri):
            raise FileNotFoundError(f"Snapshot object is missing: {uri}")
        if sha256(store.read_bytes(uri)) != item["sha256"]:
            raise ValueError(f"Snapshot object checksum mismatch: {uri}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or import an Advisor managed-runtime snapshot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--database", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--project-root", type=Path, default=Path.cwd())
    importer = subparsers.add_parser("import")
    importer.add_argument("--snapshot", type=Path, required=True)
    importer.add_argument("--gcs-prefix", required=True)
    uploader = subparsers.add_parser("upload-objects")
    uploader.add_argument("--manifest", type=Path, required=True)
    uploader.add_argument("--project-root", type=Path, default=Path.cwd())
    uploader.add_argument("--gcs-prefix", required=True)
    args = parser.parse_args()
    if args.command == "export":
        export_snapshot(args.database, args.output, args.project_root)
    elif args.command == "import":
        import_snapshot(args.snapshot, gcs_prefix=args.gcs_prefix)
    else:
        upload_snapshot_objects(args.manifest, args.project_root, args.gcs_prefix)


if __name__ == "__main__":
    main()
