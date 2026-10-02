"""Панель управления сайтом."""
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    g, abort, current_app, jsonify,
)
from sqlalchemy.orm import aliased

from .models import (
    db, User, Event, EventBadge, MediaItem, Collective, News, Page,
    MenuItem, Document, Banner, Venue, Category, Appeal, Setting, ActionLog,
    ROUTE_TAGS, referenced_uploads,
)
from . import utils

bp = Blueprint("admin", __name__)

PER_PAGE = 30

MIN_PASSWORD_LENGTH = 8

BANNER_PLACES = [
    ("main", "Главная, крупно («Госуслуги. Решаем вместе»)"),
    ("partners", "Лента баннеров на главной"),
    ("footer", "Подвал"),
]

PAGE_TEMPLATES = [
    ("page", "Обычная"),
    ("documents", "Со списком документов"),
    ("contacts", "Контакты: с площадками и картами"),
    ("pushkin", "Пушкинская карта: с концертами по карте"),
    ("benefits", "Льготное посещение: с концертами со льготами"),
]

# Смоленск живёт по московскому времени, а журнал пишет время в UTC
MOSCOW_OFFSET = timedelta(hours=3)

# Настройки, куда вставляется код сторонних виджетов: их не очищаем
WIDGET_SETTINGS = {"pos_widget", "history_map"}

# Тип объекта для журнала: модель -> (ключ, подпись)
OBJECT_TYPES = {
    Event: ("event", "Событие"), News: ("news", "Новость"), Collective: ("collective", "Коллектив"),
    Page: ("page", "Страница"), MenuItem: ("menu", "Пункт меню"), Document: ("document", "Документ"),
    Banner: ("banner", "Баннер"), Venue: ("venue", "Площадка"), Category: ("category", "Жанр"),
    User: ("user", "Сотрудник"), Appeal: ("appeal", "Обращение"), MediaItem: ("media", "Фото или видео"),
    EventBadge: ("badge", "Баннер на афише"), Setting: ("settings", "Настройки"),
}
OBJECT_LABELS = dict(OBJECT_TYPES.values())
ACTION_LABELS = {
    "create": "создал", "update": "изменил", "delete": "удалил", "copy": "скопировал",
    "move": "переставил", "purge": "удалил по сроку хранения",
}


# Доступ
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("admin.login", next=request.path))
        if not g.user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def safe_next(target: str) -> str:
    """Адрес возврата после входа — только внутри сайта.

    Без проверки ссылка `/admin/login?next=https://чужой-сайт` отправила бы
    сотрудника после ввода пароля на поддельную страницу. «//host» и «/\\host»
    браузер тоже понимает как чужой сайт, поэтому отсекаем и их.
    """
    if target and target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return url_for("admin.dashboard")


@bp.context_processor
def inject_counters():
    """Число необработанных обращений — для красного кружка в левом меню."""
    if not g.get("user"):
        return {}
    return {"new_appeals": Appeal.query.filter_by(is_processed=False).count()}


# Общие помощники
def get_or_404(model, item_id):
    """Объект по идентификатору либо 404."""
    item = db.session.get(model, item_id)
    if item is None:
        abort(404)
    return item


def unique_slug(model, title: str, item, given: str = "") -> str:
    """Адрес страницы: введённый вручную либо построенный из заголовка.

    Через `slugify` проходят оба варианта: колонка `slug` объявлена уникальной,
    и занятый адрес, введённый руками, обрывал бы сохранение ошибкой базы.
    Занятый адрес получает числовой хвост: `kontsert`, `kontsert-2`.
    """
    def taken(candidate: str) -> bool:
        return model.query.filter(
            model.slug == candidate, model.id != item.id
        ).first() is not None

    return utils.slugify((given or "").strip() or title, taken)


def uploaded_name(field: str, kinds=("image",)) -> str:
    """Сохраняет файл из поля формы. Пустая строка — файл не выбирали.

    При недопустимом расширении `utils.save_upload` бросает ValueError,
    который обработчик формы превращает в сообщение редактору.
    """
    uploaded = request.files.get(field)
    if uploaded and uploaded.filename:
        return utils.save_upload(uploaded, kinds)
    return ""


def rich(field: str) -> str:
    """Текст из визуального редактора — без скриптов и чужих атрибутов."""
    return utils.clean_html(request.form.get(field, ""))


def sorted_by(query, columns: dict, default: str, default_dir: str = "asc",
              joins: dict = None, tiebreak=None):
    """Сортирует список по столбцу из адреса: ?sort=<ключ>&dir=asc|desc.

    columns — {ключ: колонка}; чужой ключ из адреса игнорируется, и список
    идёт в порядке по умолчанию. joins — {ключ: модель} для столбцов из
    связанной таблицы (площадка события, раздел страницы): присоединяем её,
    только когда сортируют по этому столбцу. Пустые значения уходят в конец
    при любом направлении. Возвращает запрос и {"key", "dir"} для шаблона.
    """
    key = request.args.get("sort")
    if key in columns:
        direction = "desc" if request.args.get("dir") == "desc" else "asc"
    else:
        key, direction = default, default_dir
    if joins and key in joins:
        query = query.outerjoin(*joins[key]) if isinstance(joins[key], tuple) \
            else query.outerjoin(joins[key])
    column = columns[key]
    order = (column.desc() if direction == "desc" else column.asc()).nullslast()
    query = query.order_by(order, tiebreak) if tiebreak is not None else query.order_by(order)
    return query, {"key": key, "dir": direction}


def search_text() -> str:
    return (request.args.get("q") or "").strip()


def paginated(query, per_page: int = PER_PAGE):
    page = utils.parse_int(request.args.get("page"), 1)
    return query.paginate(page=page, per_page=per_page, error_out=False)


def edited(model):
    """Запись, открытая на правку из списка: ?edit=<id>. None — форма добавления."""
    item_id = utils.parse_int(request.args.get("edit"))
    return db.session.get(model, item_id) if item_id else None


