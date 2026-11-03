"""Подготовка release/ к загрузке на хостинг.

Сверяет файлы проекта с бэкапом хостинга (backup/) и копирует в release/
только то, что изменилось или новое. Файлы, одинаковые на обеих сторонах,
и данные хостинга (база, uploads, .env, index.cgi, .htaccess) не берутся.
"""
import filecmp
import os
import shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT)
DST = os.path.join(ROOT, "release")
BACKUP = os.path.join(ROOT, "backup")

# Пути, которые не участвуют в сверке: данные и служебные файлы хостинга
SKIP_DIRS = {"__pycache__", ".pytest_cache", "uploads"}
SKIP_FILES = {"filarmonia.db", ".env", "index.cgi", ".htaccess", "test.txt"}


def same(rel: str) -> bool:
    """Файл одинаков в проекте и на хостинге?

    Переводы строк не учитываются: у хостинга CRLF, в проекте LF — для
    Python это одно и то же, дубли ради них не нужны.
    """
    a = os.path.join(SRC, rel)
    b = os.path.join(BACKUP, rel)
    if not os.path.isfile(b):
        return False
    if os.path.getsize(a) == os.path.getsize(b) and filecmp.cmp(a, b, shallow=False):
        return True
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read().replace(b"\r\n", b"\n") == fb.read().replace(b"\r\n", b"\n")


def main() -> None:
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)

    # Сверяем только те файлы проекта, что есть в бэкапе: там, где в проекте
    # есть код, а на хостинге его нет — это новые файлы, их берём всегда.
    copied, same_count = [], 0
    for dirpath, dirnames, filenames in os.walk(BACKUP):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != "scripts"]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), BACKUP)
            if name in SKIP_FILES:
                continue
            if rel.startswith(os.path.join("filarmonia", "static", "uploads") + os.sep):
                continue
            src = os.path.join(SRC, rel)
            if not os.path.isfile(src):
                continue  # файла больше нет в проекте — на хостинге тоже не нужен
            if same(rel):
                same_count += 1
                continue
            dst = os.path.join(DST, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)

    # Новые файлы: есть в проекте, на хостинге отсутствуют
    for dirpath, dirnames, filenames in os.walk(os.path.join(SRC, "filarmonia")):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != "uploads"]
        for name in filenames:
            if name == "filarmonia.db":
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), SRC)
            dst = os.path.join(DST, rel)
            if os.path.isfile(dst):
                continue  # уже скопирован как изменённый
            if os.path.isfile(os.path.join(BACKUP, rel)) and same(rel):
                continue
            if rel in copied:
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)

    # Корневые файлы кода
    for name in ("app.py", "config.py", "requirements.txt"):
        if not same(name):
            shutil.copy2(os.path.join(SRC, name), os.path.join(DST, name))
            copied.append(name)

    # Миграции: сверяем целиком
    versions = os.path.join(SRC, "migrations", "versions")
    for name in sorted(os.listdir(versions)):
        if not name.endswith(".py"):
            continue
        rel = os.path.join("migrations", "versions", name)
        if not os.path.isfile(os.path.join(BACKUP, rel)) or not same(rel):
            dst = os.path.join(DST, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(SRC, rel), dst)
            copied.append(rel)

    print(f"Одинаковых файлов (не берём): {same_count}")
    copied = sorted(set(copied))
    print(f"Копируем на хостинг ({len(copied)}):")
    for rel in copied:
        print("  ", rel.replace(os.sep, "/"))


if __name__ == "__main__":
    main()
