"""Публичная часть сайта."""
import time
from datetime import datetime, timedelta, date

from flask import (
    Blueprint, render_template, request, abort, redirect, url_for,
    flash, make_response, current_app, g,
)
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from .models import (
    db, Event, Venue, Category, Collective, News, Page, Document,
    Banner, Appeal, Setting,
)
from . import utils

bp = Blueprint("public", __name__)

PER_PAGE_AFISHA = 15
PER_PAGE_NEWS = 12
SEARCH_LIMIT = 20
HOME_EVENTS = 6
CALENDAR_DAYS = 60
# Сколько концертов показывать на страницах «Пушкинская карта» и «Льготное посещение»
FLAGGED_EVENTS = 5
ROUTE_RESULTS = 6

# «Музыкальный маршрут»: три вопроса и варианты ответа (ключ, подпись)
ROUTE_QUESTIONS = [
    ("who", "С кем вы идёте?", [
        ("solo", "Один"), ("couple", "Вдвоём"),
        ("family", "Семьёй с детьми"), ("friends", "С друзьями"),
    ]),
    ("mood", "Какую атмосферу ищете?", [
        ("calm", "Спокойное вдохновение"), ("romance", "Тёплая романтика"),
        ("energy", "Энергия и драйв"), ("discover", "Новые открытия"),
    ]),
    ("when", "Когда вам удобно?", [
        ("today", "Сегодня"), ("week", "На этой неделе"), ("month", "В этом месяце"),
    ]),
]
# Какая атмосфера обычно подходит компании — добавляет концерту очков в подборке
WHO_MOODS = {"solo": {"calm", "discover"}, "couple": {"romance"}, "friends": {"energy"}}
# Детям на концерт до этого возраста включительно
FAMILY_MAX_AGE = 6


def cards():
    """События для карточек: площадка, жанр и фото приезжают сразу.

    Без этого каждая карточка отдельно ходила бы в базу за площадкой
    и за фото — по два запроса на концерт.
    """
    return Event.query.options(
        joinedload(Event.venue), joinedload(Event.category), selectinload(Event.media),
    )


def check_published(item) -> None:
    """Скрытую запись видят только сотрудники, вошедшие в админку; остальным — 404.

    Шаблон получает пометку и показывает плашку «Скрыто с сайта», чтобы редактор
    не принял предпросмотр за опубликованную страницу.
    """
    if not item.is_published:
        if not g.get("user"):
            abort(404)
        g.draft = True


# Главная
@bp.route("/")
def index():
    now = datetime.now()
    upcoming = (
        cards().filter(Event.is_published.is_(True), Event.starts_at >= now)
        .order_by(Event.starts_at)
        .limit(HOME_EVENTS)
        .all()
    )
    news = (
        News.query.filter_by(is_published=True)
        .order_by(News.published_at.desc())
        .limit(3)
        .all()
    )
    banners = Banner.query.filter_by(is_published=True).order_by(Banner.sort).all()
    history = Page.query.filter_by(
        slug=Setting.get("history_page", "istoriya"), is_published=True
    ).first()

    answers = _route_answers()
    route = _route_pick(**answers) if all(answers.values()) else None
    return render_template(
        "public/index.html",
        upcoming=upcoming,
        news=news,
        main_banners=[b for b in banners if b.place == "main"],
        banners=[b for b in banners if b.place == "partners"],
        history=history,
        day_strip=_day_strip(CALENDAR_DAYS),
        route_questions=ROUTE_QUESTIONS,
        answers=answers,
        route=route,
    )


# Музыкальный маршрут
@bp.route("/marshrut")
def route():
    """Подборка концертов по трём ответам.

    Скрипт главной запрашивает отсюда только кусок разметки с результатом.
    Без скрипта форма отправляется на главную и подборка приходит там же.
    """
    answers = _route_answers()
    if not all(answers.values()):
        return redirect(url_for("public.index", _anchor="marshrut"))
    return render_template("public/_route_result.html", route=_route_pick(**answers))


def _route_answers() -> dict:
    """Ответы из адреса; чужие значения отбрасываются."""
    return {
        key: request.args.get(key) if request.args.get(key) in {v for v, _ in options} else ""
        for key, _, options in ROUTE_QUESTIONS
    }


