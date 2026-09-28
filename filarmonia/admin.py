"""Панель управления сайтом."""
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    g, abort,
)

from .models import (
    db, User, Event, EventBadge, MediaItem, Collective, News, Album, Page,
    MenuItem, Document, Banner, Venue, Category, Appeal, Setting,
)
from . import utils

bp = Blueprint("admin", __name__)

PER_PAGE = 30


# ------------------------------------------------------------------- доступ
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
        if not g.get("user") or not g.user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------- общие помощники
def get_or_404(model, item_id):
    """Объект по идентификатору либо 404."""
    item = db.session.get(model, item_id)
    if item is None:
        abort(404)
    return item


def unique_slug(model, title: str, item, given: str = "") -> str:
    """Адрес страницы: введённый вручную либо построенный из заголовка."""
    given = (given or "").strip()
    if given:
        return given
    return utils.slugify(
        title,
        lambda candidate: model.query.filter(
            model.slug == candidate, model.id != item.id
        ).first() is not None,
    )


def uploaded_name(field: str, kinds=("image",)) -> str:
    """Сохраняет файл из поля формы. Пустая строка — файл не выбирали.

    При недопустимом расширении `utils.save_upload` бросает ValueError,
    который обработчик формы превращает в сообщение редактору.
    """
    uploaded = request.files.get(field)
    if uploaded and uploaded.filename:
        return utils.save_upload(uploaded, kinds)
    return ""


def paginated(query, per_page: int = PER_PAGE):
    page = utils.parse_int(request.args.get("page"), 1)
    return query.paginate(page=page, per_page=per_page, error_out=False)


def save(item, message: str):
    """Добавляет объект в сессию, если он новый, и сохраняет изменения."""
    if item.id is None:
        db.session.add(item)
    db.session.commit()
    flash(message, "ok")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(login=request.form.get("login", "").strip()).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            session["user_id"] = user.id
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            return redirect(request.args.get("next") or url_for("admin.dashboard"))
        flash("Неверный логин или пароль.", "error")
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("public.index"))


