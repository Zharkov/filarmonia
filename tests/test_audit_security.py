"""Аудит 2026-10-21, этап A: безопасность (ссылки, размеры запросов, доступ, сроки хранения,
пароль стенда) и серверное SEO (robots, карта сайта, 404 пагинации, Last-Modified)."""
import base64
import logging
from datetime import timedelta

import pytest
from conftest import PASSWORD, create_event, login, make_app, text

from filarmonia import surveys, utils
from filarmonia.admin.common import safe_next, safe_url
from filarmonia.models import (
    db, ActionLog, Appeal, Banner, Document, Event, EventBadge, MenuItem, News, Page, Redirect,
    Setting, SurveyResponse, Throttle,
)

BAD_URLS = [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "\tjavascript:alert(1)",
    "\njavascript:alert(1)", "java\tscript:alert(1)", "data:text/html,<script>1</script>",
    "vbscript:x", "//evil.ru", "/\\evil.ru", "/\t/evil.ru", "evil.ru/path",
]
GOOD_URLS = ["/путь", "/afisha/koncert", "https://example.ru/a?b=1", "http://example.ru", "mailto:a@b.ru",
             "tel:+74812000000"]


@pytest.mark.parametrize("value", BAD_URLS)
def test_safe_url_rejects(value):
    assert safe_url(value) is None


@pytest.mark.parametrize("value", GOOD_URLS + ["", "   ", "#", "#anketa"])
def test_safe_url_accepts(value):
    assert safe_url(value) == value.strip()


# С-1. Каждое поле со ссылкой в панели: плохая ссылка не сохраняется, хорошая сохраняется
def _post_menu(c, url):
    return c.post("/admin/menu", data={"title": "Пункт", "url": url, "is_published": "1"})


def _post_banner(c, url):
    return c.post("/admin/banners", data={"title": "Баннер", "url": url, "is_published": "1"},
                  content_type="multipart/form-data")


def _post_document(c, url):
    return c.post("/admin/documents", data={"title": "Документ", "url": url, "is_published": "1"},
                  content_type="multipart/form-data")


def _post_event(c, url):
    return create_event(c, ticket_url=url)


def _stored(model, column):
    row = model.query.first()
    return getattr(row, column) if row else None


FIELDS = {
    "menu": (_post_menu, MenuItem, "url"),
    "banner": (_post_banner, Banner, "url"),
    "document": (_post_document, Document, "url"),
    "ticket": (_post_event, Event, "ticket_url"),
}


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_bad_url_not_saved(app, admin, field):
    post, model, column = FIELDS[field]
    for value in BAD_URLS:
        post(admin, value)
    with app.app_context():
        assert model.query.count() == 0, field


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_good_url_saved(app, admin, field):
    post, model, column = FIELDS[field]
    for value in GOOD_URLS:
        post(admin, value)
    with app.app_context():
        assert sorted(getattr(r, column) for r in model.query) == sorted(GOOD_URLS), field


def test_bad_url_shows_error(admin):
    r = admin.post("/admin/menu", data={"title": "Пункт", "url": "javascript:alert(1)"},
                   follow_redirects=True)
    assert "Ссылка должна начинаться" in text(r)


def test_bad_url_on_edit_keeps_old(app, admin):
    _post_menu(admin, "/afisha")
    with app.app_context():
        item_id = MenuItem.query.first().id
    admin.post("/admin/menu", data={"id": str(item_id), "title": "Пункт", "url": "javascript:alert(1)"})
    with app.app_context():
        assert MenuItem.query.first().url == "/afisha"


def test_bad_ticket_url_leaves_no_event_error_in_form(admin):
    r = create_event(admin, ticket_url="javascript:alert(1)")
    assert "Ссылка на билеты" in text(r)


def test_news_document_bad_url(app, admin):
    with app.app_context():
        db.session.add(News(title="Н", slug="n", is_published=True, published_at=utils.utcnow()))
        db.session.commit()
        news_id = News.query.first().id
    for value in BAD_URLS:
        admin.post(f"/admin/news/{news_id}/documents", data={"title": "Док", "url": value},
                   content_type="multipart/form-data")
    admin.post(f"/admin/news/{news_id}/documents", data={"title": "Док", "url": "https://ok.ru/x"},
               content_type="multipart/form-data")
    with app.app_context():
        assert [d.url for d in Document.query] == ["https://ok.ru/x"]


