"""Вспомогательные функции: адреса страниц, даты, загрузка файлов, видео."""
import html as htmllib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit, urlunsplit

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


# Смоленск живёт по московскому времени, а оно с 2014 года без перехода
# на летнее: UTC+3. Фиксированное смещение не требует базы часовых поясов,
# которой нет в Windows без пакета tzdata.
MSK = timezone(timedelta(hours=3), "MSK")


def now_msk() -> datetime:
    """Текущее московское время без пояса — в той же шкале, что и даты концертов.

    Вместо `datetime.now()`: то показывает часы сервера, а на сервере в UTC
    прошедший концерт ещё три часа висел бы в афише как предстоящий.
    """
    return datetime.now(MSK).replace(tzinfo=None)


def iso_msk(value) -> str:
    """Дата концерта для микроразметки: «2026-10-10T18:30:00+03:00»."""
    return value.replace(tzinfo=MSK).isoformat() if value else ""


def utcnow() -> datetime:
    """Текущее время UTC без часового пояса.

    Замена `datetime.utcnow()`, которая объявлена устаревшей и будет удалена.
    Пояс срезаем намеренно: колонки в базе объявлены без него, а часть дат
    (начало концерта) приходит из формы тоже без пояса — смешивать нельзя.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc(value):
    """Московское время без пояса (дата концерта, дата публикации новости) — в UTC без пояса,
    в шкалу полей updated_at и заголовка Last-Modified."""
    return value - timedelta(hours=3) if value else value


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


UPLOAD_KINDS = ("image", "video", "doc")
UPLOAD_EXT_ORDER = ("jpg", "jpeg", "png", "webp", "gif", "mp4", "webm",
                    "pdf", "doc", "docx", "xls", "xlsx", "odt", "rtf", "zip")


def _kind_ext(kind: str) -> set:
    return current_app.config[f"ALLOWED_{kind.upper()}_EXT"]


def _kind_of(ext: str, kinds) -> str:
    """Вид файла по расширению: image, video или doc; пусто — не разрешён."""
    return next((k for k in UPLOAD_KINDS if k in kinds and ext in _kind_ext(k)), "")


def _ext_list(exts) -> str:
    """«JPG, PNG, WebP, GIF» — расширения для подсказки, jpeg не повторяем."""
    names = {"webp": "WebP", "webm": "WebM"}
    return ", ".join(names.get(e, e.upper()) for e in UPLOAD_EXT_ORDER if e in exts and e != "jpeg")


def upload_rules(kinds=("image",)) -> dict:
    """Ограничения поля загрузки для формы: accept, предел в МБ и текст подсказки.

    «Картинки: JPG, PNG, WebP, GIF · до 20 МБ · до 8000 px по длинной стороне».
    """
    cfg = current_app.config
    limits = cfg["UPLOAD_LIMITS_MB"]
    labels = {"image": "Фото", "video": "Видео", "doc": "Документы"}
    exts, parts = set(), []
    for kind in UPLOAD_KINDS:
        if kind not in kinds:
            continue
        exts |= _kind_ext(kind)
        text = f"{_ext_list(_kind_ext(kind))} · до {limits[kind]} МБ"
        if kind == "image":
            text += f" · до {cfg['IMAGE_UPLOAD_MAX_SIDE']} px по длинной стороне"
        parts.append(f"{labels[kind]}: {text}" if len(kinds) > 1 else text)
    return {
        "accept": ",".join(f".{e}" for e in UPLOAD_EXT_ORDER if e in exts),
        "max_mb": max(limits[k] for k in kinds),
        "limits": {e: limits[_kind_of(e, kinds)] for e in exts},
        "total_mb": cfg["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "text": "; ".join(parts) + ".",
    }


def _file_size(file_storage) -> int:
    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def save_upload(file_storage, kinds=("image",)) -> str:
    """Сохраняет файл в каталог загрузок, возвращает имя файла.

    Имя файла делается уникальным, расширение проверяется по белому списку,
    размер — по пределу для своего вида (UPLOAD_LIMITS_MB).
    """
    if not file_storage or not file_storage.filename:
        return ""
    ext = _ext(file_storage.filename)
    cfg = current_app.config
    kind = _kind_of(ext, kinds)
    if not kind:
        raise ValueError(f"Недопустимый тип файла: .{ext}. Допустимые типы: "
                         f"{_ext_list(set().union(*(_kind_ext(k) for k in kinds)))}.")
    limit_mb = cfg["UPLOAD_LIMITS_MB"][kind]
    if _file_size(file_storage) > limit_mb * 1024 * 1024:
        raise ValueError(f"Размер файла «{file_storage.filename}» превышает {limit_mb} МБ.")

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
        try:
            check_image(path)
        except ValueError:
            os.remove(path)
            raise
        shrink_image(path)
        make_variants(path)
    return name


# Форматы, которые разбирает Pillow при загрузке. Формат он определяет по
# содержимому, а не по расширению: без списка файл PSD или PDF, названный .jpg,
# прошёл бы проверку расширения и попал в декодер редкого формата — именно
# в таких декодерах находят большинство уязвимостей.
IMAGE_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")
# Защита от «бомб»: картинки, которая весит килобайты, а в памяти занимает гигабайты.
# 8000 × 8000 — самое крупное фото, которое пропускает IMAGE_UPLOAD_MAX_SIDE
MAX_IMAGE_PIXELS = 64_000_000


def _pil():
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    return Image


def check_image(path: str) -> None:
    """Убеждается, что файл — картинка одного из разрешённых форматов и не крупнее предела."""
    Image = _pil()
    max_side = current_app.config["IMAGE_UPLOAD_MAX_SIDE"]
    too_big = f"Размер изображения превышает {max_side} px по длинной стороне."
    try:
        with Image.open(path, formats=IMAGE_FORMATS) as img:
            size = img.size
            img.verify()
    except Image.DecompressionBombError:
        raise ValueError(too_big)
    except Exception:
        raise ValueError("Файл не распознан как изображение JPEG, PNG, WebP или GIF.")
    if max(size) > max_side:
        raise ValueError(too_big)


# Уменьшенные копии фото. Карточка концерта на экране шириной около 400 px,
# а оригинал ужат только до 2000: без копий браузер качал бы его целиком.
# 1200 — для телефонов с плотным экраном (390 px × 3): без неё они брали
# оригинал JPEG вместо WebP. 1600 и 1920 — для широких экранов и главной картинки
# страницы (LCP): иначе на большом мониторе браузер брал оригинал JPEG.
VARIANT_WIDTHS = (400, 800, 1200, 1600, 1920)


def variant_name(name: str, width: int) -> str:
    """«foto-1a2b.jpg» -> «foto-1a2b-400w.webp»."""
    return f"{name.rsplit('.', 1)[0]}-{width}w.webp"


def make_variants(path: str) -> int:
    """Сохраняет рядом с фото копии шириной 400, 800, 1200, 1600 и 1920 px в WebP.

    Копию шире оригинала не делаем — она была бы просто тяжелее.
    GIF не трогаем, чтобы не потерять анимацию. Возвращает число созданных копий.
    """
    from PIL import UnidentifiedImageError

    Image = _pil()
    made = 0
    try:
        with Image.open(path, formats=IMAGE_FORMATS) as img:
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
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as error:
        current_app.logger.warning("Не удалось сделать копии %s: %s", os.path.basename(path), error)
    return made


@lru_cache(maxsize=2048)
def _srcset_for(name: str, mtime: float, folder: str) -> str:
    """Строка srcset для файла; кэш по времени изменения файла."""
    parts = [
        f"{UPLOADS_PREFIX}{variant_name(name, w)} {w}w"
        for w in VARIANT_WIDTHS
        if os.path.exists(os.path.join(folder, variant_name(name, w)))
    ]
    if not parts:
        return ""
    try:
        with _pil().open(os.path.join(folder, name), formats=IMAGE_FORMATS) as img:
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


@lru_cache(maxsize=2048)
def _size_for(name: str, mtime: float, folder: str):
    try:
        with _pil().open(os.path.join(folder, name), formats=IMAGE_FORMATS) as img:
            return img.size
    except Exception:
        return None


def image_size(url: str):
    """Фильтр шаблона: (ширина, высота) фото из загрузок или None.

    Нужен для width/height у <img> и для og:image:width/height: с размерами
    браузер резервирует место до загрузки картинки, и страница не прыгает.
    """
    if not url or not url.startswith(UPLOADS_PREFIX):
        return None
    name = url[len(UPLOADS_PREFIX):]
    folder = current_app.config["UPLOAD_FOLDER"]
    try:
        mtime = os.path.getmtime(os.path.join(folder, name))
    except OSError:
        return None
    return _size_for(name, mtime, folder)


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


# Очистка HTML из панели администратора: оставляем разметку текста, вырезаем скрипты,
# обработчики событий и javascript:-ссылки. Код виджетов (схема зала, карта)
# сюда не попадает — его вводит только администратор.
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
    """Безопасная разметка из текста, введённого в панели администратора."""
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
    from PIL import UnidentifiedImageError

    Image = _pil()
    cfg = current_app.config
    side = cfg["IMAGE_MAX_SIDE"]
    try:
        with Image.open(path, formats=IMAGE_FORMATS) as img:
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
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as error:
        current_app.logger.warning("Не удалось ужать %s: %s", os.path.basename(path), error)


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

    Адрес разбирается целиком: схема только https, хост сверяется со списком
    точно, а не поиском подстроки. Иначе ссылка вида
    `javascript:…//vk.com/video_ext.php` попала бы в src фрейма и выполнилась
    бы на сайте. Код проигрывателя собирается только из проверенных частей
    адреса (цифры, латиница), исходная строка в разметку не идёт.
    """
    url = (url or "").strip()
    if not url:
        return ""
    # Свой файл с сайта: /static/uploads/clip.mp4
    if url.startswith("/") and not url.startswith("//"):
        parts = urlsplit(url)
        if VIDEO_FILE_RE.search(parts.path):
            return _tag('<video controls preload="metadata" src="{}"></video>', parts.path)
        return ""

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return ""
    host = host[4:] if host.startswith("www.") else host
    path, query = parts.path, parse_qs(parts.query)

    if host in VK_HOSTS:
        # https://vk.com/video-123456_789 или код для вставки video_ext.php?oid=…&id=…&hash=…
        m = re.fullmatch(r"/video(-?\d+)_(\d+)/?", path)
        if m:
            oid, vid, video_hash = m.group(1), m.group(2), ""
        elif path == "/video_ext.php":
            oid, vid = _query_value(query, "oid", r"-?\d+"), _query_value(query, "id", r"\d+")
            video_hash = _query_value(query, "hash", r"[0-9a-f]+")
            if not (oid and vid):
                return ""
        else:
            return ""
        extra = f"&hash={video_hash}" if video_hash else ""
        return (
            f'<iframe src="https://vk.com/video_ext.php?oid={oid}&id={vid}{extra}&hd=2"'
            ' title="Видео VK" loading="lazy"'
            ' allow="autoplay; encrypted-media; fullscreen" allowfullscreen frameborder="0"></iframe>'
        )

    if host == "rutube.ru":
        m = re.fullmatch(r"/(?:video|play/embed)/([0-9a-f]{32})/?", path)
        if m:
            return (
                f'<iframe src="https://rutube.ru/play/embed/{m.group(1)}"'
                ' title="Видео Rutube" loading="lazy"'
                ' allow="clipboard-write; autoplay" allowfullscreen frameborder="0"></iframe>'
            )
        return ""

    if host == "dzen.ru":
        m = re.fullmatch(r"/(?:video/)?(?:watch|embed)/([\w-]+)/?", path, re.ASCII)
        if m:
            return (
                f'<iframe src="https://dzen.ru/embed/{m.group(1)}"'
                ' title="Видео Дзен" loading="lazy"'
                ' allow="autoplay; fullscreen" allowfullscreen frameborder="0"></iframe>'
            )
        return ""

    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        if host == "youtu.be":
            m = re.fullmatch(r"/([\w-]{11})/?", path, re.ASCII)
            video_id = m.group(1) if m else ""
        elif path == "/watch":
            video_id = _query_value(query, "v", r"[\w-]{11}")
        else:
            m = re.fullmatch(r"/(?:embed|shorts)/([\w-]{11})/?", path, re.ASCII)
            video_id = m.group(1) if m else ""
        if video_id:
            return (
                f'<iframe src="https://www.youtube.com/embed/{video_id}"'
                ' title="Видео YouTube" loading="lazy"'
                ' allow="accelerometer; clipboard-write; encrypted-media; picture-in-picture"'
                ' allowfullscreen frameborder="0"></iframe>'
            )
        return ""

    # Прямая ссылка на файл на другом сайте — только https
    if VIDEO_FILE_RE.search(path):
        return _tag('<video controls preload="metadata" src="{}"></video>', urlunsplit(parts))
    return ""