# ----------------------------------------------------------------- сводка
@bp.route("/")
@login_required
def dashboard():
    now = datetime.now()
    return render_template(
        "admin/dashboard.html",
        upcoming=Event.query.filter(Event.starts_at >= now).order_by(Event.starts_at).limit(8).all(),
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


# ------------------------------------------------------------------ афиша
@bp.route("/events")
@login_required
def events():
    q = Event.query
    search = (request.args.get("q") or "").strip()
    if search:
        q = q.filter(Event.title.ilike(f"%{search}%"))
    scope = request.args.get("scope", "upcoming")
    if scope == "upcoming":
        q = q.filter(Event.starts_at >= datetime.now())
    elif scope == "past":
        q = q.filter(Event.starts_at < datetime.now())
    items = paginated(q.order_by(Event.starts_at.desc()))
    return render_template("admin/events.html", items=items, scope=scope, search=search)


@bp.route("/events/new", methods=["GET", "POST"])
@bp.route("/events/<int:event_id>", methods=["GET", "POST"])
@login_required
def event_form(event_id=None):
    ev = get_or_404(Event, event_id) if event_id else Event(starts_at=datetime.now())

    if request.method == "POST":
        f = request.form
        ev.title = f.get("title", "").strip()
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
            ev.description = f.get("description", "").strip()
            ev.performers = f.get("performers", "").strip()
            ev.organizer = f.get("organizer", "").strip()
            ev.ticket_url = f.get("ticket_url", "").strip()
            ev.tickets_left = f.get("tickets_left", "").strip()
            ev.show_pushkin = bool(f.get("show_pushkin"))
            ev.pushkin_text = f.get("pushkin_text", "").strip()
            ev.show_benefits = bool(f.get("show_benefits"))
            ev.benefits_text = f.get("benefits_text", "").strip()
            ev.is_published = bool(f.get("is_published"))
            ev.is_new = bool(f.get("is_new"))
            ev.is_featured = bool(f.get("is_featured"))

            chosen = [utils.parse_int(i) for i in f.getlist("collectives")]
            ev.collectives = Collective.query.filter(Collective.id.in_(chosen)).all() if chosen else []

            for field in ("poster", "cover"):
                name = uploaded_name(field)
                if name:
                    setattr(ev, field, name)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/event_form.html", ev=ev, **_event_refs())

        save(ev, "Событие сохранено.")
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


# ------------------------------------------- всплывающие баннеры на афише
@bp.route("/events/<int:event_id>/badges", methods=["POST"])
@login_required
def badge_add(event_id):
    ev = get_or_404(Event, event_id)
    text = request.form.get("text", "").strip()
    if not text:
        flash("У баннера должна быть надпись.", "error")
    else:
        db.session.add(
            EventBadge(
                event_id=ev.id,
                text=text,
                hint=request.form.get("hint", "").strip(),
                url=request.form.get("url", "").strip(),
                position=request.form.get("position", "top-left"),
                style=request.form.get("style", "brick"),
                sort=utils.parse_int(request.form.get("sort"), 100),
            )
        )
        db.session.commit()
        flash("Баннер добавлен.", "ok")
    return redirect(url_for("admin.event_form", event_id=ev.id) + "#badges")


@bp.route("/badges/<int:badge_id>/delete", methods=["POST"])
@login_required
def badge_delete(badge_id):
    badge = get_or_404(EventBadge, badge_id)
    event_id = badge.event_id
    db.session.delete(badge)
    db.session.commit()
    return redirect(url_for("admin.event_form", event_id=event_id) + "#badges")


# --------------------------------------------------------- медиа (общее)
OWNERS = {
    "event": ("event_id", "admin.event_form", "event_id"),
    "collective": ("collective_id", "admin.collective_form", "item_id"),
    "news": ("news_id", "admin.news_form", "item_id"),
    "album": ("album_id", "admin.album_form", "item_id"),
}


@bp.route("/media/add", methods=["POST"])
@login_required
def media_add():
    owner = request.form.get("owner")
    owner_id = utils.parse_int(request.form.get("owner_id"))
    if owner not in OWNERS or not owner_id:
        abort(400)
    field, endpoint, arg = OWNERS[owner]

    kind = request.form.get("kind", "photo")
    item = MediaItem(kind=kind, title=request.form.get("title", "").strip(),
                     sort=utils.parse_int(request.form.get("sort"), 100))
    setattr(item, field, owner_id)

    try:
        if kind == "photo":
            files = request.files.getlist("file")
            saved = 0
            for uploaded in files:
                if uploaded and uploaded.filename:
                    clone = MediaItem(kind="photo", title=item.title, sort=item.sort)
                    setattr(clone, field, owner_id)
                    clone.file = utils.save_upload(uploaded, ("image",))
                    db.session.add(clone)
                    saved += 1
            if not saved:
                flash("Выберите хотя бы один файл.", "error")
            else:
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
                return redirect(url_for(endpoint, **{arg: owner_id}) + "#media")
            if preview and preview.filename:
                item.preview = utils.save_upload(preview, ("image",))
            db.session.add(item)
            db.session.commit()
            flash("Видео добавлено.", "ok")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for(endpoint, **{arg: owner_id}) + "#media")


@bp.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def media_delete(media_id):
    item = get_or_404(MediaItem, media_id)
    for field, endpoint, arg in OWNERS.values():
        value = getattr(item, field)
        if value:
            db.session.delete(item)
            db.session.commit()
            return redirect(url_for(endpoint, **{arg: value}) + "#media")
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


# ------------------------------------------------------------- коллективы
@bp.route("/collectives")
@login_required
def collectives():
    items = Collective.query.order_by(Collective.sort).all()
    return render_template("admin/collectives.html", items=items)


