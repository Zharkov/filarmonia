"""Обслуживание каталога загрузок.

    python app.py thumbs              сделать уменьшенные копии для всех фото
    python app.py cleanup --dry-run   показать файлы, на которые никто не ссылается
    python app.py cleanup             удалить такие файлы
"""
import os
import re

from .models import referenced_uploads
from . import utils

IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp)$", re.I)
VARIANT = re.compile(r"-\d+w\.webp$")


def make_all_variants(app) -> int:
    """Уменьшенные копии для фото, загруженных до их появления, и для демо-картинок."""
    with app.app_context():
        folder = app.config["UPLOAD_FOLDER"]
        made = 0
        for name in sorted(os.listdir(folder)):
            if IMAGE_EXT.search(name) and not VARIANT.search(name):
                made += utils.make_variants(os.path.join(folder, name))
        return made


def unused_uploads(app) -> list:
    """Файлы каталога загрузок, на которые не ссылается ни одна запись базы.

    Уменьшенная копия считается занятой, пока жив её оригинал.
    """
    with app.app_context():
        folder = app.config["UPLOAD_FOLDER"]
        used = referenced_uploads()
        used_variants = {
            utils.variant_name(name, w) for name in used for w in utils.VARIANT_WIDTHS
        }
        return sorted(
            name for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name))
            and name not in used and name not in used_variants and not name.startswith(".")
        )


def cleanup(app, dry_run: bool = False) -> list:
    """Удаляет неиспользуемые файлы. Возвращает их список."""
    names = unused_uploads(app)
    if not dry_run:
        folder = app.config["UPLOAD_FOLDER"]
        for name in names:
            try:
                os.remove(os.path.join(folder, name))
            except OSError as error:
                print(f"Не удалось удалить {name}: {error}")
    return names
