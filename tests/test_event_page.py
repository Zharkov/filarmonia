"""Страница события: порядок блоков, бесплатный концерт, стрелки каруселей."""
from conftest import create_event, png, text

from filarmonia.models import db, Event, Venue, Setting


def _full_event(app, admin, **extra):
    """Событие со всеми блоками страницы, плюс второе — для «Ближайших концертов»."""
    create_event(admin, description="<p>Описание-концерта</p>", show_pushkin="1", show_benefits="1",
                 benefits_text="<p>Льгота-пенсионерам</p>", **extra)
    create_event(admin, title="Соседний концерт", starts_at="2030-12-30T19:00")
    with app.app_context():
        venue = Venue(name="Зал-карта", slug="zal-karta", address="ул. Карты, 1",
                      map_embed='<iframe title="карта-площадки"></iframe>')
        db.session.add(venue)
        db.session.flush()
        Event.query.filter_by(title="Тестовый концерт").first().venue_id = venue.id
        db.session.commit()
    ev_id = None
    with app.app_context():
        ev_id = Event.query.filter_by(title="Тестовый концерт").first().id
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(ev_id), "kind": "photo",
                                         "file": (png(), "f.png")}, content_type="multipart/form-data")


def _order(html, *marks):
    positions = [html.index(m) for m in marks]
    assert positions == sorted(positions), dict(zip(marks, positions))


def test_event_blocks_order_with_hall_scheme(app, admin):
    _full_event(app, admin, hall_widget='<div id="hall-scheme"></div>')
    html = text(admin.get("/afisha/testovyy-koncert"))
    # Верх: афиша, цена и факты; затем медиа, описание, схема зала, условия, карта, ближайшие
    _order(html, "event__facts", "Фото и видео", "<h2>О концерте</h2>",
           'id="hall"', "Льгота-пенсионерам", "Оплата Пушкинской картой",
           "Как добраться", "Ближайшие концерты")
    assert "event__terms--pair" in html


def test_event_blocks_order_with_yandex_widget(app, admin):
    _full_event(app, admin, yandex_id="496249")
    html = text(admin.get("/afisha/testovyy-koncert"))
    _order(html, "Фото и видео", "<h2>О концерте</h2>", 'id="bilety"', "Льгота-пенсионерам",
           "Оплата Пушкинской картой", "Как добраться", "Ближайшие концерты")
    # Виджет остаётся скрытым до скрипта, а вторая схема зала не выводится
    assert 'data-ya-widget="' in html and "data-ya-widget-frame" in html and 'id="hall"' not in html
    assert 'id="bilety" data-ya-widget="' in html and "hidden>" in html[html.index('id="bilety"'):][:120]


def test_event_description_not_in_facts_column(app, admin):
    create_event(admin, description="<p>Описание-концерта</p>")
    html = text(admin.get("/afisha/testovyy-koncert"))
    facts_end = html.index("event__facts")
    # Между таблицей фактов и описанием уже закрыта сетка .event (заголовок «О концерте»)
    assert html.index("О концерте") > facts_end
    assert "</div>\n  </div>" in html[facts_end:html.index("О концерте")]
    assert "event__terms" not in html


def test_free_event_label(app, admin):
    create_event(admin, price_min="", price_max="", is_free="1", ticket_url="https://tickets.example/1")
    new = "Бесплатные пригласительные билеты в кассе филармонии"
    for url in ("/afisha/testovyy-koncert", "/afisha", "/"):
        html = text(admin.get(url))
        assert new in html and "Вход свободный" not in html
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert "event__price--text" in html and "buybar__price--text" in html
    # Бесплатный концерт: цена 0 и признак бесплатности (SEO-10)
    assert '"price": 0' in html or '"price":0' in html


def test_paid_event_label_unchanged(app, admin):
    create_event(admin)
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert "от 500 ₽" in html and "event__price--text" not in html


def test_carousel_arrows_in_section_head(app, admin):
    create_event(admin)
    html = text(admin.get("/"))
    head = html.index('class="section__head"')
    nav = html.index('data-ecarousel-nav="home-events"')
    track = html.index("data-ecarousel-track")
    assert head < nav < track
    # Стрелки в одной строке заголовка с кнопкой «Вся афиша», слева от неё
    assert nav < html.index("Вся афиша") and "section__tools" in html
    assert 'id="home-events"' in html and 'aria-controls="home-events"' in html
    # Скрыты до скрипта и подписаны
    assert 'data-ecarousel-nav="home-events" hidden' in html
    assert 'aria-label="Назад"' in html and 'aria-label="Вперёд"' in html