@bp.route("/collectives/new", methods=["GET", "POST"])
@bp.route("/collectives/<int:item_id>", methods=["GET", "POST"])
@login_required
def collective_form(item_id=None):
    item = get_or_404(Collective, item_id) if item_id else Collective()
    if request.method == "POST":
        f = request.form
        item.name = f.get("name", "").strip()
        try:
            if not item.name:
                raise ValueError("Укажите название коллектива.")
            item.slug = unique_slug(Collective, item.name, item, f.get("slug"))
            item.lead = f.get("lead", "").strip()
            item.annotation = f.get("annotation", "").strip()
            item.description = f.get("description", "").strip()
            item.contacts = f.get("contacts", "").strip()
            item.sort = utils.parse_int(f.get("sort"), 100)
            item.is_published = bool(f.get("is_published"))
            item.logo = uploaded_name("logo") or item.logo
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/collective_form.html", item=item)
        save(item, "Коллектив сохранён.")
        return redirect(url_for("admin.collective_form", item_id=item.id))
    return render_template("admin/collective_form.html", item=item)


# ----------------------------------------------------------------- новости
@bp.route("/news")
@login_required
def news():
    return render_template(
        "admin/news.html", items=paginated(News.query.order_by(News.published_at.desc()))
    )


@bp.route("/news/new", methods=["GET", "POST"])
@bp.route("/news/<int:item_id>", methods=["GET", "POST"])
@login_required
def news_form(item_id=None):
    item = get_or_404(News, item_id) if item_id else News(published_at=datetime.now())
    if request.method == "POST":
        f = request.form
        item.title = f.get("title", "").strip()
        try:
            if not item.title:
                raise ValueError("Укажите заголовок новости.")
            item.slug = unique_slug(News, item.title, item, f.get("slug"))
            item.lead = f.get("lead", "").strip()
            item.content = f.get("content", "").strip()
            item.published_at = (
                utils.parse_dt(f.get("published_at")) or item.published_at or datetime.now()
            )
            item.is_published = bool(f.get("is_published"))
            item.image = uploaded_name("image") or item.image
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/news_form.html", item=item)
        save(item, "Новость сохранена.")
        return redirect(url_for("admin.news_form", item_id=item.id))
    return render_template("admin/news_form.html", item=item)


# ----------------------------------------------------------------- галерея
@bp.route("/albums")
@login_required
def albums():
    items = Album.query.order_by(Album.year.desc(), Album.created_at.desc()).all()
    return render_template("admin/albums.html", items=items)


@bp.route("/albums/new", methods=["GET", "POST"])
@bp.route("/albums/<int:item_id>", methods=["GET", "POST"])
@login_required
def album_form(item_id=None):
    item = get_or_404(Album, item_id) if item_id else Album()
    if request.method == "POST":
        f = request.form
        item.title = f.get("title", "").strip()
        try:
            if not item.title:
                raise ValueError("Укажите название альбома.")
            item.slug = unique_slug(Album, item.title, item, f.get("slug"))
            item.year = utils.parse_int(f.get("year"), datetime.now().year)
            item.description = f.get("description", "").strip()
            item.is_published = bool(f.get("is_published"))
            item.cover = uploaded_name("cover") or item.cover
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/album_form.html", item=item)
        save(item, "Альбом сохранён.")
        return redirect(url_for("admin.album_form", item_id=item.id))
    return render_template("admin/album_form.html", item=item)


# ---------------------------------------------------------------- страницы
@bp.route("/pages")
@login_required
def pages():
    items = Page.query.order_by(Page.sort, Page.title).all()
    return render_template("admin/pages.html", items=items)


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
            return render_template("admin/page_form.html", item=item, parents=parents)
        item.slug = unique_slug(Page, item.title, item, f.get("slug"))
        item.content = f.get("content", "")
        item.parent_id = utils.parse_int(f.get("parent_id"))
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.template = f.get("template", "page")
        item.seo_description = f.get("seo_description", "").strip()
        item.is_published = bool(f.get("is_published"))
        item.show_in_menu = bool(f.get("show_in_menu"))
        save(item, "Страница сохранена.")
        return redirect(url_for("admin.page_form", item_id=item.id))
    return render_template("admin/page_form.html", item=item, parents=parents)


