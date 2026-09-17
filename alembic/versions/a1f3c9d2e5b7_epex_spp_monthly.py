"""add epex_spp_monthly table (prix mensuel EPEX SPP pour la formule Octa+)

Revision ID: a1f3c9d2e5b7
Revises: 5c9b22bdbf25
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d2e5b7'
down_revision: Union[str, None] = '5c9b22bdbf25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table('epex_spp_monthly')
