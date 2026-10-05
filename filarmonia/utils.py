"""Вспомогательные функции: адреса страниц, даты, загрузка файлов, видео."""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import nh3
from flask import current_app
from markupsafe import Markup
from sqlalchemy import func
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
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def utcnow() -> datetime:
    """Текущее время UTC без часового пояса.

    Замена `datetime.utcnow()`, которая объявлена устаревшей и будет удалена.
    Пояс срезаем намеренно: колонки в базе объявлены без него, а часть дат
    (начало концерта) приходит из формы тоже без пояса — смешивать нельзя.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def to_moscow(value):
    """Время из базы (UTC) — в московское, для показа сотрудникам."""
    return value + timedelta(hours=3) if value else value


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


def ru_month_short(value) -> str:
    """«апр» — для отметки даты на карточке концерта."""
    return MONTHS_SHORT[value.month - 1] if value else ""


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

    # slugify до secure_filename: тот вырезает кириллицу целиком, и от имени
    # «Снимок с концерта.jpg» оставалось бы только расширение
    stem = file_storage.filename.rsplit(".", 1)[0]
    base = secure_filename(slugify(stem))[:60] or "file"
    name = f"{base}-{secrets.token_hex(4)}.{ext}"
    folder = cfg["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    file_storage.save(path)
    if ext in cfg["ALLOWED_IMAGE_EXT"]:
        shrink_image(path)
        make_variants(path)
    return name


# Уменьшенные копии фото. Карточка концерта на экране шириной около 400 px,
# а оригинал ужат только до 2000: без копий браузер качал бы его целиком.
VARIANT_WIDTHS = (400, 800)


def variant_name(name: str, width: int) -> str:
    """«foto-1a2b.jpg» -> «foto-1a2b-400w.webp»."""
    return f"{name.rsplit('.', 1)[0]}-{width}w.webp"


def make_variants(path: str) -> int:
    """Сохраняет рядом с фото копии шириной 400 и 800 px в WebP.

    Копию шире оригинала не делаем — она была бы просто тяжелее.
    GIF не трогаем, чтобы не потерять анимацию. Возвращает число созданных копий.
    """
    from PIL import Image, UnidentifiedImageError

    made = 0
    try:
        with Image.open(path) as img:
            if img.format == "GIF":
                return 0
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            folder, name = os.path.split(path)
            for width in VARIANT_WIDTHS:
                target = os.path.join(folder, variant_name(name, width))
                if img.width <= width or os.path.exists(target):
                    continue
                copy = img.copy()
                copy.thumbnail((width, width * 10))
                copy.save(target, "WEBP", quality=current_app.config["IMAGE_QUALITY"], method=4)
                made += 1
    except (OSError, UnidentifiedImageError, ValueError) as error:
        print(f"Не удалось сделать копии {os.path.basename(path)}: {error}")
    return made


@lru_cache(maxsize=2048)
def _srcset_for(name: str, mtime: float, folder: str) -> str:
    """Строка srcset для файла; кэш по времени изменения файла."""
    from PIL import Image

    parts = [
        f"{UPLOADS_PREFIX}{variant_name(name, w)} {w}w"
        for w in VARIANT_WIDTHS
        if os.path.exists(os.path.join(folder, variant_name(name, w)))
    ]
    if not parts:
        return ""
    try:
        with Image.open(os.path.join(folder, name)) as img:
            parts.append(f"{UPLOADS_PREFIX}{name} {img.width}w")
    except OSError:
        pass
    return ", ".join(parts)


UPLOADS_PREFIX = "/static/uploads/"


def srcset(url: str) -> str:
    """Фильтр шаблона: для фото из загрузок — набор копий разной ширины.

    Пустая строка, если копий нет (старое фото, внешняя ссылка): тогда
    браузер просто берёт адрес из src.
    """
    if not url or not url.startswith(UPLOADS_PREFIX):
        return ""
    name = url[len(UPLOADS_PREFIX):]
    folder = current_app.config["UPLOAD_FOLDER"]
    try:
        mtime = os.path.getmtime(os.path.join(folder, name))
    except OSError:
        return ""
    return _srcset_for(name, mtime, folder)


def delete_uploads(names) -> int:
    """Удаляет файлы из каталога загрузок вместе с их уменьшенными копиями.

    Имена с путём («../x») не принимаются: удалить можно только файл
    непосредственно в каталоге загрузок. Возвращает число удалённых файлов.
    """
    folder = current_app.config["UPLOAD_FOLDER"]
    removed = 0
    for name in {n for n in names if n}:
        if os.path.basename(name) != name:
            continue
        for candidate in [name] + [variant_name(name, w) for w in VARIANT_WIDTHS]:
            try:
                os.remove(os.path.join(folder, candidate))
                removed += 1
            except OSError:
                pass
    return removed


# Очистка HTML из админки: оставляем разметку текста, вырезаем скрипты,
# обработчики событий и javascript:-ссылки. Код виджетов (схема зала, карта,
# «Решаем вместе») сюда не попадает — его вводит только администратор.
SAFE_TAGS = {
    "p", "br", "hr", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "ul", "ol", "li", "blockquote", "a", "img", "figure", "figcaption", "span", "div",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
}
SAFE_ATTRS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan", "scope"},
    "col": {"span"}, "colgroup": {"span"},
}


def clean_html(html: str) -> str:
    """Безопасная разметка из текста, введённого в админке."""
    if not html:
        return ""
    return nh3.clean(
        html, tags=SAFE_TAGS, attributes=SAFE_ATTRS,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener",
    ).strip()


# Поиск без учёта регистра и без различия «е» и «ё»
def search_norm(text: str) -> str:
    return (text or "").strip().lower().replace("ё", "е")


def like_ci(column, text: str):
    """Условие «колонка содержит текст»: регистр и «ё» не важны.

    Знаки % и _ из запроса экранируются — иначе «100%» искало бы что угодно.
    """
    pattern = search_norm(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.replace(func.lower(column), "ё", "е").like(f"%{pattern}%", escape="\\")


def shrink_image(path: str) -> None:
    """Ужимает загруженную фотографию до разумного размера.

    Снимок с телефона — это 4000 px и 8-12 МБ, а в вёрстке фотографии нигде
    не крупнее 2000 px: без этого посетитель скачивал бы оригинал целиком,
    чтобы браузер уменьшил его до размера плитки в галерее.

    Картинку, которую Pillow не смог открыть или пересохранить, оставляем
    как есть: загрузка не должна срываться из-за неудачной оптимизации.
    """
    from PIL import Image, UnidentifiedImageError

    cfg = current_app.config
    side = cfg["IMAGE_MAX_SIDE"]
    try:
        with Image.open(path) as img:
            img.load()
            # GIF не трогаем: пересохранение убило бы анимацию
            if img.format == "GIF" or (img.width <= side and img.height <= side):
                return
            fmt = img.format
            # Прозрачность у JPEG невозможна, поэтому режим сводим только для него
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((side, side))
            img.save(path, fmt, quality=cfg["IMAGE_QUALITY"], optimize=True)
    except (OSError, UnidentifiedImageError, ValueError) as error:
        print(f"Не удалось ужать {os.path.basename(path)}: {error}")


def file_size_kb(filename: str) -> int:
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    try:
        return max(1, round(os.path.getsize(path) / 1024))
    except OSError:
        return 0


# Видео
def _tag(template: str, *values) -> str:
    """Собирает кусок разметки, экранируя подставляемые значения.

    Нужен там, где в атрибут идёт введённый редактором адрес целиком: без
    экранирования кавычка в адресе закрыла бы атрибут, и остаток строки стал бы
    обработчиком события. Результат попадает в базу и выводится через `| safe`,
    так что подставлять сырую строку нельзя.
    """
    return str(Markup(template).format(*values))


def video_embed(url: str) -> str:
    """Превращает ссылку на видео в код проигрывателя.

    Поддержаны VK Видео, RuTube, Дзен, YouTube и прямые ссылки на mp4/webm.
    Если формат не распознан, возвращается пустая строка — тогда шаблон
    покажет обычную ссылку.

    Ветки с разбором адреса подставляют только группы регулярного выражения
    (цифры и латиница), адрес целиком идёт в разметку через `_tag`.
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
        return _tag('<iframe src="{}" allowfullscreen frameborder="0"></iframe>', url)

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
        return _tag('<video controls preload="metadata" src="{}"></video>', url)

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


