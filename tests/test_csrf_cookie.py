"""Кука токена защиты (`csrf_cookie.CookieCSRFProtect`).

Токен формы подписан ключом сайта, а случайная строка лежит в отдельной cookie
`csrf_token` на год. Отсюда проверяемое поведение: форма входа работает без cookie
сеанса (случай заказчика в Яндекс.Браузере), не требует записи на сервере и
переживает выход из панели. Все проверки — с включённой защитой: в `conftest`
она выключена, поэтому приложение поднимаем через `make_app(..., WTF_CSRF_ENABLED=True)`.
"""
import re
import time

from itsdangerous import URLSafeTimedSerializer

from conftest import PASSWORD, make_app, png, text

from filarmonia.csrf_cookie import CSRF_COOKIE_MAX_AGE, CSRF_COOKIE_NAME, SALT
from filarmonia.models import Appeal, Page


def csrf_app(tmp_path, **overrides):
    """Приложение с включённой защитой от подделки запросов."""
    overrides.setdefault("WTF_CSRF_ENABLED", True)
    return make_app(tmp_path, **overrides)


def cookie_headers(response, name=CSRF_COOKIE_NAME):
    """Заголовки Set-Cookie про куку `name` — по ним видно, ставил её ответ или нет."""
    return [value for key, value in response.headers
            if key.lower() == "set-cookie" and value.startswith(name + "=")]


def cookie_value(header_line) -> str:
    return header_line.split(";", 1)[0].split("=", 1)[1]


def form_token(client, path="/admin/login") -> str:
    """Токен из скрытого поля формы — как его отправляет браузер."""
    return re.search(r'name="csrf_token" value="([^"]+)"', text(client.get(path))).group(1)


def meta_token(client, path="/admin/") -> str:
    """Токен из `<meta name="csrf-token">` — его берёт admin.js для заголовка X-CSRFToken."""
    return re.search(r'<meta name="csrf-token" content="([^"]+)"', text(client.get(path))).group(1)


def sign_ago(app, raw, seconds):
    """Токен, подписанный `seconds` назад: страница могла лежать открытой сутки и больше."""

    class AgedSerializer(URLSafeTimedSerializer):
        def make_signer(self, salt=None):
            signer = super().make_signer(salt)
            signer.get_timestamp = lambda: int(time.time()) - seconds
            return signer

    with app.app_context():
        return AgedSerializer(app.secret_key, salt=SALT).dumps(raw)


def enter(client, token=None):
    return client.post("/admin/login",
                       data={"login": "admin", "password": PASSWORD,
                             "csrf_token": token or form_token(client)},
                       follow_redirects=True)


# --- кука: как она ставится -------------------------------------------------

def test_csrf_cookie_is_set_on_first_get(tmp_path):
    """Первый же GET отдаёт куку токена: год, SameSite=Lax, доступна скриптам."""
    client = csrf_app(tmp_path).test_client()
    page = client.get("/admin/login")
    headers = cookie_headers(page)
    assert len(headers) == 1, f"кука токена не поставлена: {page.headers.getlist('Set-Cookie')}"
    attrs = headers[0].lower()
    assert re.fullmatch(r"[0-9a-f]{64}", cookie_value(headers[0])), "в куке должна быть случайная hex-строка"
    assert f"max-age={CSRF_COOKIE_MAX_AGE}" in attrs, "срок куки должен быть около года"
    assert "samesite=lax" in attrs
    assert "path=/" in attrs, "токен нужен формам всего сайта"
    assert "httponly" not in attrs, "токен читается из meta страницы, кука не должна его прятать"
    assert "secure" not in attrs, "на http-сайте Secure-кука не приезжает обратно"
    assert 'name="csrf_token" value="' in text(page)


def test_csrf_cookie_is_secure_on_https_site(tmp_path):
    """Боевой сайт с HTTPS-куками (`SESSION_COOKIE_SECURE=1`) ставит Secure и токену."""
    client = csrf_app(tmp_path, SESSION_COOKIE_SECURE=True).test_client()
    headers = cookie_headers(client.get("/admin/login"))
    assert len(headers) == 1
    assert "secure" in headers[0].lower()


