"""Правки заказчика от 2026-11-03.

Пункт 5 — редактируемая подводка страницы «Коллективы и артисты» (настройка
`collectives_lead`, миграция 0018); пункт 7 — пункт меню следует за страницей
(`sync_menu_item` в `admin/content.py`); пункт 8 — загрузка картинок из
визуального редактора (`POST /admin/upload`).
"""
import importlib.util
import io
import os
import re
import sqlite3
from pathlib import Path

import pytest
from conftest import make_app, png, text

from filarmonia import create_app, maintenance, migrate, reset_site_data, seed, utils
from filarmonia.models import ActionLog, MenuItem, Page, Setting, db, referenced_uploads
from filarmonia.seed import SETTINGS

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_0018 = ROOT / "migrations" / "versions" / "0018_collectives_lead.py"
REVISION_0017 = "b7d1e6a39c42"

LEAD_DEFAULT = ("Оркестры, ансамбли и солисты филармонии. У каждого коллектива — "
                "фото и видео, контакты для заявок и подробный рассказ.")
LEAD_FALLBACK = "Оркестры, ансамбли и солисты филармонии"
BIG_PNG = (2200, 1500)


@pytest.fixture(autouse=True)
def _fresh_site_data():
    """Настройки и меню кешируются в памяти процесса — между проверками сбрасываем."""
    reset_site_data()
    yield
    reset_site_data()


def put_setting(app, key, value, kind="html", group="Страницы"):
    """Значение настройки с обходом кеша: `Setting.set` + commit + `reset_site_data()`."""
    with app.app_context():
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key, kind=kind, group=group)
            db.session.add(row)
        row.value = value
        db.session.commit()
    reset_site_data()


def read_setting(app, key):
    with app.app_context():
        return Setting.get(key)


# ---------- Пункт 5: настройка collectives_lead ----------

def _migration_0018():
    spec = importlib.util.spec_from_file_location("m0018", str(MIGRATION_0018))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collectives_lead_is_seeded_like_migration(tmp_path):
    """Значение по умолчанию в seed и в миграции 0018 одинаковые — иначе на боевом
    базе после миграции текст отличался бы от созданного seed."""
    entry = {row[0]: row for row in SETTINGS}["collectives_lead"]
    assert entry[1] == LEAD_DEFAULT
    assert entry[3] == "Страницы" and entry[4] == "html"
    migration = _migration_0018()
    assert migration.COLLECTIVES_LEAD == (entry[0], entry[1], entry[2], entry[3])
    assert migration.down_revision == REVISION_0017

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    app = make_app(seed_dir)
    seed.run(app, structure_only=True)
    assert read_setting(app, "collectives_lead") == LEAD_DEFAULT


def test_collectives_page_shows_setting_value(app):
    put_setting(app, "collectives_lead", "<p>Наша подводка про оркестры.</p>")
    html = text(app.test_client().get("/kollektivy"))
    assert "<p>Наша подводка про оркестры.</p>" in html
    assert LEAD_DEFAULT not in html


def test_collectives_page_falls_back_when_setting_empty(app):
    put_setting(app, "collectives_lead", "")
    html = text(app.test_client().get("/kollektivy"))
    assert LEAD_FALLBACK in html
    assert 'class="lead"' in html


def test_collectives_page_falls_back_when_setting_missing(app):
    """База, созданная до миграции 0018: настройки нет вовсе — текст прежний."""
    with app.app_context():
        assert db.session.get(Setting, "collectives_lead") is None
    html = text(app.test_client().get("/kollektivy"))
    assert LEAD_FALLBACK in html