def _route_pick(who: str, mood: str, when: str) -> dict:
    """Подбирает концерты по ответам посетителя.

    Срок — жёсткий фильтр. Остальное начисляет очки: совпала атмосфера жанра —
    два, подходит компании — одно. Семье с детьми концерты старше 6+ не
    предлагаются вовсе. Если совпадений нет, показываем ближайшее в этот срок,
    чтобы посетитель не упирался в пустой экран.
    """
    now = datetime.now()
    # «Неделя» и «месяц» отсчитываются от сегодняшнего дня, а не по календарю:
    # иначе в воскресенье «на этой неделе» сводилось бы к одному вечеру
    ends = _day_end(now.date() + timedelta(days={"today": 0, "week": 6, "month": 30}[when]))
    candidates = (
        cards().filter(Event.is_published.is_(True),
                           Event.starts_at >= now, Event.starts_at <= ends)
        .order_by(Event.starts_at)
        .all()
    )
    if who == "family":
        candidates = [
            ev for ev in candidates
            if (ev.age_number is not None and ev.age_number <= FAMILY_MAX_AGE)
            or (ev.category and "family" in ev.category.tags)
        ]

    def score(ev) -> int:
        tags = set(ev.category.tags) if ev.category else set()
        if ev.is_new:
            tags.add("discover")
        points = 2 if mood in tags else 0
        if who == "family" and "family" in tags:
            points += 1
        elif tags & WHO_MOODS.get(who, set()):
            points += 1
        return points

    scored = [(score(ev), ev) for ev in candidates]
    matched = [ev for points, ev in sorted(scored, key=lambda p: (-p[0], p[1].starts_at)) if points]
    chosen = {"who": who, "mood": mood, "when": when}
    return {
        "events": (matched or candidates)[:ROUTE_RESULTS],
        "exact": bool(matched),
        # Подписи выбранных ответов — для строки «Вы выбрали: …»
        "labels": [dict(options)[chosen[key]] for key, _, options in ROUTE_QUESTIONS],
    }


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


# Афиша
@bp.route("/afisha")
def afisha():
    q = cards().filter(Event.is_published.is_(True))

    day = utils.parse_date(request.args.get("day", ""))
    date_from = utils.parse_date(request.args.get("from", ""))
    date_to = utils.parse_date(request.args.get("to", ""))
    venue_slug = request.args.get("venue", "")
    category_slug = request.args.get("category", "")
    price_max = utils.parse_int(request.args.get("price"))
    pushkin = request.args.get("pushkin") == "1"
    benefits = request.args.get("benefits") == "1"
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
    if benefits:
        q = q.filter(Event.show_benefits.is_(True))
    if only_new:
        q = q.filter(Event.is_new.is_(True))
    if search:
        like = search
        q = q.filter(
            or_(utils.like_ci(Event.title, like), utils.like_ci(Event.annotation, like),
                utils.like_ci(Event.description, like), utils.like_ci(Event.performers, like))
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
        day_strip=_day_strip(CALENDAR_DAYS),
        selected_day=day,
        args=request.args,
    )


