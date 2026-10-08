"""Исправления по техническому аудиту: безопасность, ошибки, перенаправления, сжатие, разметка."""
import gzip
import io
import json
import os
import re
import time
from datetime import timedelta

import pytest
from conftest import create_event, login, make_app, text

from filarmonia import utils
from filarmonia.models import Event, Redirect, Throttle


# Ссылки на видео
@pytest.mark.parametrize("url", [
    "javascript:alert(document.domain)//vk.com/video_ext.php",
    "javascript:alert(1)//youtube.com/watch?v=dQw4w9WgXcQ",
    "data:text/html,<script>alert(1)</script>//rutube.ru/video/" + "a" * 32,
    "http://vk.com/video-1_2",
    "https://vk.com.evil.ru/video-1_2",
    "https://evil.ru/?vk.com/video_ext.php",
    "//evil.ru/clip.mp4",
])
def test_video_embed_rejects_foreign_and_script_urls(url):
    assert utils.video_embed(url) == ""


@pytest.mark.parametrize("url, expected", [
    ("https://vk.com/video-123_456", "https://vk.com/video_ext.php?oid=-123&id=456&hd=2"),
    ("https://vk.com/video_ext.php?oid=-1&id=2&hash=ab12", "oid=-1&id=2&hash=ab12&hd=2"),
    ("https://rutube.ru/video/" + "a1b2c3d4" * 4 + "/", "https://rutube.ru/play/embed/" + "a1b2c3d4" * 4),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
    ("https://dzen.ru/video/watch/abc-123", "https://dzen.ru/embed/abc-123"),
    ("https://cdn.example.ru/clip.mp4", 'src="https://cdn.example.ru/clip.mp4"'),
    ("/static/uploads/clip.mp4", 'src="/static/uploads/clip.mp4"'),
])
def test_video_embed_known_hosts(url, expected):
    assert expected in utils.video_embed(url)


def test_editor_cannot_store_script_video(app, editor):
    create_event(editor)
    with app.app_context():
        eid = Event.query.first().id
    editor.post("/admin/media/add", data={
        "owner": "event", "owner_id": str(eid), "kind": "video",
        "url": "javascript:alert(1)//vk.com/video_ext.php"})
    html = text(editor.get("/afisha/testovyy-koncert"))
    assert "javascript:alert" not in html.split("<main", 1)[1]