def test_collectives_lead_is_sanitized_on_save(app, admin):
    """kind=html чистится через `rich` (common.rich -> utils.clean_html): скрипт вырезается."""
    put_setting(app, "collectives_lead", "<p>Оркестры</p>")
    r = admin.post("/admin/settings", data={
        "site_name": "Филармония",
        "collectives_lead": "<p>Ансамбли</p><script>fetch('/evil')</script>",
    }, content_type="multipart/form-data", follow_redirects=True)
    assert "Настройки сохранены." in text(r)
    value = read_setting(app, "collectives_lead")
    assert value == "<p>Ансамбли</p>"
    assert "<script" not in value and "fetch" not in value
    html = text(app.test_client().get("/kollektivy"))
    assert "<p>Ансамбли</p>" in html and "<script>fetch" not in html


def test_collectives_lead_not_available_to_editor(app, editor):
    """Настройки раздела «Страницы» правит только администратор."""
    assert editor.get("/admin/settings").status_code == 403
    r = editor.post("/admin/settings", data={"collectives_lead": "<p>Через редактора</p>"},
                    content_type="multipart/form-data")
    assert r.status_code == 403
    assert read_setting(app, "collectives_lead") != "<p>Через редактора</p>"


def _migration_env(tmp_path):
    from alembic import command

    path = tmp_path / "mig.db"
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path),
                     UPLOAD_FOLDER=str(tmp_path / "up"), TESTING=True, SECRET_KEY="x")
    return app, command, migrate.alembic_config(app), path


