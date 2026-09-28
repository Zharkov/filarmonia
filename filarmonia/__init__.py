"""Сайт Смоленской областной филармонии. Фабрика приложения."""
import os
from datetime import datetime

from flask import Flask, render_template, g, session
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

from config import build_config
from .models import db, Setting, MenuItem, User
from . import utils

# Фильтры шаблонов: имя в Jinja -> функция из utils
JINJA_FILTERS = {
    "ru_date": utils.ru_date,
    "ru_datetime": utils.ru_datetime,
    "ru_weekday": utils.ru_weekday,
    "ru_month": utils.ru_month,
    "ru_duration": utils.ru_duration,
    "strip_tags": utils.strip_tags,
    "video_embed": lambda url: Markup(utils.video_embed(url)),
}


def create_app(**config_overrides) -> Flask:
    """Собирает приложение. Именованные аргументы перекрывают настройки окружения."""
    app = Flask(__name__)
    app.config.from_mapping(build_config(**config_overrides))
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    if app.config["TRUST_PROXY"]:
        # Один прокси перед приложением: без этого sitemap.xml и robots.txt
        # подставляли бы http:// вместо https://
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    app.jinja_env.filters.update(JINJA_FILTERS)

    from .public import bp as public_bp
    from .admin import bp as admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.context_processor
    def inject_globals():
        """Данные, доступные во всех шаблонах."""
        return {
            "settings": {row.key: row.value for row in Setting.query.all()},
            "main_menu": (
                MenuItem.query.filter_by(parent_id=None, is_published=True)
                .order_by(MenuItem.sort)
                .all()
            ),
            "now": datetime.now(),
            "current_user": g.get("user"),
        }

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = db.session.get(User, user_id) if user_id else None

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("public/404.html"), 404

    return app
