"""Настройка текста над списком коллективов

Ревизия: c8f2a5d3e419
Предыдущая: b7d1e6a39c42
Создана: 2026-11-03 10:00:00

Схема не меняется. Подводка страницы «Коллективы и артисты» была зашита в шаблон,
и редактор не мог её поправить. В «Настройках» появляется соответствующая строка
(если её ещё нет) со прежним текстом; значения редактора не затираются.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8f2a5d3e419'
down_revision = 'b7d1e6a39c42'
branch_labels = None
depends_on = None

COLLECTIVES_LEAD = (
    'collectives_lead',
    "Оркестры, ансамбли и солисты филармонии. У каждого коллектива — фото и видео, "
    "контакты для заявок и подробный рассказ.",
    "Текст над списком на странице «Коллективы и артисты»",
    "Страницы",
)

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    bind = op.get_bind()
    key, value, title, group = COLLECTIVES_LEAD
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
        bind.execute(settings.insert().values(key=key, value=value, title=title, group=group, kind='html'))


def downgrade():
    op.get_bind().execute(settings.delete().where(settings.c.key == COLLECTIVES_LEAD[0]))