@bp.route("/afisha/<slug>")
def event(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    check_published(ev)
    similar = (
        cards().filter(
            Event.is_published.is_(True),
            Event.id != ev.id,
            Event.starts_at >= datetime.now(),
        )
        .order_by(Event.starts_at)
        .limit(4)
        .all()
    )
    return render_template("public/event.html", ev=ev, similar=similar)


# Коллективы
@bp.route("/kollektivy")
def collectives():
    items = Collective.query.filter_by(is_published=True).order_by(Collective.sort).all()
    return render_template("public/collectives.html", items=items)


@bp.route("/kollektivy/<slug>")
def collective(slug):
    item = Collective.query.filter_by(slug=slug).first_or_404()
    check_published(item)
    events = (
        cards().filter(
            Event.is_published.is_(True),
            Event.starts_at >= datetime.now(),
            Event.collectives.any(id=item.id),
        )
        .order_by(Event.starts_at)
        .limit(6)
        .all()
    )
    return render_template("public/collective.html", item=item, events=events)


# Новости
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
    item = News.query.filter_by(slug=slug).first_or_404()
    check_published(item)
    other = (
        News.query.filter(News.is_published.is_(True), News.id != item.id)
        .order_by(News.published_at.desc())
        .limit(3)
        .all()
    )
    return render_template("public/news_item.html", item=item, other=other)


# Страницы и документы
# Страницы, под текстом которых выводятся концерты с отметкой:
# тип страницы -> (колонка-признак, параметр фильтра афиши)
FLAGGED_PAGES = {
    "pushkin": (Event.show_pushkin, "pushkin"),
    "benefits": (Event.show_benefits, "benefits"),
}


@bp.route("/info/<slug>")
def page(slug):
    pg = Page.query.filter_by(slug=slug).first_or_404()
    check_published(pg)
    documents, venues, events, afisha_filter = [], [], [], None
    if pg.template == "documents":
        documents = (
            Document.query.filter_by(is_published=True, category=pg.title)
            .order_by(Document.sort, Document.year.desc())
            .all()
        )
    elif pg.template == "contacts":
        # Страница «Контакты и схема проезда»: под текстом выводим площадки
        # с адресами и картами, которые заданы в разделе «Площадки и жанры»
        venues = Venue.query.order_by(Venue.name).all()
    elif pg.template in FLAGGED_PAGES:
        flag, afisha_filter = FLAGGED_PAGES[pg.template]
        events = (
            cards().filter(Event.is_published.is_(True), flag.is_(True),
                               Event.starts_at >= datetime.now())
            .order_by(Event.starts_at)
            .limit(FLAGGED_EVENTS)
            .all()
        )
    return render_template("public/page.html", pg=pg, documents=documents, venues=venues,
                           events=events, afisha_filter=afisha_filter)


@bp.route("/dokumenty")
def documents():
    rows = (
        Document.query.filter_by(is_published=True)
        .order_by(Document.category, Document.sort, Document.title)
        .all()
    )
    return render_template("public/documents.html", grouped=utils.group_by_category(rows))


# Интернет-приёмная
# Время последней отправки с адреса — чтобы форму не забивали роботы.
# Словарь в памяти процесса, как и счётчик попыток входа в админке.
_last_appeal = {}


def appeal_too_soon() -> bool:
    """Правда, если с этого адреса только что уже отправляли обращение."""
    window = current_app.config["APPEAL_INTERVAL_SECONDS"]
    now = time.time()
    for addr, sent in list(_last_appeal.items()):
        if now - sent > window:
            del _last_appeal[addr]
    return now - _last_appeal.get(request.remote_addr or "", 0.0) < window


@bp.route("/obrashcheniya", methods=["GET", "POST"])
def appeals():
    if request.method == "POST":
        if request.form.get("website"):
            # Поле-приманка скрыто стилями: его заполняют только роботы.
            # Отвечаем как при успехе, чтобы не подсказывать, что письмо не ушло.
            flash("Обращение принято. Ответ придёт в течение 30 дней.", "ok")
            return redirect(url_for("public.appeals"))
        if appeal_too_soon():
            flash("Обращение уже отправлено. Следующее можно отправить через минуту.", "error")
        elif not request.form.get("consent"):
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
            _last_appeal[request.remote_addr or ""] = time.time()
            flash("Обращение принято. Ответ придёт в течение 30 дней.", "ok")
            return redirect(url_for("public.appeals"))
    pg = Page.query.filter_by(slug="internet-priemnaya").first()
    return render_template("public/appeals.html", pg=pg)


# Поиск
@bp.route("/poisk")
def search():
    query = (request.args.get("q") or "").strip()
    found = {"events": [], "news": [], "pages": [], "collectives": []}
    if query:
        like = query
        found["events"] = (
            cards().filter(
                Event.is_published.is_(True),
                or_(utils.like_ci(Event.title, like), utils.like_ci(Event.description, like),
                    utils.like_ci(Event.performers, like)),
            )
            .order_by(Event.starts_at.desc())
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["news"] = (
            News.query.filter(
                News.is_published.is_(True),
                or_(utils.like_ci(News.title, like), utils.like_ci(News.content, like), utils.like_ci(News.lead, like)),
            )
            .order_by(News.published_at.desc())
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["pages"] = (
            Page.query.filter(
                Page.is_published.is_(True),
                or_(utils.like_ci(Page.title, like), utils.like_ci(Page.content, like)),
            )
            .limit(SEARCH_LIMIT)
            .all()
        )
        found["collectives"] = (
            Collective.query.filter(
                Collective.is_published.is_(True),
                or_(utils.like_ci(Collective.name, like), utils.like_ci(Collective.description, like)),
            )
            .limit(SEARCH_LIMIT)
            .all()
        )
    return render_template("public/search.html", query=query, **found)


# Служебное
@bp.route("/sitemap.xml")
def sitemap():
    urls = [(u, None) for u in ("/", "/afisha", "/kollektivy", "/novosti",
                                "/dokumenty", "/obrashcheniya")]
    # Адрес строится из slug, дата обновления подсказывает поисковику,
    # что переобходить. У коллективов своей даты нет — отдаём без неё.
    sources = (
        (Event, "/afisha/", Event.created_at),
        (Collective, "/kollektivy/", None),
        (News, "/novosti/", News.published_at),
        (Page, "/info/", Page.updated_at),
    )
    for model, prefix, changed in sources:
        columns = (model.slug, changed) if changed is not None else (model.slug,)
        for row in db.session.query(*columns).filter(model.is_published.is_(True)):
            urls.append((prefix + row[0], row[1] if changed is not None else None))
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