def test_csrf_cookie_is_set_on_public_pages(tmp_path):
    """Публичные формы (обращения, анкеты) тоже получают куку — без входа в панель."""
    app = csrf_app(tmp_path)
    for path in ("/", "/obrashcheniya"):
        # Каждый раз новый «браузер»: целая кука второй раз не ставится, см. проверку ниже
        page = app.test_client().get(path)
        assert len(cookie_headers(page)) == 1, path


def test_valid_cookie_is_not_rewritten_on_every_request(tmp_path):
    """Целая кука не перезаписывается: иначе браузер получал бы новый Set-Cookie на запрос."""
    client = csrf_app(tmp_path).test_client()
    assert cookie_headers(client.get("/admin/login"))
    raw = client.get_cookie(CSRF_COOKIE_NAME).value
    for path in ("/admin/login", "/", "/afisha", "/obrashcheniya"):
        again = client.get(path)
        assert cookie_headers(again) == [], f"на {path} кука токена перезаписана"
        assert client.get_cookie(CSRF_COOKIE_NAME).value == raw, path


def test_corrupted_cookie_is_replaced_with_working_one(tmp_path):
    """Битую куку браузер всё равно получает рабочую: токен со страницы подписан новой строкой.

    Иначе посетитель с испорченной кукой застрял бы на «Форма устарела» — тем же
    симптомом, от которого этот механизм и избавляет.
    """
    client = csrf_app(tmp_path).test_client()
    client.set_cookie(CSRF_COOKIE_NAME, "abc")
    page = client.get("/admin/login")
    headers = cookie_headers(page)
    assert len(headers) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", cookie_value(headers[0]))
    token = re.search(r'name="csrf_token" value="([^"]+)"', text(page)).group(1)
    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": token}, follow_redirects=True)
    assert "Форма устарела" not in text(r)
    assert "Сводка" in text(r), "токен со страницы не совпал с новой кукой"


# --- форма входа ------------------------------------------------------------

def test_login_with_token_from_form_and_cookie(tmp_path):
    """Форма входа «как в браузере»: токен из поля + кука этого же браузера."""
    client = csrf_app(tmp_path).test_client()
    token = form_token(client)
    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": token}, follow_redirects=True)
    assert r.status_code == 200
    assert "Сводка" in text(r), "вход с рабочим токеном не выполнен"


def test_login_without_token_but_with_cookie_is_rejected(tmp_path):
    """Куки недостаточно — токен обязан прийти в форме (иначе double submit не работает)."""
    client = csrf_app(tmp_path).test_client()
    form_token(client)  # кука есть
    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD})
    assert r.status_code == 400
    assert "Форма устарела" in text(r)
    with client.session_transaction() as sess:
        assert "user_id" not in sess, "вход без токена выполнен"


def test_token_survives_session_reset_on_login(tmp_path):
    """Вход РОТИРУЕТ токен: старый (до входа) не работает, свежий (из meta) — работает.

    Токен, полученный до входа, после `rotate_csrf_token()` больше не годится —
    это защита от подсмотренного токена на общем компьютере (С-23). Браузер не
    ломается, потому что после входа открывается новая страница со свежим токеном.
    """
    client = csrf_app(tmp_path).test_client()
    token_before = form_token(client)
    client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                      "csrf_token": token_before}, follow_redirects=True)
    assert client.get("/admin/").status_code == 200, "вход не выполнен"
    # Старый токен — 400 (ротация)
    denied = client.post("/admin/upload", data={"file": (png((900, 700)), "foto.png")},
                         content_type="multipart/form-data", headers={"X-CSRFToken": token_before})
    assert denied.status_code == 400 and "Форма устарела" in text(denied)
    # Свежий токен из meta — работает
    fresh_token = meta_token(client, "/admin/")
    r = client.post("/admin/upload", data={"file": (png((900, 700)), "foto.png")},
                    content_type="multipart/form-data", headers={"X-CSRFToken": fresh_token})
    assert r.status_code == 200, text(r)
    assert r.get_json()["success"] is True


