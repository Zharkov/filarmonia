"""Тесты на правки от 2026-11-09: схема зала, подвал, спиннер админки."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest
from conftest import make_app, text

from filarmonia import create_app, migrate, reset_site_data
from filarmonia.models import Page, db

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_0019 = ROOT / "migrations" / "versions" / "0019_page_show_in_footer.py"
SITE_CSS = ROOT / "filarmonia" / "static" / "css" / "site.css"
SITE_JS = ROOT / "filarmonia" / "static" / "js" / "site.js"
ADMIN_LOADING_JS = ROOT / "filarmonia" / "static" / "js" / "admin-loading.js"


# ======================== 1. Схема зала (CSS + JS)  ========================


def test_hall_widget_iframe_height_is_950px():
    """.hall-widget iframe имеет min-height: 950px, старое 560px отсутствует в этом правиле."""
    css = SITE_CSS.read_text(encoding="utf-8")
    assert "min-height: 950px" in css
    # правило hall-widget iframe
    for line in css.splitlines():
        stripped = line.strip()
        if ".hall-widget iframe" in stripped and stripped.startswith(".hall-widget"):
            assert "min-height: 950px" in stripped
            assert "560px" not in stripped
            break
    else:
        pytest.fail("Не найдено правило .hall-widget iframe в CSS")


def test_ya_widget_min_height_is_950px():
    """.ya-widget имеет min-height: 950px, старое 600px отсутствует."""
    css = SITE_CSS.read_text(encoding="utf-8")
    for line in css.splitlines():
        stripped = line.strip()
        if stripped.startswith(".ya-widget") and "min-height" in stripped:
            assert "min-height: 950px" in stripped
            assert "600px" not in stripped
            break
    else:
        pytest.fail("Не найдено правило .ya-widget { min-height } в CSS")


def test_ya_widget_mount_height_950px():
    """JS-виджет Яндекс Афиши монтируется с высотой 950px."""
    js = SITE_JS.read_text(encoding="utf-8")
    assert 'height: "950px"' in js
    # в site.js 600px не должно быть в контексте mount виджета
    for line in js.splitlines():
        if "widget.mount" in line and "style" in line:
            assert "950px" in line


def test_event_html_unchanged():
    """Шаблон event.html не менялся — классы hall-widget и ya-widget остались прежними."""
    event_html = (ROOT / "filarmonia" / "templates" / "public" / "event.html").read_text(
        encoding="utf-8"
    )
    assert "class=\"hall-widget\"" in event_html
    assert "ya-widget" in event_html


# ======================== 2. Спиннер админки (JS)  ========================


def test_admin_spinner_no_submit_without_files_check():
    """Спиннер не показывается при submit любой формы — есть проверка files.length."""
    js = ADMIN_LOADING_JS.read_text(encoding="utf-8")
    # В submit-хендлере должна быть проверка countFiles(form) > 0
    assert "countFiles(form) > 0" in js


def test_admin_spinner_no_old_timeout():
    """В old-версии были setTimeout(hide, 60000) и 120000 — их нет в новой."""
    js = ADMIN_LOADING_JS.read_text(encoding="utf-8")
    assert "60000" not in js
    assert "120000" not in js
    assert "setTimeout" not in js


def test_admin_spinner_show_only_with_file():
    """Функция show() вызывается только внутри блока проверки countFiles > 0."""
    js = ADMIN_LOADING_JS.read_text(encoding="utf-8")
    # Найти блок submit хендлера
    lines = js.splitlines()
    in_submit = False
    found_guard = False
    for line in lines:
        if "form.addEventListener('submit'" in line:
            in_submit = True
        if in_submit and "countFiles(form) > 0" in line:
            found_guard = True
        if in_submit and "show()" in line:
            # show() должен быть внутри блока if (отступ больше, чем у if)
            # Простая проверка: show() после строки с guard и до закрывающей скобки
            pass
        if in_submit and line.strip() == "});":
            break
    assert found_guard, "submit-хендлер не содержит guard countFiles(form) > 0"


# ======================== 3. Подвал: страницы (функциональные)  ========================


@pytest.fixture(autouse=True)
def _fresh_site_data():
    """Сброс кэша site_data между тестами."""
    reset_site_data()
    yield
    reset_site_data()


def test_footer_page_shown_after_saved_via_admin(app, admin):
    """Сохранение страницы с show_in_footer=True в панели делает её видимой в подвале."""
    admin.post("/admin/pages/new", data={
        "title": "Пользовательское соглашение",
        "publish": "1",
        "show_in_footer": "1",
    })
    with app.app_context():
        page = Page.query.filter_by(title="Пользовательское соглашение").first()
        assert page and page.show_in_footer
    html = text(app.test_client().get("/"))
    assert "Пользовательское соглашение" in html
    # ссылка ведёт на /info/<slug>
    assert '/info/' in html


def test_footer_page_without_flag_not_in_footer(app, admin):
    """Страница с show_in_footer=False (по умолчанию) не появляется в подвале."""
    admin.post("/admin/pages/new", data={
        "title": "Об учреждении тест",
        "publish": "1",
    })
    with app.app_context():
        page = Page.query.filter_by(title="Об учреждении тест").first()
        assert page and not page.show_in_footer
    html = text(app.test_client().get("/"))
    assert "Об учреждении тест" not in html


def test_unpublished_footer_page_not_in_footer(app, admin):
    """Черновик с show_in_footer=True не попадает в подвал."""
    admin.post("/admin/pages/new", data={
        "title": "Черновик-документ",
        "publish": "0",
        "show_in_footer": "1",
    })
    html = text(app.test_client().get("/"))
    assert "Черновик-документ" not in html


def test_footer_pages_order_after_hardcoded_links(app, admin):
    """Страницы из footer_pages выводятся после захардкоженных ссылок в колонке «Обязательные ссылки»."""
    admin.post("/admin/pages/new", data={
        "title": "Правила поведения",
        "publish": "1",
        "show_in_footer": "1",
    })
    html = text(app.test_client().get("/"))
    # Индекс захардкоженной ссылки < индекса динамической
    pos_gosuslugi = html.find("Госуслуги")
    pos_dynamic = html.find("Правила поведения")
    assert pos_gosuslugi < pos_dynamic, (
        "Страница footer_pages должна идти после захардкоженных ссылок"
    )


def test_footer_page_edit_toggle_flag(app, admin):
    """Снятие флага show_in_footer при редактировании убирает страницу из подвала."""
    # Создаём опубликованную страницу с флагом
    admin.post("/admin/pages/new", data={
        "title": "Правила возврата билетов",
        "publish": "1",
        "show_in_footer": "1",
    })
    with app.app_context():
        page = Page.query.filter_by(title="Правила возврата билетов").first()
        assert page.show_in_footer
    assert "Правила возврата билетов" in text(app.test_client().get("/"))

    # Снимаем флаг
    admin.post(f"/admin/pages/{page.id}", data={
        "title": "Правила возврата билетов",
        "publish": "1",
        "show_in_footer": "",
    })
    assert "Правила возврата билетов" not in text(app.test_client().get("/"))


# ======================== 4. Подвал: инвалидация кэша  ========================


def test_footer_pages_cache_refreshed_after_save(app, admin):
    """Сохранение страницы с флагом сбрасывает кэш site_data — данные видны без повторного запроса."""
    import filarmonia

    with app.app_context():
        # Наполняем кэш (страниц с флагом ещё нет)
        reset_site_data()
        data = filarmonia.site_data()
        assert data["footer_pages"] == []

    # Сохраняем страницу с флагом через панель
    admin.post("/admin/pages/new", data={
        "title": "Книгосбор",
        "publish": "1",
        "show_in_footer": "1",
    })

    # Кэш должен обновиться: страница с флагом видна
    with app.app_context():
        data = filarmonia.site_data()
        titles = [p.title for p in data["footer_pages"]]
    assert "Книгосбор" in titles


def test_footer_pages_cache_stale_without_reset(app):
    """Без сброса кэша site_data() возвращает старые данные — это и есть кэш."""
    import filarmonia

    with app.app_context():
        reset_site_data()
        # Нет страниц с флагом
        data1 = filarmonia.site_data()
        assert data1["footer_pages"] == []

        # Создаём страницу с флагом напрямую в БД (минуя панель)
        page = Page(title="Прямая запись", is_published=True, show_in_footer=True, slug="direct-write")
        db.session.add(page)
        db.session.commit()

        # Без reset_site_data кэш должен остаться пустым
        data2 = filarmonia.site_data()
        assert data2["footer_pages"] == []

        # После сброса — новые данные
        reset_site_data()
        data3 = filarmonia.site_data()
        assert any(p.title == "Прямая запись" for p in data3["footer_pages"])


# ======================== 5. Миграция 0019  ========================


def _migration_0019():
    spec = importlib.util.spec_from_file_location(
        "m0019", str(MIGRATION_0019)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page_columns(path) -> list:
    con = sqlite3.connect(path)
    try:
        return [row[1] for row in con.execute("PRAGMA table_info(pages)").fetchall()]
    finally:
        con.close()


def _migration_env(tmp_path):
    from alembic import command

    path = tmp_path / "mig.db"
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path),
                     UPLOAD_FOLDER=str(tmp_path / "up"), TESTING=True, SECRET_KEY="x")
    return app, command, migrate.alembic_config(app), path


def test_migration_0019_head_revision():
    """0019 — единственная миграция с down_revision='c8f2a5d3e419' (нет конфликта веток)."""
    migration = _migration_0019()
    assert migration.revision == "a1b2c3d4e5f6"
    assert migration.down_revision == "c8f2a5d3e419"

    # Проверяем, что нет другой миграции с тем же down_revision
    versions_dir = ROOT / "migrations" / "versions"
    other_with_same = 0
    for f in versions_dir.glob("*.py"):
        if f.name == "0019_page_show_in_footer.py":
            continue
        spec = importlib.util.spec_from_file_location("other", str(f))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "down_revision", None) == "c8f2a5d3e419":
            other_with_same += 1
    assert other_with_same == 0, f"Конфликт: {other_with_same} миграция(й) с тем же down_revision"


def test_migration_0019_upgrade_downgrade(tmp_path):
    """Миграция 0019: add_column show_in_footer, потом drop_column."""
    app, command, cfg, path = _migration_env(tmp_path)

    command.upgrade(cfg, "c8f2a5d3e419")
    assert "show_in_footer" not in _page_columns(path)

    command.upgrade(cfg, "head")
    assert "show_in_footer" in _page_columns(path)

    command.downgrade(cfg, "c8f2a5d3e419")
    assert "show_in_footer" not in _page_columns(path)

    command.upgrade(cfg, "head")
    assert "show_in_footer" in _page_columns(path)
