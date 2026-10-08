"""Вход в панель администратора, права и защита."""
from conftest import PASSWORD, login, make_app, text

from filarmonia.models import db, User


def test_wrong_password(app):
    assert "Неверный логин" in text(login(app.test_client(), password="wrong"))


def test_login_ok(app):
    assert "Сводка" in text(login(app.test_client()))


def test_admin_closed_for_guest(app):
    r = app.test_client().get("/admin/events")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_next_inside_site(app):
    r = app.test_client().post("/admin/login?next=/admin/news",
                               data={"login": "admin", "password": PASSWORD})
    assert r.headers["Location"].endswith("/admin/news")


def test_next_to_foreign_site_ignored(app):
    for target in ("https://evil.example/", "//evil.example/", "/\\evil.example"):
        r = app.test_client().post(f"/admin/login?next={target}",
                                   data={"login": "admin", "password": PASSWORD})
        assert "evil.example" not in r.headers["Location"], target


def test_disabled_user_kicked_out_immediately(app, editor):
    assert editor.get("/admin/events").status_code == 200
    with app.app_context():
        User.query.filter_by(login="editor").first().is_active = False
        db.session.commit()
    r = editor.get("/admin/events")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_demotion_applies_immediately(app, tmp_path):
    client = app.test_client()
    login(client, "editor")
    with app.app_context():
        User.query.filter_by(login="editor").first().role = "admin"
        db.session.commit()
    assert client.get("/admin/settings").status_code == 200
    with app.app_context():
        User.query.filter_by(login="editor").first().role = "editor"
        db.session.commit()
    assert client.get("/admin/settings").status_code == 403


def test_editor_does_not_see_admin_sections(editor):
    html = text(editor.get("/admin/"))
    assert "Настройки" not in html and "Журнал действий" not in html
    assert editor.get("/admin/settings").status_code == 403
    assert editor.get("/admin/users").status_code == 403
    assert editor.get("/admin/log").status_code == 403


def test_csrf_required(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    client = app.test_client()
    assert client.post("/obrashcheniya", data={"name": "Бот", "message": "x", "consent": "1"}).status_code == 400
    assert client.post("/admin/login", data={"login": "admin", "password": PASSWORD}).status_code == 400
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_lockout(tmp_path):
    app = make_app(tmp_path, LOGIN_MAX_ATTEMPTS=3)
    client = app.test_client()
    for _ in range(3):
        login(client, password="wrong")
    html = text(login(client))
    assert "Слишком много попыток" in html and "Сводка" not in html