def title_of(item) -> str:
    for attr in ("title", "name", "login", "text"):
        value = getattr(item, attr, None)
        if value:
            return str(value)[:400]
    return ""


def log(action: str, item=None, details: str = "", object_type: str = "") -> None:
    """Запись в журнал действий. Сохраняется вместе с ближайшим commit."""
    key = object_type or (OBJECT_TYPES.get(type(item), ("", ""))[0] if item is not None else "")
    user = g.get("user")
    db.session.add(ActionLog(
        user_id=user.id if user else None,
        user_name=(user.name or user.login) if user else "",
        action=action, object_type=key,
        object_id=getattr(item, "id", None) if item is not None else None,
        title=title_of(item) if item is not None else "", details=details[:400],
    ))


def save(item, message: str):
    """Добавляет объект в сессию, если он новый, сохраняет и пишет в журнал."""
    created = item.id is None
    if created:
        db.session.add(item)
        db.session.flush()
    log("create" if created else "update", item)
    db.session.commit()
    flash(message, "ok")


def files_of(item) -> list:
    """Файлы, которые принадлежат записи: афиша, обложка, фото галереи."""
    names = []
    for attr in ("poster", "cover", "image", "logo", "file", "preview"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value:
            names.append(value)
    for media in getattr(item, "media", None) or []:
        names += [media.file, media.preview]
    return [n for n in names if n]


def release_files(names) -> None:
    """Удаляет с диска файлы, на которые в базе больше никто не ссылается.

    Вызывается после commit: если сохранение сорвалось, файлы остаются на месте.
    """
    names = {n for n in names if n}
    if names:
        utils.delete_uploads(names - referenced_uploads())


def replace_file(item, attr: str, new_name: str) -> list:
    """Ставит новый файл вместо прежнего. Возвращает прежний — на удаление."""
    if not new_name:
        return []
    old = getattr(item, attr, "") or ""
    setattr(item, attr, new_name)
    return [old] if old and old != new_name else []


# Неудачные попытки входа: (логин, адрес) -> [сколько подряд, время последней].
# Словарь в памяти процесса: при перезапуске счётчики обнуляются, а у каждого
# работника gunicorn он свой. Для филармонии с десятком сотрудников этого
# достаточно; под несколько серверов счётчики выносят в общее хранилище.
_login_attempts = {}


def _attempt_key():
    return (request.form.get("login", "").strip().lower(), request.remote_addr or "")


def login_locked_for() -> int:
    """Сколько секунд осталось до конца блокировки. 0 — вход разрешён."""
    cfg = current_app.config
    count, last = _login_attempts.get(_attempt_key(), (0, 0.0))
    if count < cfg["LOGIN_MAX_ATTEMPTS"]:
        return 0
    return max(0, int(cfg["LOGIN_LOCKOUT_SECONDS"] - (time.time() - last)))


def note_login_failure() -> None:
    """Считает неудачу входа и убирает из памяти давно остывшие записи."""
    window = current_app.config["LOGIN_LOCKOUT_SECONDS"]
    now = time.time()
    for key, (_, last) in list(_login_attempts.items()):
        if now - last > window:
            del _login_attempts[key]

    key = _attempt_key()
    count, last = _login_attempts.get(key, (0, 0.0))
    # Отсидел блокировку — счётчик начинается заново, иначе одна опечатка
    # после разблокировки сразу запирала бы ещё на четверть часа
    if now - last > window:
        count = 0
    _login_attempts[key] = (count + 1, now)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        locked = login_locked_for()
        if locked:
            flash(f"Слишком много попыток входа. Повторите через "
                  f"{utils.plural(locked // 60 + 1, 'минуту', 'минуты', 'минут')}.", "error")
            return render_template("admin/login.html")

        user = User.query.filter_by(login=request.form.get("login", "").strip()).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            _login_attempts.pop(_attempt_key(), None)
            session.clear()
            session["user_id"] = user.id
            user.last_login_at = utils.utcnow()
            db.session.commit()
            return redirect(safe_next(request.args.get("next", "")))

        note_login_failure()
        flash("Неверный логин или пароль.", "error")
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("public.index"))


# Сводка
@bp.route("/")
@login_required
def dashboard():
    now = datetime.now()
    return render_template(
        "admin/dashboard.html",
        upcoming=Event.query.options(db.joinedload(Event.venue))
        .filter(Event.starts_at >= now).order_by(Event.starts_at).limit(8).all(),
        counts={
            "events": Event.query.count(),
            "upcoming": Event.query.filter(Event.starts_at >= now).count(),
            "news": News.query.count(),
            "collectives": Collective.query.count(),
            "documents": Document.query.count(),
            "appeals_new": Appeal.query.filter_by(is_processed=False).count(),
        },
        appeals=Appeal.query.order_by(Appeal.created_at.desc()).limit(5).all(),
    )


# Афиша
@bp.route("/events")
@login_required
def events():
    q = Event.query.options(db.joinedload(Event.venue), db.selectinload(Event.media))
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Event.title, search))
    scope = a.get("scope", "upcoming")
    if scope == "upcoming":
        q = q.filter(Event.starts_at >= datetime.now())
    elif scope == "past":
        q = q.filter(Event.starts_at < datetime.now())
    if utils.parse_int(a.get("venue")):
        q = q.filter(Event.venue_id == utils.parse_int(a.get("venue")))
    if utils.parse_int(a.get("category")):
        q = q.filter(Event.category_id == utils.parse_int(a.get("category")))
    if a.get("status") in ("on", "off"):
        q = q.filter(Event.is_published.is_(a.get("status") == "on"))
    mark = a.get("mark")
    if mark == "pushkin":
        q = q.filter(Event.show_pushkin.is_(True))
    elif mark == "benefits":
        q = q.filter(Event.show_benefits.is_(True))
    elif mark == "new":
        q = q.filter(Event.is_new.is_(True))

    # Предстоящие удобнее читать от ближайших, прошедшие — от последних
    q, sorting = sorted_by(
        q,
        {"date": Event.starts_at, "title": Event.title, "venue": Venue.name,
         "price": Event.price_min, "status": Event.is_published},
        default="date", default_dir="asc" if scope == "upcoming" else "desc",
        joins={"venue": Event.venue}, tiebreak=Event.starts_at,
    )
    return render_template(
        "admin/events.html", items=paginated(q), scope=scope, search=search, sorting=sorting,
        venues=Venue.query.order_by(Venue.name).all(),
        categories=Category.query.order_by(Category.sort).all(),
    )


