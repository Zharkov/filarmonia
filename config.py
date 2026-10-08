"""Конфигурация приложения.

Все параметры читаются из переменных окружения, чтобы боевые настройки
не попадали в репозиторий. Значения по умолчанию рассчитаны на локальный запуск.

Настройки собираются функцией, а не константами класса: так переменные
окружения читаются в момент создания приложения, а не при импорте модуля.
Это нужно, например, проверке `python app.py test`, которая поднимает
приложение на временной базе.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Значение-заглушка. Приложение отказывается работать с ним на боевом сервере,
# см. filarmonia.check_secret_key.
INSECURE_SECRET_KEY = "change-me-in-production"

# Расширения, разрешённые к загрузке через панель администратора
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_VIDEO_EXT = {"mp4", "webm"}
ALLOWED_DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "odt", "rtf", "zip"}


def build_config(**overrides) -> dict:
    """Настройки приложения. Именованные аргументы перекрывают окружение."""
    config = {
        "SECRET_KEY": os.environ.get("SECRET_KEY", INSECURE_SECRET_KEY),

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

        # Загруженные фотографии ужимаются до этой стороны и пересохраняются:
        # снимок с телефона весит 8-12 МБ, а в вёрстке нигде не крупнее 2000 px.
        "IMAGE_MAX_SIDE": int(os.environ.get("IMAGE_MAX_SIDE", "2000")),
        "IMAGE_QUALITY": int(os.environ.get("IMAGE_QUALITY", "85")),

        # Защита входа в панель администратора от подбора пароля: сколько неудач подряд
        # с одной пары «логин + адрес» и на сколько секунд после этого запирать.
        "LOGIN_MAX_ATTEMPTS": int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5")),
        "LOGIN_LOCKOUT_SECONDS": int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900")),

        # Пауза между обращениями граждан с одного адреса — от спама.
        "APPEAL_INTERVAL_SECONDS": int(os.environ.get("APPEAL_INTERVAL_SECONDS", "60")),

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

        # Адрес сайта для канонических ссылок, карты сайта и микроразметки,
        # например https://smolensk-filarmonia.ru. Пусто — адрес берётся из запроса
        # (годится для разработки; на боевом сервере задать обязательно).
        "SITE_URL": os.environ.get("SITE_URL", "").rstrip("/"),

        # Сеанс сотрудника: не дольше рабочего дня и до часа без действий
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=int(os.environ.get("SESSION_HOURS", "8"))),
        "SESSION_IDLE_SECONDS": int(os.environ.get("SESSION_IDLE_MINUTES", "60")) * 60,

        # Сжатие ответов самим приложением. За nginx с gzip можно выключить (0)
        "COMPRESS_RESPONSES": bool(int(os.environ.get("COMPRESS_RESPONSES", "1"))),

        # Файл журнала с ротацией. Пусто — журнал только в поток ошибок
        "LOG_FILE": os.environ.get("LOG_FILE", ""),
    }
    config.update(overrides)
    return config
