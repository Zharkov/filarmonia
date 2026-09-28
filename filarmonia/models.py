"""Модели базы данных Смоленской областной филармонии."""
from datetime import datetime, date

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

UPLOADS_URL = "/static/uploads/"


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


# ---------------------------------------------------------------- пользователи
class User(db.Model):
    """Сотрудник, работающий с админкой."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="editor")  # admin | editor
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ------------------------------------------------------------------ настройки
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


# --------------------------------------------------------------- меню/страницы
class Page(db.Model):
    """Статическая страница (Об учреждении, Услуги, Отчёты, НПА и т.д.)."""

    __tablename__ = "pages"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, default="")
    parent_id = db.Column(db.Integer, db.ForeignKey("pages.id"))
    sort = db.Column(db.Integer, default=100)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    show_in_menu = db.Column(db.Boolean, default=True, nullable=False)
    template = db.Column(db.String(32), default="page")  # page | documents | contacts
    seo_description = db.Column(db.String(400), default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    children = db.relationship(
        "Page",
        backref=db.backref("parent", remote_side=[id]),
        order_by="Page.sort",
        cascade="all",
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


# ------------------------------------------------------------------- афиша
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


class Category(db.Model):
    """Жанр или категория события: классика, детям, джаз, органная музыка."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    sort = db.Column(db.Integer, default=100)


class Event(db.Model, HasMedia):
    """Концерт или спектакль."""

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(300), unique=True, nullable=False)
    poster = db.Column(db.String(300), default="")  # афиша (вертикальная)
    cover = db.Column(db.String(300), default="")   # широкое фото для карточки
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_min = db.Column(db.Integer)
    age_limit = db.Column(db.String(8), default="6+")
    price_min = db.Column(db.Integer)
    price_max = db.Column(db.Integer)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    annotation = db.Column(db.Text, default="")        # короткий анонс для карточки
    description = db.Column(db.Text, default="")       # основной текст
    performers = db.Column(db.Text, default="")        # блок «В концерте принимают участие»
    organizer = db.Column(db.String(300), default="")

    ticket_url = db.Column(db.String(500), default="")  # ссылка билетной системы
    tickets_left = db.Column(db.String(80), default="")  # «осталось более 100 билетов»

    # --- блоки, которые редактор включает и выключает на своё усмотрение
    show_pushkin = db.Column(db.Boolean, default=False, nullable=False)
    pushkin_text = db.Column(db.Text, default="")
    show_benefits = db.Column(db.Boolean, default=False, nullable=False)
    benefits_text = db.Column(db.Text, default="")

    is_published = db.Column(db.Boolean, default=True, nullable=False)
    is_new = db.Column(db.Boolean, default=False, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        return self.starts_at < datetime.now()

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


# --------------------------------------------------------------- медиагалерея
class MediaItem(db.Model):
    """Фото или видео. Прикрепляется к событию, коллективу или новости.

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    collective_id = db.Column(db.Integer, db.ForeignKey("collectives.id"))
    news_id = db.Column(db.Integer, db.ForeignKey("news.id"))
    album_id = db.Column(db.Integer, db.ForeignKey("albums.id"))

    @property
    def src(self) -> str:
        return (UPLOADS_URL + self.file) if self.file else self.url


class Album(db.Model, HasMedia):
    """Альбом общей фото- и видеогалереи сайта."""

    __tablename__ = "albums"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(300), unique=True, nullable=False)
    cover = db.Column(db.String(300), default="")
    year = db.Column(db.Integer, default=lambda: date.today().year)
    description = db.Column(db.Text, default="")
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    media = db.relationship(
        "MediaItem", backref="album", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )


# --------------------------------------------------------------- коллективы
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

    media = db.relationship(
        "MediaItem", backref="collective", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/kollektivy/{self.slug}"


# ------------------------------------------------------------------- новости
class News(db.Model, HasMedia):
    __tablename__ = "news"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(400), nullable=False)
    slug = db.Column(db.String(400), unique=True, nullable=False)
    image = db.Column(db.String(300), default="")
    lead = db.Column(db.Text, default="")
    content = db.Column(db.Text, default="")
    published_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False)

    media = db.relationship(
        "MediaItem", backref="news", order_by="MediaItem.sort",
        cascade="all, delete-orphan",
    )

    @property
    def url(self) -> str:
        return f"/novosti/{self.slug}"


# ----------------------------------------------------------------- документы
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_processed = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.Text, default="")
