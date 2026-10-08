"""Общее для всех разделов панели: доступ, журнал, сохранение записей, файлы."""
from functools import wraps

from flask import request, redirect, url_for, flash, g, abort

from ..models import (
    db, User, Event, EventBadge, MediaItem, Collective, News, Page, MenuItem, Document, Banner,
    Venue, Category, Appeal, Setting, ActionLog, Redirect, referenced_uploads,
)
from .. import reset_site_data, utils
from . import bp


PER_PAGE = 30

# Тип объекта для журнала: модель -> (ключ, подпись)
OBJECT_TYPES = {
    Event: ("event", "Событие"), News: ("news", "Новость"), Collective: ("collective", "Коллектив"),
    Page: ("page", "Страница"), MenuItem: ("menu", "Пункт меню"), Document: ("document", "Документ"),
    Banner: ("banner", "Баннер"), Venue: ("venue", "Площадка"), Category: ("category", "Жанр"),
    User: ("user", "Сотрудник"), Appeal: ("appeal", "Обращение"), MediaItem: ("media", "Фото или видео"),
    EventBadge: ("badge", "Баннер на афише"), Setting: ("settings", "Настройки"),
    Redirect: ("redirect", "Перенаправление"),
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


def publish_choice(item) -> bool:
    """Показывать ли запись на сайте после сохранения.

    Кнопки формы присылают publish=1 («Опубликовать») или publish=0
    («Снять с публикации»). Обычное «Сохранить» и «Предпросмотр» статус
    не меняют: новая запись остаётся черновиком, опубликованная — на сайте.
    Поле is_published — от прежней формы с флажком.
    """
    choice = request.form.get("publish")
    if choice in ("0", "1"):
        return choice == "1"
    if request.form.get("is_published"):
        return True
    return bool(item.id and item.is_published)


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
    """Запись в журнал действий. Сохраняется вместе с ближайшим commit.

    Любое изменение заодно сбрасывает настройки и меню, которые сайт держит
    в памяти: правка видна посетителям сразу, а не через полминуты.
    """
    reset_site_data()
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


def status_note(item, was_published: bool) -> str:
    """Пояснение к «Сохранено»: что теперь видно на сайте."""
    if item.is_published and not was_published:
        return " Запись опубликована и отображается на сайте."
    if not item.is_published and was_published:
        return " Запись снята с публикации и на сайте не отображается."
    if not item.is_published:
        return " Запись сохранена как черновик и доступна только сотрудникам."
    return ""


def after_save(item, edit_url: str):
    """Куда вести после сохранения: «Предпросмотр» открывает запись
    на сайте (черновик там видят только сотрудники), обычное — обратно в форму."""
    return redirect(item.url if request.form.get("then") == "view" else edit_url)


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


def delete_record(model, item_id: int, back: str, message: str = "", guard=None):
    """Удаляет запись вместе с её файлами и возвращает к списку раздела.

    guard(item) объясняет, почему удалять нельзя (пустая строка — можно):
    например, на страницу ещё ведут пункты меню.
    """
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