@bp.route("/events/new", methods=["GET", "POST"])
@bp.route("/events/<int:event_id>", methods=["GET", "POST"])
@login_required
def event_form(event_id=None):
    ev = get_or_404(Event, event_id) if event_id else Event(starts_at=datetime.now())

    if request.method == "POST":
        f = request.form
        ev.title = f.get("title", "").strip()
        old_files = []
        try:
            if not ev.title:
                raise ValueError("Укажите название события.")

            ev.slug = unique_slug(Event, ev.title, ev, f.get("slug"))
            ev.starts_at = utils.parse_dt(f.get("starts_at")) or ev.starts_at or datetime.now()
            ev.duration_min = utils.parse_int(f.get("duration_min"))
            ev.age_limit = f.get("age_limit", "").strip()
            ev.price_min = utils.parse_int(f.get("price_min"))
            ev.price_max = utils.parse_int(f.get("price_max"))
            ev.venue_id = utils.parse_int(f.get("venue_id"))
            ev.category_id = utils.parse_int(f.get("category_id"))
            ev.annotation = f.get("annotation", "").strip()
            ev.description = rich("description")
            ev.performers = rich("performers")
            ev.organizer = f.get("organizer", "").strip()
            ev.ticket_url = f.get("ticket_url", "").strip()
            ev.tickets_left = f.get("tickets_left", "").strip()
            # Код виджета вставляется на страницу как есть — его правит только администратор
            if g.user.is_admin:
                ev.hall_widget = f.get("hall_widget", "").strip()
            ev.show_media = bool(f.get("show_media"))
            ev.show_pushkin = bool(f.get("show_pushkin"))
            ev.pushkin_text = rich("pushkin_text")
            ev.show_benefits = bool(f.get("show_benefits"))
            ev.benefits_text = rich("benefits_text")
            ev.is_published = bool(f.get("is_published"))
            ev.is_new = bool(f.get("is_new"))
            ev.is_featured = bool(f.get("is_featured"))

            chosen = [utils.parse_int(i) for i in f.getlist("collectives")]
            ev.collectives = Collective.query.filter(Collective.id.in_(chosen)).all() if chosen else []

            for field in ("poster", "cover"):
                old_files += replace_file(ev, field, uploaded_name(field))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/event_form.html", ev=ev, **_event_refs())

        save(ev, "Событие сохранено.")
        release_files(old_files)
        return redirect(url_for("admin.event_form", event_id=ev.id))

    return render_template("admin/event_form.html", ev=ev, **_event_refs())


def _event_refs():
    return {
        "venues": Venue.query.order_by(Venue.name).all(),
        "categories": Category.query.order_by(Category.sort).all(),
        "all_collectives": Collective.query.order_by(Collective.name).all(),
        "positions": [
            ("top-left", "Сверху слева"), ("top-right", "Сверху справа"),
            ("bottom-left", "Снизу слева"), ("bottom-right", "Снизу справа"),
        ],
        "styles": [("brick", "Красный"), ("gold", "Золотой"), ("ink", "Тёмный"), ("light", "Светлый")],
    }


# Поля, которые не переносятся в копию события
NOT_COPIED = {"id", "slug", "created_at", "is_published"}


@bp.route("/events/<int:event_id>/copy", methods=["POST"])
@login_required
def event_copy(event_id):
    """Копия события для повторной программы: всё, кроме даты, переносится.

    Копия создаётся скрытой — чтобы на сайт не попал концерт с той же
    датой, пока редактор её не поменял. Фото и видео у копии общие с
    оригиналом: файлы не дублируются на диске.
    """
    ev = get_or_404(Event, event_id)
    copy = Event(**{
        c.name: getattr(ev, c.name) for c in Event.__table__.columns if c.name not in NOT_COPIED
    })
    copy.is_published = False
    copy.slug = unique_slug(Event, ev.title, copy)
    copy.collectives = list(ev.collectives)
    copy.badges = [
        EventBadge(text=b.text, hint=b.hint, url=b.url, position=b.position, style=b.style,
                   icon=b.icon, sort=b.sort)
        for b in ev.badges
    ]
    copy.media = [
        MediaItem(kind=m.kind, file=m.file, url=m.url, embed=m.embed, preview=m.preview,
                  title=m.title, sort=m.sort)
        for m in ev.media
    ]
    db.session.add(copy)
    db.session.flush()
    log("copy", copy, details=f"копия события № {ev.id}")
    db.session.commit()
    flash("Копия создана и пока скрыта с сайта. Укажите дату и время, затем отметьте «Опубликовано».", "ok")
    return redirect(url_for("admin.event_form", event_id=copy.id))


# Всплывающие баннеры на афише
@bp.route("/events/<int:event_id>/badges", methods=["POST"])
@login_required
def badge_add(event_id):
    """Добавляет баннер на афишу, а с полем id — сохраняет правку существующего."""
    ev = get_or_404(Event, event_id)
    f = request.form
    badge_id = utils.parse_int(f.get("id"))
    badge = get_or_404(EventBadge, badge_id) if badge_id else EventBadge(event_id=ev.id)
    if badge.event_id != ev.id:
        abort(404)
    text = f.get("text", "").strip()
    if not text:
        flash("У баннера должна быть надпись.", "error")
        back = url_for("admin.event_form", event_id=ev.id, edit_badge=badge_id) if badge_id \
            else url_for("admin.event_form", event_id=ev.id)
        return redirect(back + "#badges")
    badge.text = text
    badge.hint = f.get("hint", "").strip()
    badge.url = f.get("url", "").strip()
    badge.position = f.get("position", "top-left")
    badge.style = f.get("style", "brick")
    badge.sort = utils.parse_int(f.get("sort"), badge.sort or 100)
    if badge_id is None:
        db.session.add(badge)
    log("update" if badge_id else "create", badge, details=f"событие «{ev.title}»")
    db.session.commit()
    flash("Баннер сохранён." if badge_id else "Баннер добавлен.", "ok")
    return redirect(url_for("admin.event_form", event_id=ev.id) + "#badges")


