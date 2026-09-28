"""Генерация демонстрационных афиш, фотографий и видео для наполнения сайта.

Эти файлы нужны только для демонстрации. На боевом сайте их заменяют
настоящие афиши и фотографии, загруженные через админку.
Вызывается из `filarmonia.seed` при `python app.py seed`.
"""
import os
import math
import random
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(OUT, exist_ok=True)

# Шрифты ищем среди системных: Linux (DejaVu, Liberation, Noto), Windows, macOS.
# Нужна кириллица, поэтому берём только проверенные семейства.
FONT_CANDIDATES = {
    "serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
    ],
    "serif_bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    ],
    "sans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}

# Если ни одного известного пути нет (урезанный образ на хостинге), ищем
# по всему каталогу шрифтов: имя файла должно начинаться с одного из семейств,
# у которых заведомо есть кириллица.
FONT_FALLBACK_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts"]
FONT_FALLBACK_PREFIXES = {
    "serif": ("DejaVuSerif", "LiberationSerif", "NotoSerif", "FreeSerif"),
    "serif_bold": ("DejaVuSerif-Bold", "LiberationSerif-Bold", "NotoSerif-Bold", "FreeSerifBold"),
    "sans": ("DejaVuSans", "LiberationSans", "NotoSans", "FreeSans"),
}

SERIF, SERIF_BOLD, SANS = "serif", "serif_bold", "sans"


def font_path(kind):
    """Первый существующий шрифт нужного начертания; None — если ничего нет."""
    for path in FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            return path
    for root_dir in FONT_FALLBACK_DIRS:
        for root, _dirs, files in os.walk(root_dir):
            for name in sorted(files):
                if name.startswith(FONT_FALLBACK_PREFIXES[kind]) and name.endswith(".ttf"):
                    return os.path.join(root, name)
    return None