VK_HOSTS = {"vk.com", "m.vk.com", "vk.ru", "vkvideo.ru"}
VIDEO_FILE_RE = re.compile(r"\.(mp4|webm)$", re.I)


def _query_value(query: dict, key: str, pattern: str) -> str:
    """Параметр адреса, если он целиком подходит под шаблон, иначе пустая строка."""
    value = (query.get(key) or [""])[0]
    return value if re.fullmatch(pattern, value, re.ASCII) else ""


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


def map_point(value: str) -> str:
    """«Широта, долгота» из настроек → «долгота,широта» для Яндекс Карт.

    Яндекс ждёт координаты в обратном порядке, а копируются они из карт
    как «54.78, 32.04». Неразборчивое значение — пустая строка.
    """
    parts = re.findall(r"-?\d+(?:\.\d+)?", value or "")
    if len(parts) != 2:
        return ""
    lat, lon = (float(p) for p in parts)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return ""
    return f"{lon:.6f},{lat:.6f}"


YANDEX_ID = re.compile(r"[\w.\-]+@\d+")
YANDEX_NUMBER = re.compile(r"@?(\d+)")
# Часть ID сеанса до «@» — одна на все концерты филармонии (настройка yandex_session_prefix)
YANDEX_PREFIX = "ticketsteam-825"