@bp.route("/badges/<int:badge_id>/delete", methods=["POST"])
@login_required
def badge_delete(badge_id):
    badge = get_or_404(EventBadge, badge_id)
    event_id = badge.event_id
    log("delete", badge)
    db.session.delete(badge)
    db.session.commit()
    return redirect(url_for("admin.event_form", event_id=event_id) + "#badges")


# Медиа (общее)
OWNERS = {
    "event": ("event_id", "admin.event_form", "event_id"),
    "collective": ("collective_id", "admin.collective_form", "item_id"),
    "news": ("news_id", "admin.news_form", "item_id"),
    "page": ("page_id", "admin.page_form", "item_id"),
}


def media_owner(item):
    """(поле владельца, его id, адрес возврата) для фото или видео."""
    for field, endpoint, arg in OWNERS.values():
        value = getattr(item, field)
        if value:
            return field, value, url_for(endpoint, **{arg: value}) + "#media"
    return None, None, url_for("admin.dashboard")


@bp.route("/media/add", methods=["POST"])
@login_required
def media_add():
    owner = request.form.get("owner")
    owner_id = utils.parse_int(request.form.get("owner_id"))
    if owner not in OWNERS or not owner_id:
        abort(400)
    field, endpoint, arg = OWNERS[owner]
    back = url_for(endpoint, **{arg: owner_id}) + "#media"

    kind = request.form.get("kind", "photo")
    title = request.form.get("title", "").strip()
    # Новое — в конец галереи: иначе оно вставало бы между уже расставленными
    last = db.session.query(db.func.max(MediaItem.sort)).filter(
        getattr(MediaItem, field) == owner_id).scalar() or 0
    item = MediaItem(kind=kind, title=title, sort=last + 10)
    setattr(item, field, owner_id)

    try:
        if kind == "photo":
            saved = 0
            for uploaded in request.files.getlist("file"):
                if uploaded and uploaded.filename:
                    clone = MediaItem(kind="photo", title=title, sort=last + 10 * (saved + 1))
                    setattr(clone, field, owner_id)
                    clone.file = utils.save_upload(uploaded, ("image",))
                    db.session.add(clone)
                    saved += 1
            if not saved:
                flash("Выберите хотя бы один файл.", "error")
            else:
                log("create", object_type="media", details=f"фотографий: {saved} ({owner} № {owner_id})")
                db.session.commit()
                flash(f"Загружено фотографий: {saved}.", "ok")
        else:
            url = request.form.get("url", "").strip()
            uploaded = request.files.get("file")
            preview = request.files.get("preview")
            if uploaded and uploaded.filename:
                item.file = utils.save_upload(uploaded, ("video",))
            elif url:
                item.url = url
                item.embed = utils.video_embed(url)
                if not item.embed:
                    flash("Ссылку не удалось распознать — на странице будет показана обычная ссылка. "
                          "Поддерживаются VK Видео, RuTube, Дзен, YouTube и файлы .mp4.", "error")
            else:
                flash("Укажите ссылку на видео или загрузите файл.", "error")
                return redirect(back)
            if preview and preview.filename:
                item.preview = utils.save_upload(preview, ("image",))
            db.session.add(item)
            log("create", item, details=f"видео ({owner} № {owner_id})")
            db.session.commit()
            flash("Видео добавлено.", "ok")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(back)


@bp.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def media_delete(media_id):
    item = get_or_404(MediaItem, media_id)
    _, _, back = media_owner(item)
    names = files_of(item)
    log("delete", item)
    db.session.delete(item)
    db.session.commit()
    release_files(names)
    return redirect(back)


@bp.route("/media/<int:media_id>/move", methods=["POST"])
@login_required
def media_move(media_id):
    """Сдвигает фото или видео на одно место вперёд или назад в галерее."""
    item = get_or_404(MediaItem, media_id)
    field, owner_id, back = media_owner(item)
    if field is None:
        return redirect(back)
    siblings = (
        MediaItem.query.filter(getattr(MediaItem, field) == owner_id)
        .order_by(MediaItem.sort, MediaItem.id).all()
    )
    index = siblings.index(item)
    target = index - 1 if request.form.get("dir") == "up" else index + 1
    moved = 0 <= target < len(siblings)
    if moved:
        siblings[index], siblings[target] = siblings[target], siblings[index]
        # Перенумеровываем всех: у старых записей порядок мог совпадать
        for position, media in enumerate(siblings):
            media.sort = (position + 1) * 10
        db.session.commit()
    # Скрипт админки переставляет миниатюру на месте, без перезагрузки страницы
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(moved=moved)
    return redirect(back)


# Коллективы
@bp.route("/collectives")
@login_required
def collectives():
    q = Collective.query.options(db.selectinload(Collective.media))
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Collective.name, search) | utils.like_ci(Collective.lead, search))
    if request.args.get("status") in ("on", "off"):
        q = q.filter(Collective.is_published.is_(request.args.get("status") == "on"))
    q, sorting = sorted_by(
        q, {"sort": Collective.sort, "name": Collective.name, "lead": Collective.lead,
            "status": Collective.is_published},
        default="sort", tiebreak=Collective.name,
    )
    return render_template("admin/collectives.html", items=q.all(), search=search, sorting=sorting)


