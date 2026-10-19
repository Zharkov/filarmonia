"""Изменение в афише связывается с концертом

Ревизия: c9f4d7a1b663
Предыдущая: b8e3c6f9a552
Создана: 2026-10-19 15:00:00

В записи «Изменения в афише» появляется концерт из афиши: «Подробнее» ведёт
на его страницу. Удаление концерта связь обнуляет, сама запись остаётся.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9f4d7a1b663'
down_revision = 'b8e3c6f9a552'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('afisha_notices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_afisha_notices_event_id', 'events', ['event_id'], ['id'],
                                    ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('afisha_notices', schema=None) as batch_op:
        batch_op.drop_constraint('fk_afisha_notices_event_id', type_='foreignkey')
        batch_op.drop_column('event_id')
