"""Публичная часть: главная, музыкальный маршрут, страницы, новости, поиск."""
from conftest import create_event, png, text

from filarmonia.models import db, Category, Event, News, Page


def test_home_blocks(admin):
    create_event(admin)
    html = text(admin.get("/"))
    assert 'class="ecard"' in html and "Купить билет" in html
    assert "data-cal" in html and 'id="marshrut"' in html
    assert "Коллективы филармонии" not in html


def test_route(app, admin):
    create_event(admin)
    with app.app_context():
        db.session.add(Category(name="Симфоническая", slug="simf", route_tags="calm"))
        db.session.commit()
        Event.query.first().category_id = Category.query.filter_by(slug="simf").first().id
        db.session.commit()
    client = app.test_client()
    html = text(client.get("/marshrut?who=solo&mood=calm&when=month"))
    # Концерт в 2030 году в «этот месяц» не попадает — подборка пустая, но страница цела
    assert "Ваш маршрут готов" in html
    assert client.get("/marshrut?who=hacker").status_code == 302


def test_route_picks_matching_event(app, admin):
    from datetime import datetime, timedelta

    when = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT19:00")
    create_event(admin, title="Органный вечер", starts_at=when)
    with app.app_context():
        db.session.add(Category(name="Органная", slug="organ", route_tags="calm"))
        db.session.commit()
        Event.query.first().category_id = Category.query.filter_by(slug="organ").first().id
        db.session.commit()
    html = text(app.test_client().get("/marshrut?who=solo&mood=calm&when=week"))
    assert "Органный вечер" in html and "Точного совпадения не нашлось" not in html


def test_pushkin_page_lists_events(admin):
    create_event(admin, show_pushkin="1")
    admin.post("/admin/pages/new", data={"title": "Пушкинская карта", "template": "pushkin",
                                         "content": "<p>Правила</p>", "is_published": "1"})
    html = text(admin.get("/info/pushkinskaya-karta"))
    assert "Тестовый концерт" in html and "pushkin=1" in html


def test_page_photos(app, admin):
    admin.post("/admin/pages/new", data={"title": "Структура", "is_published": "1"})
    with app.app_context():
        page_id = Page.query.filter_by(slug="struktura").first().id
    admin.post("/admin/media/add", data={"owner": "page", "owner_id": str(page_id), "kind": "photo",
                                         "file": (png(), "shema.png"), "title": "Схема структуры"},
               content_type="multipart/form-data")
    assert "Схема структуры" in text(admin.get("/info/struktura"))


def test_news_text_only(app, admin):
    admin.post("/admin/news/new", data={
        "title": "Текстовая новость", "content": "<p>Без картинок</p>", "layout": "text",
        "is_published": "1", "image": (png(), "news.png")}, content_type="multipart/form-data")
    with app.app_context():
        assert not News.query.filter_by(title="Текстовая новость").first().show_media
    html = text(admin.get("/novosti/tekstovaya-novost"))
    assert "Без картинок" in html and "article__hero" not in html


def test_gallery_removed(app):
    assert app.test_client().get("/galereya").status_code == 404


def test_search_ignores_case_and_yo(admin):
    create_event(admin, title="Ёлка в филармонии")
    client = admin
    assert "Ёлка в филармонии" in text(client.get("/poisk?q=ЕЛКА"))
    assert "Ёлка в филармонии" in text(client.get("/poisk?q=ёлка"))
    assert "Ёлка в филармонии" in text(client.get("/admin/events?scope=all&q=елка"))


def test_search_percent_is_literal(admin):
    create_event(admin, title="Зимний бал")
    assert "Зимний бал" not in text(admin.get("/admin/events?scope=all&q=%25"))
    assert "Зимний бал" in text(admin.get("/admin/events?scope=all&q=бал"))


def test_menu_loaded_in_few_queries(app, admin):
    """Меню не должно подгружать страницы по одной (было 14 лишних запросов)."""
    from sqlalchemy import event as sa_event
    from filarmonia.models import MenuItem

    with app.app_context():
        for i in range(10):
            page = Page(title=f"Страница {i}", slug=f"page-{i}")
            db.session.add(page)
            db.session.flush()
            db.session.add(MenuItem(title=f"Пункт {i}", page_id=page.id, sort=i))
        db.session.commit()
        counter = []
        sa_event.listen(db.engine, "before_cursor_execute", lambda *a: counter.append(1))
    app.test_client().get("/novosti")
    assert len(counter) <= 6


def test_static_versioned_and_cached(app):
    html = text(app.test_client().get("/novosti"))
    assert "site.css?v=" in html
    r = app.test_client().get("/static/css/site.css")
    assert "max-age=2592000" in r.headers.get("Cache-Control", "")