def test_badge_bad_url(app, admin):
    create_event(admin)
    with app.app_context():
        event_id = Event.query.first().id
    for value in BAD_URLS:
        admin.post(f"/admin/events/{event_id}/badges", data={"text": "Новинка", "url": value})
    admin.post(f"/admin/events/{event_id}/badges", data={"text": "Новинка", "url": "/afisha"})
    with app.app_context():
        assert [b.url for b in EventBadge.query] == ["/afisha"]


def test_redirect_target_bad_url(app, admin):
    for i, value in enumerate(BAD_URLS):
        admin.post("/admin/redirects", data={"old_path": f"/old{i}", "new_url": value})
    admin.post("/admin/redirects", data={"old_path": "/old-ok", "new_url": "/novosti"})
    with app.app_context():
        assert [r.new_url for r in Redirect.query] == ["/novosti"]


def test_notice_link_control_chars(app, admin):
    admin.post("/admin/notices", data={"text": "Перенос", "url": "/\t/evil.ru"})
    with app.app_context():
        from filarmonia.models import AfishaNotice
        assert AfishaNotice.query.first().url == ""


# С-5. Адрес возврата после входа
@pytest.mark.parametrize("target", [
    "/\t/evil.com", "/\r\n/evil.com", "//evil", "/\\evil", "https://evil", "javascript:1",
    "evil.com", "",
])
def test_safe_next_rejects(app, target):
    with app.test_request_context():
        assert safe_next(target) == "/admin/"


def test_safe_next_accepts(app):
    with app.test_request_context():
        assert safe_next("/admin/news?page=2") == "/admin/news?page=2"


@pytest.mark.parametrize("target", ["/%09/evil.com", "/%0d%0a/evil.com", "//evil", "/%5Cevil", "https://evil"])
def test_login_next_not_open_redirect(app, target):
    r = app.test_client().post(f"/admin/login?next={target}",
                               data={"login": "admin", "password": PASSWORD})
    assert r.status_code == 302
    assert "evil" not in r.headers["Location"]


# С-3. Размеры тел запросов
def test_csp_report_big_body_413(app):
    client = app.test_client()
    assert client.post("/csp-report", data="x" * (20 * 1024)).status_code == 413
    assert client.post("/csp-report", data='{"csp-report": {}}').status_code == 204


def test_csp_report_log_cannot_be_forged(app, caplog):
    with caplog.at_level(logging.WARNING):
        app.test_client().post("/csp-report", data="ok\r\nCSP: подделка ещё\x00")
    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith("CSP:")]
    assert len(messages) == 1
    assert not any(ch in messages[0] for ch in "\r\n \x00")


def test_appeals_big_body_413(app):
    r = app.test_client().post("/obrashcheniya", data={
        "name": "Иван", "email": "a@b.ru", "message": "x" * (200 * 1024), "consent": "1"})
    assert r.status_code == 413
    with app.app_context():
        assert Appeal.query.count() == 0


def test_appeal_long_cyrillic_message_saved_truncated(app):
    message = ("Слово " * 5 + "\n") * 400          # около 12 000 знаков с переводами строк
    r = app.test_client().post("/obrashcheniya", data={
        "name": "Иван" * 200, "email": "a@b.ru", "message": message, "consent": "1",
        "subject": "Т" * 1000, "phone": "1" * 500})
    assert r.status_code == 302
    with app.app_context():
        appeal = Appeal.query.one()
        assert len(appeal.message) == 10000
        assert len(appeal.name) == 300 and len(appeal.subject) == 300 and len(appeal.phone) == 80


def test_appeal_nul_removed(app):
    app.test_client().post("/obrashcheniya", data={
        "name": "Иван", "email": "a@b.ru", "message": "до\x00после", "consent": "1"})
    with app.app_context():
        assert Appeal.query.one().message == "допосле"


# SEO-2. Адрес сайта на боевом сервере
def test_production_without_site_url_refuses_to_start(tmp_path):
    for flag in ("SESSION_COOKIE_SECURE", "TRUST_PROXY"):
        with pytest.raises(RuntimeError, match="SITE_URL"):
            make_app(tmp_path, TESTING=False, SITE_URL="", **{flag: True})


