"""Страница «Независимая оценка качества»: анкета с QR-кодом

Ревизия: c3f8a1d6e924
Предыдущая: b7e2d91c4a05
Создана: 2026-10-13 12:00:00

Схема не меняется. На рабочей базе страница НОК получает свой тип «nok»,
а в «Настройках» появляются ссылки на анкету и на результаты оценки.
Текст-заглушка страницы из первого наполнения заменяется пояснением о НОК;
текст, который уже правил редактор, не трогается.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f8a1d6e924'
down_revision = 'b7e2d91c4a05'
branch_labels = None
depends_on = None

NOK_SLUG = 'nezavisimaya-ocenka-kachestva'
GROUP = "Независимая оценка качества"
SETTINGS = [
    ('nok_survey_url', "https://forms.mkrf.ru/e/2579/xTPLeBU7/",
     "Ссылка на анкету Минкультуры (с кодом учреждения ap_orgcode=…). По ней же строится QR-код"),
    ('nok_results_url', "https://bus.gov.ru/",
     "Ссылка на результаты оценки филармонии на bus.gov.ru (пусто — кнопку не показывать)"),
]

OLD_TEXT = ("<p>Результаты независимой оценки качества условий оказания услуг, план по улучшению "
            "и отчёт о его выполнении.</p>")
NEW_TEXT = (
    "<h2>Что такое независимая оценка качества</h2>"
    "<p>Независимая оценка качества условий оказания услуг организациями культуры проводится "
    "в соответствии со статьёй 36.1 Основ законодательства Российской Федерации о культуре. "
    "Оцениваются открытость и доступность информации об учреждении, комфортность условий, "
    "доступность услуг для людей с инвалидностью, доброжелательность и вежливость работников, "
    "удовлетворённость условиями оказания услуг.</p>"
    "<p>По итогам оценки филармония утверждает план по устранению выявленных недостатков "
    "и публикует отчёт о его выполнении.</p>"
)

pages = sa.table('pages', sa.column('slug', sa.String), sa.column('template', sa.String),
                 sa.column('content', sa.Text))
settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    bind = op.get_bind()
    bind.execute(pages.update().where(pages.c.slug == NOK_SLUG, pages.c.template == 'documents')
                 .values(template='nok'))
    bind.execute(pages.update().where(pages.c.slug == NOK_SLUG, pages.c.content == OLD_TEXT)
                 .values(content=NEW_TEXT))
    for key, value, title in SETTINGS:
        if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
            bind.execute(settings.insert().values(key=key, value=value, title=title, group=GROUP, kind='text'))


def downgrade():
    bind = op.get_bind()
    bind.execute(pages.update().where(pages.c.template == 'nok').values(template='documents'))
    bind.execute(settings.delete().where(settings.c.key.in_([key for key, _, _ in SETTINGS])))