# Загрузка картинок
def test_upload_rejects_non_image_named_jpg(app, admin):
    fake = io.BytesIO(b"%PDF-1.4\n%fake pdf pretending to be a photo\n")
    r = admin.post("/admin/news/new", data={"title": "Новость", "image": (fake, "photo.jpg")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert "не распознан как изображение" in text(r)
    folder = app.config["UPLOAD_FOLDER"]
    assert not (os.path.isdir(folder) and os.listdir(folder)), "отклонённый файл должен удаляться"


# Заголовки
def test_security_headers(app, admin):
    public = app.test_client().get("/")
    assert public.headers["X-Content-Type-Options"] == "nosniff"
    assert public.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in public.headers["Content-Security-Policy"]
    assert "report-uri /csp-report" in public.headers["Content-Security-Policy-Report-Only"]

    panel = admin.get("/admin/")
    csp = panel.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert panel.headers["X-Frame-Options"] == "DENY"
    # Встроенных скриптов и обработчиков в панели нет — иначе политика их заблокирует
    html = text(panel)
    assert not re.search(r"<script>(?!\s*$)|\son(submit|change|click)=", html)


def test_hsts_only_over_https(tmp_path):
    app = make_app(tmp_path, SESSION_COOKIE_SECURE=True)
    assert "max-age" in app.test_client().get("/").headers["Strict-Transport-Security"]


def test_csp_report_accepted(app):
    r = app.test_client().post("/csp-report", data=json.dumps({"csp-report": {}}),
                               content_type="application/csp-report")
    assert r.status_code == 204


# Вход, выход, сеанс
def test_logout_requires_post(app, admin):
    assert admin.get("/admin/logout").status_code == 405
    admin.post("/admin/logout")
    assert admin.get("/admin/").status_code == 302


def test_login_lockout_is_stored_in_database(tmp_path):
    app = make_app(tmp_path, LOGIN_MAX_ATTEMPTS=2)
    for _ in range(2):
        login(app.test_client(), password="wrong")
    # Другой клиент (как другой процесс gunicorn) видит ту же блокировку
    assert "Слишком много попыток" in text(login(app.test_client()))
    with app.app_context():
        assert Throttle.query.filter(Throttle.key.like("login:admin:%")).one().count == 2


def test_successful_login_resets_counter(tmp_path):
    app = make_app(tmp_path, LOGIN_MAX_ATTEMPTS=3)
    client = app.test_client()
    login(client, password="wrong")
    login(client)
    with app.app_context():
        assert Throttle.query.count() == 0


def test_idle_session_expires(app, admin):
    with admin.session_transaction() as s:
        s["seen"] = time.time() - app.config["SESSION_IDLE_SECONDS"] - 5
    assert admin.get("/admin/").status_code == 302


def test_session_is_permanent_with_limit(app):
    client = app.test_client()
    login(client)
    with client.session_transaction() as s:
        assert s.permanent
    assert app.config["PERMANENT_SESSION_LIFETIME"] <= timedelta(hours=12)


def test_appeal_interval_shared_between_clients(app):
    form = {"name": "Иван", "message": "Вопрос", "consent": "1"}
    app.test_client().post("/obrashcheniya", data=form)
    r = app.test_client().post("/obrashcheniya", data=form, follow_redirects=True)
    assert "Следующее можно отправить через минуту" in text(r)


# Ошибки и перенаправления
def test_error_pages_styled(tmp_path):
    app = make_app(tmp_path, PROPAGATE_EXCEPTIONS=False)

    @app.route("/boom")
    def boom():
        raise RuntimeError("сбой")

    r = app.test_client().get("/boom")
    assert r.status_code == 500 and "Ошибка на сайте" in text(r) and "RuntimeError" not in text(r)
    r = app.test_client().get("/net-takoy-stranicy")
    assert r.status_code == 404 and "Страница не найдена" in text(r)


def test_trailing_slash_redirects(app):
    r = app.test_client().get("/afisha/?day=2030-12-31")
    assert r.status_code == 301 and r.headers["Location"].endswith("/afisha?day=2030-12-31")
    # Адрес панели со слешем — настоящая страница, его не трогаем
    assert app.test_client().get("/admin/").status_code == 302
    assert app.test_client().get("/net-takogo/").status_code == 404


def test_redirect_table(app, admin):
    admin.post("/admin/redirects", data={"old_path": "https://old-site.ru/afisha.php?id=5", "new_url": "/afisha"})
    with app.app_context():
        assert Redirect.query.one().old_path == "/afisha.php?id=5"
    r = app.test_client().get("/afisha.php?id=5")
    assert r.status_code == 301 and r.headers["Location"].endswith("/afisha")
    with app.app_context():
        assert Redirect.query.one().hits == 1


def test_redirect_rejects_loop_and_bad_target(app, admin):
    for new_url in ("/same", "javascript:alert(1)", "//evil.ru"):
        admin.post("/admin/redirects", data={"old_path": "/same", "new_url": new_url})
    with app.app_context():
        assert Redirect.query.count() == 0


# Производительность
def test_gzip_and_cache_headers(app):
    client = app.test_client()
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers["Content-Encoding"] == "gzip"
    assert "<html" in gzip.decompress(r.get_data()).decode("utf-8")
    assert r.headers["Cache-Control"] == "no-cache" and r.headers.get("ETag")
    assert client.get("/", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304

    css = client.get("/static/css/site.css?v=1", headers={"Accept-Encoding": "gzip"})
    assert "immutable" in css.headers["Cache-Control"] and css.headers["Content-Encoding"] == "gzip"


def test_staff_pages_not_publicly_cacheable(app, admin):
    assert admin.get("/").headers["Cache-Control"].startswith("private")


# Время и поисковики
def test_now_msk_is_utc_plus_3():
    diff = utils.now_msk() - utils.utcnow()
    assert abs(diff - timedelta(hours=3)) < timedelta(seconds=5)


def test_site_url_setting_used_for_absolute_links(tmp_path):
    app = make_app(tmp_path, SITE_URL="https://filarmonia.example")
    client = app.test_client()
    html = text(client.get("/novosti?page=2", headers={"Host": "evil.example"}))
    assert '<link rel="canonical" href="https://filarmonia.example/novosti?page=2">' in html
    assert "evil.example" not in html
    robots = text(client.get("/robots.txt"))
    assert "Sitemap: https://filarmonia.example/sitemap.xml" in robots
    assert "Disallow: /poisk" in robots and "Disallow: /kartochki-afishi" in robots
    assert client.get("/kartochki-afishi").headers["X-Robots-Tag"] == "noindex"


def test_sitemap_skips_old_events(app, admin):
    create_event(admin, title="Давний концерт", starts_at="2020-01-10T19:00")
    create_event(admin)
    xml = text(app.test_client().get("/sitemap.xml"))
    assert "/afisha/testovyy-koncert" in xml and "davniy-koncert" not in xml
    assert "<lastmod>" in xml


# Микроразметка
def _json_ld(html: str) -> list:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_event_json_ld(app, admin):
    create_event(admin, duration_min="90", tickets_left="нет билетов")
    blocks = _json_ld(text(app.test_client().get("/afisha/testovyy-koncert")))
    ev = next(b for b in blocks if b["@type"] == "Event")
    assert ev["startDate"] == "2030-12-31T19:00:00+03:00"
    assert ev["endDate"] == "2030-12-31T20:30:00+03:00"
    assert ev["offers"]["availability"].endswith("SoldOut")
    crumbs = next(b for b in blocks if b["@type"] == "BreadcrumbList")
    assert [i["name"] for i in crumbs["itemListElement"]] == ["Главная", "Афиша", "Тестовый концерт"]


def test_home_organization_json_ld(app):
    blocks = _json_ld(text(app.test_client().get("/")))
    types = {b["@type"] for b in blocks}
    assert {"PerformingArtsTheater", "WebSite"} <= types


def test_news_json_ld(app, admin):
    admin.post("/admin/news/new", data={"title": "Открытие сезона", "lead": "Анонс", "publish": "1"},
               content_type="multipart/form-data")
    blocks = _json_ld(text(app.test_client().get("/novosti/otkrytie-sezona")))
    article = next(b for b in blocks if b["@type"] == "NewsArticle")
    assert article["headline"] == "Открытие сезона" and article["datePublished"].endswith("+03:00")


def test_postal_address_parsing():
    from filarmonia.schema import postal_address

    addr = postal_address("214000, г. Смоленск, ул. Глинки, д. 3")
    assert addr["postalCode"] == "214000" and addr["streetAddress"] == "ул. Глинки, д. 3"
    assert addr["addressLocality"] == "Смоленск"

