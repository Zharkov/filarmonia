"""Модели базы данных Смоленской областной филармонии."""

import re
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash, generate_password_hash

from .utils import now_msk, utcnow

db = SQLAlchemy()

UPLOADS_URL = "/static/uploads/"


@event.listens_for(Engine, "connect")
def _sqlite_unicode_lower(dbapi_connection, _record):
    """Поиск без учёта регистра для русских букв на SQLite.

    `ilike` на SQLite превращается в `lower(колонка) LIKE lower(запрос)`, а
    встроенный lower в SQLite переводит в строчные только латиницу: «Концерт»
    не находился по запросу «концерт». Подменяем его питоновским str.lower.
    PostgreSQL на боевом сервере понимает регистр кириллицы сам, его не трогаем.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(
            "lower", 1, lambda value: value.lower() if isinstance(value, str) else value,
            deterministic=True,
        )


class HasMedia:
    """Общее для событий, коллективов, новостей и альбомов: фото и видео.

    Списки берутся из уже загруженного `media`, без дополнительных запросов.
    """

    @property
    def photos(self) -> list:
        return [m for m in self.media if m.kind == "photo"]

    @property
    def videos(self) -> list:
        return [m for m in self.media if m.kind == "video"]


# Пользователи
class User(db.Model):
    """Сотрудник, работающий с панелью администратора."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="editor")  # admin | editor
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# Настройки
class Setting(db.Model):
    """Пары ключ-значение: телефоны, адрес, видео на главной, тексты по умолчанию."""

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, default="")
    title = db.Column(db.String(160), default="")
    group = db.Column(db.String(64), default="Общие")
    kind = db.Column(db.String(16), default="text")  # text | textarea | html | file | bool

    @staticmethod
    def get(key: str, default: str = "") -> str:
        row = db.session.get(Setting, key)
        return row.value if row and row.value else default

    @staticmethod
    def set(key: str, value: str) -> None:
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.session.add(row)
        row.value = value


# Меню/страницы
class Page(db.Model, HasMedia):
    """Статическая страница (Об учреждении, Услуги, Отчёты, НПА и т.д.).

    К странице можно прикрепить фото и видео: так на «Структуре и органах
    управления» размещают схему, а фото «Истории» идут в карусель на главной.
    """

    __tablename__ = "pages"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, default="")
    parent_id = db.Column(db.Integer, db.ForeignKey("pages.id"))
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    show_in_menu = db.Column(db.Boolean, default=True, nullable=False)
    # page | documents | contacts | pushkin | benefits
    template = db.Column(db.String(32), default="page")
    seo_description = db.Column(db.String(400), default="")
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    children = db.relationship(
        "Page",
        backref=db.backref("parent", remote_side=[id]),
        order_by="Page.sort",
        cascade="all",
    )
    media = db.relationship(
        "MediaItem", backref="page", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/info/{self.slug}"


class MenuItem(db.Model):
    """Пункт главного меню. Может вести на страницу, раздел или внешний адрес."""

    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(400), default="")
    page_id = db.Column(db.Integer, db.ForeignKey("pages.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"))
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)

    page = db.relationship("Page")
    children = db.relationship(
        "MenuItem",
        backref=db.backref("parent", remote_side=[id]),
        order_by="MenuItem.sort",
        cascade="all",
    )

    @property
    def href(self) -> str:
        if self.page_id and self.page:
            return self.page.url
        return self.url or "#"


# Афиша
event_collectives = db.Table(
    "event_collectives",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id"), primary_key=True),
    db.Column("collective_id", db.Integer, db.ForeignKey("collectives.id"), primary_key=True),
)


class Venue(db.Model):
    """Концертная площадка."""

    __tablename__ = "venues"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    address = db.Column(db.String(300), default="")
    description = db.Column(db.Text, default="")
    map_embed = db.Column(db.Text, default="")  # код интерактивной карты


