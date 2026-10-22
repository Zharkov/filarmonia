"""Доработки по ревью аудита 2026-10-21: Last-Modified, перенаправления, миграция 0017,
strip_tags, ссылки в JSON-LD, тексты 413, вход и возврат из формы обращений."""
import sqlite3
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from conftest import create_event, png, text

from filarmonia import schema, utils
from filarmonia.models import db, Event, EventBadge, MediaItem, News, Page, Redirect, Venue

OLD = datetime(2020, 1, 1, 12, 0, 0)


def _event(app, **fields):
    with app.app_context():
        data = dict(title="Концерт", slug="koncert", starts_at=utils.now_msk() + timedelta(days=30),
                    is_published=True)
        data.update(fields)
        ev = Event(**data)
        db.session.add(ev)
        db.session.commit()
        Event.query.update({"updated_at": OLD})
        db.session.commit()
        return ev.id


def _reset_updated(app):
    with app.app_context():
        Event.query.update({"updated_at": OLD})
        db.session.commit()


def _updated(app):
    with app.app_context():
        return Event.query.first().updated_at


# ---------- Last-Modified ----------

def test_media_add_move_delete_touch_owner(app, admin):
    ev_id = _event(app)
    for i in range(2):
        admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(ev_id), "kind": "photo",
                                            "file": (png(), f"p{i}.png")}, content_type="multipart/form-data")
    assert _updated(app) > OLD
    with app.app_context():
        first, second = [m.id for m in MediaItem.query.order_by(MediaItem.sort)]
    _reset_updated(app)
    admin.post(f"/admin/media/{second}/move", data={"dir": "up"})
    assert _updated(app) > OLD
    _reset_updated(app)
    admin.post(f"/admin/media/{first}/delete")
    assert _updated(app) > OLD


def test_badge_add_delete_touch_event(app, admin):
    ev_id = _event(app)
    admin.post(f"/admin/events/{ev_id}/badges", data={"text": "Хит", "position": "top-left", "style": "brick"})
    assert _updated(app) > OLD
    with app.app_context():
        badge_id = EventBadge.query.one().id
    _reset_updated(app)
    admin.post(f"/admin/badges/{badge_id}/delete")
    assert _updated(app) > OLD


def test_venue_change_touches_its_events(app, admin):
    with app.app_context():
        venue = Venue(name="Зал", slug="zal")
        db.session.add(venue)
        db.session.commit()
        venue_id = venue.id
    _event(app, venue_id=venue_id)
    admin.post("/admin/refs", data={"kind": "venue", "id": str(venue_id), "name": "Зал", "address": "ул. Новая"})
    assert _updated(app) > OLD


def test_event_form_save_touches_updated_at(app, admin):
    ev_id = _event(app)
    admin.post(f"/admin/events/{ev_id}", data={"title": "Концерт", "starts_at": "2031-01-01T19:00"},
               content_type="multipart/form-data")
    assert _updated(app) > OLD


def test_last_modified_event_not_earlier_than_start(app):
    starts = utils.now_msk() - timedelta(days=2)
    _event(app, starts_at=starts)
    r = app.test_client().get("/afisha/koncert")
    assert r.status_code == 200
    got = parsedate_to_datetime(r.headers["Last-Modified"]).replace(tzinfo=None)
    # starts_at — московское время, Last-Modified — UTC
    assert abs(got - utils.to_utc(starts)) < timedelta(seconds=2)


def test_last_modified_upcoming_event_is_updated_at(app):
    _event(app)
    r = app.test_client().get("/afisha/koncert")
    assert parsedate_to_datetime(r.headers["Last-Modified"]).replace(tzinfo=None) == OLD


def test_last_modified_news_without_updated_at_uses_moscow_time(app):
    with app.app_context():
        db.session.add(News(title="Н", slug="n", is_published=True, published_at=datetime(2026, 1, 1, 12, 0)))
        db.session.commit()
        News.query.update({"updated_at": None})
        db.session.commit()
    r = app.test_client().get("/novosti/n")
    got = parsedate_to_datetime(r.headers["Last-Modified"]).replace(tzinfo=None)
    assert got == datetime(2026, 1, 1, 9, 0)


def test_to_utc():
    assert utils.to_utc(datetime(2026, 1, 1, 1, 0)) == datetime(2025, 12, 31, 22, 0)
    assert utils.to_utc(None) is None


# ---------- Копия события ----------

def test_copy_gets_own_timestamps(app, admin):
    ev_id = _event(app)
    with app.app_context():
        Event.query.update({"created_at": OLD})
        db.session.commit()
    admin.post(f"/admin/events/{ev_id}/copy")
    with app.app_context():
        copy = Event.query.filter(Event.id != ev_id).one()
        assert copy.updated_at > OLD and copy.created_at > OLD


# ---------- strip_tags ----------

def test_strip_tags_unescapes_entities():
    assert utils.strip_tags("<p>Бах &amp; Моцарт</p>") == "Бах & Моцарт"
    assert utils.strip_tags("<p>Концерт&nbsp;№1</p>") == "Концерт №1"
    # уже раз экранированный текст в базе: «&amp;amp;» не доходит до описания
    assert utils.strip_tags("<p>А &amp;amp; Б</p>") == "А &amp; Б"


def test_strip_tags_result_still_escaped_in_page(app):
    _event(app, description="<p>&lt;script&gt;alert(1)&lt;/script&gt; Бах &amp; Моцарт</p>")
    body = text(app.test_client().get("/afisha/koncert"))
    assert "<script>alert(1)" not in body
    assert "&lt;script&gt;alert(1)" in body or "\\u003cscript\\u003ealert(1)" in body
    # в JSON-LD (tojson) скобки тоже экранированы
    assert "<script>alert" not in body.split("application/ld+json")[1].split("</script>")[0]