def _lead_rows(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("select value, title, \"group\", kind from settings "
                           "where key='collectives_lead'").fetchall()
    finally:
        con.close()


def test_migration_0018_upgrade_and_downgrade(tmp_path):
    app, command, cfg, path = _migration_env(tmp_path)
    command.upgrade(cfg, REVISION_0017)
    assert _lead_rows(path) == []

    command.upgrade(cfg, "head")
    assert _lead_rows(path) == [(LEAD_DEFAULT,
                                 "Текст над списком на странице «Коллективы и артисты»",
                                 "Страницы", "html")]

    command.downgrade(cfg, REVISION_0017)
    assert _lead_rows(path) == []
    command.upgrade(cfg, "head")
    assert len(_lead_rows(path)) == 1


def test_migration_0018_keeps_editor_value(tmp_path):
    """insert-if-missing: редакторский текст после накатки миграции остаётся."""
    app, command, cfg, path = _migration_env(tmp_path)
    command.upgrade(cfg, REVISION_0017)
    con = sqlite3.connect(path)
    con.execute("insert into settings(key,value,title,\"group\",kind) "
                "values('collectives_lead','Текст редактора','','Страницы','html')")
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    assert _lead_rows(path) == [("Текст редактора", "", "Страницы", "html")]


# ---------- Пункт 7: меню следует за страницей ----------

def create_page(client, **fields):
    data = {"title": "Молодёжный абонемент", "content": "<p>Текст страницы</p>",
            "publish": "1", "show_in_menu": "1", "sort": "100"}
    data.update(fields)
    return client.post("/admin/pages/new", data=data, follow_redirects=True)


def save_page(client, page_id, **fields):
    data = {"content": "<p>Текст страницы</p>", "publish": "1", "show_in_menu": "1"}
    data.update(fields)
    return client.post(f"/admin/pages/{page_id}", data=data, follow_redirects=True)


def page_info(app, title):
    with app.app_context():
        page = Page.query.filter_by(title=title).first()
        if page is None:
            return None
        return {"id": page.id, "slug": page.slug, "parent_id": page.parent_id,
                "is_published": page.is_published, "show_in_menu": page.show_in_menu}


def menu_item(app, title):
    """Пункт меню по названию: {'id', 'page_id', 'parent_id', 'is_published', 'sort'} или None."""
    with app.app_context():
        item = MenuItem.query.filter_by(title=title).first()
        if item is None:
            return None
        return {"id": item.id, "page_id": item.page_id, "parent_id": item.parent_id,
                "is_published": item.is_published, "sort": item.sort}


def menu_count(app):
    with app.app_context():
        return MenuItem.query.count()


def nav(html):
    block = re.search(r'<nav class="nav".*?</nav>', html, re.S)
    return block.group(0) if block else ""


def test_published_page_with_menu_flag_creates_menu_item(app, admin):
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    assert page is not None and page["is_published"]
    item = menu_item(app, "Молодёжный абонемент")
    assert item is not None, "пункт меню не создан"
    assert item["page_id"] == page["id"]
    assert item["is_published"] is True
    assert item["parent_id"] is None
    # Публичная страница доступна посетителю
    assert app.test_client().get(f"/info/{page['slug']}").status_code == 200


def test_page_without_menu_flag_creates_no_item(app, admin):
    create_page(admin, title="Служебная страница", show_in_menu="")
    assert page_info(app, "Служебная страница") is not None
    assert menu_count(app) == 0


def test_draft_page_creates_no_item_until_published(app, admin):
    """Черновик посетителям не виден.

    По `docs/ARCHITECTURE.md` (раздел 5, «Меню страниц») пункт создаётся, только
    когда страница опубликована и стоит галочка «в меню»; скрытие (`is_published=False`)
    касается уже существующего пункта — его проверяет `test_unpublishing_page_hides_menu_item`.
    Здесь проверяется остальное: черновик не заводит пункта, а публикация заводит.
    """
    create_page(admin, title="Черновик раздела", publish="0")
    page = page_info(app, "Черновик раздела")
    assert page["is_published"] is False
    assert menu_item(app, "Черновик раздела") is None
    assert menu_count(app) == 0
    # Черновик посетителю не виден
    assert app.test_client().get(f"/info/{page['slug']}").status_code == 404

    save_page(admin, page["id"], title="Черновик раздела", publish="1")
    item = menu_item(app, "Черновик раздела")
    assert item is not None and item["is_published"] is True and item["page_id"] == page["id"]
    assert app.test_client().get(f"/info/{page['slug']}").status_code == 200


def test_unchecking_menu_flag_hides_item_and_rechecking_shows_it(app, admin):
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    save_page(admin, page["id"], title="Молодёжный абонемент", show_in_menu="")
    item = menu_item(app, "Молодёжный абонемент")
    assert item is not None, "пункт меню удалён вместо скрытия"
    assert item["is_published"] is False
    assert item["page_id"] == page["id"]

    save_page(admin, page["id"], title="Молодёжный абонемент", show_in_menu="1")
    item = menu_item(app, "Молодёжный абонемент")
    assert item["is_published"] is True
    assert menu_count(app) == 1, "при повторном включении создан второй пункт"


def test_unpublishing_page_hides_menu_item(app, admin):
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    save_page(admin, page["id"], title="Молодёжный абонемент", publish="0", show_in_menu="1")
    item = menu_item(app, "Молодёжный абонемент")
    assert item is not None and item["is_published"] is False


def test_renaming_page_renames_menu_item(app, admin):
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    before = menu_item(app, "Молодёжный абонемент")
    save_page(admin, page["id"], title="Абонемент молодёжи")
    assert menu_item(app, "Молодёжный абонемент") is None
    after = menu_item(app, "Абонемент молодёжи")
    assert after is not None
    assert after["id"] == before["id"] and after["page_id"] == page["id"]
    assert menu_count(app) == 1


def test_child_page_menu_item_hangs_on_parent_item(app, admin):
    create_page(admin, title="Абонементы")
    parent = page_info(app, "Абонементы")
    create_page(admin, title="Молодёжный абонемент", parent_id=str(parent["id"]))
    child = menu_item(app, "Молодёжный абонемент")
    assert child["parent_id"] == menu_item(app, "Абонементы")["id"]

    # Второй раздел с пунктом меню — пункт переезжает к нему
    create_page(admin, title="Акции")
    other = page_info(app, "Акции")
    page = page_info(app, "Молодёжный абонемент")
    save_page(admin, page["id"], title="Молодёжный абонемент", parent_id=str(other["id"]))
    assert menu_item(app, "Молодёжный абонемент")["parent_id"] == menu_item(app, "Акции")["id"]

    # Возврат на верхний уровень
    save_page(admin, page["id"], title="Молодёжный абонемент", parent_id="")
    assert menu_item(app, "Молодёжный абонемент")["parent_id"] is None


def test_child_of_page_without_menu_item_is_top_level(app, admin):
    create_page(admin, title="Служебный раздел", show_in_menu="")
    parent = page_info(app, "Служебный раздел")
    create_page(admin, title="Внутри раздела", parent_id=str(parent["id"]))
    item = menu_item(app, "Внутри раздела")
    assert item is not None and item["parent_id"] is None
    assert menu_count(app) == 1


def test_manual_menu_sort_is_not_overwritten(app, admin):
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    with app.app_context():
        MenuItem.query.filter_by(page_id=page["id"]).update({"sort": 7})
        db.session.commit()
    save_page(admin, page["id"], title="Молодёжный абонемент", sort="500")
    assert menu_item(app, "Молодёжный абонемент")["sort"] == 7
    assert page_info(app, "Молодёжный абонемент")["id"] == page["id"]


def test_existing_manual_menu_item_is_reused(app, admin):
    """Пункт, заведённый вручную в «Меню», не дублируется при сохранении страницы."""
    create_page(admin, title="Молодёжный абонемент", show_in_menu="")
    page = page_info(app, "Молодёжный абонемент")
    admin.post("/admin/menu", data={"title": "Абонементы для молодых",
                                    "page_id": str(page["id"]), "is_published": "1", "sort": "20"})
    assert menu_count(app) == 1
    save_page(admin, page["id"], title="Молодёжный абонемент", show_in_menu="1")
    assert menu_count(app) == 1
    item = menu_item(app, "Молодёжный абонемент")
    assert item is not None and item["page_id"] == page["id"] and item["is_published"] is True


def test_new_page_appears_in_public_menu(app, admin):
    guest = app.test_client()
    guest.get("/")  # заполняет кеш настроек и меню
    create_page(admin)
    page = page_info(app, "Молодёжный абонемент")
    html = nav(text(guest.get("/")))
    assert f"/info/{page['slug']}" in html and "Молодёжный абонемент" in html

    save_page(admin, page["id"], title="Молодёжный абонемент", show_in_menu="")
    assert "Молодёжный абонемент" not in nav(text(guest.get("/")))


# ---------- Пункт 8: загрузка картинок в редактор ----------

def upload(client, **files):
    return client.post("/admin/upload", data=files, content_type="multipart/form-data")


def uploads_dir(app):
    return app.config["UPLOAD_FOLDER"]


def test_upload_image_returns_json_and_writes_files(app, admin):
    r = upload(admin, file=(png(BIG_PNG), "Афиша сезона.png"))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["success"] is True
    files = body["data"]["files"]
    assert len(files) == 1 and files[0].startswith(utils.UPLOADS_PREFIX)
    assert body["files"] == files and body["path"] == files[0]
    assert body["data"]["isImages"] == [True]
    assert body["data"]["baseurl"] == ""

    name = files[0][len(utils.UPLOADS_PREFIX):]
    folder = uploads_dir(app)
    assert os.path.isfile(os.path.join(folder, name))
    made = [w for w in utils.VARIANT_WIDTHS
            if os.path.isfile(os.path.join(folder, utils.variant_name(name, w)))]
    assert made == list(utils.VARIANT_WIDTHS), "копии -NNNw.webp созданы не все"
    assert name.endswith(".png") and "/" not in name

    with app.app_context():
        entry = ActionLog.query.filter_by(action="create", object_type="media").first()
    assert entry is not None and files[0] in (entry.details or "")


def test_upload_accepts_any_field_name(app, admin):
    """Jodit шлёт файл своим полем — handler берёт любое поле с файлом."""
    r = upload(admin, upload=(png((900, 700)), "foto.jpg"))
    assert r.status_code == 200
    assert r.get_json()["data"]["files"][0].endswith(".jpg")


def test_upload_without_file_is_bad_request(app, admin):
    for data in ({}, {"note": "нет файла"}):
        r = upload(admin, **data)
        assert r.status_code == 400, data
        body = r.get_json()
        assert body["success"] is False
        assert "Выберите файл." in body["data"]["messages"]


def test_upload_rejects_non_image(app, admin):
    r = admin.post("/admin/upload", data={"file": (io.BytesIO("Текст вместо картинки".encode()), "note.txt")},
                   content_type="multipart/form-data")
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    message = " ".join(body["data"]["messages"])
    assert "Недопустимый тип файла" in message and ".txt" in message
    assert os.listdir(uploads_dir(app)) == []


def test_upload_rejects_broken_png(app, admin):
    r = upload(admin, file=(io.BytesIO(b"not a png at all"), "broken.png"))
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    message = " ".join(body["data"]["messages"])
    assert "не распознан как изображение" in message
    # Неудачная загрузка не оставляет файлов в каталоге
    assert os.listdir(uploads_dir(app)) == []


def test_upload_requires_login(app):
    guest = app.test_client()
    r = guest.post("/admin/upload", data={"file": (png(), "a.png")},
                   content_type="multipart/form-data")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["Location"]
    assert os.listdir(uploads_dir(app)) == []


def test_upload_available_to_editor(app, editor):
    r = upload(editor, file=(png((900, 700)), "foto.png"))
    assert r.status_code == 200 and r.get_json()["success"] is True


def test_upload_needs_csrf_header(tmp_path):
    """Запрос редактора идёт мимо формы, поэтому токен — в заголовке X-CSRFToken.

    Вход делает `session.clear()`, поэтому токен берём из meta уже панели,
    как это делает `admin.js` в браузере редактора.
    """
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    client = csrf_app.test_client()
    page = text(client.get("/admin/login"))
    login_token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    client.post("/admin/login", data={"login": "admin", "password": "secret123",
                                      "csrf_token": login_token}, follow_redirects=True)
    assert client.get("/admin/").status_code == 200, "вход с токеном не выполнен"

    form = text(client.get("/admin/pages/new"))
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', form).group(1)

    ok = client.post("/admin/upload", data={"file": (png((900, 700)), "foto.png")},
                     content_type="multipart/form-data", headers={"X-CSRFToken": token})
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.get_json()["success"] is True

    before = sorted(os.listdir(csrf_app.config["UPLOAD_FOLDER"]))
    denied = client.post("/admin/upload", data={"file": (png((900, 700)), "foto2.png")},
                         content_type="multipart/form-data")
    assert denied.status_code == 400
    assert "Форма устарела" in text(denied)
    assert sorted(os.listdir(csrf_app.config["UPLOAD_FOLDER"])) == before


def test_image_in_page_text_is_not_unused(app, admin):
    """Файл из текста страницы занят: `cleanup` не должен его удалить."""
    url = upload(admin, file=(png(BIG_PNG), "schema.png")).get_json()["data"]["files"][0]
    name = url[len(utils.UPLOADS_PREFIX):]
    folder = uploads_dir(app)
    assert name in maintenance.unused_uploads(app)

    create_page(admin, title="Схема зала", content=f'<p>Схема</p><img src="{url}" alt="Схема">')
    with app.app_context():
        assert name in referenced_uploads()
    unused = maintenance.unused_uploads(app)
    assert name not in unused
    assert not [w for w in utils.VARIANT_WIDTHS
                if utils.variant_name(name, w) in unused]
    assert os.path.isfile(os.path.join(folder, name))


def test_editor_form_wires_uploader(app, admin):
    html = text(admin.get("/admin/pages/new"))
    assert 'data-upload-url="/admin/upload"' in html
    assert '<meta name="csrf-token" content="' in html


def test_admin_js_posts_file_with_csrf_header():
    js = (ROOT / "filarmonia" / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert "data-upload-url" in js
    assert "X-CSRFToken" in js
    assert "csrf-token" in js
    assert "insertImageAsBase64URI: false" in js
