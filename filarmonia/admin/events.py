"""Афиша: события, их копии и всплывающие баннеры на афише."""
from flask import render_template, request, redirect, url_for, flash, g, abort

from ..models import db, Event, EventBadge, MediaItem, Collective, Venue, Category
from .. import utils
from . import bp
from .common import (
    after_save, delete_record, get_or_404, log, login_required, paginated, publish_choice,
    release_files, replace_file, rich, save, search_text, sorted_by, status_note, unique_slug,
    uploaded_name,
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
        q = q.filter(Event.starts_at >= utils.now_msk())
    elif scope == "past":
        q = q.filter(Event.starts_at < utils.now_msk())
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
    ev = get_or_404(Event, event_id) if event_id else Event(starts_at=utils.now_msk(), is_published=False)

    if request.method == "POST":
        f = request.form
        was_published = bool(ev.id and ev.is_published)
        ev.title = f.get("title", "").strip()
        old_files = []
        try:
            if not ev.title:
                raise ValueError("Укажите название события.")

            ev.slug = unique_slug(Event, ev.title, ev, f.get("slug"))
            ev.starts_at = utils.parse_dt(f.get("starts_at")) or ev.starts_at or utils.now_msk()
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
            ev.yandex_id = utils.yandex_session_id(f.get("yandex_id", ""))
            ev.tickets_left = f.get("tickets_left", "").strip()
            # Код виджета вставляется на страницу как есть — его правит только администратор
            if g.user.is_admin:
                ev.hall_widget = f.get("hall_widget", "").strip()
            ev.show_media = bool(f.get("show_media"))
            ev.show_pushkin = bool(f.get("show_pushkin"))
            ev.pushkin_text = rich("pushkin_text")
            ev.show_benefits = bool(f.get("show_benefits"))
            ev.benefits_text = rich("benefits_text")
            ev.is_published = publish_choice(ev)
            ev.is_new = bool(f.get("is_new"))
            ev.is_featured = bool(f.get("is_featured"))

            chosen = [utils.parse_int(i) for i in f.getlist("collectives")]
            ev.collectives = Collective.query.filter(Collective.id.in_(chosen)).all() if chosen else []

            for field in ("poster", "cover"):
                old_files += replace_file(ev, field, uploaded_name(field))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("admin/event_form.html", ev=ev, unsaved=True, **_event_refs())

        save(ev, "Событие сохранено." + status_note(ev, was_published))
        release_files(old_files)
        return after_save(ev, url_for("admin.event_form", event_id=ev.id))

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
    flash("Копия сохранена как черновик и на сайте не отображается. Укажите дату и время, затем нажмите «Опубликовать».", "ok")
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


@bp.route("/events/<int:item_id>/delete", methods=["POST"])
@login_required
def event_delete(item_id):
    return delete_record(Event, item_id, "admin.events", "Событие удалено.")
