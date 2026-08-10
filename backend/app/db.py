from collections.abc import Generator
import json
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    db_path = Path(database_url.replace("sqlite:///", "", 1))
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()


def build_engine(runtime_settings=settings) -> Engine:
    if not runtime_settings.is_gcp:
        _ensure_sqlite_parent(runtime_settings.database_url)
        return create_engine(
            runtime_settings.database_url,
            connect_args={"check_same_thread": False}
            if runtime_settings.database_url.startswith("sqlite")
            else {},
        )
    try:
        from google.cloud.sql.connector import Connector, IPTypes
    except ImportError as exc:  # pragma: no cover - exercised in the GCP image
        raise RuntimeError("Cloud SQL Python Connector is required in the GCP runtime") from exc
    connector = Connector(refresh_strategy="LAZY")
    ip_type = IPTypes.PRIVATE if runtime_settings.cloud_sql_ip_type == "private" else IPTypes.PUBLIC

    def get_connection():  # type: ignore[no-untyped-def]
        return connector.connect(
            runtime_settings.cloud_sql_instance,
            "pg8000",
            user=runtime_settings.cloud_sql_iam_user,
            db=runtime_settings.cloud_sql_database,
            enable_iam_auth=True,
            ip_type=ip_type,
        )

    target = create_engine(
        "postgresql+pg8000://",
        creator=get_connection,
        pool_size=runtime_settings.database_pool_size,
        max_overflow=runtime_settings.database_max_overflow,
        pool_recycle=runtime_settings.database_pool_recycle_seconds,
        pool_pre_ping=True,
    )
    setattr(target, "_ttlab_cloud_sql_connector", connector)
    return target


engine = build_engine()


def install_sqlite_connection_pragmas(target_engine: Engine) -> None:
    """Install safe per-connection controls on a SQLite engine.

    ``foreign_keys`` and ``busy_timeout`` are connection-local. Journal mode is
    deliberately absent: changing it while every pooled connection opens can
    contend with active readers and writers.
    """

    if target_engine.dialect.name != "sqlite":
        return

    def configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    event.listen(target_engine, "connect", configure_sqlite)


install_sqlite_connection_pragmas(engine)


def initialize_sqlite_durability(target_engine: Engine = engine) -> str:
    """Configure WAL once at controlled startup and fail diagnostically.

    In-memory databases legitimately retain ``memory`` journal mode. A
    read-only file database is accepted only when it is already in WAL mode;
    otherwise startup cannot establish the required operating contract.
    """

    if target_engine.dialect.name != "sqlite":
        return "not_applicable"
    try:
        with target_engine.connect() as connection:
            mode = str(connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()).lower()
    except Exception as exc:  # pragma: no cover - driver-specific detail is reported verbatim
        raise RuntimeError(
            "SQLite durability initialization failed; use a writable database prepared for WAL "
            "or run the service in an explicitly read-only mode."
        ) from exc
    if mode not in {"wal", "memory"}:
        raise RuntimeError(f"SQLite durability initialization returned unsupported journal_mode={mode}")
    return mode


def create_db_and_tables() -> None:
    if settings.is_gcp:
        verify_database_revision(engine, settings.expected_database_revision)
        return
    initialize_sqlite_durability(engine)
    SQLModel.metadata.create_all(engine)
    ensure_sqlite_schema()


def verify_database_revision(target_engine: Engine, expected_revision: str) -> None:
    """Fail readiness/startup when managed schema migrations are not at head."""

    try:
        with target_engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    except Exception as exc:
        raise RuntimeError("Managed database migration revision could not be verified") from exc
    if str(revision) != expected_revision:
        raise RuntimeError(
            f"Managed database revision is {revision!s}; expected {expected_revision}. Run the migration job first."
        )


def close_managed_engine() -> None:
    if not settings.is_gcp:
        return
    engine.dispose()
    connector = getattr(engine, "_ttlab_cloud_sql_connector", None)
    if connector is not None:
        connector.close()


