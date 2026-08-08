"""opportunity lifecycle state overlay

Revision ID: 0007
Revises: 0006
Additive, reversible. One new table.

Why this table exists
---------------------
Opportunities are *derived* from the Intelligence Graph (recommendations,
validated findings, competitor pressure, pipeline signals) — they are not stored
records, and duplicating them would create a second source of truth that drifts
from the graph. But lifecycle decisions (status, owner) are user input that
cannot be derived from evidence.

So this table stores ONLY the decision overlay, keyed by a stable opportunity
key, and nothing about the opportunity's content. The graph remains the single
source of truth for what the opportunity *is*.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunity_states",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32),
                  sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("organization_id", sa.String(length=32),
                  sa.ForeignKey("organizations.id"), index=True),
        # Stable identity of the derived opportunity (e.g. the backing insight
        # id, or a synthetic key for cross-module signals).
        sa.Column("opportunity_key", sa.String(length=120), index=True),
        sa.Column("status", sa.String(length=20), default="new"),
        sa.Column("owner", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "organization_id", "opportunity_key",
                            name="uq_opportunity_state"),
    )


def downgrade() -> None:
    op.drop_table("opportunity_states")
