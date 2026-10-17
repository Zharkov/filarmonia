"""Карточка ближайшего концерта в баннере главной и счётчик Яндекс Метрики

Ревизия: e5b8f3c0d229
Предыдущая: d4a7e2b9c118
Создана: 2026-10-13 23:00:00

Схема не меняется. В «Настройках» появляются галочка «Показывать в баннере
карточку ближайшего концерта» (включена) и номер счётчика Яндекс Метрики (пусто —
статистика не собирается). Уже существующие настройки не трогаются.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5b8f3c0d229'
down_revision = 'd4a7e2b9c118'
branch_labels = None
depends_on = None

SETTINGS = [
    ('hero_next_event', "1", "Показывать в баннере карточку ближайшего концерта", "Главная страница", 'bool'),
    ('yandex_metrika_id', "", "Номер счётчика Яндекс Метрики (только цифры). Пусто — статистика не собирается",
     "Статистика", 'text'),
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