def ensure_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    paper_columns = {
        "pdf_unavailability_reason": "VARCHAR",
        "pdf_unavailability_detail": "VARCHAR",
        "extracted_json_path": "VARCHAR",
        "extracted_text_path": "VARCHAR",
        "pdf_storage_uri": "VARCHAR",
        "extracted_json_storage_uri": "VARCHAR",
        "extracted_text_storage_uri": "VARCHAR",
        "extraction_generation_id": "VARCHAR",
        "extraction_input_pdf_sha256": "VARCHAR",
        "extraction_config_sha256": "VARCHAR",
        "chunk_extraction_generation_id": "VARCHAR",
        "chunk_generation_id": "VARCHAR",
        "public_index_generation_id": "VARCHAR",
        "extraction_diagnostics": "VARCHAR",
        "extraction_content_type": "VARCHAR DEFAULT 'unknown' NOT NULL",
        "ocr_status": "VARCHAR DEFAULT 'not_requested' NOT NULL",
        "ocr_provider": "VARCHAR",
        "ocr_provider_version": "VARCHAR",
        "ocr_pages_count": "INTEGER DEFAULT 0 NOT NULL",
        "ocr_review_required": "BOOLEAN DEFAULT 0 NOT NULL",
        "metadata_provenance": "VARCHAR",
        "metadata_field_reviews": "VARCHAR",
        "corpus_eligibility_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "corpus_exclusion_reason": "VARCHAR",
        "publication_status": "VARCHAR DEFAULT 'pending_review' NOT NULL",
        "rights_status": "VARCHAR DEFAULT 'unknown' NOT NULL",
        "public_access_level": "VARCHAR DEFAULT 'hidden' NOT NULL",
        "pdf_title_match_status": "VARCHAR DEFAULT 'not_assessed' NOT NULL",
        "pdf_title_match_score": "FLOAT",
        "page_count": "INTEGER",
        "total_char_count": "INTEGER DEFAULT 0 NOT NULL",
        "total_word_count": "INTEGER DEFAULT 0 NOT NULL",
        "pages_with_text": "INTEGER DEFAULT 0 NOT NULL",
        "pages_without_text": "INTEGER DEFAULT 0 NOT NULL",
        "possible_scanned_pdf": "BOOLEAN DEFAULT 0 NOT NULL",
        "chunk_count": "INTEGER DEFAULT 0 NOT NULL",
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "extraction_review_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "extraction_reviewer_notes": "VARCHAR",
        "extraction_reviewed_at": "DATETIME",
        "extraction_reviewed_by": "VARCHAR",
    }
    author_columns = {
        "canonical_name": "VARCHAR",
        "normalized_name": "VARCHAR",
        "identity_status": "VARCHAR DEFAULT 'unresolved' NOT NULL",
        "identity_review_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "identity_review_notes": "VARCHAR",
        "identity_reviewed_at": "DATETIME",
        "identity_reviewed_by": "VARCHAR",
        "merged_into_author_id": "INTEGER",
        "persistent_identifier": "VARCHAR",
        "persistent_identifier_source": "VARCHAR",
    }
    author_alias_columns = {
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
    }
    topic_columns = {
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
    }
    graph_review_columns = {
        "review_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "updated_at": "DATETIME",
    }
    chunk_columns = {
        "chunk_index": "INTEGER DEFAULT 0 NOT NULL",
        "char_count": "INTEGER DEFAULT 0 NOT NULL",
        "word_count": "INTEGER DEFAULT 0 NOT NULL",
        "token_count_estimate": "INTEGER",
        "extraction_generation_id": "VARCHAR",
    }
    rag_answer_columns = {
        "review_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "citation_correct": "BOOLEAN",
        "answer_faithfulness_score": "INTEGER",
        "usefulness_score": "INTEGER",
        "generation_metadata_json": "VARCHAR",
        "runtime_provenance_json": "VARCHAR",
        "claim_support_json": "VARCHAR",
        "answerability_json": "VARCHAR",
    }
    recommendation_columns = {
        "review_status": "VARCHAR DEFAULT 'needs_review' NOT NULL",
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "corrected_recommendations_json": "VARCHAR",
        "runtime_provenance_json": "VARCHAR",
        "correction_grounding_status": "VARCHAR DEFAULT 'not_applicable' NOT NULL",
        "correction_source_chunk_ids_json": "VARCHAR",
        "correction_citations_json": "VARCHAR",
        "correction_runtime_provenance_json": "VARCHAR",
    }
    artifact_columns = {
        "reviewer_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "corrected_text": "VARCHAR",
        "corrected_json": "VARCHAR",
        "runtime_provenance_json": "VARCHAR",
        "correction_grounding_status": "VARCHAR DEFAULT 'not_applicable' NOT NULL",
        "correction_source_chunk_ids_json": "VARCHAR",
        "correction_citations_json": "VARCHAR",
        "correction_runtime_provenance_json": "VARCHAR",
    }
    review_event_columns = {
        "reviewer_id": "VARCHAR DEFAULT 'legacy-unattributed' NOT NULL",
        "reviewer_type": "VARCHAR DEFAULT 'unknown' NOT NULL",
        "reviewer_role": "VARCHAR DEFAULT 'unknown' NOT NULL",
        "request_id": "VARCHAR DEFAULT 'unavailable' NOT NULL",
        "previous_event_hash": "VARCHAR",
        "event_hash": "VARCHAR",
    }
    with engine.begin() as connection:
        add_missing_columns(connection, "paper", paper_columns)
        add_missing_columns(connection, "author", author_columns)
        add_missing_columns(connection, "authoralias", author_alias_columns)
        add_missing_columns(connection, "topic", topic_columns)
        add_missing_columns(connection, "papertopic", graph_review_columns)
        add_missing_columns(connection, "authortopic", graph_review_columns)
        add_missing_columns(connection, "chunk", chunk_columns)
        add_missing_columns(connection, "raganswer", rag_answer_columns)
        add_missing_columns(connection, "thesisrecommendation", recommendation_columns)
        add_missing_columns(connection, "paperartifact", artifact_columns)
        add_missing_columns(connection, "reviewevent", review_event_columns)
        install_author_merge_fk_guard(connection)
        connection.execute(
            text(
                "UPDATE paper SET extraction_diagnostics = '{}' "
                "WHERE extraction_diagnostics IS NULL OR extraction_diagnostics = '[]'"
            )
        )
        connection.execute(
            text(
                "UPDATE paper SET metadata_provenance = '{}' "
                "WHERE metadata_provenance IS NULL OR metadata_provenance = '[]'"
            )
        )
        connection.execute(
            text(
                "UPDATE paper SET metadata_field_reviews = '{}' "
                "WHERE metadata_field_reviews IS NULL OR metadata_field_reviews = '[]'"
            )
        )
        connection.execute(
            text(
                "UPDATE author SET canonical_name = name "
                "WHERE canonical_name IS NULL OR TRIM(canonical_name) = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE thesisrecommendation SET corrected_recommendations_json = '{}' "
                "WHERE corrected_recommendations_json IS NULL OR corrected_recommendations_json = '[]'"
            )
        )
        for column_name, empty_value in (
            ("generation_metadata_json", "{}"),
            ("runtime_provenance_json", "{}"),
            ("claim_support_json", "[]"),
            ("answerability_json", "{}"),
        ):
            connection.execute(
                text(
                    f"UPDATE raganswer SET {column_name} = :empty_value "
                    f"WHERE {column_name} IS NULL OR {column_name} = '[]'"
                ),
                {"empty_value": empty_value},
            )
        connection.execute(
            text(
                "UPDATE paperartifact SET corrected_json = '{}' "
                "WHERE corrected_json IS NULL OR corrected_json = '[]'"
            )
        )
        connection.execute(
            text(
                "UPDATE thesisrecommendation SET runtime_provenance_json = '{}' "
                "WHERE runtime_provenance_json IS NULL OR runtime_provenance_json = '[]'"
            )
        )
        connection.execute(
            text(
                "UPDATE paperartifact SET runtime_provenance_json = '{}' "
                "WHERE runtime_provenance_json IS NULL OR runtime_provenance_json = '[]'"
            )
        )
        for table_name in ("thesisrecommendation", "paperartifact"):
            for column_name, empty_value in (
                ("correction_source_chunk_ids_json", "[]"),
                ("correction_citations_json", "[]"),
                ("correction_runtime_provenance_json", "{}"),
            ):
                connection.execute(
                    text(
                        f"UPDATE {table_name} SET {column_name} = :empty_value "
                        f"WHERE {column_name} IS NULL"
                    ),
                    {"empty_value": empty_value},
                )
        install_review_event_immutability(connection)
        install_review_event_chain_uniqueness(connection)
        assert_sqlite_relational_integrity(connection)
        assert_sqlite_json_integrity(connection)