@bp.route("/collectives/new", methods=["GET", "POST"])
@bp.route("/collectives/<int:item_id>", methods=["GET", "POST"])
@login_required
def collective_form(item_id=None):
    item = get_or_404(Collective, item_id) if item_id else Collective()
    if request.method == "POST":
        f = request.form
        item.name = f.get("name", "").strip()
        old_files = []
        try:
            if not item.name:
                raise ValueError("Укажите название коллектива.")
            item.slug = unique_slug(Collective, item.name, item, f.get("slug"))
            item.lead = f.get("lead", "").strip()
            item.annotation = f.get("annotation", "").strip()
            item.description = rich("description")
            item.contacts = rich("contacts")
            item.sort = utils.parse_int(f.get("sort"), 100)
            item.is_published = bool(f.get("is_published"))
            old_files = replace_file(item, "logo", uploaded_name("logo"))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/collective_form.html", item=item)
        save(item, "Коллектив сохранён.")
        release_files(old_files)
        return redirect(url_for("admin.collective_form", item_id=item.id))
    return render_template("admin/collective_form.html", item=item)


# Новости
@bp.route("/news")
@login_required
def news():
    q = News.query.options(db.selectinload(News.media))
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(News.title, search))
    if request.args.get("status") in ("on", "off"):
        q = q.filter(News.is_published.is_(request.args.get("status") == "on"))
    if request.args.get("layout") in ("media", "text"):
        q = q.filter(News.show_media.is_(request.args.get("layout") == "media"))
    q, sorting = sorted_by(
        q, {"date": News.published_at, "title": News.title, "status": News.is_published},
        default="date", default_dir="desc", tiebreak=News.id.desc(),
    )
    return render_template("admin/news.html", items=paginated(q), search=search, sorting=sorting)


@bp.route("/news/new", methods=["GET", "POST"])
@bp.route("/news/<int:item_id>", methods=["GET", "POST"])
@login_required
def news_form(item_id=None):
    item = get_or_404(News, item_id) if item_id else News(published_at=datetime.now())
    if request.method == "POST":
        f = request.form
        item.title = f.get("title", "").strip()
        old_files = []
        try:
            if not item.title:
                raise ValueError("Укажите заголовок новости.")
            item.slug = unique_slug(News, item.title, item, f.get("slug"))
            item.lead = f.get("lead", "").strip()
            item.content = rich("content")
            item.published_at = (
                utils.parse_dt(f.get("published_at")) or item.published_at or datetime.now()
            )
            item.is_published = bool(f.get("is_published"))
            item.show_media = f.get("layout", "media") == "media"
            old_files = replace_file(item, "image", uploaded_name("image"))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/news_form.html", item=item)
        save(item, "Новость сохранена.")
        release_files(old_files)
        return redirect(url_for("admin.news_form", item_id=item.id))
    return render_template("admin/news_form.html", item=item)


# Страницы
@bp.route("/pages")
@login_required
def pages():
    q = Page.query.options(db.joinedload(Page.parent))
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Page.title, search))
    parent = a.get("parent")
    if parent == "top":
        q = q.filter(Page.parent_id.is_(None))
    elif utils.parse_int(parent):
        q = q.filter(Page.parent_id == utils.parse_int(parent))
    if a.get("template") in dict(PAGE_TEMPLATES):
        q = q.filter(Page.template == a.get("template"))
    if a.get("status") in ("on", "off"):
        q = q.filter(Page.is_published.is_(a.get("status") == "on"))
    # Раздел — та же таблица страниц, поэтому для сортировки по нему нужен псевдоним
    section = aliased(Page)
    q, sorting = sorted_by(
        q, {"sort": Page.sort, "title": Page.title, "parent": section.title,
            "slug": Page.slug, "status": Page.is_published},
        default="sort", joins={"parent": (section, Page.parent_id == section.id)},
        tiebreak=Page.title,
    )
    return render_template(
        "admin/pages.html", items=q.all(), search=search, sorting=sorting,
        sections=Page.query.filter(Page.children.any()).order_by(Page.title).all(),
        templates=PAGE_TEMPLATES,
    )


@bp.route("/pages/new", methods=["GET", "POST"])
@bp.route("/pages/<int:item_id>", methods=["GET", "POST"])
@login_required
def page_form(item_id=None):
    item = get_or_404(Page, item_id) if item_id else Page()
    parents = Page.query.filter(Page.id != (item.id or 0)).order_by(Page.title).all()
    if request.method == "POST":
        f = request.form
        item.title = f.get("title", "").strip()
        if not item.title:
            flash("Укажите заголовок страницы.", "error")
            return render_template("admin/page_form.html", item=item, parents=parents,
                                   templates=PAGE_TEMPLATES)
        item.slug = unique_slug(Page, item.title, item, f.get("slug"))
        item.content = rich("content")
        item.parent_id = utils.parse_int(f.get("parent_id"))
        item.sort = utils.parse_int(f.get("sort"), 100)
        template = f.get("template", "page")
        item.template = template if template in dict(PAGE_TEMPLATES) else "page"
        item.seo_description = f.get("seo_description", "").strip()
        item.is_published = bool(f.get("is_published"))
        item.show_in_menu = bool(f.get("show_in_menu"))
        save(item, "Страница сохранена.")
        return redirect(url_for("admin.page_form", item_id=item.id))
    return render_template("admin/page_form.html", item=item, parents=parents,
                           templates=PAGE_TEMPLATES)


