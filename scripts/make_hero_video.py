"""Фоновое видео на главную: сжать и нарезать на HLS, без путаницы.

    python scripts\make_hero_video.py C:\путь\к\видео.webm [имя_каталога]

Делает всё сам: ffmpeg пережимает в H.264 1280×496 + AAC (фон, звук можно
включить кнопкой) и режет на кусочки по ~6 секунд; складывает в новый каталог
filarmonia/static/uploads/hero-N (N — следующий свободный номер, или имя из
второго аргумента); обновляет настройку hero_video в локальной базе filarmonia.db; печатает список файлов для заливки на хостинг и команду для боевой базы.

Номер каталога нужен потому, что статика кэшируется браузером на год и у
видео нет ?v=: старое имя = старый ролик из кэша навсегда. Новый URL обходит
кэш гарантированно.

ffmpeg ставится одной командой: winget install Gyan.FFmpeg
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_ffmpeg() -> str:
    """Путь к ffmpeg: сначала в PATH, потом туда, куда кладёт его winget."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    pkgs = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    pattern = os.path.join(pkgs, "Gyan.FFmpeg_*", "FFmpeg-*", "bin", "ffmpeg.exe")
    for cand in sorted(_glob(pattern), reverse=True):
        if os.path.isfile(cand):
            return cand
    sys.exit("Не найден ffmpeg. Установите: winget install Gyan.FFmpeg, "
             "или запустите скрипт из оболочки, где ffmpeg уже в PATH.")


def _glob(pattern: str):
    import glob as g
    return g.glob(pattern)


def next_slug(custom: str = "") -> str:
    if custom:
        # Имя каталога должно быть безопасным для пути и ссылки
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", custom):
            sys.exit(f"Имя каталога '{custom}' не подходит: только строчные латинские буквы, цифры, «-», «_».")
        return custom
    uploads = os.path.join(ROOT, "filarmonia", "static", "uploads")
    top = 0
    for name in os.listdir(uploads):
        m = re.fullmatch(r"hero-(\d+)", name)
        if m:
            top = max(top, int(m.group(1)))
    return f"hero-{top + 1}"


def encode(src: str, outdir: str, ffmpeg: str) -> None:
    # -ac 2 страховка: исходники с 5.1-звуком не всякий браузер умеет, а стерео играет везде
    cmd = [
        ffmpeg, "-y", "-v", "error", "-stats", "-i", src,
        "-vf", "scale=1280:-2", "-c:v", "libx264", "-profile:v", "main", "-level", "3.1",
        "-preset", "slow", "-crf", "28", "-pix_fmt", "yuv420p",
        "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
        "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
        "-hls_segment_filename", os.path.join(outdir, "seg%d.ts"),
        os.path.join(outdir, "master.m3u8"),
    ]
    subprocess.run(cmd, check=True)


def set_local_setting(slug: str) -> bool:
    """Меняет настройку только в ЛОКАЛЬНОЙ базе разработки (filarmonia.db)."""
    db_path = os.path.join(ROOT, "filarmonia.db")
    if not os.path.isfile(db_path):
        return False
    value = f"{slug}/master.m3u8"
    con = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(settings)")}
        grp = "group" if "group" in cols else "group_"
        cur = con.execute("UPDATE settings SET value=? WHERE key='hero_video'", (value,))
        if cur.rowcount == 0:
            con.execute(
                f"INSERT INTO settings (key, value, title, {grp}, kind) VALUES (?,?,'Видео на главной','Главная страница','text')",
                ("hero_video", value),
            )
        con.commit()
        row = con.execute("SELECT value FROM settings WHERE key='hero_video'").fetchone()
        print(f"Локальная база: hero_video = {row[0]}")
        return True
    finally:
        con.close()


def main() -> None:
    if len(sys.argv) not in (2, 3) or not os.path.isfile(sys.argv[1]):
        sys.exit(__doc__.strip())
    src = os.path.abspath(sys.argv[1])
    ffmpeg = find_ffmpeg()

    slug = next_slug(sys.argv[2] if len(sys.argv) == 3 else "")
    outdir = os.path.join(ROOT, "filarmonia", "static", "uploads", slug)
    if os.path.isdir(outdir):
        sys.exit(f"Каталог {outdir} уже есть — возьмите другое имя каталога.")
    os.makedirs(outdir)

    size_in = os.path.getsize(src) / 1e6
    print(f"Пережимаем и нарезаем: {os.path.basename(src)} ({size_in:.1f} МБ) -> {slug}/")
    encode(src, outdir, ffmpeg)

    files = sorted(os.listdir(outdir))
    total = sum(os.path.getsize(os.path.join(outdir, f)) for f in files) / 1e6
    print(f"Готово: {len(files)} файлов, {total:.1f} МБ (было {size_in:.1f})")

    updated = set_local_setting(slug)
    print("\nНа хостинге:")
    print(f"1) Залейте содержимое папки {os.path.relpath(outdir, ROOT)} в www/filarmonia/static/uploads/{slug}/")
    print("   (нужны все файлы: master.m3u8 и seg*.ts)")
    if not updated:
        print("   и вручную поменяйте настройку hero_video на '" + slug + "/master.m3u8'")
    else:
        print("2) Обновите настройку в БОЕВОЙ базе (по SSH, из каталога www/):")
        print('   /home/u339478/python311/bin/python3.11 << "EOF"')
        print("   import sqlite3")
        print("   c = sqlite3.connect('filarmonia.db')")
        print(f"   c.execute(\"UPDATE settings SET value='{slug}/master.m3u8' WHERE key='hero_video'\")")
        print("   c.commit()")
        print("   print(c.execute(\"SELECT value FROM settings WHERE key='hero_video'\").fetchall())")
        print("   EOF")
    print("3) Проверьте главную с Ctrl+F5: фон играет, кнопка включает звук.")


if __name__ == "__main__":
    main()
