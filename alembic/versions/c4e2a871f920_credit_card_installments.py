"""credit card installment plans and payments

Revision ID: c4e2a871f920
Revises: a91e4b2c7d11
Create Date: 2026-09-19 06:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e2a871f920'
down_revision: Union[str, Sequence[str], None] = 'a91e4b2c7d11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'installment_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('credit_card_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('total_amount', sa.Float(), nullable=False),
        sa.Column('installment_count', sa.Integer(), nullable=False),
        sa.Column('installment_amount', sa.Float(), nullable=False),
        sa.Column('first_due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['credit_card_id'], ['credit_cards.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_installment_plans_id'), 'installment_plans', ['id'], unique=False)
    op.create_index('ix_installment_plans_owner_status', 'installment_plans', ['owner_id', 'status'], unique=False)
    op.create_index('ix_installment_plans_card', 'installment_plans', ['credit_card_id'], unique=False)

    op.create_table(
        'installment_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('installment_plan_id', sa.Integer(), nullable=False),
        sa.Column('installment_number', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('transaction_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['installment_plan_id'], ['installment_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('installment_plan_id', 'installment_number', name='uq_installment_plan_number'),
    )
    op.create_index(op.f('ix_installment_payments_id'), 'installment_payments', ['id'], unique=False)
    op.create_index('ix_installment_payments_plan_status', 'installment_payments', ['installment_plan_id', 'status'], unique=False)
    op.create_index('ix_installment_payments_due_date', 'installment_payments', ['due_date'], unique=False)

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('installment_plan_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_transactions_installment_plan_id', 'installment_plans', ['installment_plan_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_transactions_installment_plan_id', type_='foreignkey')
        batch_op.drop_column('installment_plan_id')

    op.drop_index('ix_installment_payments_due_date', table_name='installment_payments')
    op.drop_index('ix_installment_payments_plan_status', table_name='installment_payments')
    op.drop_index(op.f('ix_installment_payments_id'), table_name='installment_payments')
    op.drop_table('installment_payments')

    op.drop_index('ix_installment_plans_card', table_name='installment_plans')
    op.drop_index('ix_installment_plans_owner_status', table_name='installment_plans')
    op.drop_index(op.f('ix_installment_plans_id'), table_name='installment_plans')
    op.drop_table('installment_plans')