# Меню
@bp.route("/menu", methods=["GET", "POST"])
@login_required
def menu():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(MenuItem, item_id) if item_id else MenuItem()
        item.title = f.get("title", "").strip()
        item.url = f.get("url", "").strip()
        item.page_id = utils.parse_int(f.get("page_id"))
        parent_id = utils.parse_int(f.get("parent_id"))
        # Пункт не может быть подпунктом самого себя
        item.parent_id = parent_id if parent_id != item.id else None
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        if not item.title:
            flash("У пункта меню должно быть название.", "error")
            return redirect(url_for("admin.menu", edit=item_id) if item_id else url_for("admin.menu"))
        save(item, "Меню обновлено.")
        return redirect(url_for("admin.menu"))

    q = MenuItem.query.options(db.joinedload(MenuItem.page), db.joinedload(MenuItem.parent))
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(MenuItem.title, search))
    level = a.get("level")
    if level == "top":
        q = q.filter(MenuItem.parent_id.is_(None))
    elif utils.parse_int(level):
        q = q.filter(MenuItem.parent_id == utils.parse_int(level))
    if a.get("status") in ("on", "off"):
        q = q.filter(MenuItem.is_published.is_(a.get("status") == "on"))
    parent = aliased(MenuItem)
    q, sorting = sorted_by(
        q, {"sort": MenuItem.sort, "title": MenuItem.title, "parent": parent.title,
            "status": MenuItem.is_published},
        default="sort", joins={"parent": (parent, MenuItem.parent_id == parent.id)},
        tiebreak=MenuItem.title,
    )
    return render_template(
        "admin/menu.html", items=q.all(), search=search, sorting=sorting, edit=edited(MenuItem),
        # Список родителей для формы и фильтра — всегда полный, без учёта фильтров
        top_items=MenuItem.query.filter_by(parent_id=None).order_by(MenuItem.sort).all(),
        pages=Page.query.order_by(Page.title).all(),
    )


# Документы
@bp.route("/documents", methods=["GET", "POST"])
@login_required
def documents():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(Document, item_id) if item_id else Document()
        item.title = f.get("title", "").strip()
        item.category = f.get("category", "").strip() or "Прочее"
        item.year = utils.parse_int(f.get("year"))
        item.doc_date = utils.parse_date(f.get("doc_date"))
        item.url = f.get("url", "").strip()
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        back = url_for("admin.documents", edit=item_id) if item_id else url_for("admin.documents")
        try:
            old_files = replace_file(item, "file", uploaded_name("file", ("doc", "image")))
            if old_files or (item.file and not item.size_kb):
                item.size_kb = utils.file_size_kb(item.file)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(back)
        if not item.title:
            db.session.rollback()
            flash("Укажите название документа.", "error")
            return redirect(back)
        save(item, "Документ сохранён.")
        release_files(old_files)
        return redirect(url_for("admin.documents"))

    q = Document.query
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Document.title, search))
    if a.get("category"):
        q = q.filter(Document.category == a.get("category"))
    if utils.parse_int(a.get("year")):
        q = q.filter(Document.year == utils.parse_int(a.get("year")))
    if a.get("status") in ("on", "off"):
        q = q.filter(Document.is_published.is_(a.get("status") == "on"))
    q, sorting = sorted_by(
        q, {"category": Document.category, "title": Document.title, "year": Document.year,
            "size": Document.size_kb, "sort": Document.sort, "status": Document.is_published},
        default="category", tiebreak=Document.sort,
    )
    categories = [c for (c,) in db.session.query(Document.category).distinct().order_by(Document.category) if c]
    years = [y for (y,) in db.session.query(Document.year).distinct().order_by(Document.year.desc()) if y]
    return render_template("admin/documents.html", items=q.all(), search=search, sorting=sorting,
                           categories=categories, years=years, edit=edited(Document))


# Баннеры
@bp.route("/banners", methods=["GET", "POST"])
@login_required
def banners():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(Banner, item_id) if item_id else Banner()
        item.title = f.get("title", "").strip()
        item.url = f.get("url", "").strip()
        item.place = f.get("place") if f.get("place") in dict(BANNER_PLACES) else "partners"
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        back = url_for("admin.banners", edit=item_id) if item_id else url_for("admin.banners")
        try:
            old_files = replace_file(item, "image", uploaded_name("image"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(back)
        if not item.title:
            db.session.rollback()
            flash("Укажите название баннера.", "error")
            return redirect(back)
        save(item, "Баннер сохранён.")
        release_files(old_files)
        return redirect(url_for("admin.banners"))
    q = Banner.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Banner.title, search) | utils.like_ci(Banner.url, search))
    if request.args.get("place") in dict(BANNER_PLACES):
        q = q.filter(Banner.place == request.args.get("place"))
    if request.args.get("status") in ("on", "off"):
        q = q.filter(Banner.is_published.is_(request.args.get("status") == "on"))
    q, sorting = sorted_by(
        q, {"place": Banner.place, "title": Banner.title, "url": Banner.url,
            "sort": Banner.sort, "status": Banner.is_published},
        default="place", tiebreak=Banner.sort,
    )
    return render_template("admin/banners.html", items=q.all(), search=search, sorting=sorting,
                           places=BANNER_PLACES, edit=edited(Banner))


# Площадки и жанры
@bp.route("/refs", methods=["GET", "POST"])
@login_required
def refs():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        is_venue = f.get("kind") == "venue"
        model = Venue if is_venue else Category

        item = get_or_404(model, item_id) if item_id else model()
        item.name = f.get("name", "").strip()
        if is_venue:
            item.address = f.get("address", "").strip()
            item.description = rich("description")
            # Код карты вставляется на страницу как есть — его правит только администратор
            if g.user.is_admin:
                item.map_embed = f.get("map_embed", "").strip()
        else:
            item.sort = utils.parse_int(f.get("sort"), 100)
            known = dict(ROUTE_TAGS)
            item.route_tags = ",".join(t for t in f.getlist("route_tags") if t in known)

        if item.name:
            # Адрес при правке не меняем: на него ведут ссылки фильтров афиши
            if not item.slug:
                item.slug = unique_slug(model, item.name, item, f.get("slug"))
            save(item, "Площадка сохранена." if is_venue else "Категория сохранена.")
        else:
            db.session.rollback()
            flash("Укажите название.", "error")
        return redirect(url_for("admin.refs"))
    return render_template(
        "admin/refs.html",
        venues=Venue.query.order_by(Venue.name).all(),
        categories=Category.query.order_by(Category.sort).all(),
        route_tags=ROUTE_TAGS, edit=edited(Venue),
    )


