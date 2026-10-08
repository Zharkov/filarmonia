"""Оформление: меню, документы, баннеры, перенаправления, площадки и жанры."""
from urllib.parse import urlsplit

from flask import render_template, request, redirect, url_for, flash, g
from sqlalchemy.orm import aliased

from ..models import (
    db, Event, Page, MenuItem, Document, Banner, Venue, Category, Redirect, ROUTE_TAGS,
)
from .. import utils
from . import bp
from .common import (
    delete_record, edited, get_or_404, log, login_required, release_files, replace_file, rich,
    save, search_text, sorted_by, unique_slug, uploaded_name,
)


BANNER_PLACES = [
    ("main", "Главная, крупно («Госуслуги. Решаем вместе»)"),
    ("partners", "Лента баннеров на главной"),
    ("footer", "Подвал"),
]


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


# Перенаправления со старых адресов
def redirect_source(value: str) -> str:
    """Старый адрес -> путь с параметрами: «https://old.ru/a.html?id=5» -> «/a.html?id=5»."""
    parts = urlsplit((value or "").strip())
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path + ("?" + parts.query if parts.query else "")


@bp.route("/redirects", methods=["GET", "POST"])
@login_required
def redirects():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(Redirect, item_id) if item_id else Redirect(hits=0)
        old_path = redirect_source(f.get("old_path", ""))
        new_url = f.get("new_url", "").strip()
        back = url_for("admin.redirects", edit=item_id) if item_id else url_for("admin.redirects")
        taken = Redirect.query.filter(Redirect.old_path == old_path, Redirect.id != (item.id or 0)).first()
        if not f.get("old_path", "").strip() or old_path == "/":
            flash("Укажите старый адрес страницы.", "error")
        elif not (new_url.startswith("/") and not new_url.startswith("//")) and not new_url.startswith("https://"):
            flash("Новый адрес должен начинаться с «/» или с «https://».", "error")
        elif redirect_source(new_url) == old_path and new_url.startswith("/"):
            flash("Старый и новый адреса совпадают: перенаправление зациклится.", "error")
        elif taken:
            flash(f"Для адреса «{old_path}» перенаправление уже есть.", "error")
        else:
            item.old_path, item.new_url = old_path, new_url
            save(item, "Перенаправление сохранено.")
            return redirect(url_for("admin.redirects"))
        db.session.rollback()
        return redirect(back)

    q = Redirect.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Redirect.old_path, search) | utils.like_ci(Redirect.new_url, search))
    q, sorting = sorted_by(
        q, {"old": Redirect.old_path, "new": Redirect.new_url, "hits": Redirect.hits},
        default="old", tiebreak=Redirect.id,
    )
    return render_template("admin/redirects.html", items=q.all(), search=search, sorting=sorting,
                           edit=edited(Redirect))


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
        flash(f"«{item.name}» указана у событий: {used}. Сначала укажите для них другую "
              f"{'площадку' if model is Venue else 'категорию'}.", "error")
    else:
        log("delete", item)
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("admin.refs"))


def menu_in_use(item) -> str:
    if item.children:
        return (f"У пункта «{item.title}» есть подпункты: {len(item.children)}. "
                f"Сначала перенесите или удалите их.")
    return ""


@bp.route("/menu/<int:item_id>/delete", methods=["POST"])
@login_required
def menu_delete(item_id):
    return delete_record(MenuItem, item_id, "admin.menu", guard=menu_in_use)


@bp.route("/documents/<int:item_id>/delete", methods=["POST"])
@login_required
def document_delete(item_id):
    return delete_record(Document, item_id, "admin.documents")


@bp.route("/banners/<int:item_id>/delete", methods=["POST"])
@login_required
def banner_delete(item_id):
    return delete_record(Banner, item_id, "admin.banners")


@bp.route("/redirects/<int:item_id>/delete", methods=["POST"])
@login_required
def redirect_delete(item_id):
    return delete_record(Redirect, item_id, "admin.redirects")
