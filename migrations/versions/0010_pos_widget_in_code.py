"""Виджет «Госуслуги. Решаем вместе» встроен в шаблон главной

Ревизия: a7d2b5e8f441
Предыдущая: f6c9a4d1e33a
Создана: 2026-10-17 14:00:00

Схема не меняется. Код виджета теперь в public/_pos_widget.html, поэтому из
«Настроек» удаляется поле «Код виджета „Госуслуги. Решаем вместе“», а из
«Баннеров» — баннеры места «Главная, крупно»: они были запасным вариантом
на случай пустого поля и больше нигде не выводятся.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7d2b5e8f441'
down_revision = 'f6c9a4d1e33a'
branch_labels = None
depends_on = None

POS_TITLE = ("Код виджета «Госуслуги. Решаем вместе» (если пусто — баннер из раздела "
             "«Баннеры», место «Главная, крупно»)")

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)
banners = sa.table(
    'banners', sa.column('title', sa.String), sa.column('url', sa.String), sa.column('image', sa.String),
    sa.column('place', sa.String), sa.column('sort', sa.Integer), sa.column('is_published', sa.Boolean),
)


def upgrade():
    bind = op.get_bind()
    bind.execute(settings.delete().where(settings.c.key == 'pos_widget'))
    bind.execute(banners.delete().where(banners.c.place == 'main'))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == 'pos_widget')).first() is None:
        bind.execute(settings.insert().values(
            key='pos_widget', value="", title=POS_TITLE, group="Главная страница", kind='html'))
    bind.execute(banners.insert().values(
        title="Госуслуги. Решаем вместе", url="https://pos.gosuslugi.ru/landing/", image="",
        place='main', sort=10, is_published=True))
