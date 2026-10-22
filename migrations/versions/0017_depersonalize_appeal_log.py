"""Обезличивание старых записей журнала по обращениям граждан

Ревизия: b7d1e6a39c42
Предыдущая: a5e9c4d2f318
Создана: 2026-10-21 23:00:00

Данные: раньше в названии записи журнала по обращению могла стоять тема письма (а в ней — фамилия
или иные персональные данные). Теперь журнал хранит только «Обращение № <номер>» (см. title_of
в admin/common.py), и старые записи приводятся к тому же виду. Схема не меняется.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d1e6a39c42'
down_revision = 'a5e9c4d2f318'
branch_labels = None
depends_on = None

action_log = sa.table(
    'action_log', sa.column('title', sa.String), sa.column('object_type', sa.String),
    sa.column('object_id', sa.Integer),
)


def upgrade():
    # CAST AS VARCHAR и оператор || одинаково работают в SQLite и PostgreSQL
    op.get_bind().execute(
        action_log.update()
        .where(action_log.c.object_type == 'appeal', action_log.c.object_id.isnot(None))
        .values(title=sa.literal('Обращение № ') + sa.cast(action_log.c.object_id, sa.String(20)))
    )


def downgrade():
    # Прежние названия содержали персональные данные — не восстанавливаем
    pass
