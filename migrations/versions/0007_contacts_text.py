"""«Контакты»: адрес и телефон не повторяются в тексте страницы

Ревизия: d4a7e2b9c118
Предыдущая: c3f8a1d6e924
Создана: 2026-10-13 22:00:00

Схема не меняется. Адрес, телефон, почту и режим работы страница «Контакты»
выводит из «Настроек» блоком под заголовком, а текст-заглушка из первого
наполнения повторял адрес и телефон ещё раз. В заглушке остаётся только
строка о проезде; текст, который уже правил редактор, не трогается.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a7e2b9c118'
down_revision = 'c3f8a1d6e924'
branch_labels = None
depends_on = None

OLD_TEXT = ("<p>214000, г. Смоленск, ул. Глинки, д. 3.</p><p>Касса: +7 (4812) 38-31-81.</p>"
            "<p>Проезд: остановка «Площадь Ленина», автобусы и маршрутные такси.</p>")
NEW_TEXT = "<p>Проезд: остановка «Площадь Ленина», автобусы и маршрутные такси.</p>"

pages = sa.table('pages', sa.column('template', sa.String), sa.column('content', sa.Text))


def upgrade():
    op.get_bind().execute(pages.update().where(pages.c.template == 'contacts', pages.c.content == OLD_TEXT)
                          .values(content=NEW_TEXT))


def downgrade():
    op.get_bind().execute(pages.update().where(pages.c.template == 'contacts', pages.c.content == NEW_TEXT)
                          .values(content=OLD_TEXT))