def test_production_with_site_url_starts(tmp_path):
    make_app(tmp_path, TESTING=False, SITE_URL="https://example.ru", SESSION_COOKIE_SECURE=True,
             TRUST_PROXY=True)


def test_local_without_site_url_starts(tmp_path):
    make_app(tmp_path, TESTING=False, SITE_URL="")


def test_site_url_falls_back_to_render(monkeypatch):
    from config import build_config
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://stand.onrender.com/")
    config = build_config()
    assert config["SITE_URL"] == "https://stand.onrender.com" and not config["SITE_URL_EXPLICIT"]
    monkeypatch.setenv("SITE_URL", "https://example.ru")
    config = build_config()
    assert config["SITE_URL"] == "https://example.ru" and config["SITE_URL_EXPLICIT"]


def test_site_url_falls_back_to_render_hostname(monkeypatch):
    from config import build_config
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "stand.onrender.com")
    assert build_config()["SITE_URL"] == "https://stand.onrender.com"


def test_noindex_with_explicit_site_url_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        make_app(tmp_path, TESTING=False, SITE_URL="https://example.ru", SITE_NOINDEX=True)
    assert any("SITE_NOINDEX" in r.getMessage() for r in caplog.records)


# С-7, С-8. Обращения: журнал без имени, раздел только для администратора
@pytest.fixture
def appeal_id(app):
    with app.app_context():
        appeal = Appeal(name="Иванова Мария Петровна", message="Прошу ответить", email="a@b.ru")
        db.session.add(appeal)
        db.session.commit()
        return appeal.id


def test_appeal_log_has_number_not_name(app, admin, appeal_id):
    admin.post(f"/admin/appeals/{appeal_id}", data={"is_processed": "1"})
    admin.post(f"/admin/appeals/{appeal_id}/delete")
    with app.app_context():
        rows = ActionLog.query.filter_by(object_type="appeal").order_by(ActionLog.id).all()
        assert [r.action for r in rows] == ["update", "delete"]
        assert all(r.title == f"Обращение № {appeal_id}" for r in rows)
        assert Appeal.query.count() == 0


@pytest.mark.parametrize("method,path", [
    ("get", "/admin/appeals"), ("get", "/admin/appeals/{id}"), ("post", "/admin/appeals/{id}"),
    ("get", "/admin/appeals/{id}/print"), ("post", "/admin/appeals/{id}/delete"),
])
def test_editor_cannot_touch_appeals(app, editor, appeal_id, method, path):
    r = getattr(editor, method)(path.format(id=appeal_id))
    assert r.status_code == 403
    with app.app_context():
        assert Appeal.query.count() == 1


def test_guest_redirected_from_appeals(app, appeal_id):
    r = app.test_client().post(f"/admin/appeals/{appeal_id}/delete")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_editor_dashboard_hides_appeals(editor, appeal_id):
    html = text(editor.get("/admin/"))
    assert "обращений" not in html and "Иванова" not in html and "/admin/appeals" not in html


def test_admin_dashboard_shows_appeals(admin, appeal_id):
    html = text(admin.get("/admin/"))
    assert "новых обращений" in html and "Иванова" in html and "/admin/appeals" in html


def test_admin_appeal_page_has_delete_button(admin, appeal_id):
    assert f"/admin/appeals/{appeal_id}/delete" in text(admin.get(f"/admin/appeals/{appeal_id}"))


# С-9. Удаление по сроку хранения
def test_purge_command_function(app):
    from filarmonia import maintenance

    old = utils.utcnow() - timedelta(days=365 * 6)
    with app.app_context():
        db.session.add_all([
            Appeal(name="Старое обработанное", message="x", is_processed=True, created_at=old),
            Appeal(name="Старое без ответа", message="x", is_processed=False, created_at=old),
            Appeal(name="Свежее", message="x", is_processed=True),
            SurveyResponse(survey="a", answers="{}", created_at=utils.utcnow() - timedelta(days=365 * 4)),
            SurveyResponse(survey="a", answers="{}", created_at=utils.utcnow() - timedelta(days=365 * 2)),
        ])
        db.session.commit()
    assert maintenance.purge(app) == {"appeals": 1, "surveys": 1}
    with app.app_context():
        assert {a.name for a in Appeal.query} == {"Старое без ответа", "Свежее"}
        assert SurveyResponse.query.count() == 1
        assert {r.object_type for r in ActionLog.query.filter_by(action="purge")} == {"appeal", "survey"}
    assert maintenance.purge(app) == {"appeals": 0, "surveys": 0}


