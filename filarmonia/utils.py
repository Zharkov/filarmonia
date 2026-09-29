"""Вспомогательные функции: адреса страниц, даты, загрузка файлов, видео."""
import os
import re
import secrets
from datetime import datetime

from flask import current_app
from werkzeug.utils import secure_filename

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
MONTHS_NOM = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def slugify(text: str, existing_check=None) -> str:
    """Латинский адрес страницы из русского заголовка."""
    text = (text or "").strip().lower()
    out = "".join(TRANSLIT.get(ch, ch) for ch in text)
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")[:180] or "page"
    if existing_check is None:
        return out
    candidate, n = out, 2
    while existing_check(candidate):
        candidate = f"{out}-{n}"
        n += 1
    return candidate


# Даты
def ru_date(value, with_year: bool = True) -> str:
    """«28 августа 2026»."""
    if not value:
        return ""
    s = f"{value.day} {MONTHS_GEN[value.month - 1]}"
    return f"{s} {value.year}" if with_year else s


def ru_datetime(value) -> str:
    """«28 августа 2026, 19:00»."""
    if not value:
        return ""
    return f"{ru_date(value)}, {value:%H:%M}"


def ru_weekday(value, short: bool = False) -> str:
    if not value:
        return ""
    return (WEEKDAYS_SHORT if short else WEEKDAYS)[value.weekday()]


def ru_month(value, nominative: bool = True) -> str:
    if not value:
        return ""
    return (MONTHS_NOM if nominative else MONTHS_GEN)[value.month - 1]


def ru_duration(minutes) -> str:
    if not minutes:
        return ""
    h, m = divmod(int(minutes), 60)
    parts = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    return " ".join(parts)


# Файлы
def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def save_upload(file_storage, kinds=("image",)) -> str:
    """Сохраняет файл в каталог загрузок, возвращает имя файла.

    Имя файла делается уникальным, расширение проверяется по белому списку.
    """
    if not file_storage or not file_storage.filename:
        return ""
    ext = _ext(file_storage.filename)
    allowed = set()
    cfg = current_app.config
    if "image" in kinds:
        allowed |= cfg["ALLOWED_IMAGE_EXT"]
    if "video" in kinds:
        allowed |= cfg["ALLOWED_VIDEO_EXT"]
    if "doc" in kinds:
        allowed |= cfg["ALLOWED_DOC_EXT"]
    if ext not in allowed:
        raise ValueError(f"Недопустимый тип файла: .{ext}")

    base = slugify(secure_filename(file_storage.filename).rsplit(".", 1)[0])[:60] or "file"
    name = f"{base}-{secrets.token_hex(4)}.{ext}"
    folder = cfg["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, name))
    return name


def file_size_kb(filename: str) -> int:
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    try:
        return max(1, round(os.path.getsize(path) / 1024))
    except OSError:
        return 0


# Видео
def video_embed(url: str) -> str:
    """Превращает ссылку на видео в код проигрывателя.

    Поддержаны VK Видео, RuTube, Дзен, YouTube и прямые ссылки на mp4/webm.
    Если формат не распознан, возвращается пустая строка — тогда шаблон
    покажет обычную ссылку.
    """
    url = (url or "").strip()
    if not url:
        return ""

    # VK Видео: https://vk.com/video-123456_789 или vkvideo.ru/video-123_456
    m = re.search(r"(?:vk\.com|vkvideo\.ru|vk\.ru)/video(-?\d+)_(\d+)", url)
    if m:
        return (
            f'<iframe src="https://vk.com/video_ext.php?oid={m.group(1)}'
            f'&id={m.group(2)}&hd=2" allow="autoplay; encrypted-media; fullscreen"'
            ' allowfullscreen frameborder="0"></iframe>'
        )
    if "vk.com/video_ext.php" in url or "vkvideo.ru/video_ext.php" in url:
        return f'<iframe src="{url}" allowfullscreen frameborder="0"></iframe>'

    # RuTube: https://rutube.ru/video/<id>/
    m = re.search(r"rutube\.ru/(?:video|play/embed)/([0-9a-f]{32})", url)
    if m:
        return (
            f'<iframe src="https://rutube.ru/play/embed/{m.group(1)}"'
            ' allow="clipboard-write; autoplay" allowfullscreen frameborder="0"></iframe>'
        )

    # Дзен / Видео Дзен
    m = re.search(r"dzen\.ru/(?:video/)?(?:watch|embed)/([\w-]+)", url)
    if m:
        return (
            f'<iframe src="https://dzen.ru/embed/{m.group(1)}"'
            ' allow="autoplay; fullscreen" allowfullscreen frameborder="0"></iframe>'
        )

    # YouTube
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})", url)
    if m:
        return (
            f'<iframe src="https://www.youtube.com/embed/{m.group(1)}"'
            ' allow="accelerometer; clipboard-write; encrypted-media; picture-in-picture"'
            ' allowfullscreen frameborder="0"></iframe>'
        )

    # Прямая ссылка на файл
    if re.search(r"\.(mp4|webm)(\?|$)", url, re.I):
        return f'<video controls preload="metadata" src="{url}"></video>'

    return ""


def parse_dt(value: str):
    """Разбирает datetime-local из формы."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def strip_tags(html: str, limit: int = 200) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def group_by_category(rows) -> dict:
    """Раскладывает документы по категориям, сохраняя порядок запроса."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row.category or "Прочее", []).append(row)
    return grouped
