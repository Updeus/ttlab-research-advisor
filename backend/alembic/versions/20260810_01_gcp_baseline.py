"""Create the managed PostgreSQL baseline.

Revision ID: 20260810_01
"""
from alembic import op
from sqlmodel import SQLModel

from app.models import *  # noqa: F403 - registers all tables

revision = "20260810_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("The managed baseline migration is PostgreSQL-only")
    SQLModel.metadata.create_all(bind=bind)
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunk_simple_fts_gin "
        "ON chunk USING GIN (to_tsvector('simple', coalesce(text, '')))"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS keyword_index_manifest ("
        "manifest_id INTEGER PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS public_rate_limit_bucket ("
        "bucket_key VARCHAR(64) PRIMARY KEY, window_start TIMESTAMPTZ NOT NULL, "
        "request_count INTEGER NOT NULL CHECK (request_count > 0))"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION ttlab_reject_reviewevent_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'review events are append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER prevent_review_event_update BEFORE UPDATE ON reviewevent "
        "FOR EACH ROW EXECUTE FUNCTION ttlab_reject_reviewevent_mutation()"
    )
    op.execute(
        "CREATE TRIGGER prevent_review_event_delete BEFORE DELETE ON reviewevent "
        "FOR EACH ROW EXECUTE FUNCTION ttlab_reject_reviewevent_mutation()"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS reviewevent_unique_successor_hash "
        "ON reviewevent(previous_event_hash) WHERE previous_event_hash IS NOT NULL AND event_hash IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS reviewevent_unique_hashed_genesis "
        "ON reviewevent((1)) WHERE previous_event_hash IS NULL AND event_hash IS NOT NULL"
    )
    op.execute(
        "INSERT INTO reviewchainhead (chain_id, updated_at) VALUES (1, CURRENT_TIMESTAMP) "
        "ON CONFLICT (chain_id) DO NOTHING"
    )


def downgrade() -> None:
    raise RuntimeError("The managed baseline is not downgraded in place; restore a prior database instead")
