"""Коллективы, новости и страницы — записи с адресом на сайте."""
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from sqlalchemy.orm import aliased

from ..models import db, Event, Collective, News, Page, MenuItem, Document
from .. import utils
from . import bp
from .common import (
    BAD_URL_TEXT, after_save, delete_record, get_or_404, keep_old_address, log, login_required, paginated,
    publish_choice, release_files, replace_file, rich, safe_url, save, search_text, seo_text, set_seo, sorted_by,
    status_note, unique_slug, uploaded_name,
)


PAGE_TEMPLATES = [
    ("page", "Обычная"),
    ("documents", "Со списком документов"),
    ("documents_years", "Со списком документов по годам"),
    ("nok", "Независимая оценка качества: анкета с QR-кодом и документы по годам"),
    ("contacts", "Контакты: с площадками и картами"),
    ("pushkin", "Пушкинская карта: с концертами по карте"),
    ("benefits", "Льготное посещение: с концертами со льготами"),
]


# Разделы, у записей которых есть адрес страницы на сайте
SLUG_MODELS = {"event": Event, "news": News, "collective": Collective, "page": Page}


@bp.route("/slug")
@login_required
def slug_suggest():
    """Свободный адрес страницы — для подсказки в форме, пока редактор печатает.

    ?kind=event&title=…&slug=…&id=… -> {"slug": свободный, "wanted": желаемый, "taken": занят ли}.
    Сохранение всё равно проверяет адрес заново: между подсказкой и нажатием
    «Сохранить» его мог занять кто-то другой.
    """
    model = SLUG_MODELS.get(request.args.get("kind"))
    if model is None:
        abort(404)
    a = request.args
    given, title = (a.get("slug") or "").strip(), a.get("title") or ""
    if not (given or title.strip()):
        return jsonify(slug="", wanted="", taken=False)
    item = model(id=utils.parse_int(a.get("id")))
    wanted = utils.slugify(given or title)
    free = unique_slug(model, title, item, given)
    return jsonify(slug=free, wanted=wanted, taken=free != wanted)


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
    item = get_or_404(Collective, item_id) if item_id else Collective(is_published=False)
    if request.method == "POST":
        f = request.form
        was_published = bool(item.id and item.is_published)
        old_url = item.url if item.id else ""
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
            set_seo(item, f)
            item.is_published = publish_choice(item)
            old_files = replace_file(item, "logo", uploaded_name("logo"))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/collective_form.html", item=item, unsaved=True)
        moved = keep_old_address(item, old_url, was_published)
        save(item, "Коллектив сохранён." + status_note(item, was_published) + moved)
        release_files(old_files)
        return after_save(item, url_for("admin.collective_form", item_id=item.id))
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
    item = get_or_404(News, item_id) if item_id else News(published_at=utils.now_msk(), is_published=False)
    if request.method == "POST":
        f = request.form
        was_published = bool(item.id and item.is_published)
        old_url = item.url if item.id else ""
        item.title = f.get("title", "").strip()
        old_files = []
        try:
            if not item.title:
                raise ValueError("Укажите заголовок новости.")
            item.slug = unique_slug(News, item.title, item, f.get("slug"))
            item.lead = f.get("lead", "").strip()
            set_seo(item, f)
            item.content = rich("content")
            item.published_at = (
                utils.parse_dt(f.get("published_at")) or item.published_at or utils.now_msk()
            )
            item.is_published = publish_choice(item)
            item.show_media = f.get("layout", "media") == "media"
            old_files = replace_file(item, "image", uploaded_name("image"))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/news_form.html", item=item, unsaved=True)
        moved = keep_old_address(item, old_url, was_published)
        save(item, "Новость сохранена." + status_note(item, was_published) + moved)
        release_files(old_files)
        return after_save(item, url_for("admin.news_form", item_id=item.id))
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
    item = get_or_404(Page, item_id) if item_id else Page(is_published=False)
    parents = Page.query.filter(Page.id != (item.id or 0)).order_by(Page.title).all()
    if request.method == "POST":
        f = request.form
        was_published = bool(item.id and item.is_published)
        old_url = item.url if item.id else ""
        old_title = item.title
        item.title = f.get("title", "").strip()
        if not item.title:
            flash("Укажите заголовок страницы.", "error")
            return render_template("admin/page_form.html", item=item, parents=parents,
                                   templates=PAGE_TEMPLATES, unsaved=True)
        item.slug = unique_slug(Page, item.title, item, f.get("slug"))
        item.content = rich("content")
        item.parent_id = utils.parse_int(f.get("parent_id"))
        item.sort = utils.parse_int(f.get("sort"), 100)
        template = f.get("template", "page")
        item.template = template if template in dict(PAGE_TEMPLATES) else "page"
        item.seo_description = seo_text(f.get("seo_description"), 400)  # колонка pages.seo_description — 400
        item.is_published = publish_choice(item)
        item.show_in_menu = bool(f.get("show_in_menu"))
        if old_title and old_title != item.title:
            # Документы находят страницу по её заголовку — переносим их вслед за ним
            Document.query.filter_by(category=old_title, news_id=None).update({"category": item.title})
        moved = keep_old_address(item, old_url, was_published)
        save(item, "Страница сохранена." + status_note(item, was_published) + moved)
        return after_save(item, url_for("admin.page_form", item_id=item.id))
    return render_template("admin/page_form.html", item=item, parents=parents,
                           templates=PAGE_TEMPLATES)


