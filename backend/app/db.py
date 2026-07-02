from collections.abc import Generator
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    db_path = Path(database_url.replace("sqlite:///", "", 1))
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_sqlite_parent(settings.database_url)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_sqlite_schema()


def ensure_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    paper_columns = {
        "extracted_json_path": "VARCHAR",
        "extracted_text_path": "VARCHAR",
        "extraction_diagnostics": "VARCHAR",
        "page_count": "INTEGER",
        "total_char_count": "INTEGER DEFAULT 0 NOT NULL",
        "total_word_count": "INTEGER DEFAULT 0 NOT NULL",
        "pages_with_text": "INTEGER DEFAULT 0 NOT NULL",
        "pages_without_text": "INTEGER DEFAULT 0 NOT NULL",
        "possible_scanned_pdf": "BOOLEAN DEFAULT 0 NOT NULL",
        "chunk_count": "INTEGER DEFAULT 0 NOT NULL",
    }
    chunk_columns = {
        "chunk_index": "INTEGER DEFAULT 0 NOT NULL",
        "char_count": "INTEGER DEFAULT 0 NOT NULL",
        "word_count": "INTEGER DEFAULT 0 NOT NULL",
        "token_count_estimate": "INTEGER",
    }
    with engine.begin() as connection:
        add_missing_columns(connection, "paper", paper_columns)
        add_missing_columns(connection, "chunk", chunk_columns)
        connection.execute(
            text(
                "UPDATE paper SET extraction_diagnostics = '{}' "
                "WHERE extraction_diagnostics IS NULL OR extraction_diagnostics = '[]'"
            )
        )


def add_missing_columns(connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }
    for column_name, column_type in columns.items():
        if column_name not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
