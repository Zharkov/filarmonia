"""Публичная часть сайта."""
from datetime import datetime, timedelta, date

from flask import (
    Blueprint, render_template, request, abort, redirect, url_for,
    flash, make_response, current_app,
)
from sqlalchemy import or_

from .models import (
    db, Event, Venue, Category, Collective, News, Page, Document,
    Banner, Album, Appeal,
)
from . import utils

bp = Blueprint("public", __name__)

PER_PAGE_AFISHA = 15
PER_PAGE_NEWS = 12
SEARCH_LIMIT = 20


# --------------------------------------------------------------------- главная
@bp.route("/")
def index():
    now = datetime.now()
    upcoming = (
        Event.query.filter(Event.is_published.is_(True), Event.starts_at >= now)
        .order_by(Event.starts_at)
        .limit(8)
        .all()
    )
    news = (
        News.query.filter_by(is_published=True)
        .order_by(News.published_at.desc())
        .limit(6)
        .all()
    )
    collectives = (
        Collective.query.filter_by(is_published=True)
        .order_by(Collective.sort)
        .limit(4)
        .all()
    )
    banners = (
        Banner.query.filter_by(is_published=True, place="partners")
        .order_by(Banner.sort)
        .all()
    )
    return render_template(
        "public/index.html",
        upcoming=upcoming,
        news=news,
        collectives=collectives,
        banners=banners,
        day_strip=_day_strip(),
    )


def _day_strip(days: int = 21):
    """Лента ближайших дней с отметкой, есть ли в этот день концерты."""
    start = date.today()
    busy = {
        starts_at.date()
        for (starts_at,) in db.session.query(Event.starts_at).filter(
            Event.is_published.is_(True),
            Event.starts_at >= _day_start(start),
            Event.starts_at <= _day_end(start + timedelta(days=days - 1)),
        )
    }
    return [
        {"date": day, "has_events": day in busy}
        for day in (start + timedelta(days=i) for i in range(days))
    ]


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _day_end(day: date) -> datetime:
    return datetime.combine(day, datetime.max.time())


# ----------------------------------------------------------------------- афиша
@bp.route("/afisha")
def afisha():
    q = Event.query.filter(Event.is_published.is_(True))

    day = utils.parse_date(request.args.get("day", ""))
    date_from = utils.parse_date(request.args.get("from", ""))
    date_to = utils.parse_date(request.args.get("to", ""))
    venue_slug = request.args.get("venue", "")
    category_slug = request.args.get("category", "")
    price_max = utils.parse_int(request.args.get("price"))
    pushkin = request.args.get("pushkin") == "1"
    only_new = request.args.get("new") == "1"
    show_past = request.args.get("archive") == "1"
    search = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "date")

    if day:
        q = q.filter(Event.starts_at >= _day_start(day), Event.starts_at <= _day_end(day))
    else:
        if date_from:
            q = q.filter(Event.starts_at >= _day_start(date_from))
        if date_to:
            q = q.filter(Event.starts_at <= _day_end(date_to))
        if not show_past and not date_from:
            q = q.filter(Event.starts_at >= datetime.now())

    if venue_slug:
        q = q.join(Venue).filter(Venue.slug == venue_slug)
    if category_slug:
        q = q.join(Category).filter(Category.slug == category_slug)
    if price_max:
        q = q.filter(or_(Event.price_min.is_(None), Event.price_min <= price_max))
    if pushkin:
        q = q.filter(Event.show_pushkin.is_(True))
    if only_new:
        q = q.filter(Event.is_new.is_(True))
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(Event.title.ilike(like), Event.annotation.ilike(like),
                Event.description.ilike(like), Event.performers.ilike(like))
        )

    orders = {
        "price": (Event.price_min.asc().nullslast(), Event.starts_at),
        "title": (Event.title,),
        "date_desc": (Event.starts_at.desc(),),
    }
    q = q.order_by(*orders.get(sort, (Event.starts_at,)))

    page = utils.parse_int(request.args.get("page"), 1)
    events = q.paginate(page=page, per_page=PER_PAGE_AFISHA, error_out=False)

    return render_template(
        "public/afisha.html",
        events=events,
        venues=Venue.query.order_by(Venue.name).all(),
        categories=Category.query.order_by(Category.sort).all(),
        day_strip=_day_strip(28),
        selected_day=day,
        args=request.args,
    )


