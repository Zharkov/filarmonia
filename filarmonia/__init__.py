"""Сайт Смоленской областной филармонии. Фабрика приложения."""
import os
import time
from types import SimpleNamespace

from flask import Flask, render_template, g, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from markupsafe import Markup
from sqlalchemy.orm import joinedload
from werkzeug.middleware.proxy_fix import ProxyFix

from config import build_config, INSECURE_SECRET_KEY
from .models import db, Setting, MenuItem, User
from . import schema, utils, web

JINJA_FILTERS = {
    "ru_date": utils.ru_date,
    "ru_datetime": utils.ru_datetime,
    "ru_weekday": utils.ru_weekday,
    "ru_month": utils.ru_month,
    "ru_month_short": utils.ru_month_short,
    "ru_duration": utils.ru_duration,
    "strip_tags": utils.strip_tags,
    "map_point": utils.map_point,
    "plural": utils.plural,
    "compact": utils.compact,
    "video_embed": lambda url: Markup(utils.video_embed(url)),
    "srcset": utils.srcset,
    "msk": utils.to_moscow,
}

# Статика кэшируется браузером надолго: имена загруженных файлов уникальны,
# а к стилям и скриптам дописывается номер версии (см. asset_url).
# Для версионных адресов web.cache_headers поднимает срок до года.
STATIC_MAX_AGE = 30 * 24 * 3600

# Настройки и меню нужны каждой странице. Чтобы не ходить за ними в базу
# на каждый запрос, они хранятся в памяти процесса столько секунд. После
# сохранения в панели процесс, принявший правку, сбрасывает их сразу,
# остальные процессы gunicorn — не позже чем через этот срок.
SITE_DATA_TTL = 30
_site_data = {"expires": 0.0, "settings": {}, "menu": []}


def site_data() -> dict:
    """Настройки и главное меню — из памяти, если они свежие."""
    if time.time() >= _site_data["expires"]:
        items = (
            MenuItem.query.options(
                joinedload(MenuItem.page),
                joinedload(MenuItem.children).joinedload(MenuItem.page),
            )
            .filter_by(parent_id=None, is_published=True)
            .order_by(MenuItem.sort)
            .all()
        )
        # Простые объекты вместо записей базы: те после запроса отвязаны от
        # сессии, и обращение к незагруженному полю обрывало бы страницу
        menu = [
            SimpleNamespace(
                title=item.title, href=item.href, is_published=True,
                children=[SimpleNamespace(title=c.title, href=c.href, is_published=True)
                          for c in sorted(item.children, key=lambda c: (c.sort or 0, c.id))
                          if c.is_published],
            )
            for item in items
        ]
        _site_data.update(
            settings={row.key: row.value for row in Setting.query.all()},
            menu=menu, expires=time.time() + SITE_DATA_TTL,
        )
    return _site_data


def reset_site_data() -> None:
    """Сбросить настройки и меню в памяти — после их правки в панели."""
    _site_data["expires"] = 0.0

csrf = CSRFProtect()


def create_app(**config_overrides) -> Flask:
    """Собирает приложение. Именованные аргументы перекрывают настройки окружения."""
    app = Flask(__name__)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = STATIC_MAX_AGE
    app.config.from_mapping(build_config(**config_overrides))
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    check_secret_key(app)

    if app.config["TRUST_PROXY"]:
        # Один прокси перед приложением: без этого sitemap.xml и robots.txt
        # подставляли бы http:// вместо https://
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    web.init_app(app)
    app.jinja_env.filters.update(JINJA_FILTERS)
    # Микроразметка Schema.org: {{ schema.event(ev, settings) | tojson }}
    app.jinja_env.globals["schema"] = schema

    from .public import bp as public_bp
    from .admin import bp as admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.context_processor
    def inject_globals():
        """Данные, доступные во всех шаблонах."""
        # В проверках у каждого теста своя база, поэтому память не используется
        if app.testing:
            reset_site_data()
        data = site_data()
        return {
            "settings": data["settings"],
            # Подпункты и страницы, на которые ведут пункты, приезжают одним
            # запросом вместе с меню. Иначе адрес каждого пункта подгружался
            # отдельно: 14 лишних запросов к базе на каждой странице сайта.
            "main_menu": data["menu"],
            "now": utils.now_msk(),
            "current_user": g.get("user"),
            "asset_url": asset_url,
        }

    def asset_url(filename: str) -> str:
        """Адрес стиля или скрипта с версией по времени изменения файла.

        Браузер хранит статику месяц; после обновления сайта адрес меняется,
        и посетитель сразу получает новые стили, а не старые из кэша.
        """
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id else None
        # Доступ и права проверяются на каждом запросе, а не только при входе:
        # иначе отключённый сотрудник работал бы в панели администратора до своего выхода
        if user_id and (user is None or not user.is_active):
            session.pop("user_id", None)
            user = None
        g.user = user

    @app.errorhandler(CSRFError)
    def csrf_expired(_error):
        """Форму отправили со страницы, пролежавшей открытой слишком долго."""
        return render_template("public/csrf.html"), 400

    return app


HOWTO_SECRET_KEY = (
    "Сгенерируйте ключ командой\n"
    '  python -c "import secrets; print(secrets.token_hex(32))"\n'
    "и передайте его приложению через переменную окружения SECRET_KEY."
)


def check_secret_key(app: Flask) -> None:
    """Не даёт выйти в интернет с ключом подписи сессий из репозитория.

    С известным ключом кто угодно подделает сессионную куку и войдёт
    администратором. На боевом сервере это обрывает запуск, локально —
    только предупреждает, иначе разработка требовала бы лишних настроек.

    Признак боевого окружения — HTTPS-куки или работа за обратным прокси:
    ровно это задают render.yaml и systemd-юнит из README. Опереться на
    app.debug нельзя: в момент сборки приложения он ещё не выставлен.
    """
    if app.config["SECRET_KEY"] != INSECURE_SECRET_KEY or app.testing:
        return
    if app.config["SESSION_COOKIE_SECURE"] or app.config["TRUST_PROXY"]:
        raise RuntimeError("SECRET_KEY не задан, а сайт настроен как боевой.\n" + HOWTO_SECRET_KEY)
    print("ВНИМАНИЕ: SECRET_KEY из репозитория — годится только для разработки.\n"
          + HOWTO_SECRET_KEY)
