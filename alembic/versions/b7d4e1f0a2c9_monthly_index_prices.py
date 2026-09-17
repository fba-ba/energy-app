"""generalize epex_spp_monthly into monthly_index_prices (multi-index support)

Revision ID: b7d4e1f0a2c9
Revises: a1f3c9d2e5b7
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4e1f0a2c9'
down_revision: Union[str, None] = 'a1f3c9d2e5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'monthly_index_prices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('index_key', sa.String(length=32), nullable=False),
        sa.Column('month', sa.String(length=10), nullable=False),
        sa.Column('price_eur_mwh_micro', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('index_key', 'month', name='uq_monthly_index_prices_key_month'),
    )

    # Reprise des données existantes (EPEX SPP, utilisé par Octa+).
    op.execute(
        "INSERT INTO monthly_index_prices (index_key, month, price_eur_mwh_micro, created_at, updated_at) "
        "SELECT 'epex_spp', month, price_eur_mwh_micro, created_at, updated_at FROM epex_spp_monthly"
    )
    op.drop_table('epex_spp_monthly')


def downgrade() -> None:
    op.create_table(
        'epex_spp_monthly',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('month', sa.String(length=10), nullable=False),
        sa.Column('price_eur_mwh_micro', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('month', name='uq_epex_spp_monthly_month'),
    )
    op.execute(
        "INSERT INTO epex_spp_monthly (month, price_eur_mwh_micro, created_at, updated_at) "
        "SELECT month, price_eur_mwh_micro, created_at, updated_at FROM monthly_index_prices "
        "WHERE index_key = 'epex_spp'"
    )
    op.drop_table('monthly_index_prices')
