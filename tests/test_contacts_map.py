"""Правки заказчика от 2026-10-21: карта на «Контактах», без «Площадок», значок MAX, баннер."""
import re
from pathlib import Path

import pytest
from conftest import text

from filarmonia import reset_site_data
from filarmonia.models import db, Page, Setting, Venue

ROOT = Path(__file__).resolve().parent.parent
CONTACTS_URL = "/info/kontakty-i-shema-proezda"
CUSTOM_MAP = '<iframe src="https://example.test/custom-map" title="Своя карта"></iframe>'


@pytest.fixture(autouse=True)
def _fresh_site_data():
    """Настройки кешируются в памяти процесса на 30 с — между проверками сбрасываем."""
    reset_site_data()
    yield
    reset_site_data()


def put_setting(app, key, value):
    with app.app_context():
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key, kind="text")
            db.session.add(row)
        row.value = value
        db.session.commit()
    reset_site_data()


@pytest.fixture
def contacts(app):
    with app.app_context():
        db.session.add(Page(slug="kontakty-i-shema-proezda", title="Контакты и схема проезда",
                            template="contacts", content="<p>Как добраться</p>", is_published=True))
        db.session.add(Venue(name="Зал Уникальный-Тест", slug="zal-test", address="ул. Тестовая, 1"))
        db.session.commit()
    return app.test_client()


def test_contacts_has_map_widget_and_no_venues(contacts):
    resp = contacts.get(CONTACTS_URL)
    assert resp.status_code == 200
    html = text(resp)
    assert "yandex.ru/map-widget" in html and "map--wide" in html
    assert 'class="venues"' not in html and 'class="venue' not in html
    assert "Площадки" not in html
    assert "Зал Уникальный-Тест" not in html
    # Текст страницы по-прежнему выводится
    assert "Как добраться" in html


def test_contacts_map_follows_map_point(app, contacts):
    put_setting(app, "map_point", "55.1, 37.2")
    html = text(contacts.get(CONTACTS_URL))
    assert "yandex.ru/map-widget" in html and "55.1" in html


def test_contacts_custom_history_map(app, contacts):
    put_setting(app, "history_map", CUSTOM_MAP)
    html = text(contacts.get(CONTACTS_URL))
    assert CUSTOM_MAP in html
    assert "yandex.ru/map-widget" not in html


def test_home_has_no_map(app, contacts):
    resp = contacts.get("/")
    assert resp.status_code == 200
    html = text(resp)
    assert "map-widget" not in html and "map--wide" not in html
    # Даже при заданной своей карте на главной её нет
    put_setting(app, "history_map", CUSTOM_MAP)
    assert "custom-map" not in text(contacts.get("/"))


def test_regular_page_has_no_map(app, contacts):
    with app.app_context():
        db.session.add(Page(slug="obychnaya", title="Обычная", template="page", content="<p>x</p>"))
        db.session.commit()
    html = text(contacts.get("/info/obychnaya"))
    assert "map-widget" not in html and "map--wide" not in html


def test_afisha_still_has_venue_filter(contacts):
    resp = contacts.get("/afisha")
    assert resp.status_code == 200
    html = text(resp)
    assert '<select name="venue"' in html
    assert "Зал Уникальный-Тест" in html


def _max_link(html):
    m = re.search(r'<a [^>]*aria-label="MAX"[^>]*>(.*?)</a>', html, re.S)
    return m.group(1) if m else None


def test_max_icon_is_monochrome_logo(app, contacts):
    put_setting(app, "social_max", "https://max.ru/test")
    put_setting(app, "social_max_show", "1")
    svg = _max_link(text(contacts.get("/")))
    assert svg is not None, "ссылка MAX не выведена"
    assert "<svg" in svg and 'fill-rule="evenodd"' in svg and 'fill="currentColor"' in svg
    assert "<rect" not in svg


def test_max_icon_hidden_when_not_shown(app, contacts):
    put_setting(app, "social_max", "https://max.ru/test")
    put_setting(app, "social_max_show", "")
    assert _max_link(text(contacts.get("/"))) is None


def test_max_icon_hidden_without_address(contacts):
    assert _max_link(text(contacts.get("/"))) is None


def test_hero_aspect_ratio_in_css():
    css = (ROOT / "filarmonia" / "static" / "css" / "site.css").read_text(encoding="utf-8")
    block = re.search(r"\n\.hero\s*\{([^}]*)\}", css)
    assert block, ".hero не найден в site.css"
    assert "aspect-ratio: 1902 / 737" in block.group(1)
    assert "16 / 9" not in block.group(1)