def ffmpeg_exe():
    """Путь к ffmpeg: системный, иначе из пакета imageio-ffmpeg. None — если нет."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def run_ffmpeg(cmd):
    """Запускает ffmpeg. False — если ролик собрать не удалось.

    Демо-видео не обязательны: наполнение базы не должно прерываться
    из-за сборки заглушки, поэтому ошибку только показываем.
    """
    try:
        subprocess.run(cmd, check=True)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        print(f"ffmpeg не собрал {cmd[-1]}: {error}. Демо-видео пропущено.")
        return False

PALETTES = [
    ((26, 32, 48), (168, 51, 43), (222, 200, 160)),
    ((34, 26, 30), (185, 135, 63), (240, 235, 226)),
    ((20, 40, 48), (168, 51, 43), (226, 226, 218)),
    ((44, 28, 44), (185, 135, 63), (240, 226, 210)),
    ((24, 34, 30), (150, 60, 44), (232, 226, 206)),
]


_FONT_WARNED = set()


def font(kind, size):
    path = font_path(kind)
    if path is None:                      # системных шрифтов нет — встроенный Pillow
        if kind not in _FONT_WARNED:
            _FONT_WARNED.add(kind)
            print(f"Шрифт «{kind}» не найден: подписи на демо-картинках "
                  f"могут выйти без кириллицы.")
        return ImageFont.load_default(size)
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, max_width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if draw.textlength(probe, font=fnt) <= max_width:
            cur = probe
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def ellipsize(draw, line, fnt, max_width):
    """Обрезает строку по словам и ставит многоточие, если она не влезает."""
    words = line.split()
    while words and draw.textlength(" ".join(words) + "…", font=fnt) > max_width:
        words.pop()
    return (" ".join(words) + "…") if words else "…"


def fitted(draw, text, kind, size, max_width, max_lines, min_size=20):
    """Подбирает кегль так, чтобы текст целиком уместился в max_lines строк.

    Возвращает (шрифт, строки, кегль). Если текст не влезает даже минимальным
    кеглем — последняя строка обрезается многоточием, а не словом посередине.
    """
    size = max(size, min_size)
    while True:
        fnt = font(kind, size)
        lines = wrap(draw, text, fnt, max_width)
        if len(lines) <= max_lines:
            return fnt, lines, size
        if size <= min_size:
            lines = lines[:max_lines]
            lines[-1] = ellipsize(draw, lines[-1], fnt, max_width)
            return fnt, lines, size
        size -= 3


def texture(img, seed):
    """Мягкий градиент и круги — вместо фотографии."""
    rnd = random.Random(seed)
    w, h = img.size
    overlay = Image.new("RGB", (w // 4, h // 4))
    d = ImageDraw.Draw(overlay)
    base = img.getpixel((0, 0))
    d.rectangle([0, 0, w, h], fill=base)
    for _ in range(14):
        r = rnd.randint(w // 20, w // 5)
        x, y = rnd.randint(0, w // 4), rnd.randint(0, h // 4)
        shade = tuple(min(255, max(0, c + rnd.randint(-26, 34))) for c in base)
        d.ellipse([x - r, y - r, x + r, y + r], fill=shade)
    overlay = overlay.filter(ImageFilter.GaussianBlur(14)).resize((w, h))
    return overlay


def poster(name, title, subtitle, date_line, seed):
    w, h = 900, 1200
    bg, accent, light = PALETTES[seed % len(PALETTES)]
    img = Image.new("RGB", (w, h), bg)
    img = texture(img, seed)
    d = ImageDraw.Draw(img, "RGBA")

    # ломаная «нотная» графика
    rnd = random.Random(seed * 7)
    for i in range(5):
        y = 300 + i * 90 + rnd.randint(-20, 20)
        d.line([(60, y), (w - 60, y - rnd.randint(0, 60))], fill=accent + (70,), width=2)
    d.ellipse([w - 330, 120, w - 60, 390], outline=accent + (170,), width=3)
    d.rectangle([0, 0, 18, h], fill=accent)

    # На странице события поверх афиши выводятся баннеры («Пушкинская карта»,
    # «Есть льготы», «Премьера сезона») — они занимают полосы у верхнего и
    # нижнего края. Свой текст держим между ними, иначе надписи наложатся.
    safe_top, safe_bottom = 165, h - 175

    d.text((60, safe_top), date_line.upper(), font=font(SANS, 30), fill=light)

    brand_top = safe_bottom - 82
    d.rectangle([60, brand_top, 360, brand_top + 82], fill=accent)
    d.text((88, brand_top + 14), "Смоленская", font=font(SANS, 26), fill=(255, 255, 255))
    d.text((88, brand_top + 44), "филармония", font=font(SANS, 26), fill=(255, 255, 255))

    # Заголовок и аннотацию подгоняем по кеглю: слова не должны пропадать
    text_top = safe_top + 80
    f_sub, sub_lines, _ = fitted(d, subtitle, SANS, 34, w - 160, 3)
    sub_h = len(sub_lines) * 48
    avail = brand_top - 46 - text_top - sub_h - 16
    f_title, title_lines, title_size = fitted(d, title, SERIF_BOLD, 74, w - 140,
                                              max(1, avail // 92), min_size=44)
    line_h = int(title_size * 1.24)

    y = brand_top - 46 - (len(title_lines) * line_h + 16 + sub_h)
    y = max(y, text_top)
    for line in title_lines:
        d.text((60, y), line, font=f_title, fill=(255, 255, 255))
        y += line_h
    y += 16
    for line in sub_lines:
        d.text((60, y), line, font=f_sub, fill=light)
        y += 48

    img.save(os.path.join(OUT, name), quality=88)
    return name


def photo(name, caption, seed, size=(1600, 1000)):
    bg, accent, light = PALETTES[seed % len(PALETTES)]
    img = Image.new("RGB", size, bg)
    img = texture(img, seed + 11)
    d = ImageDraw.Draw(img, "RGBA")
    w, h = size
    for i in range(9):
        x = 80 + i * (w - 160) / 9
        height = 120 + int(abs(math.sin(i * 1.3 + seed)) * (h * 0.45))
        d.rectangle([x, h - height - 90, x + (w - 160) / 14, h - 90], fill=accent + (120,))
    # Подпись держим в центральной части кадра: в плитках галереи фото
    # кадрируется под 4:3 и 16:10, у самого края текст срезало бы.
    pad = max(60, int((w - h * 4 / 3) / 2) + 24)
    d.rectangle([0, h - 124, w, h], fill=(0, 0, 0, 120))
    f_cap, lines, size = fitted(d, caption, SANS, 34, w - pad * 2, 2, min_size=24)
    line_h = size + 10
    y = h - 46 - len(lines) * line_h
    for line in lines:
        d.text((pad, y), line, font=f_cap, fill=(255, 255, 255))
        y += line_h
    img.save(os.path.join(OUT, name), quality=86)
    return name


def hero_video(image_name, video_name):
    """Короткий цикл с медленным наездом — заглушка для видео на главной.

    Без ffmpeg возвращает None: на главной останется кадр-заставка.
    """
    exe = ffmpeg_exe()
    if exe is None:
        return None
    src = os.path.join(OUT, image_name)
    dst = os.path.join(OUT, video_name)
    cmd = [
        exe, "-y", "-loglevel", "error", "-loop", "1", "-i", src, "-t", "10",
        "-vf", "zoompan=z='min(zoom+0.0006,1.15)':d=250:s=1600x900:fps=25,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-an", dst,
    ]
    return video_name if run_ffmpeg(cmd) else None


def clip(name="demo-clip.mp4", source="hero-hall.jpg"):
    """Короткий ролик-заглушка вместо присланного артистами видео.

    Без ffmpeg возвращает None — вызывающий код подставляет ссылку на внешнее видео.
    """
    dst = os.path.join(OUT, name)
    if os.path.exists(dst):
        return name
    exe = ffmpeg_exe()
    if exe is None:
        return None
    src = os.path.join(OUT, source)
    if not os.path.exists(src):
        photo(source, "Концертный зал филармонии", 3, (1920, 1080))
    ok = run_ffmpeg([
        exe, "-y", "-loglevel", "error", "-loop", "1", "-i", src, "-t", "6",
        "-vf", "zoompan=z='min(zoom+0.001,1.2)':d=150:s=1280x720:fps=25,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-an", dst,
    ])
    return name if ok else None


