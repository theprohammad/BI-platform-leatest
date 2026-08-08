"""phase3: claims.value_entity_id (B9 — canonical entity-valued predicates)

Revision ID: 0003
Revises: 0002
Additive, reversible. Existing rows stay NULL (string comparison fallback).
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("claims") as batch:
        batch.add_column(sa.Column("value_entity_id", sa.String(length=32),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("claims") as batch:
        batch.drop_column("value_entity_id")