def test_carousel_arrows_on_event_page(app, admin):
    create_event(admin)
    create_event(admin, title="Соседний концерт", starts_at="2030-12-30T19:00")
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert html.index("Ближайшие концерты") < html.index("data-ecarousel-nav") < html.index("data-ecarousel-track")


# ---------- Пустые блоки, прошедшее событие, стрелки на других страницах ----------
import json
import re

from filarmonia.models import Page, Collective

FREE = "Бесплатные пригласительные билеты в кассе филармонии"
SLUG_EV = "/afisha/testovyy-koncert"
LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _no_empty_headings(html):
    assert not re.search(r"<h2>\s*</h2>", html)
    assert not re.search(r'<section class="section">\s*</section>', html)


def test_minimal_event_has_no_empty_sections(app, admin):
    create_event(admin)  # без медиа, описания, схемы, льгот, площадки
    resp = admin.get(SLUG_EV)
    assert resp.status_code == 200
    html = text(resp)
    for title in ("Фото и видео", "О концерте", "Схема зала", "Льготы", "Пушкинской картой",
                  "Как добраться", "Ближайшие концерты"):
        assert title not in html, title
    assert 'id="hall"' not in html and 'id="bilety"' not in html
    _no_empty_headings(html)


def test_benefits_flag_without_text_has_no_empty_block(app, admin):
    create_event(admin, show_benefits="1", benefits_text="")
    html = text(admin.get(SLUG_EV))
    assert "Льготы" not in html and "event__terms" not in html
    _no_empty_headings(html)


def test_media_flag_without_media_no_section(app, admin):
    create_event(admin, show_media="1")
    assert "Фото и видео" not in text(admin.get(SLUG_EV))


def test_only_pushkin_terms_single_block(app, admin):
    create_event(admin, show_pushkin="1")
    html = text(admin.get(SLUG_EV))
    assert "Оплата Пушкинской картой" in html and "Льготы" not in html
    assert "event__terms--pair" not in html


def test_collectives_only_shows_about_block(app, admin):
    create_event(admin)
    with app.app_context():
        c = Collective(name="Оркестр-тест", slug="orkestr-test")
        db.session.add(c)
        db.session.flush()
        ev = Event.query.first()
        ev.collectives.append(c)
        db.session.commit()
    html = text(admin.get(SLUG_EV))
    assert "О концерте" in html and "Участвуют:" in html and "Оркестр-тест" in html
    assert 'class="prose"' not in html


def test_past_event_with_yandex_id_no_widget_no_buybar(app, admin):
    create_event(admin, starts_at="2020-01-10T19:00", yandex_id="496249",
                 hall_widget='<div id="hall-scheme"></div>', ticket_url="https://t.example/1")
    resp = admin.get(SLUG_EV)
    assert resp.status_code == 200
    html = text(resp)
    assert 'id="bilety"' not in html and "data-ya-widget" not in html
    assert "data-buybar" not in html and "buybar__price" not in html
    assert "event__buy" not in html


def test_past_event_with_hall_widget_and_yandex_id_shows_hall(app, admin):
    create_event(admin, starts_at="2020-01-10T19:00")
    with app.app_context():
        ev = Event.query.first()
        ev.yandex_id, ev.hall_widget = "496249", '<div id="hall-scheme"></div>'
        db.session.commit()
    html = text(admin.get(SLUG_EV))
    # Прошедшее событие: покупки нет, но схема зала (hall_widget) должна быть видна
    assert 'id="hall"' in html and "hall-scheme" in html
    assert 'id="bilety"' not in html and "data-buybar" not in html


def _flagged_page(app, template, slug):
    with app.app_context():
        db.session.add(Page(title="Страница-" + template, slug=slug, template=template,
                            content="<p>x</p>", is_published=True))
        db.session.commit()


