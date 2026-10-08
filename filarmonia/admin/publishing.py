"""Публикация и снятие с сайта прямо из таблиц разделов."""
from flask import request, redirect, url_for, flash, abort, jsonify

from ..models import db, Event, Collective, News, Page, MenuItem, Document, Banner
from . import bp
from .common import get_or_404, log, login_required, safe_next, title_of


# Публикация из списка
# Раздел -> (модель, список, куда вернуться по умолчанию)
PUBLISH_TOGGLES = {
    "event": (Event, "admin.events"),
    "news": (News, "admin.news"),
    "collective": (Collective, "admin.collectives"),
    "page": (Page, "admin.pages"),
    "document": (Document, "admin.documents"),
    "banner": (Banner, "admin.banners"),
    "menu": (MenuItem, "admin.menu"),
}


@bp.route("/publish/<kind>/<int:item_id>", methods=["POST"])
@login_required
def toggle_publish(kind, item_id):
    """Публикует запись или снимает её с сайта прямо из таблицы раздела.

    Возвращает на ту же страницу списка — с фильтрами, сортировкой
    и прокруткой к строке записи.
    """
    if kind not in PUBLISH_TOGGLES:
        abort(404)
    model, endpoint = PUBLISH_TOGGLES[kind]
    item = get_or_404(model, item_id)
    item.is_published = not item.is_published
    state = "показывается на сайте" if item.is_published else "скрыто с сайта"
    log("update", item, details=state)
    db.session.commit()
    message = f"«{title_of(item)}» — {state}."
    # Скрипт панели администратора переключает метку на месте, без перезагрузки страницы
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(published=item.is_published, message=message)
    flash(message, "ok")
    back = safe_next(request.form.get("next", "")) if request.form.get("next") else url_for(endpoint)
    return redirect(f"{back}#row-{item.id}")
