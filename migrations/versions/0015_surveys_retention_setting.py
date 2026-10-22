"""Срок хранения ответов на анкеты НОК

Ревизия: f4d8b3c1e207
Предыдущая: e3c7a2b9d106
Создана: 2026-10-21 20:00:00

Схема не меняется. В «Настройках» появляется срок хранения ответов на анкеты
(3 года), если его ещё нет. Существующие значения не трогаются. Удаление по сроку
выполняет команда `python app.py purge`.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f4d8b3c1e207'
down_revision = 'e3c7a2b9d106'
branch_labels = None
depends_on = None

SURVEYS_RETENTION = (
    'surveys_retention_years', "3",
    "Срок хранения ответов на анкеты НОК, лет (0 — хранить бессрочно)",
    "Независимая оценка качества",
)

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    bind = op.get_bind()
    key, value, title, group = SURVEYS_RETENTION
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
        bind.execute(settings.insert().values(key=key, value=value, title=title, group=group, kind='text'))


def downgrade():
    op.get_bind().execute(settings.delete().where(settings.c.key == SURVEYS_RETENTION[0]))
