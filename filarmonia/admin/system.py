"""Только для администратора: настройки сайта, сотрудники, журнал действий."""
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, g

from ..models import db, User, Setting, ActionLog
from .. import utils
from . import bp
from .common import (
    ACTION_LABELS, OBJECT_LABELS, admin_required, edited, get_or_404, log, paginated,
    release_files, replace_file, rich, save, search_text, sorted_by, uploaded_name,
)


MIN_PASSWORD_LENGTH = 8

# Смоленск живёт по московскому времени, а журнал пишет время в UTC
MOSCOW_OFFSET = timedelta(hours=3)

# Настройки, куда вставляется код сторонних виджетов: их не очищаем
WIDGET_SETTINGS = {"pos_widget", "history_map"}


# Настройки
# Только администратор: здесь меняются телефон кассы, адрес учреждения
# и тексты, общие для всего сайта
@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    rows = Setting.query.order_by(Setting.group, Setting.title).all()
    if request.method == "POST":
        old_files = []
        for row in rows:
            if row.kind == "file":
                kinds = ("video",) if "video" in row.key else ("image",)
                try:
                    old_files += replace_file(row, "value", uploaded_name("f_" + row.key, kinds))
                except ValueError as exc:
                    flash(str(exc), "error")
            elif row.kind == "bool":
                row.value = "1" if request.form.get(row.key) else ""
            elif row.kind == "html" and row.key not in WIDGET_SETTINGS:
                row.value = rich(row.key)
            else:
                row.value = request.form.get(row.key, "")
        log("update", object_type="settings", details="настройки сайта")
        db.session.commit()
        release_files(old_files)
        flash("Настройки сохранены.", "ok")
        return redirect(url_for("admin.settings_page"))

    grouped = {}
    for row in rows:
        grouped.setdefault(row.group, []).append(row)
    return render_template("admin/settings.html", grouped=grouped, widget_keys=WIDGET_SETTINGS,
                           values={row.key: row.value for row in rows})


# Пользователи
@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        f = request.form
        item_id = utils.parse_int(f.get("id"))
        item = get_or_404(User, item_id) if item_id else User()
        login_name = f.get("login", "").strip()
        password = f.get("password", "").strip()
        role = f.get("role") if f.get("role") in ("admin", "editor") else "editor"
        is_active = bool(f.get("is_active"))
        taken = User.query.filter(User.login == login_name, User.id != (item.id or 0)).first()
        if not login_name:
            flash("Укажите логин.", "error")
        elif taken:
            flash(f"Логин «{login_name}» уже занят. Выберите другой.", "error")
        elif item.id is None and not password:
            flash("Задайте пароль новому сотруднику.", "error")
        # Проверяем любой введённый пароль, а не только у новых: иначе смена
        # пароля существующему сотруднику проходила мимо ограничения длины
        elif password and len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Пароль — не короче {MIN_PASSWORD_LENGTH} символов.", "error")
        # Иначе можно случайно запереть панель администратора от самого себя
        elif item.id == g.user.id and (role != "admin" or not is_active):
            flash("Нельзя снять права администратора или отключить доступ для собственной учётной записи.", "error")
        else:
            item.login, item.name = login_name, f.get("name", "").strip()
            item.role, item.is_active = role, is_active
            if password:
                item.set_password(password)
            save(item, "Сотрудник сохранён.")
            return redirect(url_for("admin.users"))
        # Ошибка: показываем ту же форму с введёнными данными, а не пустую
        return users_page(edit=item if item.id else None, form=f)
    return users_page(edit=edited(User))


def users_page(edit=None, form=None):
    q = User.query
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(User.login, search) | utils.like_ci(User.name, search))
    if request.args.get("role") in ("admin", "editor"):
        q = q.filter(User.role == request.args.get("role"))
    if request.args.get("status") in ("on", "off"):
        q = q.filter(User.is_active.is_(request.args.get("status") == "on"))
    q, sorting = sorted_by(
        q, {"login": User.login, "name": User.name, "role": User.role,
            "last_login": User.last_login_at},
        default="login", tiebreak=User.id,
    )
    return render_template("admin/users.html", items=q.all(), search=search, sorting=sorting,
                           edit=edit, form=form)


@bp.route("/users/<int:item_id>/delete", methods=["POST"])
@admin_required
def user_delete(item_id):
    item = get_or_404(User, item_id)
    if item.id == g.user.id:
        flash("Нельзя удалить собственную учётную запись.", "error")
    else:
        log("delete", item)
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("admin.users"))


# Журнал действий
@bp.route("/log")
@admin_required
def action_log():
    q = ActionLog.query
    a = request.args
    search = search_text()
    if search:
        q = q.filter(utils.like_ci(ActionLog.title, search) | utils.like_ci(ActionLog.details, search))
    if utils.parse_int(a.get("user")):
        q = q.filter(ActionLog.user_id == utils.parse_int(a.get("user")))
    if a.get("type") in OBJECT_LABELS:
        q = q.filter(ActionLog.object_type == a.get("type"))
    if a.get("action") in ACTION_LABELS:
        q = q.filter(ActionLog.action == a.get("action"))
    # Даты в фильтре — московские, а в журнале время хранится в UTC
    date_from, date_to = utils.parse_date(a.get("from", "")), utils.parse_date(a.get("to", ""))
    if date_from:
        q = q.filter(ActionLog.created_at >= datetime.combine(date_from, datetime.min.time()) - MOSCOW_OFFSET)
    if date_to:
        q = q.filter(ActionLog.created_at <= datetime.combine(date_to, datetime.max.time()) - MOSCOW_OFFSET)
    q, sorting = sorted_by(
        q, {"date": ActionLog.created_at, "user": ActionLog.user_name, "action": ActionLog.action,
            "type": ActionLog.object_type, "title": ActionLog.title},
        default="date", default_dir="desc", tiebreak=ActionLog.id.desc(),
    )
    return render_template(
        "admin/log.html", items=paginated(q, 50), search=search, sorting=sorting,
        users=User.query.order_by(User.login).all(),
        object_labels=OBJECT_LABELS, action_labels=ACTION_LABELS,
    )
