"""Всё, что сайт делает с запросом и ответом помимо самих страниц.

Заголовки безопасности, сжатие, кэширование, страницы ошибок, журнал,
перенаправления со старых адресов и абсолютный адрес сайта.
"""
import gzip
import logging
import os
import time
from logging.handlers import RotatingFileHandler

from flask import current_app, g, redirect, render_template, request, session
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

from .models import db, Redirect

# Политика для панели администратора: свои скрипты и стили, картинки и фреймы
# по https (предпросмотр видео, карты). Встраивать панель в чужие сайты нельзя.
ADMIN_CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    # Визуальный редактор расставляет стили прямо в разметке
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "media-src 'self' https:",
    "font-src 'self' data:",
    "frame-src https:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))

# Сайт для посетителей: строгая часть, которая не мешает виджетам
PUBLIC_CSP = "; ".join((
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",
))

# Полная политика сайта пока только наблюдает (Report-Only): администратор
# вставляет коды виджетов Госуслуг и карт, и их источники нужно сначала
# собрать по отчётам браузеров в журнале, а потом включить запрет.
PUBLIC_CSP_REPORT = "; ".join((
    "default-src 'self'",
    "script-src 'self' https://widget.afisha.yandex.ru https://*.yandex.ru https://*.yandex.net "
    "https://pos.gosuslugi.ru https://*.gosuslugi.ru",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "media-src 'self' https:",
    "font-src 'self' data:",
    "frame-src https:",
    "connect-src 'self' https:",
    "report-uri /csp-report",
))

# Адреса, которые не должны попадать в поиск: куски разметки для скриптов
# и результаты поиска по сайту
NOINDEX_ENDPOINTS = {"public.more_cards", "public.route", "public.search", "csp_report"}

# Что сжимать: текст. Картинки, видео и шрифты WOFF2 уже сжаты.
COMPRESSIBLE = ("text/", "application/javascript", "application/json", "application/xml",
                "image/svg+xml")
COMPRESS_MIN_BYTES = 1024

# Год: адрес версионной статики меняется при каждом её обновлении,
# имена загруженных файлов уникальны
IMMUTABLE = "public, max-age=31536000, immutable"

ERROR_TEXTS = {
    403: ("Нет доступа", "У вас нет прав на эту страницу."),
    404: ("Страница не найдена", "Возможно, адрес изменился или страница удалена."),
    405: ("Действие недоступно", "Эту страницу нельзя открыть таким способом."),
    413: ("Файл слишком большой", "Размер загрузки — не больше 64 МБ. Уменьшите файл и повторите."),
    500: ("Ошибка на сайте", "Мы уже знаем о ней и исправим. Попробуйте обновить страницу позже."),
}


def init_app(app) -> None:
    setup_logging(app)

    @app.before_request
    def end_idle_session():
        """Сеанс сотрудника завершается после часа бездействия.

        Отметку времени обновляем не чаще раза в минуту, чтобы не отдавать
        новую куку на каждый запрос.
        """
        if "user_id" not in session:
            return
        now = time.time()
        seen = session.get("seen", now)
        if now - seen > app.config["SESSION_IDLE_SECONDS"]:
            session.clear()
            return
        if now - seen > 60 or "seen" not in session:
            session["seen"] = now

    @app.after_request
    def finish(response):
        if request.endpoint in NOINDEX_ENDPOINTS:
            response.headers["X-Robots-Tag"] = "noindex"
        security_headers(response)
        cache_headers(response)
        compress(response)
        return response

    @app.route("/csp-report", methods=["POST"])
    def csp_report():
        """Браузер сообщает, что ресурс нарушил бы политику безопасности."""
        body = request.get_data(cache=False, as_text=True)[:2000]
        app.logger.warning("CSP: %s", body)
        return "", 204

    app.extensions["csrf"].exempt(csp_report)

    for code in (403, 405, 413):
        app.register_error_handler(code, error_page)

    @app.errorhandler(404)
    def not_found(error):
        return redirect_for_missing() or error_page(error)

    @app.errorhandler(500)
    def server_error(error):
        user = g.get("user")
        app.logger.error("Ошибка 500: %s %s, пользователь %s", request.method, request.url,
                         user.login if user else "—")
        return error_page(error)

    @app.context_processor
    def absolute_urls():
        return {"site_url": site_url}