def sqlite_json_integrity_violations(connection) -> list[dict[str, object]]:
    """Locate malformed JSON without invoking ORM result converters.

    The audit reports only table/key/column metadata, never the potentially
    sensitive damaged value. SQL identifiers come exclusively from SQLModel
    metadata rather than external input.
    """

    existing_tables = {
        str(row[0])
        for row in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all()
    }
    violations: list[dict[str, object]] = []

    def quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        table_info = list(
            connection.exec_driver_sql(
                f"PRAGMA table_info({quote(table.name)})"
            ).mappings()
        )
        actual_columns = {str(row["name"]) for row in table_info}
        json_columns = [
            column.name
            for column in table.columns
            if column.name in actual_columns
            and column.type.__class__.__name__ == "JSONEncodedValue"
        ]
        if not json_columns:
            continue
        primary_keys = [
            column.name
            for column in table.primary_key.columns
            if column.name in actual_columns
        ]
        selected = list(dict.fromkeys([*primary_keys, *json_columns]))
        sql = (
            f'SELECT rowid AS "__audit_rowid", '
            + ", ".join(quote(name) for name in selected)
            + f" FROM {quote(table.name)}"
        )
        for row in connection.exec_driver_sql(sql).mappings():
            locator = {
                name: row[name]
                for name in primary_keys
                if row.get(name) is not None
            } or {"rowid": row["__audit_rowid"]}
            for column_name in json_columns:
                raw_value = row[column_name]
                if raw_value is None:
                    continue
                try:
                    decoded = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError, UnicodeError):
                    error = "malformed_json"
                else:
                    error = None if isinstance(decoded, (dict, list)) else "invalid_json_container"
                if error:
                    violations.append(
                        {
                            "table": table.name,
                            "row": locator,
                            "column": column_name,
                            "error": error,
                        }
                    )
    return violations