# -------------------------------------------------------------------- меню
@bp.route("/menu", methods=["GET", "POST"])
@login_required
def menu():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = db.session.get(MenuItem, item_id) if item_id else MenuItem()
        item.title = f.get("title", "").strip()
        item.url = f.get("url", "").strip()
        item.page_id = utils.parse_int(f.get("page_id"))
        item.parent_id = utils.parse_int(f.get("parent_id"))
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        if not item.title:
            flash("У пункта меню должно быть название.", "error")
        else:
            save(item, "Меню обновлено.")
        return redirect(url_for("admin.menu"))
    return render_template(
        "admin/menu.html",
        items=MenuItem.query.order_by(MenuItem.sort).all(),
        pages=Page.query.order_by(Page.title).all(),
    )


# --------------------------------------------------------------- документы
@bp.route("/documents", methods=["GET", "POST"])
@login_required
def documents():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = db.session.get(Document, item_id) if item_id else Document()
        item.title = f.get("title", "").strip()
        item.category = f.get("category", "").strip() or "Прочее"
        item.year = utils.parse_int(f.get("year"))
        item.doc_date = utils.parse_date(f.get("doc_date"))
        item.url = f.get("url", "").strip()
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        try:
            name = uploaded_name("file", ("doc", "image"))
            if name:
                item.file = name
                item.size_kb = utils.file_size_kb(name)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.documents"))
        if not item.title:
            flash("Укажите название документа.", "error")
        else:
            save(item, "Документ сохранён.")
        return redirect(url_for("admin.documents"))

    rows = Document.query.order_by(Document.category, Document.sort).all()
    return render_template("admin/documents.html", grouped=utils.group_by_category(rows))


# ----------------------------------------------------------------- баннеры
@bp.route("/banners", methods=["GET", "POST"])
@login_required
def banners():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = db.session.get(Banner, item_id) if item_id else Banner()
        item.title = f.get("title", "").strip()
        item.url = f.get("url", "").strip()
        item.place = f.get("place", "partners")
        item.sort = utils.parse_int(f.get("sort"), 100)
        item.is_published = bool(f.get("is_published"))
        try:
            item.image = uploaded_name("image") or item.image
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.banners"))
        if not item.title:
            flash("Укажите название баннера.", "error")
        else:
            save(item, "Баннер сохранён.")
        return redirect(url_for("admin.banners"))
    return render_template(
        "admin/banners.html", items=Banner.query.order_by(Banner.place, Banner.sort).all()
    )


# ------------------------------------------------------ площадки и жанры
@bp.route("/refs", methods=["GET", "POST"])
@login_required
def refs():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        is_venue = f.get("kind") == "venue"
        model = Venue if is_venue else Category

        item = db.session.get(model, item_id) if item_id else model()
        item.name = f.get("name", "").strip()
        if is_venue:
            item.address = f.get("address", "").strip()
            item.map_embed = f.get("map_embed", "").strip()
            item.description = f.get("description", "").strip()
        else:
            item.sort = utils.parse_int(f.get("sort"), 100)

        if item.name:
            item.slug = unique_slug(model, item.name, item, f.get("slug"))
            save(item, "Площадка сохранена." if is_venue else "Категория сохранена.")
        return redirect(url_for("admin.refs"))
    return render_template(
        "admin/refs.html",
        venues=Venue.query.order_by(Venue.name).all(),
        categories=Category.query.order_by(Category.sort).all(),
    )


@bp.route("/refs/<kind>/<int:item_id>/delete", methods=["POST"])
@login_required
def ref_delete(kind, item_id):
    item = get_or_404(Venue if kind == "venue" else Category, item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("admin.refs"))


# -------------------------------------------------------------- обращения
@bp.route("/appeals")
@login_required
def appeals():
    return render_template(
        "admin/appeals.html", items=paginated(Appeal.query.order_by(Appeal.created_at.desc()))
    )