# Метки жанров для «Музыкального маршрута»: по ним подбираются концерты
# под ответы посетителя. Ключ хранится в базе, подпись видит редактор.
ROUTE_TAGS = [
    ("calm", "Спокойное вдохновение"),
    ("romance", "Тёплая романтика"),
    ("energy", "Энергия и драйв"),
    ("discover", "Новые открытия"),
    ("family", "Для семьи с детьми"),
]


class Category(db.Model):
    """Жанр или категория события: классика, детям, джаз, органная музыка."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    sort = db.Column(db.Integer, default=100)
    route_tags = db.Column(db.String(200), default="")  # ключи ROUTE_TAGS через запятую

    @property
    def tags(self) -> set:
        return {t for t in (self.route_tags or "").split(",") if t}


class Event(db.Model, HasMedia):
    """Концерт или спектакль."""

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(300), unique=True, nullable=False)
    poster = db.Column(db.String(300), default="")  # афиша (вертикальная)
    cover = db.Column(db.String(300), default="")   # горизонтальное фото для карточки
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_min = db.Column(db.Integer)
    age_limit = db.Column(db.String(8), default="6+")
    price_min = db.Column(db.Integer)
    price_max = db.Column(db.Integer)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    annotation = db.Column(db.Text, default="")        # короткий анонс для карточки
    description = db.Column(db.Text, default="")       # основной текст
    performers = db.Column(db.Text, default="")        # «Исполнители»
    organizer = db.Column(db.String(300), default="")

    ticket_url = db.Column(db.String(500), default="")  # ссылка билетной системы
    # ID сеанса в Яндекс Афише, например ticketsteam-825@496249: по нему
    # кнопки «Купить билет» открывают окно покупки
    yandex_id = db.Column(db.String(120), default="")
    tickets_left = db.Column(db.String(80), default="")  # «осталось более 100 билетов»
    hall_widget = db.Column(db.Text, default="")  # код схемы зала (виджет Яндекс Афиши)

    # Блоки, которые редактор включает и выключает на своё усмотрение
    show_pushkin = db.Column(db.Boolean, default=False, nullable=False)
    pushkin_text = db.Column(db.Text, default="")
    show_benefits = db.Column(db.Boolean, default=False, nullable=False)
    benefits_text = db.Column(db.Text, default="")
    show_media = db.Column(db.Boolean, default=True, nullable=False)

    is_published = db.Column(db.Boolean, default=True, nullable=False)
    is_new = db.Column(db.Boolean, default=False, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    # Дата изменения — для карты сайта: по ней поисковик решает, что переобойти
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    venue = db.relationship("Venue", backref="events")
    category = db.relationship("Category", backref="events")
    collectives = db.relationship(
        "Collective", secondary=event_collectives, backref="events"
    )
    media = db.relationship(
        "MediaItem",
        backref="event",
        order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )
    badges = db.relationship(
        "EventBadge",
        backref="event",
        order_by="EventBadge.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/afisha/{self.slug}"

    @property
    def is_past(self) -> bool:
        return self.starts_at < now_msk()

    @property
    def card_image(self) -> str:
        """Картинка для карточки: горизонтальное фото, иначе первое из галереи, иначе афиша."""
        if self.cover:
            return UPLOADS_URL + self.cover
        first = next(iter(self.photos), None)
        if first:
            return first.src
        return (UPLOADS_URL + self.poster) if self.poster else ""

    @property
    def age_number(self):
        """Возрастное ограничение числом: «6+» -> 6. Без отметки — None."""
        digits = "".join(ch for ch in (self.age_limit or "") if ch.isdigit())
        return int(digits) if digits else None

    @property
    def price_label(self) -> str:
        if self.price_min and self.price_max and self.price_max != self.price_min:
            return f"{self.price_min}–{self.price_max} ₽"
        if self.price_min:
            return f"от {self.price_min} ₽"
        return "Вход свободный"


class EventBadge(db.Model):
    """Всплывающий баннер поверх афиши события.

    Редактор задаёт текст, угол размещения и оформление; при наведении
    (или касании на телефоне) баннер раскрывается и показывает подсказку.
    """

    __tablename__ = "event_badges"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    text = db.Column(db.String(120), nullable=False)      # короткая надпись
    hint = db.Column(db.String(400), default="")          # расшифровка
    url = db.Column(db.String(400), default="")           # необязательная ссылка
    position = db.Column(db.String(20), default="top-left")
    style = db.Column(db.String(20), default="brick")     # brick | gold | ink | light
    icon = db.Column(db.String(40), default="")
    sort = db.Column(db.Integer, default=100)


# Медиагалерея
class MediaItem(db.Model):
    """Фото или видео. Прикрепляется к событию, коллективу, новости или странице.

    Видео можно загрузить файлом либо вставить ссылкой на VK Видео, RuTube,
    Дзен, MAX — ссылка автоматически превращается в код проигрывателя.
    """

    __tablename__ = "media_items"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False, default="photo")  # photo | video
    file = db.Column(db.String(300), default="")      # загруженный файл
    url = db.Column(db.String(600), default="")       # ссылка на внешнее видео
    embed = db.Column(db.Text, default="")            # готовый код проигрывателя
    preview = db.Column(db.String(300), default="")   # обложка видео
    title = db.Column(db.String(300), default="")
    sort = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=utcnow)

    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    collective_id = db.Column(db.Integer, db.ForeignKey("collectives.id"))
    news_id = db.Column(db.Integer, db.ForeignKey("news.id"))
    page_id = db.Column(db.Integer, db.ForeignKey("pages.id"))

    @property
    def src(self) -> str:
        return (UPLOADS_URL + self.file) if self.file else self.url


# Коллективы
class Collective(db.Model, HasMedia):
    """Творческий коллектив филармонии."""

    __tablename__ = "collectives"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(300), unique=True, nullable=False)
    logo = db.Column(db.String(300), default="")
    lead = db.Column(db.String(300), default="")       # художественный руководитель
    annotation = db.Column(db.Text, default="")
    description = db.Column(db.Text, default="")
    contacts = db.Column(db.Text, default="")          # открывается в баннере
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    media = db.relationship(
        "MediaItem", backref="collective", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/kollektivy/{self.slug}"


# Новости
class News(db.Model, HasMedia):
    __tablename__ = "news"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(400), nullable=False)
    slug = db.Column(db.String(400), unique=True, nullable=False)
    image = db.Column(db.String(300), default="")
    lead = db.Column(db.Text, default="")
    content = db.Column(db.Text, default="")
    published_at = db.Column(db.DateTime, default=utcnow, index=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    # Два вида новости: с фото и видео или только текст
    show_media = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    media = db.relationship(
        "MediaItem", backref="news", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/novosti/{self.slug}"


# Документы
class Document(db.Model):
    """Документ для скачивания: устав, НПА, отчёт, план ФХД."""

    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(400), nullable=False)
    file = db.Column(db.String(300), default="")
    url = db.Column(db.String(500), default="")
    category = db.Column(db.String(160), default="Учредительные документы")
    year = db.Column(db.Integer)
    doc_date = db.Column(db.Date)
    size_kb = db.Column(db.Integer)
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def href(self) -> str:
        return (UPLOADS_URL + self.file) if self.file else self.url


class Banner(db.Model):
    """Баннер-ссылка: Госуслуги, bus.gov.ru, партнёры, Пушкинская карта."""

    __tablename__ = "banners"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    image = db.Column(db.String(300), default="")
    url = db.Column(db.String(500), default="")
    place = db.Column(db.String(40), default="partners")  # partners | main | footer
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)


class Appeal(db.Model):
    """Обращение гражданина через интернет-приёмную."""

    __tablename__ = "appeals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    email = db.Column(db.String(200), default="")
    phone = db.Column(db.String(80), default="")
    subject = db.Column(db.String(300), default="")
    message = db.Column(db.Text, nullable=False)
    consent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    is_processed = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.Text, default="")


class ActionLog(db.Model):
    """Журнал действий в панели администратора: кто, когда и что изменил или удалил.

    Имя сотрудника и название объекта хранятся строкой: запись журнала должна
    пережить и удаление сотрудника, и удаление самого объекта.
    """

    __tablename__ = "action_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(200), default="")
    action = db.Column(db.String(32), nullable=False)       # create | update | delete | ...
    object_type = db.Column(db.String(32), default="")      # event | news | page | ...
    object_id = db.Column(db.Integer)
    title = db.Column(db.String(400), default="")
    details = db.Column(db.String(400), default="")


class Throttle(db.Model):
    """Счётчик частых действий: неудачные входы, отправка обращений.

    Хранится в базе, а не в памяти процесса: у gunicorn несколько процессов,
    и счётчик в памяти каждого из них умножал бы лимит на их число, а
    перезапуск сайта обнулял бы блокировку.
    """

    __tablename__ = "throttles"

    key = db.Column(db.String(300), primary_key=True)   # «login:логин:адрес», «appeal:адрес»
    count = db.Column(db.Integer, default=0, nullable=False)
    last_at = db.Column(db.Float, default=0.0, nullable=False, index=True)  # время Unix


class Redirect(db.Model):
    """Постоянное перенаправление со старого адреса (например, прежнего сайта)."""

    __tablename__ = "redirects"

    id = db.Column(db.Integer, primary_key=True)
    old_path = db.Column(db.String(500), unique=True, nullable=False)   # «/afisha/old-page.html»
    new_url = db.Column(db.String(500), nullable=False)                 # «/afisha» или полный адрес
    hits = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


def referenced_uploads() -> set:
    """Имена всех файлов из каталога загрузок, на которые ещё ссылается база.

    Файл удаляют с диска, только если его нет в этом наборе: одно и то же фото
    может стоять у нескольких записей (копия события делит фото с оригиналом).
    """
    columns = (
        Event.poster, Event.cover, MediaItem.file, MediaItem.preview, News.image,
        Collective.logo, Document.file, Banner.image,
    )
    names = set()
    for column in columns:
        names.update(v for (v,) in db.session.query(column).filter(column.isnot(None)) if v)
    names.update(v for (v,) in db.session.query(Setting.value).filter(Setting.kind == "file") if v)
    # Фото, вставленные прямо в текст описаний, страниц и новостей
    texts = (
        Event.description, Event.performers, Event.benefits_text, Event.pushkin_text,
        News.content, Page.content, Collective.description, Collective.contacts, Setting.value,
    )
    pattern = re.compile(re.escape(UPLOADS_URL) + r"([\w.\-]+)")
    for column in texts:
        for (value,) in db.session.query(column).filter(column.like(f"%{UPLOADS_URL}%")):
            names.update(pattern.findall(value or ""))
    return names


def upgrade_schema() -> list:
    """Дописывает в существующие таблицы колонки, появившиеся в моделях.

    `create_all` создаёт только недостающие таблицы, а в уже созданные новых
    колонок не добавляет — без этого обновлённый сайт падал бы на старой базе.
    Удалённые из моделей колонки остаются в базе нетронутыми: данные не теряются.
    Возвращает список добавленных колонок вида «таблица.колонка».
    """
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    added = []
    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} " \
                  f"{column.type.compile(dialect=db.engine.dialect)}"
            default = column.default.arg if column.default is not None else None
            if isinstance(default, bool):
                ddl += f" DEFAULT {'TRUE' if default else 'FALSE'} NOT NULL"
            elif isinstance(default, (int, str)):
                ddl += " DEFAULT " + (str(default) if isinstance(default, int)
                                      else "'" + default.replace("'", "''") + "'")
            db.session.execute(text(ddl))
            added.append(f"{table.name}.{column.name}")
    db.session.commit()
    return added