# ---------- JSON-LD: относительная ссылка на билеты ----------

def test_offers_relative_ticket_url_made_absolute(app):
    with app.test_request_context("/"):
        offer = schema.offers(Event(ticket_url="/kassa", price_min=500, slug="x"))
        assert offer["url"].startswith("http") and offer["url"].endswith("/kassa")
        offer = schema.offers(Event(ticket_url="https://t.example/1", price_min=500, slug="x"))
        assert offer["url"] == "https://t.example/1"


# ---------- Описание страницы ----------

def test_page_seo_description_trimmed_to_400(app, admin):
    admin.post("/admin/pages/new", data={"title": "Стр", "seo_description": "я\x00 " * 300})
    with app.app_context():
        desc = Page.query.one().seo_description
        assert len(desc) == 400 and "\x00" not in desc
    assert 'maxlength="400"' in text(admin.get("/admin/pages/new")).split('name="seo_description"')[1][:60]


# ---------- 413 ----------

def test_413_texts_differ_for_public_and_admin(app, admin):
    public = app.test_client().post("/obrashcheniya", data={"message": "x" * (200 * 1024)})
    assert public.status_code == 413
    assert "объём данных формы" in text(public) and "64 МБ" not in text(public)
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = admin.post("/admin/pages/new", data={"title": "x" * 5000})
    assert r.status_code == 413 and "64 МБ" in text(r)


# ---------- Перенаправления ----------

def _add_rule(client, old, new, **extra):
    return client.post("/admin/redirects", data={"old_path": old, "new_url": new, **extra},
                       follow_redirects=True)


def _rules(app):
    with app.app_context():
        return {(r.old_path, r.new_url) for r in Redirect.query.all()}


def test_redirect_loops_rejected(app, admin):
    assert "зациклится" in text(_add_rule(admin, "/a", "/a"))
    _add_rule(admin, "/a", "/b")
    assert "зациклится" in text(_add_rule(admin, "/b", "/a"))
    _add_rule(admin, "/b", "/c")
    # длинная петля: c -> a, а дальше a -> b -> c
    assert "зациклится" in text(_add_rule(admin, "/c", "/a"))
    assert _rules(app) == {("/a", "/b"), ("/b", "/c")}
    # внешний адрес цепочку обрывает
    _add_rule(admin, "/c", "https://other.example/x")
    assert ("/c", "https://other.example/x") in _rules(app)


def test_redirect_edit_does_not_loop_on_itself(app, admin):
    _add_rule(admin, "/a", "/b")
    with app.app_context():
        rid = Redirect.query.one().id
    _add_rule(admin, "/a", "/c", id=str(rid))
    assert _rules(app) == {("/a", "/c")}


def test_auto_redirect_overwrites_stale_rule_for_reused_slug(app, admin):
    create_event(admin, ticket_url="https://t.example/1")
    with app.app_context():
        db.session.add(Redirect(old_path="/afisha/testovyy-koncert", new_url="/afisha/drugoy"))
        db.session.commit()
        ev_id = Event.query.one().id
    data = {"title": "Тестовый концерт", "starts_at": "2030-12-31T19:00", "slug": "novyy",
            "ticket_url": "https://t.example/1"}
    admin.post(f"/admin/events/{ev_id}", data=data, content_type="multipart/form-data")
    assert _rules(app) == {("/afisha/testovyy-koncert", "/afisha/novyy")}


# ---------- Вход ----------

def test_login_strips_control_chars(app):
    r = app.test_client().post("/admin/login", data={"login": "ad\x00min\x01", "password": "secret123"})
    assert r.status_code == 302 and "/admin/login" not in r.headers["Location"]
    r = app.test_client().post("/admin/login", data={"login": "\x00", "password": "x"})
    assert r.status_code == 200


# ---------- Возврат из формы обращений ----------

def test_appeal_back_with_control_chars(app):
    client = app.test_client()
    bad = "/info/kontakty\r\nX: y\x00"
    for extra in ({"website": "bot"}, {}):
        r = client.post("/obrashcheniya", data={"back": bad, "name": "И", "email": "a@b.ru", "message": "m",
                                                "consent": "1", **extra})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/obrashcheniya"), r.headers["Location"]
    ok = client.post("/obrashcheniya", data={"back": "/info/kontakty", "website": "bot"})
    assert ok.headers["Location"].endswith("/info/kontakty#feedback")


# ---------- Миграция 0017 ----------

def test_migration_0017_depersonalizes_appeal_log(tmp_path):
    from alembic import command
    from filarmonia import create_app, migrate
    path = tmp_path / "m17.db"
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path), UPLOAD_FOLDER=str(tmp_path / "up"),
                     TESTING=True, SECRET_KEY="x")
    cfg = migrate.alembic_config(app)
    command.upgrade(cfg, "a5e9c4d2f318")
    con = sqlite3.connect(path)
    for oid, otype, title in ((7, "appeal", "Иванова М.П. — про билеты"), (None, "appeal", "Без номера"),
                              (3, "event", "Концерт")):
        con.execute("insert into action_log(action, object_type, object_id, title, details) "
                    "values('update',?,?,?,'')", (otype, oid, title))
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    rows = set(con.execute("select object_type, object_id, title from action_log"))
    assert rows == {("appeal", 7, "Обращение № 7"), ("appeal", None, "Без номера"), ("event", 3, "Концерт")}
    con.close()
    command.downgrade(cfg, "a5e9c4d2f318")
    command.upgrade(cfg, "head")
