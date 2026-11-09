"""outcome_modes and judge_calibrations: the Phase 2 instrument tables.

FROZEN DDL. This mirrors app/db.py at the time of writing and must never import
live metadata: a later edit to app/db.py must produce a NEW revision, not a
silent change to this one.

11 app tables + alembic_version = 12. EXPECTED_TABLE_COUNT=12 (Standard 4).

Revision ID: 0004_modes_and_judges
Revises: 0003_target_calls
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0004_modes_and_judges"
down_revision = "0003_target_calls"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "outcome_modes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("probe_key", sa.Text, nullable=False),
        sa.Column("perturbation", sa.Text, nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("modes", JSON, nullable=False),
        sa.Column("second_mode_share", sa.Float, nullable=False),
        sa.Column("second_mode_detected", sa.Boolean, nullable=False),
    )
    op.create_index("ix_outcome_modes_run_id", "outcome_modes", ["run_id"])
    op.create_table(
        "judge_calibrations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("judge", sa.Text, nullable=False),
        sa.Column("round", sa.Integer, nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("agree", sa.Integer, nullable=False),
        sa.Column("rate", sa.Float, nullable=False),
        sa.Column("kappa", sa.Float, nullable=False),
        sa.Column("quarantined", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("judge", "round", name="uq_judge_round"),
    )


def downgrade() -> None:
    op.drop_table("judge_calibrations")
    op.drop_index("ix_outcome_modes_run_id", table_name="outcome_modes")
    op.drop_table("outcome_modes")
