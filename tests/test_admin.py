"""Админка: таблицы, правка записей, защита от опасного удаления, журнал."""
from datetime import timedelta

from conftest import create_event, text

from filarmonia import utils
from filarmonia.models import (
    db, ActionLog, Appeal, Banner, Document, MenuItem, Page, Setting, User,
)

TABLES = (
    ("/admin/events", "date title venue price status"),
    ("/admin/news", "date title status"),
    ("/admin/collectives", "sort name lead status"),
    ("/admin/pages", "sort title parent slug status"),
    ("/admin/appeals", "date name subject status"),
    ("/admin/documents", "title category year size sort status"),
    ("/admin/menu", "sort title parent status"),
    ("/admin/banners", "place title url sort status"),
    ("/admin/users", "login name role last_login"),
    ("/admin/log", "date user action type title"),
)


def test_every_column_sorts(admin):
    for url, keys in TABLES:
        for key in keys.split():
            for direction in ("asc", "desc"):
                assert admin.get(f"{url}?sort={key}&dir={direction}").status_code == 200, (url, key)


def test_publish_toggle_everywhere(app, admin, editor):
    """Статус в каждой таблице переключается щелчком, в том числе редактором."""
    from filarmonia.models import Collective, News

    with app.app_context():
        page = Page(title="Страница", slug="stranica")
        db.session.add_all([
            News(title="Новость", slug="novost"), Collective(name="Оркестр", slug="orkestr"), page,
            Document(title="Устав"), Banner(title="Госуслуги"), MenuItem(title="Афиша", url="/afisha"),
        ])
        db.session.commit()
        items = {"news": News, "collective": Collective, "page": Page, "document": Document,
                 "banner": Banner, "menu": MenuItem}
        ids = {kind: model.query.first().id for kind, model in items.items()}
    lists = {"news": "/admin/news", "collective": "/admin/collectives", "page": "/admin/pages",
             "document": "/admin/documents", "banner": "/admin/banners", "menu": "/admin/menu"}
    for kind, model in items.items():
        assert f'action="/admin/publish/{kind}/{ids[kind]}"' in text(admin.get(lists[kind])), kind
        editor.post(f"/admin/publish/{kind}/{ids[kind]}")
        with app.app_context():
            assert not db.session.get(model, ids[kind]).is_published, kind
    assert editor.post("/admin/publish/user/1").status_code == 404
    with app.app_context():
        assert ActionLog.query.filter_by(details="скрыто с сайта").count() == len(items)


def test_dashboard_counters_are_links(admin):
    html = text(admin.get("/admin/"))
    for href in ("/admin/events?scope=upcoming", "/admin/news", "/admin/collectives",
                 "/admin/documents", "/admin/events?scope=all", "/admin/appeals?status=new"):
        assert f'class="stat' in html and f'href="{href}"' in html, href


def test_unknown_sort_ignored(admin):
    assert admin.get("/admin/events?sort=drop_table&dir=x").status_code == 200


def test_event_filters(admin):
    create_event(admin, show_pushkin="1")
    assert "Тестовый концерт" in text(admin.get("/admin/events?scope=all&mark=pushkin&q=ТЕСТОВЫЙ"))
    assert "Тестовый концерт" not in text(admin.get("/admin/events?scope=all&mark=benefits"))


def test_appeals_counter(app, admin):
    with app.app_context():
        db.session.add(Appeal(name="Проверка", message="Текст", consent=True))
        db.session.commit()
        appeal_id = Appeal.query.first().id
    html = text(admin.get("/admin/"))
    assert 'class="counter"' in html and ">1<" in html
    admin.post(f"/admin/appeals/{appeal_id}", data={"is_processed": "1"})
    assert 'class="counter"' not in text(admin.get("/admin/"))


def test_appeal_print(app, admin):
    with app.app_context():
        db.session.add(Appeal(name="Иванова", message="Прошу ответить", consent=True))
        db.session.commit()
    html = text(admin.get("/admin/appeals/1/print"))
    assert "Иванова" in html and "Прошу ответить" in html and "window.print" in html


def test_old_processed_appeals_purged(app, admin):
    with app.app_context():
        old = utils.utcnow() - timedelta(days=365 * 6)
        db.session.add_all([
            Appeal(name="Старое обработанное", message="x", is_processed=True, created_at=old),
            Appeal(name="Старое без ответа", message="x", is_processed=False, created_at=old),
            Appeal(name="Свежее", message="x", is_processed=True),
        ])
        db.session.add(Setting(key="appeals_retention_years", value="5", kind="text"))
        db.session.commit()
    admin.get("/admin/appeals")
    with app.app_context():
        names = {a.name for a in Appeal.query}
    assert names == {"Старое без ответа", "Свежее"}


def test_edit_document(app, admin):
    admin.post("/admin/documents", data={"title": "Устав", "category": "Учредительные", "year": "2020",
                                         "is_published": "1"}, content_type="multipart/form-data")
    with app.app_context():
        doc_id = Document.query.first().id
    assert 'value="Устав"' in text(admin.get(f"/admin/documents?edit={doc_id}"))
    admin.post("/admin/documents", data={"id": str(doc_id), "title": "Устав (ред. 2026)",
                                         "category": "Учредительные", "year": "2026", "is_published": "1"},
               content_type="multipart/form-data")
    with app.app_context():
        assert Document.query.count() == 1
        doc = db.session.get(Document, doc_id)
        assert doc.title == "Устав (ред. 2026)" and doc.year == 2026


