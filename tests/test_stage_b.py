"""Аудит 2026-10-21, этап B: статус концерта, «бесплатно», SEO-поля, согласие на обработку
данных, JSON-LD, перенаправления при смене адреса, копии картинок, миграция 0016."""
import json
import os
import re
import sqlite3
from datetime import datetime

import pytest
from conftest import create_event, png, text

from filarmonia import schema, seed, utils
from filarmonia.models import (
    db, AfishaNotice, Appeal, Collective, Event, News, Page, Redirect, Setting, Venue,
)

LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
EVENT = "/afisha/testovyy-koncert"
FREE = "Бесплатные пригласительные билеты в кассе филармонии"


def event_ld(client, url=EVENT):
    blobs = [json.loads(m) for m in LDJSON.findall(text(client.get(url)))]
    return next(b for b in blobs if b.get("@type") == "Event")


def get_event(app, slug="testovyy-koncert"):
    with app.app_context():
        return Event.query.filter_by(slug=slug).one()


def edit_event(client, app, **fields):
    """Правка существующего события из формы (все поля, как отправил бы браузер)."""
    ev_id = get_event(app).id
    data = {"title": "Тестовый концерт", "starts_at": "2030-12-31T19:00", "price_min": "500",
            "age_limit": "6+", "ticket_url": "https://tickets.example/1", "show_media": "1"}
    data.update(fields)
    return client.post(f"/admin/events/{ev_id}", data=data, content_type="multipart/form-data",
                       follow_redirects=True)


# ---------- Модель: цена и статус ----------

def test_price_label_variants():
    assert Event(is_free=True, price_min=500).price_label == FREE
    assert Event(price_min=500, price_max=900).price_label == "500–900 ₽"
    assert Event(price_min=500, price_max=500).price_label == "от 500 ₽"
    assert Event(price_min=500).price_label == "от 500 ₽"
    # Цена не указана и «бесплатно» не отмечено — раньше сайт писал «бесплатно»
    assert Event().price_label == "Цена уточняется"
    assert Event(price_max=700).price_label == "Цена уточняется"


def test_status_properties():
    assert Event(status="scheduled").status_label == "" and Event().status_label == ""
    assert Event(status="cancelled").status_label == "Отменён"
    assert Event(status="rescheduled").status_label == "Перенесён"
    assert Event(status="postponed").status_label == "Отложен"
    assert Event(status="cancelled").sells_tickets is False
    assert Event(status="postponed").sells_tickets is False
    assert Event(status="rescheduled").sells_tickets is True
    future = datetime(2099, 1, 1)
    assert Event(starts_at=future, ticket_url="https://x.ru").can_buy is True
    assert Event(starts_at=future, ticket_url="https://x.ru", status="cancelled").can_buy is False
    assert Event(starts_at=future).can_buy is False                      # купить негде
    assert Event(starts_at=datetime(2000, 1, 1), ticket_url="https://x.ru").can_buy is False


# ---------- Админка: статус, прежняя дата, «бесплатно» ----------

