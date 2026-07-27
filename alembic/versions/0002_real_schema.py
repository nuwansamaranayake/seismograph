"""Phase 1 real schema: contracts, probes, variants, plans, runs, metrics, chart points,
gate decisions.

Revision ID: 0002_real_schema
Revises: 0001_baseline
Create Date: 2026-07-23

The DDL below is FROZEN — generated once from app.db.metadata as of this revision and
written out explicitly. It must never import the live metadata: a migration that applies
whatever app/db.py currently says drifts silently (fresh databases get the new shape,
databases already at head keep the old one, under the same revision id). Any future change
to app/db.py requires a new numbered revision. After upgrade the public schema holds
8 app tables + alembic_version = 9. EXPECTED_TABLE_COUNT=9 (Standard 4).
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0002_real_schema"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("yaml", sa.Text, nullable=False),
        sa.Column("plan_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "probes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("probe_key", sa.Text, nullable=False),
        sa.Column("input", sa.Text, nullable=False),
    )
    op.create_table(
        "probe_variants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("probe_id", sa.Integer, sa.ForeignKey("probes.id"), nullable=False),
        sa.Column("perturbation", sa.Text, nullable=False),
        sa.Column("variant_input", sa.Text, nullable=False),
        sa.Column("back_check_score", sa.Float),
        sa.Column("accepted", sa.Boolean, nullable=False),
    )
    op.create_table(
        "experiment_plans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("plan_id", sa.Text, nullable=False, unique=True),
        sa.Column("entries", JSON, nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan_fk", sa.Integer, sa.ForeignKey("experiment_plans.id"),
                  nullable=False),
        sa.Column("t", sa.Integer, nullable=False),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("sut", sa.Text, nullable=False),
        sa.Column("embedder", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "consistency_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("probe_key", sa.Text, nullable=False),
        sa.Column("perturbation", sa.Text, nullable=False),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("malformed_rate", sa.Float, nullable=False),
        sa.Column("flip_rate", JSON, nullable=False),
        sa.Column("jaccard_mean", JSON, nullable=False),
        sa.Column("semantic_variance", sa.Float, nullable=False),
    )
    op.create_table(
        "control_chart_points",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("t", sa.Integer, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("center", sa.Float, nullable=False),
        sa.Column("ucl", sa.Float, nullable=False),
        sa.Column("lcl", sa.Float, nullable=False),
        sa.Column("alarm", sa.Boolean, nullable=False),
        sa.Column("rule", sa.Text),
    )
    op.create_table(
        "gate_decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("decision", sa.Text, nullable=False),          # pass | block
        sa.Column("worst_flip_rate", sa.Float, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("evidence", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in ("gate_decisions", "control_chart_points", "consistency_metrics", "runs",
                  "experiment_plans", "probe_variants", "probes", "contracts"):
        op.drop_table(table)