@bp.route("/appeals/<int:item_id>", methods=["GET", "POST"])
@login_required
def appeal_view(item_id):
    item = get_or_404(Appeal, item_id)
    if request.method == "POST":
        item.is_processed = bool(request.form.get("is_processed"))
        item.note = request.form.get("note", "").strip()
        db.session.commit()
        flash("Обращение обновлено.", "ok")
        return redirect(url_for("admin.appeals"))
    return render_template("admin/appeal_view.html", item=item)


# --------------------------------------------------------------- настройки
@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    rows = Setting.query.order_by(Setting.group, Setting.title).all()
    if request.method == "POST":
        for row in rows:
            if row.kind == "file":
                kinds = ("video",) if "video" in row.key else ("image",)
                try:
                    row.value = uploaded_name("f_" + row.key, kinds) or row.value
                except ValueError as exc:
                    flash(str(exc), "error")
            elif row.kind == "bool":
                row.value = "1" if request.form.get(row.key) else ""
            else:
                row.value = request.form.get(row.key, "")
        db.session.commit()
        flash("Настройки сохранены.", "ok")
        return redirect(url_for("admin.settings_page"))

    grouped = {}
    for row in rows:
        grouped.setdefault(row.group, []).append(row)
    return render_template("admin/settings.html", grouped=grouped)


# ------------------------------------------------------------ пользователи
@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = db.session.get(User, item_id) if item_id else User()
        item.login = f.get("login", "").strip()
        item.name = f.get("name", "").strip()
        item.role = f.get("role", "editor")
        item.is_active = bool(f.get("is_active"))
        password = f.get("password", "").strip()
        if not item.login:
            flash("Укажите логин.", "error")
        elif item.id is None and len(password) < 8:
            flash("Пароль нового сотрудника — не короче 8 символов.", "error")
        else:
            if password:
                item.set_password(password)
            save(item, "Сотрудник сохранён.")
        return redirect(url_for("admin.users"))
    return render_template("admin/users.html", items=User.query.order_by(User.login).all())


@bp.route("/users/<int:item_id>/delete", methods=["POST"])
@admin_required
def user_delete(item_id):
    item = get_or_404(User, item_id)
    if item.id == g.user.id:
        flash("Нельзя удалить самого себя.", "error")
    else:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("admin.users"))


# ------------------------------------------------------------- удаление
# Восемь разделов удаляются одинаково, поэтому маршруты описаны таблицей.
# Адреса и имена (admin.event_delete и прочие) прежние — шаблоны не меняются.
DELETE_ROUTES = [
    # (адрес, имя маршрута, модель, сообщение, куда вернуться)
    ("/events/<int:item_id>/delete", "event_delete", Event, "Событие удалено.", "admin.events"),
    ("/collectives/<int:item_id>/delete", "collective_delete", Collective,
     "Коллектив удалён.", "admin.collectives"),
    ("/news/<int:item_id>/delete", "news_delete", News, "Новость удалена.", "admin.news"),
    ("/albums/<int:item_id>/delete", "album_delete", Album, "Альбом удалён.", "admin.albums"),
    ("/pages/<int:item_id>/delete", "page_delete", Page, "Страница удалена.", "admin.pages"),
    ("/menu/<int:item_id>/delete", "menu_delete", MenuItem, "", "admin.menu"),
    ("/documents/<int:item_id>/delete", "document_delete", Document, "", "admin.documents"),
    ("/banners/<int:item_id>/delete", "banner_delete", Banner, "", "admin.banners"),
]


def _make_delete_view(model, message, back):
    def view(item_id):
        db.session.delete(get_or_404(model, item_id))
        db.session.commit()
        if message:
            flash(message, "ok")
        return redirect(url_for(back))

    return view


for _rule, _endpoint, _model, _message, _back in DELETE_ROUTES:
    bp.add_url_rule(
        _rule, _endpoint,
        login_required(_make_delete_view(_model, _message, _back)),
        methods=["POST"],
    )