def test_edit_menu_and_banner(app, admin):
    admin.post("/admin/menu", data={"title": "Афиша", "url": "/afisha", "is_published": "1"})
    admin.post("/admin/banners", data={"title": "Госуслуги", "url": "https://gosuslugi.ru",
                                       "place": "partners", "is_published": "1"},
               content_type="multipart/form-data")
    with app.app_context():
        menu_id, banner_id = MenuItem.query.first().id, Banner.query.first().id
    admin.post("/admin/menu", data={"id": str(menu_id), "title": "Афиша сезона", "url": "/afisha",
                                    "is_published": "1"})
    admin.post("/admin/banners", data={"id": str(banner_id), "title": "Госуслуги", "url": "https://www.gosuslugi.ru",
                                       "place": "main"}, content_type="multipart/form-data")
    with app.app_context():
        assert db.session.get(MenuItem, menu_id).title == "Афиша сезона"
        banner = db.session.get(Banner, banner_id)
        assert banner.place == "main" and not banner.is_published


def test_edit_user_and_duplicate_login(app, admin):
    with app.app_context():
        editor_id = User.query.filter_by(login="editor").first().id
    r = admin.post("/admin/users", data={"login": "admin", "password": "password123", "role": "editor",
                                         "is_active": "1"}, follow_redirects=True)
    assert "уже занят" in text(r)
    admin.post("/admin/users", data={"id": str(editor_id), "login": "editor", "name": "Мария",
                                     "role": "editor"})
    with app.app_context():
        user = db.session.get(User, editor_id)
        assert user.name == "Мария" and not user.is_active
        assert user.check_password("secret123")  # пустой пароль при правке не меняет его


def test_user_form_keeps_input_on_error(app, admin):
    r = admin.post("/admin/users", data={"login": "novikova", "name": "Анна Новикова",
                                         "password": "123", "role": "admin", "is_active": "1"})
    html = text(r)
    assert r.status_code == 200 and "не короче 8 символов" in html
    assert 'value="novikova"' in html and 'value="Анна Новикова"' in html
    assert '<option value="admin" selected>' in html
    with app.app_context():
        assert User.query.filter_by(login="novikova").first() is None


def test_save_and_view(app, admin):
    r = admin.post("/admin/news/new", data={"title": "Черновик новости", "then": "view"},
                   content_type="multipart/form-data")
    assert r.headers["Location"].endswith("/novosti/chernovik-novosti")
    html = text(admin.get("/novosti/chernovik-novosti"))
    assert "Скрыто с сайта." in html and "Вернуться к редактированию" in html
    assert app.test_client().get("/novosti/chernovik-novosti").status_code == 404


def test_social_icon_can_be_hidden(app, admin):
    with app.app_context():
        for key, value, kind in (("social_tg", "https://t.me/filarmonia", "text"),
                                 ("social_tg_show", "1", "bool"),
                                 ("social_max", "https://max.ru/filarmonia", "text")):
            db.session.add(Setting(key=key, value=value, kind=kind, group="Соцсети"))
        db.session.commit()
    guest = app.test_client()
    html = text(guest.get("/"))
    assert "t.me/filarmonia" in html and "max.ru/filarmonia" in html

    admin.post("/admin/settings", data={"social_tg": "https://t.me/filarmonia",
                                        "social_max": "https://max.ru/filarmonia"})
    html = text(guest.get("/"))
    assert "t.me/filarmonia" not in html and "max.ru/filarmonia" in html
    with app.app_context():
        assert Setting.get("social_tg") == "https://t.me/filarmonia"


def test_cannot_lock_yourself_out(app, admin):
    with app.app_context():
        admin_id = User.query.filter_by(login="admin").first().id
    r = admin.post("/admin/users", data={"id": str(admin_id), "login": "admin", "role": "editor",
                                         "is_active": "1"}, follow_redirects=True)
    assert "самому себе" in text(r)
    with app.app_context():
        assert db.session.get(User, admin_id).is_admin


def test_page_with_children_not_deleted(app, admin):
    admin.post("/admin/pages/new", data={"title": "Об учреждении", "is_published": "1"})
    with app.app_context():
        parent_id = Page.query.filter_by(title="Об учреждении").first().id
    admin.post("/admin/pages/new", data={"title": "История", "parent_id": str(parent_id), "is_published": "1"})
    r = admin.post(f"/admin/pages/{parent_id}/delete", follow_redirects=True)
    assert "есть подстраницы" in text(r)
    with app.app_context():
        assert Page.query.count() == 2


def test_page_in_menu_not_deleted(app, admin):
    admin.post("/admin/pages/new", data={"title": "Контакты", "is_published": "1"})
    with app.app_context():
        page_id = Page.query.first().id
    admin.post("/admin/menu", data={"title": "Контакты", "page_id": str(page_id), "is_published": "1"})
    r = admin.post(f"/admin/pages/{page_id}/delete", follow_redirects=True)
    assert "пункты меню" in text(r)


def test_action_log(app, admin, editor):
    create_event(editor)
    with app.app_context():
        entry = ActionLog.query.filter_by(action="create", object_type="event").first()
        assert entry.user_name == "Editor" and entry.title == "Тестовый концерт"
    html = text(admin.get("/admin/log?type=event"))
    assert "Тестовый концерт" in html and "создал" in html


def test_settings_html_sanitized_but_widgets_kept(app, admin):
    with app.app_context():
        db.session.add_all([
            Setting(key="history_text", value="", kind="html"),
            Setting(key="pos_widget", value="", kind="html"),
        ])
        db.session.commit()
    admin.post("/admin/settings", data={
        "history_text": "<p>История<script>x()</script></p>",
        "pos_widget": "<script src='https://pos.gosuslugi.ru/bin/script.min.js'></script>",
    }, content_type="multipart/form-data")
    with app.app_context():
        assert Setting.get("history_text") == "<p>История</p>"
        assert "<script" in Setting.get("pos_widget")
