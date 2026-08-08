"""crayon: competitor_snapshots + competitor_changes

Revision ID: 0005
Revises: 0004
Additive, reversible. New tables only.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competitor_snapshots",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("organization_id", sa.String(length=32), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("competitor_entity_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("competitor_name", sa.String(length=300)),
        sa.Column("url", sa.String(length=500), index=True),
        sa.Column("page_type", sa.String(length=40), default="homepage"),
        sa.Column("signals", sa.JSON(), default={}),
        sa.Column("content_hash", sa.String(length=64), default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), index=True),
    )
    op.create_table(
        "competitor_changes",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("organization_id", sa.String(length=32), sa.ForeignKey("organizations.id"), index=True),
        sa.Column("competitor_name", sa.String(length=300), index=True),
        sa.Column("url", sa.String(length=500)),
        sa.Column("category", sa.String(length=40), index=True),
        sa.Column("severity", sa.String(length=20), default="medium"),
        sa.Column("summary", sa.Text()),
        sa.Column("before", sa.Text(), nullable=True),
        sa.Column("after", sa.Text(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), default=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), index=True),
    )


def downgrade() -> None:
    op.drop_table("competitor_changes")
    op.drop_table("competitor_snapshots")
