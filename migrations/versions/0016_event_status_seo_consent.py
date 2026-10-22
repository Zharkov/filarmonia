"""Статус концерта, признак «бесплатно», SEO-поля, версия согласия на обработку данных

Ревизия: a5e9c4d2f318
Предыдущая: f4d8b3c1e207
Создана: 2026-10-21 22:00:00

Схема:
  events        status (по плану / отменён / перенесён / отложен), previous_starts_at, is_free,
                seo_title, seo_description
  collectives   seo_title, seo_description
  news          seo_title, seo_description
  appeals       consent_version, consent_at

Данные: у концертов без цены (ни «от», ни «до», ноль тоже считается пустым) и без продажи билетов (нет ни виджета
Яндекса, ни ссылки) ставится is_free — так сайт и раньше называл их бесплатными. В «Настройках» появляются картинка для соцсетей, коды подтверждения
Яндекса и Google, полное название учреждения, необязательный заголовок главной и версия текста согласия. Создаётся страница
«Согласие на обработку персональных данных» — ПРОЕКТ текста, его согласует юрист учреждения.
Уже существующие настройки и страница не перезаписываются.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'a5e9c4d2f318'
down_revision = 'f4d8b3c1e207'
branch_labels = None
depends_on = None

CONSENT_VERSION = '2026-10-21'
CONSENT_SLUG = 'soglasie-na-obrabotku-personalnyh-dannyh'
CONSENT_TITLE = 'Согласие на обработку персональных данных'
POLICY_SLUG = 'politika-konfidencialnosti'

# (ключ, значение, название, группа, тип)
FULL_NAME = 'Областное государственное бюджетное учреждение культуры «Смоленская областная филармония»'

SETTINGS = [
    ('site_full_name', FULL_NAME, 'Полное название учреждения (для поисковиков и документов)', 'Общие', 'text'),
    ('og_image', '', 'Картинка для соцсетей и мессенджеров по умолчанию (1200×630)', 'Поисковики и соцсети', 'file'),
    ('yandex_verification', '', 'Яндекс.Вебмастер: код подтверждения прав (content из meta-тега)',
     'Поисковики и соцсети', 'text'),
    ('google_site_verification', '', 'Google Search Console: код подтверждения прав (content из meta-тега)',
     'Поисковики и соцсети', 'text'),
    ('home_title', '', 'Заголовок главной страницы для поисковиков (пусто — стандартный)',
     'Поисковики и соцсети', 'text'),
    ('consent_version', CONSENT_VERSION,
     'Версия текста согласия на обработку персональных данных (меняйте при правке текста согласия)',
     'Обращения граждан', 'text'),
]

DEFAULT_ADDRESS = '214000, г. Смоленск, ул. Глинки, д. 3'
DEFAULT_EMAIL = 'info@smolensk-filarmonia.ru'

settings = sa.table(
    'settings', sa.column('key', sa.String), sa.column('value', sa.Text), sa.column('title', sa.String),
    sa.column('group', sa.String), sa.column('kind', sa.String),
)
pages = sa.table(
    'pages', sa.column('id', sa.Integer), sa.column('slug', sa.String), sa.column('title', sa.String),
    sa.column('content', sa.Text), sa.column('parent_id', sa.Integer), sa.column('sort', sa.Integer),
    sa.column('is_published', sa.Boolean), sa.column('show_in_menu', sa.Boolean),
    sa.column('template', sa.String), sa.column('seo_description', sa.String),
    sa.column('updated_at', sa.DateTime),
)
events = sa.table(
    'events', sa.column('is_free', sa.Boolean), sa.column('price_min', sa.Integer),
    sa.column('price_max', sa.Integer), sa.column('yandex_id', sa.String), sa.column('ticket_url', sa.String),
)


def consent_text(address: str, email: str) -> str:
    """Проект согласия по ст. 9 152-ФЗ (требования с 1 сентября 2025 г.)."""
    return (
        '<p><strong>Проект текста. Перед публикацией согласовать с юристом учреждения.</strong></p>'
        '<p>Настоящим я, действуя свободно, своей волей и в своём интересе, в соответствии со статьёй 9 '
        'Федерального закона от 27 июля 2006 г. № 152-ФЗ «О персональных данных» даю конкретное, '
        'предметное, информированное, сознательное и однозначное согласие на обработку моих '
        'персональных данных на следующих условиях.</p>'
        '<h2>Оператор</h2>'
        '<p>Областное государственное бюджетное учреждение культуры «Смоленская областная филармония» '
        f'(ОГБУК «Смоленская областная филармония»), адрес: {address}.</p>'
        '<h2>Цель обработки</h2>'
        '<p>Рассмотрение моего обращения, направленного через интернет-приёмную на сайте, '
        'и направление ответа на него.</p>'
        '<h2>Перечень персональных данных</h2>'
        '<ul><li>фамилия, имя, отчество;</li><li>адрес электронной почты;</li>'
        '<li>номер телефона (если указан);</li>'
        '<li>содержание обращения и иные сведения, которые я сообщаю в нём.</li></ul>'
        '<h2>Действия с персональными данными</h2>'
        '<p>Сбор, запись, систематизация, накопление, хранение, уточнение (обновление, изменение), '
        'извлечение, использование, удаление, уничтожение — с использованием средств автоматизации '
        'и без их использования.</p>'
        '<h2>Срок действия согласия и хранения данных</h2>'
        '<p>Согласие действует до рассмотрения обращения и направления ответа, а данные хранятся '
        '5 лет после рассмотрения обращения в соответствии с номенклатурой дел оператора, '
        'после чего уничтожаются.</p>'
        '<h2>Передача третьим лицам</h2>'
        '<p>Персональные данные не передаются третьим лицам, кроме случаев, предусмотренных '
        'законодательством Российской Федерации.</p>'
        '<h2>Отзыв согласия</h2>'
        '<p>Согласие можно отозвать в любое время, направив письменное заявление по адресу оператора '
        f'или на электронную почту {email}, либо обращением через интернет-приёмную на этом сайте. '
        'После отзыва оператор прекращает обработку данных и уничтожает их в срок, установленный '
        'законом, если иное не требуется по закону.</p>'
        f'<p>Версия текста: {CONSENT_VERSION}. Редакция от 21.10.2026.</p>'
    )


def _setting(bind, key, default=''):
    row = bind.execute(sa.select(settings.c.value).where(settings.c.key == key)).first()
    return (row[0] if row and row[0] else default)


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=16), nullable=False, server_default='scheduled'))
        batch_op.add_column(sa.Column('previous_starts_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('is_free', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('seo_title', sa.String(length=200), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('seo_description', sa.String(length=300), nullable=True, server_default=''))
    for table in ('collectives', 'news'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('seo_title', sa.String(length=200), nullable=True, server_default=''))
            batch_op.add_column(sa.Column('seo_description', sa.String(length=300), nullable=True, server_default=''))
    with op.batch_alter_table('appeals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('consent_version', sa.String(length=40), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('consent_at', sa.DateTime(), nullable=True))

    bind = op.get_bind()
    # Бесплатными считались концерты без цены (в форме 0 выглядит пустым полем):
    # сохраняем это явным признаком. Если у концерта есть продажа билетов (виджет Яндекса
    # или ссылка), цена просто не указана, и «бесплатно» писать нельзя.
    no_sale = sa.and_(
        sa.or_(events.c.yandex_id.is_(None), events.c.yandex_id == ''),
        sa.or_(events.c.ticket_url.is_(None), events.c.ticket_url == ''),
    )
    no_min = sa.or_(events.c.price_min.is_(None), events.c.price_min == 0)
    no_max = sa.or_(events.c.price_max.is_(None), events.c.price_max == 0)
    bind.execute(events.update().where(no_min, no_max, no_sale).values(is_free=sa.true()))

    for key, value, title, group, kind in SETTINGS:
        if bind.execute(sa.select(settings.c.key).where(settings.c.key == key)).first() is None:
            bind.execute(settings.insert().values(key=key, value=value, title=title, group=group, kind=kind))

    if bind.execute(sa.select(pages.c.id).where(pages.c.slug == CONSENT_SLUG)).first() is None:
        policy = bind.execute(sa.select(pages.c.parent_id).where(pages.c.slug == POLICY_SLUG)).first()
        bind.execute(pages.insert().values(
            slug=CONSENT_SLUG, title=CONSENT_TITLE, template='page', sort=92,
            content=consent_text(_setting(bind, 'address', DEFAULT_ADDRESS), _setting(bind, 'email', DEFAULT_EMAIL)),
            parent_id=policy[0] if policy else None, is_published=True, show_in_menu=True,
            seo_description='', updated_at=datetime.utcnow(),
        ))


def downgrade():
    # Данные не удаляем: откат убирает только колонки. Страницу согласия и настройки
    # редактор мог изменить, а они ссылаются на юридический текст; лишняя страница или
    # настройка прежней версии сайта не мешает (повторный upgrade их не перезапишет).
    with op.batch_alter_table('appeals', schema=None) as batch_op:
        batch_op.drop_column('consent_at')
        batch_op.drop_column('consent_version')
    for table in ('news', 'collectives'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('seo_description')
            batch_op.drop_column('seo_title')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('seo_description')
        batch_op.drop_column('seo_title')
        batch_op.drop_column('is_free')
        batch_op.drop_column('previous_starts_at')
        batch_op.drop_column('status')
