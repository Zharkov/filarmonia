"""Убрана карточка ближайшего концерта из баннера главной

Ревизия: f6c9a4d1e33a
Предыдущая: e5b8f3c0d229
Создана: 2026-10-17 12:00:00

Схема не меняется. Из «Настроек» удаляется галочка «Показывать в баннере
карточку ближайшего концерта» — карточки на сайте больше нет.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6c9a4d1e33a'
down_revision = 'e5b8f3c0d229'
branch_labels = None
depends_on = None

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    op.get_bind().execute(settings.delete().where(settings.c.key == 'hero_next_event'))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == 'hero_next_event')).first() is None:
        bind.execute(settings.insert().values(
            key='hero_next_event', value="1", title="Показывать в баннере карточку ближайшего концерта",
            group="Главная страница", kind='bool'))