def page_in_use(page) -> str:
    """Почему страницу нельзя удалить; пустая строка — можно."""
    if page.children:
        titles = ", ".join(f"«{c.title}»" for c in page.children[:3])
        return (f"У страницы есть подстраницы: {titles}. Сначала перенесите их "
                f"в другой раздел или удалите.")
    links = MenuItem.query.filter_by(page_id=page.id).count()
    if links:
        return f"На страницу ведут пункты меню: {links}. Сначала удалите их в разделе «Меню»."
    return ""


@bp.route("/collectives/<int:item_id>/delete", methods=["POST"])
@login_required
def collective_delete(item_id):
    return delete_record(Collective, item_id, "admin.collectives", "Коллектив удалён.")


# Документы, прикреплённые к новости
@bp.route("/news/<int:item_id>/documents", methods=["POST"])
@login_required
def news_document_add(item_id):
    item = get_or_404(News, item_id)
    back = url_for("admin.news_form", item_id=item.id) + "#documents"
    f = request.form
    url = safe_url(f.get("url"))
    if url is None:
        flash(BAD_URL_TEXT, "error")
        return redirect(back)
    doc = Document(news_id=item.id, category="", is_published=True,
                   title=f.get("title", "").strip(), url=url,
                   sort=utils.parse_int(f.get("sort"), (len(item.documents) + 1) * 10))
    try:
        doc.file = uploaded_name("file", ("doc", "image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(back)
    if not doc.title and doc.file:
        doc.title = request.files["file"].filename.rsplit(".", 1)[0]
    if not doc.title or not (doc.file or doc.url):
        release_files([doc.file])
        flash("Укажите название и выберите файл или впишите ссылку.", "error")
        return redirect(back)
    if doc.file:
        doc.size_kb = utils.file_size_kb(doc.file)
    db.session.add(doc)
    db.session.flush()
    log("create", doc, details=f"новость «{item.title}»")
    db.session.commit()
    flash("Документ прикреплён к новости.", "ok")
    return redirect(back)


@bp.route("/news/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def news_document_delete(doc_id):
    doc = get_or_404(Document, doc_id)
    if not doc.news_id:
        abort(404)
    back = url_for("admin.news_form", item_id=doc.news_id) + "#documents"
    names = [doc.file]
    log("delete", doc)
    db.session.delete(doc)
    db.session.commit()
    release_files(names)
    flash("Документ откреплён от новости.", "ok")
    return redirect(back)


@bp.route("/news/<int:item_id>/delete", methods=["POST"])
@login_required
def news_delete(item_id):
    return delete_record(News, item_id, "admin.news", "Новость удалена.")


@bp.route("/pages/<int:item_id>/delete", methods=["POST"])
@login_required
def page_delete(item_id):
    return delete_record(Page, item_id, "admin.pages", "Страница удалена.", guard=page_in_use)
