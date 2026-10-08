"""Галереи фото и видео у событий, новостей, коллективов и страниц."""
from flask import request, redirect, url_for, flash, abort, jsonify

from ..models import db, MediaItem
from .. import utils
from . import bp
from .common import files_of, get_or_404, log, login_required, release_files


# Медиа (общее)
OWNERS = {
    "event": ("event_id", "admin.event_form", "event_id"),
    "collective": ("collective_id", "admin.collective_form", "item_id"),
    "news": ("news_id", "admin.news_form", "item_id"),
    "page": ("page_id", "admin.page_form", "item_id"),
}


def media_owner(item):
    """(поле владельца, его id, адрес возврата) для фото или видео."""
    for field, endpoint, arg in OWNERS.values():
        value = getattr(item, field)
        if value:
            return field, value, url_for(endpoint, **{arg: value}) + "#media"
    return None, None, url_for("admin.dashboard")


@bp.route("/media/add", methods=["POST"])
@login_required
def media_add():
    owner = request.form.get("owner")
    owner_id = utils.parse_int(request.form.get("owner_id"))
    if owner not in OWNERS or not owner_id:
        abort(400)
    field, endpoint, arg = OWNERS[owner]
    back = url_for(endpoint, **{arg: owner_id}) + "#media"

    kind = request.form.get("kind", "photo")
    title = request.form.get("title", "").strip()
    # Новое — в конец галереи: иначе оно вставало бы между уже расставленными
    last = db.session.query(db.func.max(MediaItem.sort)).filter(
        getattr(MediaItem, field) == owner_id).scalar() or 0
    item = MediaItem(kind=kind, title=title, sort=last + 10)
    setattr(item, field, owner_id)

    try:
        if kind == "photo":
            saved = 0
            for uploaded in request.files.getlist("file"):
                if uploaded and uploaded.filename:
                    clone = MediaItem(kind="photo", title=title, sort=last + 10 * (saved + 1))
                    setattr(clone, field, owner_id)
                    clone.file = utils.save_upload(uploaded, ("image",))
                    db.session.add(clone)
                    saved += 1
            if not saved:
                flash("Выберите хотя бы один файл.", "error")
            else:
                log("create", object_type="media", details=f"фотографий: {saved} ({owner} № {owner_id})")
                db.session.commit()
                flash(f"Загружено фотографий: {saved}.", "ok")
        else:
            url = request.form.get("url", "").strip()
            uploaded = request.files.get("file")
            preview = request.files.get("preview")
            if uploaded and uploaded.filename:
                item.file = utils.save_upload(uploaded, ("video",))
            elif url:
                item.url = url
                item.embed = utils.video_embed(url)
                if not item.embed:
                    flash("Ссылку не удалось распознать — на странице будет показана обычная ссылка. "
                          "Поддерживаются VK Видео, RuTube, Дзен, YouTube и файлы .mp4.", "error")
            else:
                flash("Укажите ссылку на видео или загрузите файл.", "error")
                return redirect(back)
            if preview and preview.filename:
                item.preview = utils.save_upload(preview, ("image",))
            db.session.add(item)
            log("create", item, details=f"видео ({owner} № {owner_id})")
            db.session.commit()
            flash("Видео добавлено.", "ok")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(back)


@bp.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def media_delete(media_id):
    item = get_or_404(MediaItem, media_id)
    _, _, back = media_owner(item)
    names = files_of(item)
    log("delete", item)
    db.session.delete(item)
    db.session.commit()
    release_files(names)
    return redirect(back)


@bp.route("/media/<int:media_id>/move", methods=["POST"])
@login_required
def media_move(media_id):
    """Сдвигает фото или видео на одно место вперёд или назад в галерее."""
    item = get_or_404(MediaItem, media_id)
    field, owner_id, back = media_owner(item)
    if field is None:
        return redirect(back)
    siblings = (
        MediaItem.query.filter(getattr(MediaItem, field) == owner_id)
        .order_by(MediaItem.sort, MediaItem.id).all()
    )
    index = siblings.index(item)
    target = index - 1 if request.form.get("dir") == "up" else index + 1
    moved = 0 <= target < len(siblings)
    if moved:
        siblings[index], siblings[target] = siblings[target], siblings[index]
        # Перенумеровываем всех: у старых записей порядок мог совпадать
        for position, media in enumerate(siblings):
            media.sort = (position + 1) * 10
        db.session.commit()
    # Скрипт панели администратора переставляет миниатюру на месте, без перезагрузки страницы
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(moved=moved)
    return redirect(back)