YANDEX_ID = re.compile(r"[\w.\-]+@\d+")


def yandex_session_id(value: str) -> str:
    """ID сеанса Яндекс Афиши из формы: «ticketsteam-825@496249».

    Редактор может вставить и весь код кнопки из письма Яндекса — ID
    вытаскивается из него. Пусто — пусто; что-то иное — ValueError.
    """
    value = (value or "").strip()
    if not value:
        return ""
    found = YANDEX_ID.search(value)
    if not found:
        raise ValueError("ID сеанса Яндекс Афиши выглядит так: ticketsteam-825@496249.")
    return found.group(0)


def plural(number, one: str, few: str, many: str) -> str:
    """«1 материал», «2 материала», «5 материалов» — число со склонённым словом."""
    number = int(number or 0)
    tail_100 = number % 100
    tail_10 = number % 10
    if 11 <= tail_100 <= 14:
        word = many
    elif tail_10 == 1:
        word = one
    elif 2 <= tail_10 <= 4:
        word = few
    else:
        word = many
    return f"{number} {word}"


def strip_tags(html: str, limit: int = 200) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def compact(value):
    """Убирает пустые значения из словарей и списков, вглубь.

    Нужен микроразметке события: у концерта может не быть площадки, цены
    или организатора, а `null` в JSON-LD только мешает поисковику.
    """
    if isinstance(value, dict):
        cleaned = {k: compact(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v is not None and v != ""}
    if isinstance(value, list):
        return [compact(v) for v in value if v is not None and v != ""]
    return value


def group_by_category(rows) -> dict:
    """Раскладывает документы по категориям, сохраняя порядок запроса."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row.category or "Прочее", []).append(row)
    return grouped
