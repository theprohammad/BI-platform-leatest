"""apollo: leads, contacts, crm_notes, crm_tasks, crm_activities

Revision ID: 0006
Revises: 0005
Additive, reversible. New tables only.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("organization_id", sa.String(length=32), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("company_name", sa.String(length=300), index=True),
        sa.Column("domain", sa.String(length=300), nullable=True, index=True),
        sa.Column("industry", sa.String(length=200), nullable=True, index=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("employee_range", sa.String(length=50), nullable=True),
        sa.Column("enrichment", sa.JSON(), default={}),
        sa.Column("score", sa.Integer(), default=0),
        sa.Column("score_band", sa.String(length=20), default="cold"),
        sa.Column("score_breakdown", sa.JSON(), default={}),
        sa.Column("stage", sa.String(length=40), default="discovered", index=True),
        sa.Column("source", sa.String(length=40), default="discovery"),
        sa.Column("created_at", sa.DateTime(timezone=True), index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
        sa.Column("lead_id", sa.String(length=32), sa.ForeignKey("leads.id"), index=True),
        sa.Column("name", sa.String(length=200)),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("seniority", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=300), nullable=True),
        sa.Column("email_status", sa.String(length=20), default="not_found"),
        sa.Column("linkedin", sa.String(length=300), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    for tbl, cols in {
        "crm_notes": [sa.Column("body", sa.Text()), sa.Column("author", sa.String(length=100), default="user")],
        "crm_tasks": [sa.Column("title", sa.String(length=300)), sa.Column("due_date", sa.String(length=40), nullable=True), sa.Column("done", sa.Boolean(), default=False)],
        "crm_activities": [sa.Column("kind", sa.String(length=40)), sa.Column("summary", sa.Text())],
    }.items():
        op.create_table(
            tbl,
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), index=True),
            sa.Column("lead_id", sa.String(length=32), sa.ForeignKey("leads.id"), index=True),
            *cols,
            sa.Column("created_at", sa.DateTime(timezone=True), index=True),
        )


def downgrade() -> None:
    for tbl in ["crm_activities", "crm_tasks", "crm_notes", "contacts", "leads"]:
        op.drop_table(tbl)
