"""backup import tracking and recurring occurrence uniqueness

Revision ID: a91e4b2c7d11
Revises: 244dfe73397e
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a91e4b2c7d11"
down_revision: Union[str, Sequence[str], None] = "244dfe73397e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backup_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "fingerprint", name="uq_backup_import_owner_fingerprint"),
    )
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_transactions_recurring_occurrence",
            ["owner_id", "recurring_transaction_id", "occurred_on"],
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("uq_transactions_recurring_occurrence", type_="unique")
    op.drop_table("backup_imports")
