"""datasets, dataset items, eval runs and results

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(table: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{table}.id", ondelete="CASCADE")


def _now() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), _fk("projects"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        _now(),
        sa.UniqueConstraint("project_id", "name", name="uq_datasets_project_name"),
    )
    op.create_table(
        "dataset_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), _fk("datasets"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("input", JSONB),
        sa.Column("expected", JSONB, nullable=False),
        sa.UniqueConstraint("dataset_id", "key", name="uq_dataset_items_key"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), _fk("projects"), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), _fk("datasets"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("agent_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", JSONB),
        sa.Column("error", sa.Text()),
        _now(),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_eval_runs_project", "eval_runs", ["project_id", "created_at"])
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("eval_run_id", sa.Uuid(), _fk("eval_runs"), nullable=False),
        sa.Column("item_id", sa.Uuid(), _fk("dataset_items"), nullable=False),
        sa.Column("trace_id", sa.Uuid()),
        sa.Column("output", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("scores", JSONB),
        sa.Column("score", sa.Float()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("cost_usd", sa.Float()),
        sa.UniqueConstraint("eval_run_id", "item_id", name="uq_eval_results_item"),
    )


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("dataset_items")
    op.drop_table("datasets")
