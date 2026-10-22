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


def site_url_from_env() -> str:
    """Адрес сайта из SITE_URL, а на Render — из переменных, которые выставляет он сам."""
    explicit = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not render_url and os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        render_url = "https://" + os.environ["RENDER_EXTERNAL_HOSTNAME"].strip()
    return render_url


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
        "MAX_CONTENT_LENGTH": 64 * 1024 * 1024,  # 64 МБ на одну отправку формы
        "ALLOWED_IMAGE_EXT": ALLOWED_IMAGE_EXT,
        "ALLOWED_VIDEO_EXT": ALLOWED_VIDEO_EXT,
        "ALLOWED_DOC_EXT": ALLOWED_DOC_EXT,
        # Предел одного файла по видам, МБ. Подсказки в формах берутся отсюда
        "UPLOAD_LIMITS_MB": {"image": 20, "video": 60, "doc": 30},
        # Фото крупнее по длинной стороне не принимаются: такие бывают только у
        # склеенных панорам, а на сайте всё равно ужимаются до IMAGE_MAX_SIDE
        "IMAGE_UPLOAD_MAX_SIDE": 8000,

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

        # Пауза между отправками одной анкеты «Независимой оценки» с одного адреса
        "SURVEY_INTERVAL_SECONDS": int(os.environ.get("SURVEY_INTERVAL_SECONDS", "15")),

        # Исходящая почта (ответы на анкеты уходят письмом). Пустой MAIL_SERVER —
        # письма не отправляются, ответы только сохраняются в базе.
        "MAIL_SERVER": os.environ.get("MAIL_SERVER", ""),
        "MAIL_PORT": int(os.environ.get("MAIL_PORT", "465")),
        "MAIL_USE_SSL": bool(int(os.environ.get("MAIL_USE_SSL", "1"))),
        "MAIL_USE_TLS": bool(int(os.environ.get("MAIL_USE_TLS", "0"))),
        "MAIL_USERNAME": os.environ.get("MAIL_USERNAME", ""),
        "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD", ""),
        "MAIL_FROM": os.environ.get("MAIL_FROM", ""),
        "MAIL_TIMEOUT": int(os.environ.get("MAIL_TIMEOUT", "5")),
        # 1 — письмо уходит в фоновом потоке, посетитель не ждёт почтовый сервер
        "MAIL_ASYNC": bool(int(os.environ.get("MAIL_ASYNC", "1"))),

        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # На боевом сервере с HTTPS выставить SESSION_COOKIE_SECURE=1
        "SESSION_COOKIE_SECURE": bool(int(os.environ.get("SESSION_COOKIE_SECURE", "0"))),

        # За обратным прокси (nginx, render.com) протокол и адрес клиента
        # приходят в заголовках X-Forwarded-*. Включать только там, где перед
        # приложением действительно стоит доверенный прокси.
        "TRUST_PROXY": bool(int(os.environ.get("TRUST_PROXY", "0"))),

        # Запрет индексации: на все ответы ставится заголовок X-Robots-Tag: noindex, nofollow,
        # в шаблон добавляется <meta name="robots" content="noindex">. Нужно для
        # тестовых копий сайта, чтобы они не попадали в поиск.
        "SITE_NOINDEX": bool(int(os.environ.get("SITE_NOINDEX", "0"))),

        # Тестовый стенд (SITE_NOINDEX=1): если заданы оба, весь сайт закрыт паролем (basic-auth).
        # Без них стенд открыт, поэтому приём обращений и анкет на нём отключается.
        "STAND_USER": os.environ.get("STAND_USER", ""),
        "STAND_PASSWORD": os.environ.get("STAND_PASSWORD", ""),

        # Адрес сайта для канонических ссылок, карты сайта и микроразметки,
        # например https://smolensk-filarmonia.ru. Пусто — адрес берётся из запроса
        # (годится для разработки; на боевом сервере задать обязательно).
        # Если не задан, берётся адрес, который сообщает Render (RENDER_EXTERNAL_URL).
        "SITE_URL": site_url_from_env(),

        # Сеанс сотрудника: не дольше рабочего дня и до часа без действий
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=int(os.environ.get("SESSION_HOURS", "8"))),
        "SESSION_IDLE_SECONDS": int(os.environ.get("SESSION_IDLE_MINUTES", "60")) * 60,

        # Сжатие ответов самим приложением. За nginx с gzip можно выключить (0)
        "COMPRESS_RESPONSES": bool(int(os.environ.get("COMPRESS_RESPONSES", "1"))),

        # Файл журнала с ротацией. Пусто — журнал только в поток ошибок
        "LOG_FILE": os.environ.get("LOG_FILE", ""),
    }
    # Задан ли адрес руками (а не взят у Render): от этого зависит предупреждение
    # о боевом SITE_URL на закрытой от поисковиков копии, см. filarmonia.check_site_url
    config["SITE_URL_EXPLICIT"] = bool(
        os.environ.get("SITE_URL", "").strip() or overrides.get("SITE_URL"))
    config.update(overrides)
    return config