@bp.route("/afisha/<slug>")
def event(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    if not ev.is_published:
        abort(404)
    similar = (
        Event.query.filter(
            Event.is_published.is_(True),
            Event.id != ev.id,
            Event.starts_at >= datetime.now(),
        )
        .order_by(Event.starts_at)
        .limit(4)
        .all()
    )
    return render_template("public/event.html", ev=ev, similar=similar)


# ------------------------------------------------------------------ коллективы
@bp.route("/kollektivy")
def collectives():
    items = Collective.query.filter_by(is_published=True).order_by(Collective.sort).all()
    return render_template("public/collectives.html", items=items)


@bp.route("/kollektivy/<slug>")
def collective(slug):
    item = Collective.query.filter_by(slug=slug, is_published=True).first_or_404()
    events = (
        Event.query.filter(
            Event.is_published.is_(True),
            Event.starts_at >= datetime.now(),
            Event.collectives.any(id=item.id),
        )
        .order_by(Event.starts_at)
        .limit(6)
        .all()
    )
    return render_template("public/collective.html", item=item, events=events)


# --------------------------------------------------------------------- новости
@bp.route("/novosti")
def news_list():
    page = utils.parse_int(request.args.get("page"), 1)
    items = (
        News.query.filter_by(is_published=True)
        .order_by(News.published_at.desc())
        .paginate(page=page, per_page=PER_PAGE_NEWS, error_out=False)
    )
    return render_template("public/news_list.html", items=items)


@bp.route("/novosti/<slug>")
def news_item(slug):
    item = News.query.filter_by(slug=slug, is_published=True).first_or_404()
    other = (
        News.query.filter(News.is_published.is_(True), News.id != item.id)
        .order_by(News.published_at.desc())
        .limit(3)
        .all()
    )
    return render_template("public/news_item.html", item=item, other=other)


# -------------------------------------------------------------------- галерея
@bp.route("/galereya")
def gallery():
    year = utils.parse_int(request.args.get("year"))
    q = Album.query.filter_by(is_published=True)
    if year:
        q = q.filter_by(year=year)
    albums = q.order_by(Album.year.desc(), Album.created_at.desc()).all()
    years = [
        row.year
        for row in db.session.query(Album.year)
        .filter(Album.is_published.is_(True), Album.year.isnot(None))
        .distinct()
        .order_by(Album.year.desc())
    ]
    return render_template("public/gallery.html", albums=albums, years=years, year=year)


@bp.route("/galereya/<slug>")
def album(slug):
    item = Album.query.filter_by(slug=slug, is_published=True).first_or_404()
    return render_template("public/album.html", item=item)


# ------------------------------------------------------- страницы и документы
@bp.route("/info/<slug>")
def page(slug):
    pg = Page.query.filter_by(slug=slug, is_published=True).first_or_404()
    documents = []
    if pg.template == "documents":
        documents = (
            Document.query.filter_by(is_published=True, category=pg.title)
            .order_by(Document.sort, Document.year.desc())
            .all()
        )
    return render_template("public/page.html", pg=pg, documents=documents)


@bp.route("/dokumenty")
def documents():
    rows = (
        Document.query.filter_by(is_published=True)
        .order_by(Document.category, Document.sort, Document.title)
        .all()
    )
    return render_template("public/documents.html", grouped=utils.group_by_category(rows))


# ---------------------------------------------------------- интернет-приёмная
@bp.route("/obrashcheniya", methods=["GET", "POST"])
def appeals():
    if request.method == "POST":
        if not request.form.get("consent"):
            flash("Без согласия на обработку персональных данных обращение отправить нельзя.", "error")
        elif not request.form.get("name") or not request.form.get("message"):
            flash("Заполните имя и текст обращения.", "error")
        else:
            db.session.add(
                Appeal(
                    name=request.form["name"].strip()[:300],
                    email=request.form.get("email", "").strip()[:200],
                    phone=request.form.get("phone", "").strip()[:80],
                    subject=request.form.get("subject", "").strip()[:300],
                    message=request.form["message"].strip(),
                    consent=True,
                )
            )
            db.session.commit()
            flash("Обращение принято. Ответ придёт в течение 30 дней.", "ok")
            return redirect(url_for("public.appeals"))
    pg = Page.query.filter_by(slug="internet-priemnaya").first()
    return render_template("public/appeals.html", pg=pg)


# ----------------------------------------------------------------------- поиск
@bp.route("/poisk")
def search():
    query = (request.args.get("q") or "").strip()
    found = {"events": [], "news": [], "pages": [], "collectives": []}
    if query:
        like = f"%{query}%"
        found["events"] = (
            Event.query.filter(
                Event.is_published.is_(True),
                or_(Event.title.ilike(like), Event.description.ilike(like),
                    Event.performers.ilike(like)),
            )
            .order_by(Event.starts_at.desc())
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["news"] = (
            News.query.filter(
                News.is_published.is_(True),
                or_(News.title.ilike(like), News.content.ilike(like), News.lead.ilike(like)),
            )
            .order_by(News.published_at.desc())
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["pages"] = (
            Page.query.filter(
                Page.is_published.is_(True),
                or_(Page.title.ilike(like), Page.content.ilike(like)),
            )
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["collectives"] = (
            Collective.query.filter(
                Collective.is_published.is_(True),
                or_(Collective.name.ilike(like), Collective.description.ilike(like)),
            )
            .limit(SEARCH_LIMIT)
            .all()
        )
    return render_template("public/search.html", query=query, **found)


# ------------------------------------------------------------------ служебное
@bp.route("/sitemap.xml")
def sitemap():
    urls = ["/", "/afisha", "/kollektivy", "/novosti", "/galereya", "/dokumenty", "/obrashcheniya"]
    # У моделей адрес строится из slug, поэтому читаем только его.
    for model, prefix in ((Event, "/afisha/"), (Collective, "/kollektivy/"),
                          (News, "/novosti/"), (Page, "/info/")):
        urls += [
            prefix + slug
            for (slug,) in db.session.query(model.slug).filter(model.is_published.is_(True))
        ]
    body = render_template("public/sitemap.xml", urls=urls, host=request.host_url.rstrip("/"))
    resp = make_response(body)
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    return resp


@bp.route("/robots.txt")
def robots():
    if current_app.config["SITE_NOINDEX"]:
        # Тестовая копия сайта: закрыта от поисковиков целиком
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = (
            "User-agent: *\nDisallow: /admin\n"
            f"Sitemap: {request.host_url}sitemap.xml\n"
        )
    resp = make_response(body)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    return resp
