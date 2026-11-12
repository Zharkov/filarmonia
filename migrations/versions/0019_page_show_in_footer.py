"""Флаг show_in_footer на странице — вывод в колонке документов подвала.

Ревизия: a1b2c3d4e5f6
Предыдущая: c8f2a5d3e419
Создана: 2026-11-09 12:00:00

Новая колонка show_in_footer в pages (Boolean, False по умолчанию).
Страницы, отмеченные флагом, выводятся в колонке «Обязательные ссылки»
подвала после захардкоженных ссылок.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'c8f2a5d3e419'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pages', sa.Column('show_in_footer', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('pages', 'show_in_footer')