def _check_carousel_nav(html):
    ids = re.findall(r'<div class="ecarousel" id="([^"]+)"', html)
    assert ids and len(ids) == len(set(ids)), ids
    for cid in ids:
        nav = html.index(f'data-ecarousel-nav="{cid}"')
        assert html.count(f'aria-controls="{cid}"') == 2
        head = html.rindex('class="section__head"', 0, nav)
        assert "</section>" not in html[head:nav]  # стрелки в заголовке своего раздела
        assert nav < html.index(f'id="{cid}"')
    assert len(re.findall(r"data-ecarousel-nav=", html)) == len(ids)


def test_pushkin_and_benefits_pages_arrows(app, admin):
    create_event(admin, show_pushkin="1", show_benefits="1", benefits_text="<p>л</p>")
    _flagged_page(app, "pushkin", "pushkinskaya-karta")
    _flagged_page(app, "benefits", "lgoty")
    for slug in ("pushkinskaya-karta", "lgoty"):
        resp = admin.get("/info/" + slug)
        assert resp.status_code == 200
        _check_carousel_nav(text(resp))


def test_flagged_page_without_events_has_no_arrows(app, admin):
    create_event(admin)  # без флагов
    _flagged_page(app, "pushkin", "pushkinskaya-karta")
    html = text(admin.get("/info/pushkinskaya-karta"))
    assert "ecarousel" not in html and "data-ecarousel-nav" not in html
    assert "пока не опубликованы" in html


def test_collective_page_arrows_and_empty(app, admin):
    create_event(admin)
    with app.app_context():
        c = Collective(name="Хор-тест", slug="hor-test")
        c2 = Collective(name="Пустой-тест", slug="pustoy-test")
        db.session.add_all([c, c2])
        db.session.flush()
        ev = Event.query.first()
        ev.collectives.append(c)
        db.session.commit()
    _check_carousel_nav(text(admin.get("/kollektivy/hor-test")))
    html = text(admin.get("/kollektivy/pustoy-test"))
    assert "data-ecarousel-nav" not in html and "ecarousel" not in html


def test_carousel_ids_unique_and_linked_on_every_page(app, admin):
    create_event(admin, show_pushkin="1")
    create_event(admin, title="Второй", starts_at="2030-12-30T19:00")
    for url in ("/", SLUG_EV):
        _check_carousel_nav(text(admin.get(url)))


def test_more_cards_returns_cards_with_free_text(app, admin):
    create_event(admin, price_min="", price_max="", is_free="1")
    create_event(admin, title="Платный", starts_at="2030-12-30T19:00")
    resp = admin.get("/kartochki-afishi")
    assert resp.status_code == 200
    html = text(resp)
    assert "Тестовый концерт" in html and "Платный" in html
    assert FREE in html and "ecard__price--text" in html and "Вход свободный" not in html
    assert admin.get("/kartochki-afishi?offset=100").status_code == 200
    assert admin.get("/kartochki-afishi?flag=pushkin").status_code == 200


def test_admin_events_list_free_label(app, admin):
    create_event(admin, price_min="", price_max="", is_free="1")
    resp = admin.get("/admin/events")
    assert resp.status_code == 200
    html = text(resp)
    assert FREE in html and "Вход свободный" not in html


def test_jsonld_free_event_valid_with_zero_price(app, admin):
    create_event(admin, price_min="", price_max="", is_free="1", ticket_url="https://tickets.example/1")
    data = json.loads(LDJSON.search(text(admin.get(SLUG_EV))).group(1))
    assert data["name"] == "Тестовый концерт"
    blob = json.dumps(data, ensure_ascii=False)
    assert "Вход" not in blob and "Бесплатные" not in blob and "пригласительные" not in blob
    assert data["offers"]["price"] == 0 and data["isAccessibleForFree"] is True


def test_jsonld_event_without_price_has_no_offers(app, admin):
    create_event(admin, price_min="", price_max="", ticket_url="https://tickets.example/1")
    data = json.loads(LDJSON.search(text(admin.get(SLUG_EV))).group(1))
    assert "offers" not in data and "isAccessibleForFree" not in data
    assert "Цена уточняется" in text(admin.get(SLUG_EV))


def test_jsonld_paid_event_has_numeric_price(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1")
    data = json.loads(LDJSON.search(text(admin.get(SLUG_EV))).group(1))
    assert str(data["offers"]["price"]) == "500"