def test_new_event_defaults(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    ev = get_event(app)
    assert ev.status == "scheduled" and ev.is_free is False and ev.previous_starts_at is None


def test_cancelled_event_page_hides_buying(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", yandex_id="123456",
                 hall_widget="<b>схема</b>")
    html = text(admin.get(EVENT))
    assert "Купить билет" in html and 'data-buybar' in html and 'id="bilety"' in html
    edit_event(admin, app, status="cancelled", yandex_id="123456")
    ev = get_event(app)
    assert ev.status == "cancelled"
    for url in (EVENT, "/afisha", "/"):
        html = text(admin.get(url))
        assert "Купить билет" not in html, url
    html = text(admin.get(EVENT))
    assert "event__status--cancelled" in html and "Концерт отменён" in html
    assert "data-buybar" not in html and 'id="bilety"' not in html and 'id="hall"' not in html
    # В афише — пометка статуса через свойство
    assert "eventrow__status--cancelled" in text(admin.get("/afisha"))


def test_postponed_event_page(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="postponed")
    html = text(admin.get(EVENT))
    assert "Концерт отложен" in html and "Купить билет" not in html
    assert "Новая дата будет объявлена" in html


def test_rescheduled_event_keeps_buying_and_shows_old_date(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="rescheduled", previous_starts_at="2030-11-05T18:30")
    ev = get_event(app)
    assert ev.status == "rescheduled" and ev.previous_starts_at == datetime(2030, 11, 5, 18, 30)
    html = text(admin.get(EVENT))
    assert "Концерт перенесён" in html and "Прежняя дата: 5 ноября 2030, 18:30" in html
    assert "Купить билет" in html


def test_previous_date_dropped_when_not_rescheduled(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="rescheduled", previous_starts_at="2030-11-05T18:30")
    edit_event(admin, app, status="cancelled", previous_starts_at="2030-11-05T18:30")
    assert get_event(app).previous_starts_at is None
    edit_event(admin, app, status="scheduled")
    assert get_event(app).status == "scheduled"


def test_status_omitted_keeps_current(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="cancelled")
    edit_event(admin, app)                      # поле статуса не прислали
    assert get_event(app).status == "cancelled"


def test_unknown_status_rejected(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    r = edit_event(admin, app, status="exploded")
    assert "Неизвестный статус" in text(r)
    assert get_event(app).status == "scheduled"


def test_event_form_shows_status_controls(app, admin):
    html = text(admin.get("/admin/events/new"))
    for label in ("По плану", "Отменён", "Перенесён", "Отложен", "Бесплатный концерт", "Для поисковиков"):
        assert label in html
    assert "data-previous-date" in html and "data-status-select" in html


def test_free_flag_clears_prices(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, is_free="1", price_min="500", price_max="900")
    ev = get_event(app)
    assert ev.is_free is True and ev.price_min is None and ev.price_max is None
    assert FREE in text(admin.get(EVENT))


def test_no_price_not_free_says_price_unknown(app, admin):
    create_event(admin, price_min="", price_max="", ticket_url="https://tickets.example/1")
    html = text(admin.get(EVENT))
    assert "Цена уточняется" in html and FREE not in html


def test_copy_resets_status(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="rescheduled", previous_starts_at="2030-11-05T18:30")
    admin.post(f"/admin/events/{get_event(app).id}/copy")
    with app.app_context():
        copy = Event.query.filter(Event.slug != "testovyy-koncert").one()
        assert copy.status == "scheduled" and copy.previous_starts_at is None


def test_admin_list_shows_status(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, status="cancelled")
    assert "Отменён" in text(admin.get("/admin/events"))


# ---------- «Изменения в афише» подсказывают сменить статус ----------

def _notice(admin, event_id, kind):
    return admin.post("/admin/notices", data={"kind": kind, "text": "Концерт отменяется",
                                              "event_id": str(event_id), "is_published": "1"},
                      follow_redirects=True)


def test_notice_cancel_hints_status_and_does_not_change_it(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    ev_id = get_event(app).id
    html = text(_notice(admin, ev_id, "cancel"))
    assert "Поменяйте статус концерта на странице события" in html
    assert f"/admin/events/{ev_id}#status" in html
    assert get_event(app).status == "scheduled"           # молча не меняется


def test_notice_no_hint_when_status_set_or_other_kind(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    ev_id = get_event(app).id
    assert "Поменяйте статус концерта" not in text(_notice(admin, ev_id, "venue"))
    edit_event(admin, app, status="cancelled")
    html = text(_notice(admin, ev_id, "cancel"))
    assert f"/admin/events/{ev_id}#status" not in html
    with app.app_context():
        assert AfishaNotice.query.count() == 2


# ---------- SEO-поля ----------

def test_seo_fields_saved_trimmed_and_used(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", annotation="Анонс")
    edit_event(admin, app, seo_title="  Свой\tзаголовок  \n концерта ", seo_description="О" * 500,
               annotation="Анонс")
    ev = get_event(app)
    assert ev.seo_title == "Свой заголовок концерта"
    assert len(ev.seo_description) == 300
    html = text(admin.get(EVENT))
    assert "<title>Свой заголовок концерта" in html
    assert f'<meta name="description" content="{"О" * 300}">' in html


def test_seo_title_length_capped(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, seo_title="З" * 400)
    assert len(get_event(app).seo_title) == 200


def test_event_without_seo_uses_defaults(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", annotation="Анонс концерта")
    html = text(admin.get(EVENT))
    assert "<title>Тестовый концерт — 31 декабря 2030, Смоленск" in html
    assert 'content="Анонс концерта"' in html


def test_collective_and_news_seo(app, admin):
    admin.post("/admin/collectives/new", data={
        "name": "Оркестр", "seo_title": "Оркестр филармонии", "seo_description": "Про оркестр",
        "is_published": "1"}, content_type="multipart/form-data")
    admin.post("/admin/news/new", data={
        "title": "Новость", "seo_title": "Заголовок новости", "seo_description": "Про новость",
        "is_published": "1"}, content_type="multipart/form-data")
    with app.app_context():
        col, news = Collective.query.one(), News.query.one()
        assert (col.seo_title, col.seo_description) == ("Оркестр филармонии", "Про оркестр")
        assert (news.seo_title, news.seo_description) == ("Заголовок новости", "Про новость")
    html = text(admin.get("/kollektivy/orkestr"))
    assert "<title>Оркестр филармонии" in html and 'content="Про оркестр"' in html
    html = text(admin.get("/novosti/novost"))
    assert "<title>Заголовок новости" in html and 'content="Про новость"' in html


def test_seo_block_in_forms(app, admin):
    for url in ("/admin/collectives/new", "/admin/news/new", "/admin/events/new"):
        html = text(admin.get(url))
        assert "Для поисковиков" in html and 'name="seo_title"' in html and 'name="seo_description"' in html


# ---------- JSON-LD ----------

def test_jsonld_status_and_previous_date(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    assert event_ld(admin)["eventStatus"].endswith("EventScheduled")
    assert "previousStartDate" not in event_ld(admin)
    edit_event(admin, app, status="cancelled")
    assert event_ld(admin)["eventStatus"] == "https://schema.org/EventCancelled"
    edit_event(admin, app, status="postponed")
    assert event_ld(admin)["eventStatus"] == "https://schema.org/EventPostponed"
    edit_event(admin, app, status="rescheduled", previous_starts_at="2030-11-05T18:30")
    data = event_ld(admin)
    assert data["eventStatus"] == "https://schema.org/EventRescheduled"
    assert data["previousStartDate"] == "2030-11-05T18:30:00+03:00"


def test_jsonld_offers_variants(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", price_min="500", price_max="900")
    offers = event_ld(admin)["offers"]
    assert offers["@type"] == "AggregateOffer" and offers["lowPrice"] == 500 and offers["highPrice"] == 900
    assert offers["priceCurrency"] == "RUB" and offers["url"] == "https://tickets.example/1"
    edit_event(admin, app, price_min="500")
    offers = event_ld(admin)["offers"]
    assert offers["@type"] == "Offer" and offers["price"] == 500
    edit_event(admin, app, is_free="1")
    data = event_ld(admin)
    assert data["offers"]["@type"] == "Offer" and data["offers"]["price"] == 0
    assert data["isAccessibleForFree"] is True
    edit_event(admin, app, price_min="")
    data = event_ld(admin)
    assert "offers" not in data and "isAccessibleForFree" not in data


def test_jsonld_availability_only_when_known(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    assert "availability" not in event_ld(admin)["offers"]
    edit_event(admin, app, tickets_left="нет билетов")
    assert event_ld(admin)["offers"]["availability"].endswith("SoldOut")


def test_jsonld_location_performers_organizer(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", performers="<p>Иван Петров, скрипка</p>")
    with app.app_context():
        db.session.add(Setting(key="address", value="214000, г. Смоленск, ул. Глинки, д. 3"))
        db.session.commit()
    data = event_ld(admin)
    assert data["location"]["name"] == "Филармония"                      # площадки нет — организация
    assert data["location"]["address"]["streetAddress"] == "ул. Глинки, д. 3"
    assert data["performer"] == [{"@type": "PerformingGroup", "name": "Иван Петров, скрипка"}]
    assert data["organizer"]["@id"].endswith("/#organization")
    edit_event(admin, app, organizer="Концертное агентство")
    assert event_ld(admin)["organizer"] == {"@type": "Organization", "name": "Концертное агентство"}


def test_jsonld_organization_extras(app):
    settings = {
        "site_name": "Смоленская областная филармония",
        "site_full_name": "Областное государственное бюджетное учреждение культуры «Смоленская областная филармония»",
        "map_point": "54.781496, 32.048407", "work_hours": "Пн–пт 9:00–18:00",
        "social_vk": "https://vk.com/", "social_ok": "https://ok.ru/club123",
    }
    with app.test_request_context("/"):
        org = schema.organization(settings)
    assert org["alternateName"].startswith("Областное")
    assert org["geo"] == {"@type": "GeoCoordinates", "latitude": 54.781496, "longitude": 32.048407}
    assert org["sameAs"] == ["https://ok.ru/club123"]                   # заглушка vk.com/ не выводится
    spec = org["openingHoursSpecification"]
    assert spec == [{"@type": "OpeningHoursSpecification", "opens": "09:00", "closes": "18:00",
                     "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]}]
    json.dumps(org, ensure_ascii=False)


@pytest.mark.parametrize("value", [
    "Пн–пт 9:00–18:00. Касса ежедневно 11:00–19:00", "по записи", "", "Пн–пт 9:00–18:00 (обед 13:00–14:00)",
    "Пн–пт 25:00–18:00", "Касса ежедневно 11:00–19:00",
])
def test_opening_hours_not_guessed(value):
    assert schema.opening_hours(value) == []


def test_opening_hours_forms():
    assert schema.opening_hours("ежедневно 11:00–19:00")[0]["dayOfWeek"][0] == "Monday"
    assert len(schema.opening_hours("ежедневно 11:00-19:00")[0]["dayOfWeek"]) == 7
    two = schema.opening_hours("Пн–пт 9:00–18:00; сб 10:00–15:00")
    assert [s["dayOfWeek"] for s in two] == [["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], ["Saturday"]]
    assert schema.opening_hours("сб–пн 10:00–15:00")[0]["dayOfWeek"] == ["Saturday", "Sunday", "Monday"]


def test_organization_without_extras_is_valid(app):
    with app.test_request_context("/"):
        org = schema.organization({})
    assert "alternateName" not in org and "geo" not in org and "openingHoursSpecification" not in org
    json.dumps(org)


# ---------- Согласие на обработку данных ----------

def test_appeal_records_consent_version(app):
    with app.app_context():
        db.session.add(Setting(key="consent_version", value="2026-10-21"))
        db.session.commit()
    r = app.test_client().post("/obrashcheniya", data={
        "name": "Иван", "email": "a@b.ru", "message": "Текст", "consent": "1"})
    assert r.status_code == 302
    with app.app_context():
        appeal = Appeal.query.one()
        assert appeal.consent is True and appeal.consent_version == "2026-10-21"
        assert appeal.consent_at is not None
        assert (utils.utcnow() - appeal.consent_at).total_seconds() < 60


def test_appeal_without_consent_not_saved(app):
    app.test_client().post("/obrashcheniya", data={"name": "Иван", "email": "a@b.ru", "message": "Текст"})
    with app.app_context():
        assert Appeal.query.count() == 0


def test_admin_appeal_shows_consent(app, admin):
    with app.app_context():
        a = Appeal(name="Иван", message="Текст", consent=True, consent_version="2026-10-21",
                   consent_at=datetime(2026, 10, 21, 12, 30))
        old = Appeal(name="Пётр", message="Текст", consent=True)
        db.session.add_all([a, old])
        db.session.commit()
        ids = a.id, old.id
    html = text(admin.get(f"/admin/appeals/{ids[0]}"))
    assert "Согласие на обработку данных" in html and "2026-10-21" in html and "21 октября 2026, 15:30 (мск)" in html
    assert "не записаны" in text(admin.get(f"/admin/appeals/{ids[1]}"))


def test_consent_text_is_marked_draft():
    html = seed.consent_text()
    assert "Проект текста. Перед публикацией согласовать с юристом учреждения." in html
    for part in ("ст", "152-ФЗ", "ОГБУК «Смоленская областная филармония»", "5 лет", "Отзыв согласия",
                 "третьим лицам", "Перечень персональных данных"):
        assert part in html
    assert "214000" in html


def test_seed_pages_and_settings_include_consent():
    titles = [p[0] for p in seed.PAGES]
    assert "Согласие на обработку персональных данных" in titles
    assert utils.slugify("Согласие на обработку персональных данных") == "soglasie-na-obrabotku-personalnyh-dannyh"
    keys = {row[0] for row in seed.SETTINGS}
    assert {"og_image", "yandex_verification", "google_site_verification", "home_title",
            "consent_version", "site_full_name"} <= keys
    og = next(row for row in seed.SETTINGS if row[0] == "og_image")
    assert og[4] == "file"


# ---------- Фильтр image_size, favicon ----------

def test_image_size_filter_registered(app):
    assert "image_size" in app.jinja_env.filters
    from PIL import Image
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    Image.open(png((300, 200))).convert("RGB").save(os.path.join(folder, "pic.jpg"))
    with app.app_context():
        assert app.jinja_env.filters["image_size"]("/static/uploads/pic.jpg") == (300, 200)


def test_og_image_dims_in_head(app, admin):
    from PIL import Image
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    Image.open(png((1200, 630))).convert("RGB").save(os.path.join(folder, "og.jpg"))
    with app.app_context():
        db.session.add(Setting(key="og_image", value="og.jpg", kind="file"))
        db.session.commit()
    html = text(admin.get("/"))
    assert "/static/uploads/og.jpg" in html and "og:image:width" in html


def test_favicon_ico_served(app):
    r = app.test_client().get("/favicon.ico")
    assert r.status_code == 200 and r.data[:4] in (b"\x00\x00\x01\x00", b"\x89PNG")
    assert "image" in r.headers["Content-Type"]


# ---------- Перенаправление при смене адреса (SEO-12) ----------

def rules(app):
    with app.app_context():
        return {(r.old_path, r.new_url) for r in Redirect.query.all()}


def test_event_slug_change_creates_redirect(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", is_published="1")
    r = edit_event(admin, app, slug="novyy-adres", is_published="1")
    assert "перенаправление" in text(r)
    assert rules(app) == {("/afisha/testovyy-koncert", "/afisha/novyy-adres")}
    r = admin.get("/afisha/testovyy-koncert")
    assert r.status_code == 301 and r.headers["Location"].endswith("/afisha/novyy-adres")
    assert admin.get("/afisha/novyy-adres").status_code == 200


def test_slug_change_no_chain(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, slug="b")
    with app.app_context():
        ev_id = Event.query.one().id
    admin.post(f"/admin/events/{ev_id}", data={"title": "Тестовый концерт", "starts_at": "2030-12-31T19:00",
                                              "slug": "c", "price_min": "500"})
    assert rules(app) == {("/afisha/testovyy-koncert", "/afisha/c"), ("/afisha/b", "/afisha/c")}


def test_slug_change_back_does_not_loop(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app, slug="b")
    with app.app_context():
        ev_id = Event.query.one().id
    admin.post(f"/admin/events/{ev_id}", data={"title": "Тестовый концерт", "starts_at": "2030-12-31T19:00",
                                              "slug": "testovyy-koncert", "price_min": "500"})
    found = rules(app)
    assert found == {("/afisha/b", "/afisha/testovyy-koncert")}
    assert admin.get("/afisha/testovyy-koncert").status_code == 200


def test_draft_slug_change_no_redirect(app, admin):
    admin.post("/admin/events/new", data={"title": "Черновик", "starts_at": "2030-12-31T19:00"})
    with app.app_context():
        ev = Event.query.one()
        assert ev.is_published is False
        ev_id = ev.id
    admin.post(f"/admin/events/{ev_id}", data={"title": "Черновик", "starts_at": "2030-12-31T19:00",
                                              "slug": "drugoy"})
    assert rules(app) == set()


def test_same_slug_no_redirect(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    edit_event(admin, app)
    assert rules(app) == set()


def test_stale_rule_for_old_address_rewritten_to_current_record(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    with app.app_context():
        db.session.add(Redirect(old_path="/afisha/testovyy-koncert", new_url="/afisha"))
        db.session.commit()
    edit_event(admin, app, slug="novyy")
    # Старый адрес занимала эта запись, а правило вело в другое место: переписывается на неё
    assert rules(app) == {("/afisha/testovyy-koncert", "/afisha/novyy")}


def test_news_collective_page_slug_change(app, admin):
    admin.post("/admin/news/new", data={"title": "Новость", "is_published": "1"}, content_type="multipart/form-data")
    admin.post("/admin/collectives/new", data={"name": "Хор", "is_published": "1"}, content_type="multipart/form-data")
    admin.post("/admin/pages/new", data={"title": "Страница", "is_published": "1"})
    with app.app_context():
        ids = News.query.one().id, Collective.query.one().id, Page.query.one().id
    admin.post(f"/admin/news/{ids[0]}", data={"title": "Новость", "slug": "n2", "publish": "1"})
    admin.post(f"/admin/collectives/{ids[1]}", data={"name": "Хор", "slug": "h2", "publish": "1"})
    admin.post(f"/admin/pages/{ids[2]}", data={"title": "Страница", "slug": "p2", "publish": "1"})
    assert rules(app) == {
        ("/novosti/novost", "/novosti/n2"), ("/kollektivy/hor", "/kollektivy/h2"),
        ("/info/stranica", "/info/p2"),
    }
    assert admin.get("/info/stranica").status_code == 301


# ---------- Копии картинок (SEO-17) ----------

def test_variants_include_1600_and_1920(app):
    assert utils.VARIANT_WIDTHS == (400, 800, 1200, 1600, 1920)
    from PIL import Image
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "wide.jpg")
    Image.new("RGB", (2000, 1000), (10, 20, 30)).save(path)
    with app.app_context():
        assert utils.make_variants(path) == 5
        assert utils.make_variants(path) == 0                               # повторно — ничего нового
        srcset = utils.srcset("/static/uploads/wide.jpg")
    for width in (1600, 1920):
        assert f"wide-{width}w.webp {width}w" in srcset
    # Картинку меньше 1600 не раздуваем
    small = os.path.join(folder, "mid.jpg")
    Image.new("RGB", (1300, 700), (10, 20, 30)).save(small)
    with app.app_context():
        utils.make_variants(small)
    assert not os.path.exists(os.path.join(folder, "mid-1600w.webp"))
    assert os.path.exists(os.path.join(folder, "mid-1200w.webp"))


def test_thumbs_adds_missing_copies_only(app):
    from filarmonia import maintenance
    from PIL import Image
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    Image.new("RGB", (2000, 1000), (10, 20, 30)).save(os.path.join(folder, "old.jpg"))
    Image.new("RGB", (400, 200), (1, 1, 1)).save(os.path.join(folder, "old-400w.webp"), "WEBP")
    before = os.path.getmtime(os.path.join(folder, "old-400w.webp"))
    assert maintenance.make_all_variants(app) == 4          # 800, 1200, 1600, 1920 — 400 уже есть
    assert os.path.getmtime(os.path.join(folder, "old-400w.webp")) == before
    assert maintenance.make_all_variants(app) == 0


# ---------- Миграция 0016 ----------

def _migration_env(tmp_path):
    from alembic import command
    from filarmonia import create_app, migrate
    path = tmp_path / "mig.db"
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path), UPLOAD_FOLDER=str(tmp_path / "up"),
                     TESTING=True, SECRET_KEY="x")
    return app, command, migrate.alembic_config(app), path


def test_migration_0016_upgrade_downgrade(tmp_path):
    app, command, cfg, path = _migration_env(tmp_path)
    command.upgrade(cfg, "f4d8b3c1e207")
    con = sqlite3.connect(path)
    con.execute("insert into pages(slug,title,content,sort,is_published,show_in_menu,template) "
                "values('politika-konfidencialnosti','П','',90,1,1,'page')")
    con.execute("insert into settings(key,value,title,\"group\",kind) values('address','г. Смоленск, ул. Тестовая','','','text')")
    for slug, lo, hi, yandex, url in (
            ("free", None, None, None, None), ("zero", 0, None, "", ""), ("zeros", 0, 0, None, ""),
            ("paid", 500, None, None, None), ("range", 100, 300, None, None), ("upto", None, 500, None, None),
            ("zero_up", 0, 500, None, None),
            # цена не указана, но билеты продаются: «бесплатно» писать нельзя
            ("sale_url", None, None, None, "https://t.example/1"), ("sale_yandex", 0, 0, "abc123", ""),
    ):
        con.execute("insert into events(title,slug,starts_at,price_min,price_max,yandex_id,ticket_url,"
                    "show_pushkin,show_benefits,show_media,is_published,is_new,is_featured) "
                    "values(?,?, '2030-01-01',?,?,?,?,0,0,1,1,0,0)", (slug, slug, lo, hi, yandex, url))
    con.execute("insert into appeals(name,message,consent,is_processed) values('n','m',1,0)")
    con.commit()
    con.close()

    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    # Раньше «бесплатными» считались концерты без цены (ни «от», ни «до»)
    free = dict(con.execute("select slug, is_free from events"))
    assert free == {"free": 1, "zero": 1, "zeros": 1, "paid": 0, "range": 0, "upto": 0, "zero_up": 0,
                    "sale_url": 0, "sale_yandex": 0}
    assert {r[0] for r in con.execute("select status from events")} == {"scheduled"}
    assert con.execute("select seo_title, seo_description from events").fetchone() == ("", "")
    assert con.execute("select consent_version, consent_at from appeals").fetchone() == ("", None)
    keys = dict(con.execute("select key, kind from settings"))
    for key in ("og_image", "yandex_verification", "google_site_verification", "home_title",
                "consent_version", "site_full_name"):
        assert key in keys
    assert keys["og_image"] == "file"
    assert con.execute("select value from settings where key='consent_version'").fetchone()[0] == "2026-10-21"
    page = con.execute("select title, is_published, parent_id, content from pages "
                       "where slug='soglasie-na-obrabotku-personalnyh-dannyh'").fetchone()
    assert page[0] == "Согласие на обработку персональных данных" and page[1] == 1 and page[2] is None
    assert "Проект текста" in page[3] and "г. Смоленск, ул. Тестовая" in page[3]
    con.close()

    # downgrade и повторный upgrade
    command.downgrade(cfg, "f4d8b3c1e207")
    con = sqlite3.connect(path)
    columns = {r[1] for r in con.execute("pragma table_info(events)")}
    assert not {"status", "previous_starts_at", "is_free", "seo_title", "seo_description"} & columns
    assert "consent_at" not in {r[1] for r in con.execute("pragma table_info(appeals)")}
    # Данные при откате не удаляются: страница согласия и настройки остаются
    assert con.execute("select count(*) from pages where slug like 'soglasie%'").fetchone()[0] == 1
    assert con.execute("select count(*) from settings where key in ('og_image','consent_version')").fetchone()[0] == 2
    con.close()
    command.upgrade(cfg, "head")


def test_migration_0016_keeps_existing_settings_and_page(tmp_path):
    app, command, cfg, path = _migration_env(tmp_path)
    command.upgrade(cfg, "f4d8b3c1e207")
    con = sqlite3.connect(path)
    con.execute("insert into settings(key,value,title,\"group\",kind) values('og_image','mine.jpg','','','file')")
    con.execute("insert into pages(slug,title,content,sort,is_published,show_in_menu,template) "
                "values('soglasie-na-obrabotku-personalnyh-dannyh','Моё','Текст юриста',92,1,1,'page')")
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    assert con.execute("select value from settings where key='og_image'").fetchone()[0] == "mine.jpg"
    assert con.execute("select content from pages where slug like 'soglasie%'").fetchone()[0] == "Текст юриста"
    con.close()