def test_csrf_cookie_rotates_on_logout_and_login(tmp_path):
    """Выход и вход РОТИРУЮТ куку: значение меняется, старая форма даёт 400.

    Токен не должен пережить смену пользователя (С-23): при выходе — новый токен
    гостя, при входе — новый токен сотрудника. Форма, открытая до ротации,
    отклоняется; свежая — проходит.
    """
    app = csrf_app(tmp_path)
    client = app.test_client()
    assert "Сводка" in text(enter(client))
    raw_after_login = client.get_cookie(CSRF_COOKIE_NAME).value
    meta = meta_token(client, "/admin/")

    # Выход: кука меняется
    out = client.post("/admin/logout", data={"csrf_token": meta}, follow_redirects=True)
    assert out.status_code == 200, "выход из панели вернул не страницу сайта"
    assert client.get("/admin/").status_code == 302, "сеанс после выхода остался"
    raw_after_logout = client.get_cookie(CSRF_COOKIE_NAME).value
    assert raw_after_logout != raw_after_login, "выход не ротировал куку токена"
    with client.session_transaction() as sess:
        assert "user_id" not in sess

    # Вход с новой кукой: кука меняется снова
    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": form_token(client)},
                    follow_redirects=True)
    assert "Сводка" in text(r), "повторный вход не выполнен"
    raw_after_relogin = client.get_cookie(CSRF_COOKIE_NAME).value
    assert raw_after_relogin != raw_after_logout, "вход не ротировал куку токена"

    # Форма, открытая ДО ротации, не проходит после смены куки.
    # Берём токен из одной сессии, а куку меняем — имитация ротации:
    guest = app.test_client()
    token_before = form_token(guest)
    # Ротация: браузер получил новую куку (токен от старой не годится)
    guest.set_cookie(CSRF_COOKIE_NAME, "0" * 64)
    denied = guest.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                              "csrf_token": token_before})
    assert denied.status_code == 400 and "Форма устарела" in text(denied)



def test_login_works_after_session_cookie_is_dropped(tmp_path):
    """Сеанс браузер потерял посреди работы — форма входа всё равно принимает запрос."""
    client = csrf_app(tmp_path).test_client()
    assert "Сводка" in text(enter(client))
    token = form_token(client)
    client.delete_cookie("session")

    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": token}, follow_redirects=True)
    assert "Форма устарела" not in text(r)
    assert "Сводка" in text(r)


def test_token_needs_no_server_side_state(tmp_path):
    """Токен ничего не хранит в процессе: его принимает другое приложение того же ключа.

    Так работают несколько процессов gunicorn и перезапуск сайта — страница,
    открытая одним воркером, отправляется другим.
    """
    first = csrf_app(tmp_path)
    client = first.test_client()
    token = form_token(client)
    raw = client.get_cookie(CSRF_COOKIE_NAME).value

    other = make_app(tmp_path, WTF_CSRF_ENABLED=True,
                     SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "worker2.db"))
    guest = other.test_client()
    guest.set_cookie(CSRF_COOKIE_NAME, raw)
    r = guest.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                         "csrf_token": token}, follow_redirects=True)
    assert "Форма устарела" not in text(r)
    assert "Сводка" in text(r)


# --- срок подписи -----------------------------------------------------------

def test_expired_token_is_rejected(tmp_path):
    """Токен старше срока куки отклоняется: подпись сверяется со временем."""
    app = csrf_app(tmp_path)
    client = app.test_client()
    form_token(client)
    raw = client.get_cookie(CSRF_COOKIE_NAME).value
    ancient = sign_ago(app, raw, CSRF_COOKIE_MAX_AGE + 3600)

    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": ancient})
    assert r.status_code == 400
    assert "Форма устарела" in text(r)


def test_day_old_token_is_accepted(tmp_path):
    """Страница могла лежать открытой сутки: час (как у Flask-WTF) сюда не годится."""
    app = csrf_app(tmp_path)
    client = app.test_client()
    form_token(client)
    raw = client.get_cookie(CSRF_COOKIE_NAME).value
    yesterday = sign_ago(app, raw, 24 * 3600)

    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": yesterday}, follow_redirects=True)
    assert "Форма устарела" not in text(r)
    assert "Сводка" in text(r)


