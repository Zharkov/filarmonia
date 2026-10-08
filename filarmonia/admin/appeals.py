"""Обращения граждан из интернет-приёмной."""
from datetime import timedelta

from flask import render_template, request, redirect, url_for, flash

from ..models import db, Appeal, Setting
from .. import utils
from . import bp
from .common import get_or_404, log, login_required, paginated, search_text, sorted_by


# Обращения
def purge_old_appeals() -> int:
    """Удаляет обработанные обращения старше срока хранения из «Настроек».

    Срок 0 или пустой — ничего не удаляется. Необработанные не трогаем никогда:
    сначала на обращение нужно ответить.
    """
    years = utils.parse_int(Setting.get("appeals_retention_years", "5"), 0)
    if not years:
        return 0
    border = utils.utcnow() - timedelta(days=365 * years)
    old = Appeal.query.filter(Appeal.is_processed.is_(True), Appeal.created_at < border)
    count = old.count()
    if count:
        old.delete(synchronize_session=False)
        log("purge", object_type="appeal", details=f"обращений: {count}, срок {years} лет")
        db.session.commit()
    return count


@bp.route("/appeals")
@login_required
def appeals():
    purged = purge_old_appeals()
    if purged:
        flash(f"Удалено обработанных обращений старше срока хранения: {purged}.", "ok")
    q = Appeal.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(Appeal.name, search) | utils.like_ci(Appeal.subject, search)
                     | utils.like_ci(Appeal.email, search) | utils.like_ci(Appeal.phone, search))
    if request.args.get("status") in ("new", "done"):
        q = q.filter(Appeal.is_processed.is_(request.args.get("status") == "done"))
    q, sorting = sorted_by(
        q, {"date": Appeal.created_at, "name": Appeal.name, "subject": Appeal.subject,
            "status": Appeal.is_processed},
        default="date", default_dir="desc", tiebreak=Appeal.id.desc(),
    )
    return render_template(
        "admin/appeals.html", items=paginated(q), search=search, sorting=sorting,
        retention=utils.parse_int(Setting.get("appeals_retention_years", "5"), 0),
    )


@bp.route("/appeals/<int:item_id>", methods=["GET", "POST"])
@login_required
def appeal_view(item_id):
    item = get_or_404(Appeal, item_id)
    if request.method == "POST":
        item.is_processed = bool(request.form.get("is_processed"))
        item.note = request.form.get("note", "").strip()
        log("update", item, details="обработано" if item.is_processed else "")
        db.session.commit()
        flash("Обращение обновлено.", "ok")
        return redirect(url_for("admin.appeals"))
    return render_template("admin/appeal_view.html", item=item)


@bp.route("/appeals/<int:item_id>/print")
@login_required
def appeal_print(item_id):
    """Обращение на отдельной странице для печати или сохранения в PDF."""
    return render_template("admin/appeal_print.html", item=get_or_404(Appeal, item_id))
