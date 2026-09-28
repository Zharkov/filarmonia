"""Конфигурация приложения.

Все параметры читаются из переменных окружения, чтобы боевые настройки
не попадали в репозиторий. Значения по умолчанию рассчитаны на локальный запуск.

Настройки собираются функцией, а не константами класса: так переменные
окружения читаются в момент создания приложения, а не при импорте модуля.
Это нужно, например, проверке `python app.py test`, которая поднимает
приложение на временной базе.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Расширения, разрешённые к загрузке через админку
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_VIDEO_EXT = {"mp4", "webm"}
ALLOWED_DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "odt", "rtf", "zip"}


def build_config(**overrides) -> dict:
    """Настройки приложения. Именованные аргументы перекрывают окружение."""
    config = {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "change-me-in-production"),

        # SQLite по умолчанию; для боевого сервера задать DATABASE_URL вида
        # postgresql+psycopg://user:pass@localhost/filarmonia
        "SQLALCHEMY_DATABASE_URI": os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "filarmonia.db")
        ),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},

        "UPLOAD_FOLDER": os.environ.get(
            "UPLOAD_FOLDER", os.path.join(BASE_DIR, "filarmonia", "static", "uploads")
        ),
        "MAX_CONTENT_LENGTH": 64 * 1024 * 1024,  # 64 МБ на загрузку
        "ALLOWED_IMAGE_EXT": ALLOWED_IMAGE_EXT,
        "ALLOWED_VIDEO_EXT": ALLOWED_VIDEO_EXT,
        "ALLOWED_DOC_EXT": ALLOWED_DOC_EXT,

        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # На боевом сервере с HTTPS выставить SESSION_COOKIE_SECURE=1
        "SESSION_COOKIE_SECURE": bool(int(os.environ.get("SESSION_COOKIE_SECURE", "0"))),

        # За обратным прокси (nginx, render.com) протокол и адрес клиента
        # приходят в заголовках X-Forwarded-*. Включать только там, где перед
        # приложением действительно стоит доверенный прокси.
        "TRUST_PROXY": bool(int(os.environ.get("TRUST_PROXY", "0"))),

        # Запрет индексации: robots.txt закрывает сайт целиком, в шаблон
        # добавляется <meta name="robots" content="noindex">. Нужно для
        # тестовых копий сайта, чтобы они не попадали в поиск.
        "SITE_NOINDEX": bool(int(os.environ.get("SITE_NOINDEX", "0"))),
    }
    config.update(overrides)
    return config