def yandex_session_id(value: str, prefix: str = YANDEX_PREFIX) -> str:
    """ID сеанса Яндекс Афиши из формы: «ticketsteam-825@496249».

    Обычно редактор вводит только номер после «@» — приставка берётся из
    настроек. Можно вставить и полный ID, и весь код кнопки из письма
    Яндекса — ID вытаскивается из него. Пусто — пусто; что-то иное — ValueError.
    """
    value = (value or "").strip()
    if not value:
        return ""
    number = YANDEX_NUMBER.fullmatch(value)
    if number:
        return f"{prefix or YANDEX_PREFIX}@{number.group(1)}"
    found = YANDEX_ID.search(value)
    if not found:
        raise ValueError("Введите номер сеанса Яндекс Афиши — цифры после «@», например 496249.")
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


BLOCK_CLOSE = re.compile(r"</\s*(?:p|h[1-6]|li|div|tr|blockquote|section|article)\s*>|<\s*br\s*/?\s*>", re.I)


def strip_tags(html: str, limit: int = 200) -> str:
    """Текст без разметки для описаний. Между блоками (абзацы, заголовки, пункты списка)
    ставится точка, чтобы «О концерте» и следующий за ним абзац не склеивались в одну фразу."""
    marked = BLOCK_CLOSE.sub(" ", html or "")
    parts = (re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", part)).strip()
             for part in marked.split(" "))
    parts = [part for part in parts if part]
    text = ""
    for i, part in enumerate(parts):
        text += part
        if i < len(parts) - 1:
            text = text.rstrip(",") + ("" if text.endswith((".", "!", "?", ":", ";", "…")) else ".") + " "
    # Сущности («&amp;», «&nbsp;») — в обычные знаки, иначе в описание попадёт «&amp;amp;».
    # Разметку после этого не вырезаем; вывод экранируется шаблоном (autoescape, tojson).
    text = " ".join(htmllib.unescape(text).split())
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



@lru_cache(maxsize=32)
def qr_svg(url: str) -> Markup:
    """QR-код ссылки картинкой SVG прямо в разметке, без файла и внешних сервисов.

    Модули всегда чёрные на белом поле с отступом: камеры телефонов плохо
    читают светлый код на тёмном, поэтому цвета темы сюда не попадают.
    Ссылку меняют в «Настройках» — код перерисовывается сам.
    """
    url = (url or "").strip()
    if not url:
        return Markup("")
    import segno

    matrix = segno.make(url, error="m").matrix
    size, border = len(matrix), 4
    path = "".join(
        f"M{x + border} {y + border}h1v1h-1z"
        for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark
    )
    full = size + border * 2
    return Markup(
        f'<svg class="qr" viewBox="0 0 {full} {full}" shape-rendering="crispEdges" '
        f'role="img" aria-label="QR-код ссылки на анкету" focusable="false">'
        f'<rect width="{full}" height="{full}" fill="#fff"/><path d="{path}" fill="#000"/></svg>'
    )