def test_token_signed_in_the_future_is_rejected(tmp_path):
    """Подпись «из будущего» (сбой часов) не принимается — как и у штатного Flask-WTF."""
    app = csrf_app(tmp_path)
    client = app.test_client()
    form_token(client)
    raw = client.get_cookie(CSRF_COOKIE_NAME).value
    future = sign_ago(app, raw, -3600)

    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                          "csrf_token": future})
    assert r.status_code == 400 and "Форма устарела" in text(r)


def test_time_limit_setting_is_respected(tmp_path):
    """Срок подписи берётся из настройки, а не зашит: Flask-WTF по умолчанию ставит час."""
    app = csrf_app(tmp_path, WTF_CSRF_TIME_LIMIT=CSRF_COOKIE_MAX_AGE)
    client = app.test_client()
    form_token(client)
    raw = client.get_cookie(CSRF_COOKIE_NAME).value
    month = client.post("/admin/login", data={"login": "admin", "password": PASSWORD,
                                              "csrf_token": sign_ago(app, raw, 30 * 24 * 3600)},
                        follow_redirects=True)
    assert "Сводка" in text(month), "месячный токен отклонён при годичном сроке"
    two_years = client.post("/admin/login",
                            data={"login": "admin", "password": PASSWORD,
                                  "csrf_token": sign_ago(app, raw, 2 * 365 * 24 * 3600)})
    assert two_years.status_code == 400 and "Форма устарела" in text(two_years)


# --- остальные формы --------------------------------------------------------

def test_admin_page_form_still_needs_token(tmp_path):
    """Постановка страниц в панели осталась под защитой: без токена — 400."""
    app = csrf_app(tmp_path)
    client = app.test_client()
    assert "Сводка" in text(enter(client))

    denied = client.post("/admin/pages/new", data={"title": "Без токена"})
    assert denied.status_code == 400 and "Форма устарела" in text(denied)
    with app.app_context():
        assert Page.query.filter_by(title="Без токена").first() is None

    token = form_token(client, "/admin/pages/new")
    ok = client.post("/admin/pages/new", data={"title": "Новая страница",
                                               "content": "<p>Текст</p>",
                                               "csrf_token": token},
                     follow_redirects=True)
    assert ok.status_code == 200 and "Страница сохранена" in text(ok)
    with app.app_context():
        assert Page.query.filter_by(title="Новая страница").first() is not None


def test_public_appeal_post_works_with_form_token(tmp_path):
    """Анонимное обращение проходит по-прежнему: токен берётся из публичной формы."""
    app = csrf_app(tmp_path)
    client = app.test_client()
    token = form_token(client, "/obrashcheniya")
    r = client.post("/obrashcheniya", data={"name": "Иван Петров",
                                            "email": "ivan@example.ru",
                                            "message": "Спасибо за концерт!",
                                            "consent": "1", "csrf_token": token},
                    follow_redirects=True)
    assert r.status_code == 200 and "Обращение принято" in text(r)
    with app.app_context():
        assert Appeal.query.count() == 1


def test_csp_report_stays_exempt(tmp_path):
    """Отчёт браузера о политике безопасности приходит без входа и без токена."""
    client = csrf_app(tmp_path).test_client()
    r = client.post("/csp-report", data='{"csp-report": {"blocked-uri": "x"}}',
                    content_type="application/csp-report")
    assert r.status_code == 204


def test_cookie_name_is_not_session_cookie(tmp_path):
    """Кука токена не перекрывает сеанс: имена разные, обе приезжают вместе."""
    client = csrf_app(tmp_path).test_client()
    assert CSRF_COOKIE_NAME == "csrf_token" != "session"
    assert "Сводка" in text(enter(client))
    assert client.get_cookie(CSRF_COOKIE_NAME) is not None
    assert client.get_cookie("session") is not None
