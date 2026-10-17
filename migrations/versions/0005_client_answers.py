"""Ответы заказчика: страницы фестивалей, изменения в афише, подраздел субсидий

Ревизия: b7e2d91c4a05
Предыдущая: a51f3c8e2d17
Создана: 2026-10-12 12:00:00

Кроме схемы, на рабочей базе: отдельный подраздел «Сведения об операциях
с целевыми субсидиями» (документы с «субсиди…» в названии переезжают туда
из плана ФХД) и дубль пункта «Контакты» в подменю «Об учреждении».
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'b7e2d91c4a05'
down_revision = 'a51f3c8e2d17'
branch_labels = None
depends_on = None

PFHD = "План финансово-хозяйственной деятельности"
SUBSIDIES = "Сведения об операциях с целевыми субсидиями"
CONTACTS = "Контакты и схема проезда"
ABOUT = "Об учреждении"

pages = sa.table(
    'pages', sa.column('id', sa.Integer), sa.column('title', sa.String), sa.column('slug', sa.String),
    sa.column('content', sa.Text), sa.column('parent_id', sa.Integer), sa.column('sort', sa.Integer),
    sa.column('is_published', sa.Boolean), sa.column('show_in_menu', sa.Boolean),
    sa.column('template', sa.String), sa.column('seo_description', sa.String),
    sa.column('updated_at', sa.DateTime),
)
menu = sa.table(
    'menu_items', sa.column('id', sa.Integer), sa.column('title', sa.String), sa.column('url', sa.String),
    sa.column('page_id', sa.Integer), sa.column('parent_id', sa.Integer), sa.column('sort', sa.Integer),
    sa.column('is_published', sa.Boolean),
)
documents = sa.table('documents', sa.column('title', sa.String), sa.column('category', sa.String))


def upgrade():
    with op.batch_alter_table('festivals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))

    op.create_table(
        'afisha_notices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('show_until', sa.DateTime(), nullable=True),
        sa.Column('sort', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    bind = op.get_bind()
    if bind.execute(sa.select(sa.func.count()).select_from(pages)).scalar():
        _restructure(bind)


def _restructure(bind):
    from filarmonia.utils import slugify

    def page_row(title):
        return bind.execute(sa.select(pages.c.id, pages.c.sort).where(pages.c.title == title)).first()

    def slug_taken(slug):
        return bind.execute(sa.select(pages.c.id).where(pages.c.slug == slug)).first() is not None

    pfhd = page_row(PFHD)
    if pfhd and page_row(SUBSIDIES) is None:
        # Место сразу за планом ФХД: следующие подразделы сдвигаются на одну позицию
        bind.execute(pages.update().where(pages.c.sort > pfhd.sort, pages.c.sort < 200)
                     .values(sort=pages.c.sort + 1))
        bind.execute(pages.insert().values(
            title=SUBSIDIES, slug=slugify(SUBSIDIES, slug_taken),
            content="<p>Сведения об операциях с целевыми субсидиями по годам.</p>",
            parent_id=None, sort=pfhd.sort + 1, is_published=True, show_in_menu=True,
            template='documents_years', seo_description='', updated_at=datetime.utcnow(),
        ))
        bind.execute(documents.update().where(
            documents.c.category == PFHD, documents.c.title.ilike('%субсиди%')).values(category=SUBSIDIES))
        # В подменю «Документы» — сразу за планом ФХД
        pfhd_item = bind.execute(sa.select(menu.c.id, menu.c.parent_id, menu.c.sort)
                                 .where(menu.c.page_id == pfhd.id, menu.c.parent_id.isnot(None))).first()
        if pfhd_item:
            bind.execute(menu.update().where(menu.c.parent_id == pfhd_item.parent_id,
                                             menu.c.sort > pfhd_item.sort).values(sort=menu.c.sort + 10))
            bind.execute(menu.insert().values(
                title=SUBSIDIES, url='', page_id=page_row(SUBSIDIES).id, parent_id=pfhd_item.parent_id,
                sort=pfhd_item.sort + 5, is_published=True))

    contacts, about = page_row(CONTACTS), page_row(ABOUT)
    about_item = bind.execute(sa.select(menu.c.id).where(
        menu.c.page_id == about.id, menu.c.parent_id.is_(None))).first() if about else None
    if contacts and about_item:
        exists = bind.execute(sa.select(menu.c.id).where(
            menu.c.parent_id == about_item.id, menu.c.page_id == contacts.id)).first()
        if not exists:
            last = bind.execute(sa.select(sa.func.max(menu.c.sort)).where(menu.c.parent_id == about_item.id)).scalar()
            bind.execute(menu.insert().values(
                title=CONTACTS, url='', page_id=contacts.id, parent_id=about_item.id,
                sort=(last or 0) + 10, is_published=True))


def downgrade():
    op.drop_table('afisha_notices')
    with op.batch_alter_table('festivals', schema=None) as batch_op:
        batch_op.drop_column('description')
