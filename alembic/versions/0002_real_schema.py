"""Phase 1 real schema: contracts, probes, variants, plans, runs, metrics, chart points,
gate decisions.

Revision ID: 0002_real_schema
Revises: 0001_baseline
Create Date: 2026-07-23

app.db.metadata is the single source of truth; this migration applies it. After upgrade the
public schema holds 8 app tables + alembic_version = 9. EXPECTED_TABLE_COUNT=9 (Standard 4).
"""
import sys
from pathlib import Path

from alembic import op

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

revision = "0002_real_schema"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import metadata
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    from app.db import metadata
    metadata.drop_all(op.get_bind())
