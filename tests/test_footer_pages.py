"""Страницы в подвале: флаг show_in_footer добавляет ссылку в «Обязательные ссылки»."""
from conftest import text

from filarmonia.models import db, Page


def test_footer_page_with_flag(app, admin):
    """Страница с show_in_footer=True появляется в колонке подвала."""
    admin.post("/admin/pages/new", data={
        "title": "Пользовательское соглашение",
        "is_published": "1",
        "show_in_footer": "1",
    })
    with app.app_context():
        assert db.session.get(Page, Page.query.first().id).show_in_footer
    html = text(app.test_client().get("/"))
    assert "Пользовательское соглашение" in html


def test_footer_page_without_flag_not_shown(app, admin):
    """Страница без флага show_in_footer не появляется в подвале."""
    admin.post("/admin/pages/new", data={
        "title": "Об учреждении",
        "is_published": "1",
    })
    with app.app_context():
        page = Page.query.filter_by(title="Об учреждении").first()
        assert not page.show_in_footer
    html = text(app.test_client().get("/"))
    assert "Об учреждении" not in html


def test_unpublished_footer_page_not_shown(app, admin):
    """Черновик с show_in_footer=True не появляется в подвале."""
    admin.post("/admin/pages/new", data={
        "title": "Черновик-документ",
        "publish": "0",
        "show_in_footer": "1",
    })
    html = text(app.test_client().get("/"))
    assert "Черновик-документ" not in html
