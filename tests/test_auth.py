"""Вход в панель администратора, права и защита."""
import re

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


def token_from_login_form(client) -> str:
    """Токен защиты из формы входа — как его видит браузер в поле csrf_token."""
    return re.search(r'name="csrf_token" value="([^"]+)"', text(client.get("/admin/login"))).group(1)


def test_csrf_token_lives_in_its_own_cookie(tmp_path):
    """Токен не зависит от сеанса: он подписан и лежит в своей cookie на 90 дней."""
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    client = csrf_app.test_client()
    token = token_from_login_form(client)
    with client.session_transaction() as sess:
        assert "csrf_token" not in sess, "токен по-прежнему хранится в сессии"
    cookie = client.get_cookie("csrf_token")
    assert cookie is not None and cookie.value != token, "в cookie должна лежать строка, а не токен"
    # Срок cookie и срок подписи берутся из одной настройки, иначе при целой cookie
    # возвращалась бы страница «Форма устарела» (С-24)
    assert cookie.max_age == csrf_app.config["WTF_CSRF_TIME_LIMIT"] == 90 * 24 * 3600
    assert cookie.same_site == "Lax"
    # JS читает токен из meta-тега страницы, а не из cookie, поэтому HttpOnly не мешает
    assert not cookie.http_only


def test_login_after_session_cookie_lost(tmp_path):
    """Случай заказчика: Яндекс.Браузер потерял cookie сеанса — вход всё равно проходит.

    Новый клиент получает только cookie токена; проверка CSRF не смотрит в сессию,
    поэтому страница «Форма устарела» не появляется.
    """
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    client = csrf_app.test_client()
    token = token_from_login_form(client)
    raw = client.get_cookie("csrf_token").value

    guest = csrf_app.test_client()
    guest.set_cookie("csrf_token", raw)
    html = text(guest.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                                 "csrf_token": token}, follow_redirects=True))
    assert "Форма устарела" not in html
    assert "Сводка" in html, "вход с cookie токена без сеанса не выполнен"


def test_wrong_password_after_session_cookie_lost(tmp_path):
    """Без сеанса CSRF пропускает запрос, а пароль по-прежнему проверяется."""
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    first = csrf_app.test_client()
    token = token_from_login_form(first)
    raw = first.get_cookie("csrf_token").value

    guest = csrf_app.test_client()
    guest.set_cookie("csrf_token", raw)
    r = guest.post("/admin/login", data={"login": "admin", "password": "wrong",
                                         "csrf_token": token})
    assert r.status_code == 200 and "Неверный логин или пароль" in text(r)


def test_csrf_token_of_another_browser_rejected(tmp_path):
    """Токен чужого браузера не проходит: подпись сверяется с cookie этого."""
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    token = token_from_login_form(csrf_app.test_client())

    second = csrf_app.test_client()
    token_from_login_form(second)  # у второго клиента своя строка в cookie
    r = second.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": token})
    assert r.status_code == 400 and "Форма устарела" in text(r)


def test_login_with_forged_csrf_cookie_rejected(tmp_path):
    """Подставная cookie токена не принимается: токен должен быть подписан ключом сайта."""
    csrf_app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    token = token_from_login_form(csrf_app.test_client())

    guest = csrf_app.test_client()
    guest.set_cookie("csrf_token", "0" * 64)
    r = guest.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                         "csrf_token": token})
    assert r.status_code == 400 and "Форма устарела" in text(r)


def test_login_lockout(tmp_path):
    app = make_app(tmp_path, LOGIN_MAX_ATTEMPTS=3)
    client = app.test_client()
    for _ in range(3):
        login(client, password="wrong")
    html = text(login(client))
    assert "Слишком много попыток" in html and "Сводка" not in html
