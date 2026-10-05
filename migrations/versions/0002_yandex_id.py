"""ID сеанса Яндекс Афиши у события

Ревизия: 4889a3fa2f4b
Предыдущая: 31524c3df3fe
Создана: 2026-10-05 09:06:44.500367
"""
from alembic import op
import sqlalchemy as sa


revision = '4889a3fa2f4b'
down_revision = '31524c3df3fe'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('yandex_id', sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('yandex_id')
