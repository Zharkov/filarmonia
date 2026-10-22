"""Настройка получателя анкет и подписи настроек карты

Ревизия: e3c7a2b9d106
Предыдущая: d2b6f1a8c995
Создана: 2026-10-21 18:00:00

Схема не меняется. В «Настройках» появляется адрес, на который приходят
заполненные анкеты (если его ещё нет), а настройки карты, перенесённой с главной
в «Контакты», получают новые подпись и группу. Значения не трогаются.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e3c7a2b9d106'
down_revision = 'd2b6f1a8c995'
branch_labels = None
depends_on = None

SURVEY_EMAIL = (
    'survey_email', "test@test.ru",
    "Почта, на которую приходят заполненные анкеты с сайта (несколько адресов — через запятую)",
    "Независимая оценка качества",
)
# ключ: (новая подпись, новая группа, прежняя подпись, прежняя группа)
MAP_SETTINGS = {
    'map_point': (
        "Контакты: метка на карте — широта, долгота (из Яндекс Карт: правой кнопкой по зданию → «Что здесь?»)",
        "Контакты",
        "Блок о здании: метка на карте — широта, долгота (из Яндекс Карт: правой кнопкой по зданию → «Что здесь?»)",
        "Главная страница"),
    'history_map': (
        "Контакты: код интерактивной карты (если пусто — карта по метке или адресу)",
        "Контакты",
        "Блок о здании: код интерактивной карты (если пусто — карта по адресу)",
        "Главная страница"),
}

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    bind = op.get_bind()
    key, value, title, group = SURVEY_EMAIL
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
        bind.execute(settings.insert().values(key=key, value=value, title=title, group=group, kind='text'))
    for key, (title, group, _old_title, _old_group) in MAP_SETTINGS.items():
        bind.execute(settings.update().where(settings.c.key == key).values(title=title, group=group))


def downgrade():
    bind = op.get_bind()
    for key, (_title, _group, old_title, old_group) in MAP_SETTINGS.items():
        bind.execute(settings.update().where(settings.c.key == key).values(title=old_title, group=old_group))
    bind.execute(settings.delete().where(settings.c.key == SURVEY_EMAIL[0]))
