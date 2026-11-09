"""target_calls — the audit row every adapter call writes.

FROZEN DDL. This mirrors app/db.py at the time of writing and must never import
live metadata: a later edit to app/db.py must produce a NEW revision, not a
silent change to this one.

9 app tables + alembic_version = 10. EXPECTED_TABLE_COUNT=10 (Standard 4).

Revision ID: 0003_target_calls
Revises: 0002_real_schema
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0003_target_calls"
down_revision = "0002_real_schema"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "target_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column("adapter", sa.Text, nullable=False),
        sa.Column("route", sa.Text, nullable=False),
        sa.Column("arguments_hash", sa.Text, nullable=False),
        sa.Column("raw_response", JSON),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("target_calls")
