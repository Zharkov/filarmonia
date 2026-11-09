"""Фоновое видео на главной: нарезка в HLS сразу после загрузки в панели.

Заказчик загружает обычный mp4/webm в «Настройках» — сервер сам пережимает его
(H.264 1280 px + AAC стерео) и режет на кусочки по ~6 секунд в каталог
uploads/hero-<отпечаток>/, а настройка hero_video получает путь плейлиста
hero-<отпечаток>/master.m3u8. Отпечаток содержимого = новый адрес при каждой
новой загрузке, поэтому годовой кэш браузера не показывает старый ролик.

ffmpeg берётся из пакета imageio-ffmpeg (статический бинарник ~77 МБ, один на
всех платформах) либо из PATH. Пережатие занимает десятки секунд, потому идёт
в отдельном процессе (detached): запрос сохранения настроек не виснет и CGI-
таймаут хостинга не ловится. Готовность определяется просто: если плейлиста
ещё нет — страница играет postер, как до загрузки видео.

Старые каталоги hero-* остаются на диске; их чистит человек, когда убедится,
что новый ролик играет.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys

# Параметры как в scripts/make_hero_video.py: фон, качество «на глаз», звук лёгким стерео
FF_ARGS = [
    "-vf", "scale=1280:-2", "-c:v", "libx264", "-profile:v", "main", "-level", "3.1",
    "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
    "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
    "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
]


def slug_for(filename: str) -> str:
    """Имя каталога по содержимому файла: 12 hex-символов sha1."""
    digest = hashlib.sha1()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return "hero-" + digest.hexdigest()[:12]


def find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.isfile(exe):
            return exe
    except Exception:  # пакет не установлен или не смог скачать бинарник
        pass
    return shutil.which("ffmpeg") or ""


def encode(src: str, outdir: str, ffmpeg: str) -> None:
    """Синхронная нарезка (для скриптов и тестов)."""
    os.makedirs(outdir, exist_ok=True)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", src] + FF_ARGS + [
        "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
        "-hls_segment_filename", os.path.join(outdir, "seg%d.ts"),
        os.path.join(outdir, "master.m3u8"),
    ]
    subprocess.run(cmd, check=True)
    # Исходник больше не нужен: роль ролика выполняет нарезка
    os.remove(src)


def spawn_encode(src: str, outdir: str) -> bool:
    """Запускает нарезку отдельным процессом и не ждёт его. False, если ffmpeg нет."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "encode.log"), "w", encoding="utf-8")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", src] + FF_ARGS + [
        "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
        "-hls_segment_filename", os.path.join(outdir, "seg%d.ts"),
        os.path.join(outdir, "master.m3u8"),
    ]
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: процесс не наследует консоль CGI
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                      creationflags=0x00000008 | 0x00000200)
    else:
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                      close_fds=True, start_new_session=True)
    subprocess.Popen(cmd, **kwargs)
    return True


HERO_DIR_RE = re.compile(r"^hero-[a-z0-9][a-z0-9_-]*$")


def is_hls_value(value: str) -> bool:
    """Значение hero_video указывает на нарезанный ролик?"""
    return bool(value) and "/" in value and value.endswith("/master.m3u8") \
        and HERO_DIR_RE.match(value.split("/", 1)[0]) is not None


def prepare(app, upload_name: str, source_exts=(".mp4", ".webm")) -> str:
    """Вызывается после сохранения настроек с новым видео.

    Возвращает значение для hero_video (hero-hash/master.m3u8) или "", если
    ffmpeg недоступен — тогда hero_video остаётся обычным файлом и работает по-старому.
    """
    uploads = app.config["UPLOAD_FOLDER"]
    src = os.path.join(uploads, upload_name)
    if not os.path.isfile(src) or os.path.splitext(upload_name)[1].lower() not in source_exts:
        return ""
    slug = slug_for(src)
    outdir = os.path.join(uploads, slug)
    target = f"{slug}/master.m3u8"
    # Нарезка идёт в отдельном процессе: до её готовности страница играет постер;
    # когда процесс завершится не успешно, следующий сохраняющий настройки запрос
    # попробует ещё раз (плейлиста нет — spawn_encode запускается заново)
    if spawn_encode(src, outdir):
        return target
    shutil.rmtree(outdir, ignore_errors=True)  # каталог создаётся внутри spawn_encode
    return ""