@bp.route("/refs/<kind>/<int:item_id>/delete", methods=["POST"])
@login_required
def ref_delete(kind, item_id):
    model = Venue if kind == "venue" else Category
    item = get_or_404(model, item_id)
    column = Event.venue_id if model is Venue else Event.category_id
    used = Event.query.filter(column == item.id).count()
    if used:
        flash(f"«{item.name}» указана у событий: {used}. Сначала выберите им другую "
              f"{'площадку' if model is Venue else 'категорию'}.", "error")
    else:
        log("delete", item)
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("admin.refs"))


# Обращения
def purge_old_appeals() -> int:
    """Удаляет обработанные обращения старше срока хранения из «Настроек».

    Срок 0 или пустой — ничего не удаляется. Необработанные не трогаем никогда:
    сначала на обращение нужно ответить.
    """
    years = utils.parse_int(Setting.get("appeals_retention_years", "5"), 0)
    if not years:
        return 0
    border = utils.utcnow() - timedelta(days=365 * years)
    old = Appeal.query.filter(Appeal.is_processed.is_(True), Appeal.created_at < border)
    count = old.count()
    if count:
        old.delete(synchronize_session=False)
        log("purge", object_type="appeal", details=f"обращений: {count}, срок {years} лет")
        db.session.commit()
    return count


@bp.route("/appeals")
@login_required
def appeals():
    purged = purge_old_appeals()
    if purged:
        flash(f"Удалено обработанных обращений старше срока хранения: {purged}.", "ok")
    q = Appeal.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Appeal.name, search) | utils.like_ci(Appeal.subject, search)
                     | utils.like_ci(Appeal.email, search) | utils.like_ci(Appeal.phone, search))
    if request.args.get("status") in ("new", "done"):
        q = q.filter(Appeal.is_processed.is_(request.args.get("status") == "done"))
    q, sorting = sorted_by(
        q, {"date": Appeal.created_at, "name": Appeal.name, "subject": Appeal.subject,
            "status": Appeal.is_processed},
        default="date", default_dir="desc", tiebreak=Appeal.id.desc(),
    )
    return render_template(
        "admin/appeals.html", items=paginated(q), search=search, sorting=sorting,
        retention=utils.parse_int(Setting.get("appeals_retention_years", "5"), 0),
    )


@bp.route("/appeals/<int:item_id>", methods=["GET", "POST"])
@login_required
def appeal_view(item_id):
    item = get_or_404(Appeal, item_id)
    if request.method == "POST":
        item.is_processed = bool(request.form.get("is_processed"))
        item.note = request.form.get("note", "").strip()
        log("update", item, details="обработано" if item.is_processed else "")
        db.session.commit()
        flash("Обращение обновлено.", "ok")
        return redirect(url_for("admin.appeals"))
    return render_template("admin/appeal_view.html", item=item)


@bp.route("/appeals/<int:item_id>/print")
@login_required
def appeal_print(item_id):
    """Обращение на отдельной странице для печати или сохранения в PDF."""
    return render_template("admin/appeal_print.html", item=get_or_404(Appeal, item_id))


# Настройки
# Только администратор: здесь меняются телефон кассы, адрес учреждения
# и тексты, общие для всего сайта
@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    rows = Setting.query.order_by(Setting.group, Setting.title).all()
    if request.method == "POST":
        old_files = []
        for row in rows:
            if row.kind == "file":
                kinds = ("video",) if "video" in row.key else ("image",)
                try:
                    old_files += replace_file(row, "value", uploaded_name("f_" + row.key, kinds))
                except ValueError as exc:
                    flash(str(exc), "error")
            elif row.kind == "bool":
                row.value = "1" if request.form.get(row.key) else ""
            elif row.kind == "html" and row.key not in WIDGET_SETTINGS:
                row.value = rich(row.key)
            else:
                row.value = request.form.get(row.key, "")
        log("update", object_type="settings", details="настройки сайта")
        db.session.commit()
        release_files(old_files)
        flash("Настройки сохранены.", "ok")
        return redirect(url_for("admin.settings_page"))

    grouped = {}
    for row in rows:
        grouped.setdefault(row.group, []).append(row)
    return render_template("admin/settings.html", grouped=grouped, widget_keys=WIDGET_SETTINGS)


# Пользователи
@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(User, item_id) if item_id else User()
        back = url_for("admin.users", edit=item_id) if item_id else url_for("admin.users")
        login_name = f.get("login", "").strip()
        password = f.get("password", "").strip()
        role = f.get("role") if f.get("role") in ("admin", "editor") else "editor"
        is_active = bool(f.get("is_active"))
        taken = User.query.filter(User.login == login_name, User.id != (item.id or 0)).first()
        if not login_name:
            flash("Укажите логин.", "error")
        elif taken:
            flash(f"Логин «{login_name}» уже занят. Выберите другой.", "error")
        elif item.id is None and not password:
            flash("Задайте пароль новому сотруднику.", "error")
        # Проверяем любой введённый пароль, а не только у новых: иначе смена
        # пароля существующему сотруднику проходила мимо ограничения длины
        elif password and len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Пароль — не короче {MIN_PASSWORD_LENGTH} символов.", "error")
        # Иначе можно случайно запереть админку от самого себя
        elif item.id == g.user.id and (role != "admin" or not is_active):
            flash("Нельзя снять права администратора или отключить доступ самому себе.", "error")
        else:
            item.login, item.name = login_name, f.get("name", "").strip()
            item.role, item.is_active = role, is_active
            if password:
                item.set_password(password)
            save(item, "Сотрудник сохранён.")
            return redirect(url_for("admin.users"))
        return redirect(back)

    q = User.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(User.login, search) | utils.like_ci(User.name, search))
    if request.args.get("role") in ("admin", "editor"):
        q = q.filter(User.role == request.args.get("role"))
    if request.args.get("status") in ("on", "off"):
        q = q.filter(User.is_active.is_(request.args.get("status") == "on"))
    q, sorting = sorted_by(
        q, {"login": User.login, "name": User.name, "role": User.role,
            "last_login": User.last_login_at},
        default="login", tiebreak=User.id,
    )
    return render_template("admin/users.html", items=q.all(), search=search, sorting=sorting,
                           edit=edited(User))