def assert_sqlite_json_integrity(connection) -> None:
    violations = sqlite_json_integrity_violations(connection)
    if not violations:
        return
    locations = ", ".join(
        f"{item['table']}[{item['row']}].{item['column']}"
        for item in violations[:10]
    )
    suffix = "" if len(violations) <= 10 else f" (+{len(violations) - 10} more)"
    raise RuntimeError(
        "SQLite persisted JSON integrity check failed; repair or quarantine the exact rows before startup: "
        f"{locations}{suffix}"
    )


def sqlite_integrity_diagnostics(target_engine: Engine = engine) -> dict[str, object]:
    """Return operator-facing SQLite durability settings without mutating data."""

    if target_engine.dialect.name != "sqlite":
        return {"dialect": "non_sqlite", "status": "not_applicable"}
    with target_engine.connect() as connection:
        foreign_keys = int(connection.execute(text("PRAGMA foreign_keys")).scalar_one())
        journal_mode = str(connection.execute(text("PRAGMA journal_mode")).scalar_one())
        busy_timeout = int(connection.execute(text("PRAGMA busy_timeout")).scalar_one())
        fk_rows = [tuple(row) for row in connection.execute(text("PRAGMA foreign_key_check")).all()]
        json_violations = sqlite_json_integrity_violations(connection)
        author_table = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='author'")
        ).first()
        orphan_author_merges = 0
        merge_fk_declared = False
        merge_guard_triggers = False
        if author_table:
            columns = {str(row[1]) for row in connection.execute(text("PRAGMA table_info(author)")).all()}
            if "merged_into_author_id" in columns:
                orphan_author_merges = int(
                    connection.execute(
                        text(
                            "SELECT COUNT(*) FROM author AS child "
                            "LEFT JOIN author AS parent ON parent.id = child.merged_into_author_id "
                            "WHERE child.merged_into_author_id IS NOT NULL AND parent.id IS NULL"
                        )
                    ).scalar_one()
                )
                merge_fk_declared = any(
                    str(row[3]) == "merged_into_author_id" and str(row[2]) == "author"
                    for row in connection.execute(text("PRAGMA foreign_key_list(author)")).all()
                )
                trigger_names = {
                    str(row[0])
                    for row in connection.execute(
                        text(
                            "SELECT name FROM sqlite_master WHERE type='trigger' "
                            "AND name IN ('author_merge_fk_insert', 'author_merge_fk_update', 'author_merge_fk_delete')"
                        )
                    ).all()
                }
                merge_guard_triggers = len(trigger_names) == 3
    relational_ready = not fk_rows and not json_violations and orphan_author_merges == 0 and (
        not author_table or merge_fk_declared or merge_guard_triggers
    )
    return {
        "dialect": "sqlite",
        "foreign_keys": foreign_keys,
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout,
        "foreign_key_check_violations": [
            {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
            for row in fk_rows
        ],
        "json_integrity_violation_count": len(json_violations),
        "json_integrity_violations": json_violations,
        "orphan_author_merge_count": orphan_author_merges,
        "author_merge_fk_enforcement": (
            "declared_foreign_key" if merge_fk_declared else "legacy_trigger_guard" if merge_guard_triggers else "missing"
        ),
        "single_writer": True,
        "writer_topology": "one application/ingestion writer; concurrent readers allowed",
        "multi_writer_supported": False,
        "status": "ready"
        if foreign_keys == 1
        and journal_mode.lower() in {"wal", "memory"}
        and busy_timeout >= 5_000
        and relational_ready
        else "misconfigured",
    }


def add_missing_columns(connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }
    for column_name, column_type in columns.items():
        if column_name not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def install_author_merge_fk_guard(connection) -> None:
    """Enforce the self-reference for legacy ALTER-migrated SQLite tables.

    SQLite cannot add a foreign-key constraint with ``ALTER TABLE ADD COLUMN``.
    Fresh databases receive the declared SQLModel FK; legacy tables receive an
    equivalent insert/update/delete trigger boundary and are surfaced as such
    in diagnostics.
    """

    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS author_merge_fk_insert "
            "BEFORE INSERT ON author WHEN NEW.merged_into_author_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM author WHERE id = NEW.merged_into_author_id) "
            "BEGIN SELECT RAISE(ABORT, 'author merged_into_author_id foreign key violation'); END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS author_merge_fk_update "
            "BEFORE UPDATE OF merged_into_author_id ON author WHEN NEW.merged_into_author_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM author WHERE id = NEW.merged_into_author_id) "
            "BEGIN SELECT RAISE(ABORT, 'author merged_into_author_id foreign key violation'); END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS author_merge_fk_delete "
            "BEFORE DELETE ON author WHEN EXISTS (SELECT 1 FROM author WHERE merged_into_author_id = OLD.id) "
            "BEGIN SELECT RAISE(ABORT, 'author merge target is still referenced'); END"
        )
    )


