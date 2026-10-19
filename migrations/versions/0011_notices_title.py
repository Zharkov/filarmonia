"""Заголовок всплывающего окна «Изменения в афише»

Ревизия: b8e3c6f9a552
Предыдущая: a7d2b5e8f441
Создана: 2026-10-19 12:00:00

Схема не меняется. Изменения в афише теперь показываются не плашкой под меню,
а окном в правом нижнем углу; его заголовок редактируется в разделе
«Изменения в афише» и в «Настройках». Уже существующая настройка не трогается.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8e3c6f9a552'
down_revision = 'a7d2b5e8f441'
branch_labels = None
depends_on = None

SETTINGS = [
    ('notices_title', "Изменения в афише", "Заголовок всплывающего окна об отменах и переносах концертов",
     "Изменения в афише", 'text'),
]

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    bind = op.get_bind()
    for key, value, title, group, kind in SETTINGS:
        if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
            bind.execute(settings.insert().values(key=key, value=value, title=title, group=group, kind=kind))


def downgrade():
    op.get_bind().execute(settings.delete().where(settings.c.key.in_([key for key, *_ in SETTINGS])))
