"""Schema and session plumbing. metadata is the single source of truth; the alembic
migration applies it, and EXPECTED_TABLE_COUNT asserts the result (Standard 4)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from .config import settings

JSON = sa.JSON().with_variant(JSONB(), "postgresql")

metadata = sa.MetaData()

contracts = sa.Table(
    "contracts", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False, unique=True),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("yaml", sa.Text, nullable=False),
    sa.Column("plan_id", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)

probes = sa.Table(
    "probes", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
    sa.Column("probe_key", sa.Text, nullable=False),
    sa.Column("input", sa.Text, nullable=False),
)

probe_variants = sa.Table(
    "probe_variants", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("probe_id", sa.Integer, sa.ForeignKey("probes.id"), nullable=False),
    sa.Column("perturbation", sa.Text, nullable=False),
    sa.Column("variant_input", sa.Text, nullable=False),
    sa.Column("back_check_score", sa.Float),
    sa.Column("accepted", sa.Boolean, nullable=False),
)

experiment_plans = sa.Table(
    "experiment_plans", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
    sa.Column("plan_id", sa.Text, nullable=False, unique=True),
    sa.Column("entries", JSON, nullable=False),
)

runs = sa.Table(
    "runs", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("plan_fk", sa.Integer, sa.ForeignKey("experiment_plans.id"), nullable=False),
    sa.Column("t", sa.Integer, nullable=False),
    sa.Column("seed", sa.Integer, nullable=False),
    sa.Column("sut", sa.Text, nullable=False),
    sa.Column("embedder", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)

consistency_metrics = sa.Table(
    "consistency_metrics", metadata,
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

control_chart_points = sa.Table(
    "control_chart_points", metadata,
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

gate_decisions = sa.Table(
    "gate_decisions", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("contract_id", sa.Integer, sa.ForeignKey("contracts.id"), nullable=False),
    sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
    sa.Column("decision", sa.Text, nullable=False),          # pass | block
    sa.Column("worst_flip_rate", sa.Float, nullable=False),
    sa.Column("threshold", sa.Float, nullable=False),
    sa.Column("evidence", JSON, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)

_engine = None
_Session = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        _engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
        _Session = sessionmaker(bind=_engine)
    return _engine


def get_session():
    get_engine()
    return _Session()


def set_engine_for_tests(engine) -> None:
    """Tests inject their own engine (sqlite in-memory). Explicit, never automatic."""
    global _engine, _Session
    _engine = engine
    _Session = sessionmaker(bind=engine)