def assert_sqlite_relational_integrity(connection) -> None:
    violations = [tuple(row) for row in connection.execute(text("PRAGMA foreign_key_check")).all()]
    orphans = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM author AS child "
                "LEFT JOIN author AS parent ON parent.id = child.merged_into_author_id "
                "WHERE child.merged_into_author_id IS NOT NULL AND parent.id IS NULL"
            )
        ).scalar_one()
    )
    if violations or orphans:
        raise RuntimeError(
            "SQLite relational integrity check failed after migration: "
            f"foreign_key_violations={len(violations)} orphan_author_merges={orphans}"
        )


def install_review_event_immutability(connection) -> None:
    """Enforce append-only review events at the SQLite boundary."""

    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS prevent_review_event_update "
            "BEFORE UPDATE ON reviewevent BEGIN "
            "SELECT RAISE(ABORT, 'review events are append-only'); END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS prevent_review_event_delete "
            "BEFORE DELETE ON reviewevent BEGIN "
            "SELECT RAISE(ABORT, 'review events are append-only'); END"
        )
    )


def install_review_event_chain_uniqueness(connection) -> None:
    """Reject forked hash-chain successors even if an external writer ignores the API lock."""

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS reviewevent_unique_successor_hash "
            "ON reviewevent(previous_event_hash) "
            "WHERE previous_event_hash IS NOT NULL AND event_hash IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS reviewevent_unique_hashed_genesis "
            "ON reviewevent((1)) WHERE previous_event_hash IS NULL AND event_hash IS NOT NULL"
        )
    )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
