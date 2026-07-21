"""baseline — empty schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-21 08:00:00.000000

Baseline migration. Creates no tables; alembic itself creates the alembic_version table,
so after `alembic upgrade head` the public schema holds exactly one table. EXPECTED_TABLE_COUNT
starts at 1 and is raised as real tables are added (Standard 4).
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
