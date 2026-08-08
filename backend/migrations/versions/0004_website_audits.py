"""phase-seo: website_audits table (persisted SEO audit snapshots)

Revision ID: 0004
Revises: 0003
Additive, reversible. New table only — no existing table touched.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_audits",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("organization_id", sa.String(length=32), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("url", sa.String(length=500), index=True),
        sa.Column("ok", sa.Boolean(), default=True),
        sa.Column("scores", sa.JSON(), default={}),
        sa.Column("analysis", sa.JSON(), default={}),
        sa.Column("issue_count", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), index=True),
    )


def downgrade() -> None:
    op.drop_table("website_audits")
