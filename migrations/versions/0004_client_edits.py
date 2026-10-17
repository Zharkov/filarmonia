"""Правки заказчика: документы в новостях, фестивали, новая структура разделов

Ревизия: a51f3c8e2d17
Предыдущая: 7c1d2e9a4b30
Создана: 2026-10-08 12:00:00

Кроме схемы, шаг переносит на рабочую базу новую структуру разделов
«Документы» и «Посетителям» и пункт меню «Контакты». Всё ищется по
заголовкам: страница, которой нет, пропускается, уже созданная не дублируется.
Переименованная страница получает новый адрес, а старый перенаправляется на него.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'a51f3c8e2d17'
down_revision = '7c1d2e9a4b30'
branch_labels = None
depends_on = None


# Прежний заголовок -> новый
RENAMES = {
    "Годовые отчёты о деятельности": "Отчёт о деятельности за предыдущие годы",
    "Нормативные правовые акты": "Локальные нормативные акты",
}

# Подразделы «Документов» по порядку: (заголовок, тип страницы, текст новой страницы)
DOCUMENT_PAGES = [
    ("Учредительные документы", "documents", ""),
    ("План финансово-хозяйственной деятельности", "documents_years", ""),
    ("Государственное задание", "documents_years",
     "<p>Государственное задание и отчёты о его выполнении по годам.</p>"),
    ("Отчёт о деятельности за предыдущие годы", "documents_years", ""),
    ("Комплексная оценка условий труда", "documents",
     "<p>Результаты специальной оценки условий труда.</p>"),
    ("Антитеррор", "documents",
     "<p>Документы и памятки по антитеррористической защищённости учреждения.</p>"),
    ("Доступная среда", "documents",
     "<p>Сведения о доступности учреждения для людей с ограниченными возможностями здоровья.</p>"),
    ("Локальные нормативные акты", "documents", ""),
    ("Услуги", "documents", ""),
]

VISITORS = "Посетителям"
# Подразделы «Посетителям» по порядку: (заголовок, текст новой страницы)
VISITOR_PAGES = [
    ("Правила посещения", ""),
    ("Правила продажи и возврата билетов",
     "<p>Порядок покупки билетов в кассе и на сайте, условия возврата.</p>"),
    ("Цифровой ID", "<p>Как пройти на концерт по цифровому ID.</p>"),
    ("Пушкинская карта", ""),
    ("Льготное посещение", ""),
    ("Информация о работе кассы", "<p>Режим работы кассы и способы оплаты.</p>"),
]

CONTACTS = "Контакты и схема проезда"

FESTIVALS = [
    ("Фестиваль имени М. И. Глинки", "festival-imeni-m-i-glinki"),
    ("Фестиваль имени В. П. Дубровского", "festival-imeni-v-p-dubrovskogo"),
    ("Фестиваль «Большая сцена — талантливым детям»", "festival-bolshaya-scena-talantlivym-detyam"),
]

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
documents = sa.table('documents', sa.column('category', sa.String))
redirects = sa.table(
    'redirects', sa.column('old_path', sa.String), sa.column('new_url', sa.String),
    sa.column('hits', sa.Integer), sa.column('created_at', sa.DateTime),
)
settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)


def upgrade():
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('news_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_documents_news_id'), ['news_id'], unique=False)
        batch_op.create_foreign_key('fk_documents_news_id', 'news', ['news_id'], ['id'])

    festivals = op.create_table(
        'festivals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_table(
        'event_festivals',
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('festival_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['festival_id'], ['festivals.id']),
        sa.PrimaryKeyConstraint('event_id', 'festival_id'),
    )
    op.bulk_insert(festivals, [
        {"name": name, "slug": slug, "sort": (i + 1) * 10} for i, (name, slug) in enumerate(FESTIVALS)
    ])

    bind = op.get_bind()
    # Новая база: страниц ещё нет, структуру создаст наполнение (seed)
    if bind.execute(sa.select(sa.func.count()).select_from(pages)).scalar():
        _restructure(bind)
    if bind.execute(sa.select(settings.c.key).where(settings.c.key == 'work_hours')).first() is None:
        bind.execute(settings.insert().values(
            key='work_hours', value="Пн–пт 9:00–18:00. Касса ежедневно 11:00–19:00",
            title="Режим работы", group="Контакты", kind="textarea",
        ))


def _restructure(bind):
    from filarmonia.utils import slugify

    now = datetime.utcnow()

    def page_id(title):
        row = bind.execute(sa.select(pages.c.id).where(pages.c.title == title)).first()
        return row[0] if row else None

    def slug_taken(slug):
        return bind.execute(sa.select(pages.c.id).where(pages.c.slug == slug)).first() is not None

    def ensure_page(title, template, content, parent_id=None):
        found = page_id(title)
        if found:
            return found
        slug = slugify(title, slug_taken)
        bind.execute(pages.insert().values(
            title=title, slug=slug, content=content, parent_id=parent_id, sort=100,
            is_published=True, show_in_menu=True, template=template, seo_description='',
            updated_at=now,
        ))
        return page_id(title)

    for old, new in RENAMES.items():
        old_id = page_id(old)
        if old_id is None or page_id(new):
            continue
        old_slug = bind.execute(sa.select(pages.c.slug).where(pages.c.id == old_id)).scalar()
        new_slug = slugify(new, slug_taken)
        bind.execute(pages.update().where(pages.c.id == old_id).values(title=new, slug=new_slug))
        bind.execute(documents.update().where(documents.c.category == old).values(category=new))
        bind.execute(menu.update().where(menu.c.title == old).values(title=new))
        old_path = f"/info/{old_slug}"
        if bind.execute(sa.select(redirects.c.old_path).where(redirects.c.old_path == old_path)).first() is None:
            bind.execute(redirects.insert().values(
                old_path=old_path, new_url=f"/info/{new_slug}", hits=0, created_at=now))

    doc_ids = []
    for i, (title, template, content) in enumerate(DOCUMENT_PAGES):
        pid = ensure_page(title, template, content)
        bind.execute(pages.update().where(pages.c.id == pid).values(template=template, sort=101 + i))
        doc_ids.append((title, pid))

    visitors_id = ensure_page(VISITORS, "page", "")
    visitor_ids = []
    for i, (title, content) in enumerate(VISITOR_PAGES):
        pid = ensure_page(title, "page", content, visitors_id)
        bind.execute(pages.update().where(pages.c.id == pid).values(parent_id=visitors_id, sort=31 + i))
        visitor_ids.append((title, pid))

    # Подменю «Документы» и «Посетителям» собираются заново в новом составе
    docs_item = bind.execute(sa.select(menu.c.id).where(
        menu.c.url == '/dokumenty', menu.c.parent_id.is_(None))).first()
    if docs_item:
        _fill_submenu(bind, docs_item[0], doc_ids)
    visitors_item = bind.execute(sa.select(menu.c.id).where(
        menu.c.page_id == visitors_id, menu.c.parent_id.is_(None))).first()
    if visitors_item:
        _fill_submenu(bind, visitors_item[0], visitor_ids)

    contacts_id = page_id(CONTACTS)
    has_contacts = bind.execute(sa.select(menu.c.id).where(
        menu.c.parent_id.is_(None), menu.c.title == 'Контакты')).first()
    if contacts_id and not has_contacts:
        last = bind.execute(sa.select(sa.func.max(menu.c.sort)).where(menu.c.parent_id.is_(None))).scalar()
        bind.execute(menu.insert().values(
            title='Контакты', url='', page_id=contacts_id, parent_id=None,
            sort=(last or 0) + 10, is_published=True))


def _fill_submenu(bind, parent_id, children):
    bind.execute(menu.delete().where(menu.c.parent_id == parent_id))
    for i, (title, pid) in enumerate(children):
        bind.execute(menu.insert().values(
            title=title, url='', page_id=pid, parent_id=parent_id, sort=(i + 1) * 10, is_published=True))


def downgrade():
    # Структура разделов назад не возвращается: это правка содержимого, а не схемы
    op.drop_table('event_festivals')
    op.drop_table('festivals')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_documents_news_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_documents_news_id'))
        batch_op.drop_column('news_id')