@bp.route("/users/<int:item_id>/delete", methods=["POST"])
@admin_required
def user_delete(item_id):
    item = get_or_404(User, item_id)
    if item.id == g.user.id:
        flash("Нельзя удалить самого себя.", "error")
    else:
        log("delete", item)
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("admin.users"))


# Журнал действий
@bp.route("/log")
@admin_required
def action_log():
    q = ActionLog.query
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(ActionLog.title, search) | utils.like_ci(ActionLog.details, search))
    if utils.parse_int(a.get("user")):
        q = q.filter(ActionLog.user_id == utils.parse_int(a.get("user")))
    if a.get("type") in OBJECT_LABELS:
        q = q.filter(ActionLog.object_type == a.get("type"))
    if a.get("action") in ACTION_LABELS:
        q = q.filter(ActionLog.action == a.get("action"))
    # Даты в фильтре — московские, а в журнале время хранится в UTC
    date_from, date_to = utils.parse_date(a.get("from", "")), utils.parse_date(a.get("to", ""))
    if date_from:
        q = q.filter(ActionLog.created_at >= datetime.combine(date_from, datetime.min.time()) - MOSCOW_OFFSET)
    if date_to:
        q = q.filter(ActionLog.created_at <= datetime.combine(date_to, datetime.max.time()) - MOSCOW_OFFSET)
    q, sorting = sorted_by(
        q, {"date": ActionLog.created_at, "user": ActionLog.user_name, "action": ActionLog.action,
            "type": ActionLog.object_type, "title": ActionLog.title},
        default="date", default_dir="desc", tiebreak=ActionLog.id.desc(),
    )
    return render_template(
        "admin/log.html", items=paginated(q, 50), search=search, sorting=sorting,
        users=User.query.order_by(User.login).all(),
        object_labels=OBJECT_LABELS, action_labels=ACTION_LABELS,
    )


# Публикация из списка
# Раздел -> (модель, список, куда вернуться по умолчанию)
PUBLISH_TOGGLES = {
    "event": (Event, "admin.events"),
    "news": (News, "admin.news"),
    "collective": (Collective, "admin.collectives"),
    "page": (Page, "admin.pages"),
    "document": (Document, "admin.documents"),
    "banner": (Banner, "admin.banners"),
    "menu": (MenuItem, "admin.menu"),
}


@bp.route("/publish/<kind>/<int:item_id>", methods=["POST"])
@login_required
def toggle_publish(kind, item_id):
    """Публикует запись или снимает её с сайта прямо из таблицы раздела.

    Возвращает на ту же страницу списка — с фильтрами, сортировкой
    и прокруткой к строке записи.
    """
    if kind not in PUBLISH_TOGGLES:
        abort(404)
    model, endpoint = PUBLISH_TOGGLES[kind]
    item = get_or_404(model, item_id)
    item.is_published = not item.is_published
    state = "показывается на сайте" if item.is_published else "скрыто с сайта"
    log("update", item, details=state)
    db.session.commit()
    message = f"«{title_of(item)}» — {state}."
    # Скрипт админки переключает метку на месте, без перезагрузки страницы
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(published=item.is_published, message=message)
    flash(message, "ok")
    back = safe_next(request.form.get("next", "")) if request.form.get("next") else url_for(endpoint)
    return redirect(f"{back}#row-{item.id}")


# Удаление
# Семь разделов удаляются одинаково, поэтому маршруты описаны таблицей.
# Адреса и имена (admin.event_delete и прочие) прежние — шаблоны не меняются.
def page_in_use(page) -> str:
    """Почему страницу нельзя удалить; пустая строка — можно."""
    if page.children:
        titles = ", ".join(f"«{c.title}»" for c in page.children[:3])
        return (f"У страницы есть подстраницы: {titles}. Сначала перенесите их "
                f"в другой раздел или удалите.")
    links = MenuItem.query.filter_by(page_id=page.id).count()
    if links:
        return f"На страницу ведут пункты меню: {links}. Сначала уберите их в разделе «Меню»."
    return ""


def menu_in_use(item) -> str:
    if item.children:
        return (f"У пункта «{item.title}» есть подпункты: {len(item.children)}. "
                f"Сначала перенесите или удалите их.")
    return ""


DELETE_ROUTES = [
    # (адрес, имя маршрута, модель, сообщение, куда вернуться, проверка)
    ("/events/<int:item_id>/delete", "event_delete", Event, "Событие удалено.", "admin.events", None),
    ("/collectives/<int:item_id>/delete", "collective_delete", Collective,
     "Коллектив удалён.", "admin.collectives", None),
    ("/news/<int:item_id>/delete", "news_delete", News, "Новость удалена.", "admin.news", None),
    ("/pages/<int:item_id>/delete", "page_delete", Page, "Страница удалена.", "admin.pages", page_in_use),
    ("/menu/<int:item_id>/delete", "menu_delete", MenuItem, "", "admin.menu", menu_in_use),
    ("/documents/<int:item_id>/delete", "document_delete", Document, "", "admin.documents", None),
    ("/banners/<int:item_id>/delete", "banner_delete", Banner, "", "admin.banners", None),
]


def _make_delete_view(model, message, back, guard):
    def view(item_id):
        item = get_or_404(model, item_id)
        reason = guard(item) if guard else ""
        if reason:
            flash(reason, "error")
            return redirect(url_for(back))
        names = files_of(item)
        log("delete", item)
        db.session.delete(item)
        db.session.commit()
        release_files(names)
        if message:
            flash(message, "ok")
        return redirect(url_for(back))

    return view


for _rule, _endpoint, _model, _message, _back, _guard in DELETE_ROUTES:
    bp.add_url_rule(
        _rule, _endpoint,
        login_required(_make_delete_view(_model, _message, _back, _guard)),
        methods=["POST"],
    )