def error_page(error):
    code = getattr(error, "code", 500) or 500
    title, text = ERROR_TEXTS.get(code, ERROR_TEXTS[500])
    return render_template("public/error.html", code=code, title=title, text=text), code


def redirect_for_missing():
    """Для несуществующего адреса — постоянное перенаправление, если оно есть.

    1. Адрес из таблицы перенаправлений (старый сайт, переименованная страница).
    2. Тот же адрес без слеша в конце: «/afisha/» -> «/afisha».
    """
    if request.method not in ("GET", "HEAD"):
        return None
    path = request.path
    row = Redirect.query.filter_by(old_path=path).first()
    if row is None and request.query_string:
        row = Redirect.query.filter_by(old_path=request.full_path.rstrip("?")).first()
    if row is not None:
        row.hits = (row.hits or 0) + 1
        db.session.commit()
        return redirect(row.new_url, 301)

    if len(path) > 1 and path.endswith("/"):
        target = path.rstrip("/")
        adapter = current_app.url_map.bind("")
        try:
            adapter.match(target, method="GET")
        except RequestRedirect:
            pass
        except (NotFound, MethodNotAllowed):
            return None
        query = request.query_string.decode("latin-1")
        return redirect(target + ("?" + query if query else ""), 301)
    return None


def site_url(path: str = "") -> str:
    """Абсолютный адрес на сайте.

    Берётся из настройки SITE_URL, а не из заголовка Host: иначе подставленный
    в запрос чужой домен попал бы в канонический адрес, карту сайта и разметку.
    Без настройки (разработка) — адрес из запроса.
    """
    base = (current_app.config.get("SITE_URL") or request.host_url).rstrip("/")
    if path and not path.startswith("/"):
        path = "/" + path
    return base + path


def security_headers(response) -> None:
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config["SESSION_COOKIE_SECURE"]:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if not response.mimetype == "text/html":
        return
    if request.path.startswith("/admin"):
        headers.setdefault("Content-Security-Policy", ADMIN_CSP)
        headers.setdefault("X-Frame-Options", "DENY")
    else:
        headers.setdefault("Content-Security-Policy", PUBLIC_CSP)
        headers.setdefault("Content-Security-Policy-Report-Only", PUBLIC_CSP_REPORT)
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")


def cache_headers(response) -> None:
    """Статика с версией и загрузки — на год; страницы — с проверкой по ETag."""
    path = request.path
    if path.startswith("/static/"):
        if response.status_code == 200 and (path.startswith("/static/uploads/") or request.args.get("v")):
            response.headers["Cache-Control"] = IMMUTABLE
        return
    if request.method != "GET" or response.status_code != 200 or response.mimetype != "text/html":
        return
    if response.direct_passthrough or response.is_streamed:
        return
    # Страница сотрудника (ссылки «Редактировать», черновики) не должна попасть в общий кэш
    private = g.get("user") is not None or "_flashes" in session
    response.headers["Cache-Control"] = "private, no-cache" if private else "no-cache"
    response.add_etag(weak=True)
    response.make_conditional(request)


def compress(response) -> None:
    """Сжатие gzip, если перед сайтом нет nginx, который сожмёт сам."""
    if not current_app.config["COMPRESS_RESPONSES"]:
        return
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return
    if response.status_code != 200 or "Content-Encoding" in response.headers:
        return
    if not (response.mimetype or "").startswith(COMPRESSIBLE):
        return
    if response.is_streamed and not response.direct_passthrough:
        return
    response.direct_passthrough = False
    data = response.get_data()
    if len(data) < COMPRESS_MIN_BYTES:
        return
    response.set_data(gzip.compress(data, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")


def setup_logging(app) -> None:
    """Журнал сайта: поток ошибок (его собирает systemd или Render) и,
    если задан LOG_FILE, файл с ротацией по 5 МБ."""
    if app.testing:
        return
    level = logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_file = app.config.get("LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(fmt)
        handler.setLevel(level)
        app.logger.addHandler(handler)
    app.logger.setLevel(level)