def test_purge_respects_settings(app):
    from filarmonia import maintenance

    with app.app_context():
        db.session.add_all([
            Setting(key="surveys_retention_years", value="1", kind="text"),
            Setting(key="appeals_retention_years", value="0", kind="text"),
            SurveyResponse(survey="a", answers="{}", created_at=utils.utcnow() - timedelta(days=500)),
            Appeal(name="Старое", message="x", is_processed=True,
                   created_at=utils.utcnow() - timedelta(days=365 * 9)),
        ])
        db.session.commit()
    assert maintenance.purge(app) == {"appeals": 0, "surveys": 1}


def test_surveys_retention_setting_in_seed():
    from filarmonia import seed
    row = next(s for s in seed.SETTINGS if s[0] == "surveys_retention_years")
    assert row[1] == "3"


def test_migration_0015_chain():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "migrations", "versions", "0015_surveys_retention_setting.py")
    spec = importlib.util.spec_from_file_location("m0015", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "e3c7a2b9d106"


# С-11, SEO-4. Тестовый стенд
def basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": "Basic " + token}


@pytest.fixture
def stand(tmp_path):
    return make_app(tmp_path, SITE_NOINDEX=True, STAND_USER="stand", STAND_PASSWORD="пароль-стенда")


def test_stand_requires_password(stand):
    client = stand.test_client()
    r = client.get("/afisha")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Basic")
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert client.get("/afisha", headers=basic("stand", "wrong")).status_code == 401
    assert client.get("/afisha", headers=basic("other", "пароль-стенда")).status_code == 401
    assert client.post("/admin/login", data={"login": "admin", "password": PASSWORD}).status_code == 401


def test_stand_accepts_password(stand):
    r = stand.test_client().get("/afisha", headers=basic("stand", "пароль-стенда"))
    assert r.status_code == 200
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_stand_health_and_static_open(stand):
    client = stand.test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/css/site.css").status_code == 200


def test_stand_robots_allows_crawling(stand):
    body = text(stand.test_client().get("/robots.txt", headers=basic("stand", "пароль-стенда")))
    assert "Disallow: /\n" not in body and "Allow: /" in body


def test_stand_without_password_is_open_but_closed_for_forms(tmp_path):
    app = make_app(tmp_path, SITE_NOINDEX=True)
    client = app.test_client()
    r = client.get("/afisha")
    assert r.status_code == 200 and r.headers["X-Robots-Tag"] == "noindex, nofollow"
    r = client.post("/obrashcheniya", data={"name": "Иван", "email": "a@b.ru", "message": "Текст",
                                           "consent": "1"}, follow_redirects=True)
    assert "отключён" in text(r)
    with app.app_context():
        assert Appeal.query.count() == 0
        db.session.add(Page(title="НОК", slug="nok", template="nok", is_published=True))
        db.session.commit()
    data = {q.id: "yes" for q in surveys.SNOC.questions}
    data.update({"org": "Филармония", "address": "Смоленск"})
    r = client.post("/info/nok/anketa/snoc", data=data)
    assert "отключён" in text(r)
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_normal_site_not_affected_by_stand_code(app):
    client = app.test_client()
    assert client.get("/afisha").status_code == 200
    assert "X-Robots-Tag" not in client.get("/afisha").headers
    assert "Disallow: /admin" in text(client.get("/robots.txt"))
    assert client.get("/healthz").status_code == 200


# SEO-13. Clean-param
def test_robots_clean_param(app):
    body = text(app.test_client().get("/robots.txt"))
    assert ("Clean-param: day&from&to&venue&category&price&sort&q&pushkin&benefits&new&archive /afisha"
            in body)
    assert "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid" in body


# SEO-14, SEO-15. Карта сайта
def _add_pages(app):
    with app.app_context():
        db.session.add_all([
            Page(title="Интернет-приёмная", slug="internet-priemnaya", content="x"),
            Page(title="Пустые документы", slug="pustye", template="documents"),
            Page(title="Есть документы", slug="est", template="documents"),
            Page(title="Независимая оценка", slug="nok", template="nok"),
            Page(title="Обычная", slug="obychnaya"),
            Document(title="Устав", category="Есть документы", is_published=True),
            Document(title="Скрытый", category="Пустые документы", is_published=False),
        ])
        db.session.commit()


def test_sitemap_skips_moved_and_empty_document_pages(app):
    _add_pages(app)
    body = text(app.test_client().get("/sitemap.xml"))
    assert "/info/internet-priemnaya" not in body
    assert "/info/pustye" not in body
    assert "/info/est<" in body.replace("</loc>", "<") and "/info/nok" in body and "/info/obychnaya" in body


def test_internet_priemnaya_redirects(app):
    _add_pages(app)
    r = app.test_client().get("/info/internet-priemnaya")
    assert r.status_code == 301 and r.headers["Location"].endswith("/obrashcheniya")


def test_site_map_page_skips_moved(app):
    _add_pages(app)
    assert "/info/internet-priemnaya" not in text(app.test_client().get("/karta-sajta"))


# SEO-21. Страница за пределами выдачи
def test_pagination_out_of_range_404(app, admin):
    client = app.test_client()
    assert client.get("/afisha?page=999").status_code == 404
    assert client.get("/novosti?page=999").status_code == 404
    assert client.get("/afisha").status_code == 200 and client.get("/afisha?page=1").status_code == 200
    assert client.get("/novosti").status_code == 200
    create_event(admin)
    with app.app_context():
        db.session.add(News(title="Н", slug="n", is_published=True, published_at=utils.utcnow()))
        db.session.commit()
    assert client.get("/afisha?page=1").status_code == 200
    assert client.get("/afisha?page=2").status_code == 404
    assert client.get("/novosti?page=2").status_code == 404


# SEO-24. Last-Modified
def test_event_and_news_last_modified(app, admin):
    create_event(admin)
    with app.app_context():
        db.session.add(News(title="Н", slug="n", is_published=True, published_at=utils.utcnow()))
        db.session.commit()
        slug = Event.query.first().slug
    client = app.test_client()
    for path in (f"/afisha/{slug}", "/novosti/n"):
        r = client.get(path)
        assert r.status_code == 200 and "Last-Modified" in r.headers, path
        date = r.headers["Last-Modified"]
        again = client.get(path, headers={"If-Modified-Since": date})
        assert again.status_code == 304, path
        old = client.get(path, headers={"If-Modified-Since": "Mon, 01 Jan 2001 00:00:00 GMT"})
        assert old.status_code == 200
    # сотруднику страница не кэшируется
    assert "Last-Modified" not in admin.get(f"/afisha/{slug}").headers


# SEO-25. Описания без склеенных заголовков
def test_strip_tags_separates_blocks():
    assert utils.strip_tags("<h2>О концерте</h2><p>Играет оркестр.</p><p>Билеты в кассе</p>") \
        == "О концерте. Играет оркестр. Билеты в кассе"
    assert utils.strip_tags("<p>Первый.</p><p>Второй!</p>") == "Первый. Второй!"
    assert utils.strip_tags("Строка<br>другая") == "Строка. другая"
    assert utils.strip_tags("<p>Слово <b>жирное</b> и <i>курсив</i></p>") == "Слово жирное и курсив"
    assert utils.strip_tags("") == "" and utils.strip_tags(None) == ""


# С-16, С-17. Вход
def test_unknown_login_spends_password_time(app, monkeypatch):
    from filarmonia.admin import auth

    calls = []
    real = auth.check_password_hash
    monkeypatch.setattr(auth, "check_password_hash", lambda h, p: calls.append(h) or real(h, p))
    client = app.test_client()
    client.post("/admin/login", data={"login": "nobody", "password": "x"})
    assert len(calls) == 1
    client.post("/admin/login", data={"login": "admin", "password": PASSWORD})
    assert len(calls) == 1


def test_inactive_user_wrong_password_still_checked(app):
    from filarmonia.models import User
    with app.app_context():
        User.query.filter_by(login="editor").first().is_active = False
        db.session.commit()
    assert "Неверный логин" in text(login(app.test_client(), "editor"))


def test_long_login_key_truncated(app):
    client = app.test_client()
    r = client.post("/admin/login", data={"login": "я" * 5000, "password": "x"})
    assert r.status_code == 200
    with app.app_context():
        keys = [t.key for t in Throttle.query]
        assert keys and all(len(k) < 300 for k in keys)
