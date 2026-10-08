"""Вход и выход сотрудников, защита от подбора пароля."""
import time

from flask import render_template, request, redirect, url_for, flash, session, current_app

from ..models import db, User
from .. import throttle, utils
from . import bp
from .common import safe_next


# Неудачные попытки входа считаются по паре «логин + адрес» в таблице throttles:
# счётчик общий для всех процессов gunicorn и переживает перезапуск сайта.
def _attempt_key() -> str:
    return f"login:{request.form.get('login', '').strip().lower()}:{request.remote_addr or ''}"


def login_locked_for() -> int:
    """Сколько секунд осталось до конца блокировки. 0 — вход разрешён."""
    cfg = current_app.config
    count, last = throttle.state(_attempt_key())
    if count < cfg["LOGIN_MAX_ATTEMPTS"]:
        return 0
    return max(0, int(cfg["LOGIN_LOCKOUT_SECONDS"] - (time.time() - last)))


def note_login_failure() -> None:
    """Считает неудачу входа. Отсидел блокировку — счёт начинается заново:
    иначе одна опечатка после разблокировки сразу запирала бы ещё на четверть часа."""
    throttle.hit(_attempt_key(), current_app.config["LOGIN_LOCKOUT_SECONDS"])


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        locked = login_locked_for()
        if locked:
            flash(f"Слишком много попыток входа. Повторите через "
                  f"{utils.plural(locked // 60 + 1, 'минуту', 'минуты', 'минут')}.", "error")
            return render_template("admin/login.html")

        user = User.query.filter_by(login=request.form.get("login", "").strip()).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            throttle.reset(_attempt_key())
            session.clear()
            # Сеанс ограничен по времени (PERMANENT_SESSION_LIFETIME), а при
            # бездействии завершается раньше — см. load_user в __init__.py
            session.permanent = True
            session["user_id"] = user.id
            session["seen"] = time.time()
            user.last_login_at = utils.utcnow()
            db.session.commit()
            return redirect(safe_next(request.args.get("next", "")))

        note_login_failure()
        flash("Неверный логин или пароль.", "error")
    return render_template("admin/login.html")


# Только POST с CSRF-токеном: иначе любая страница могла бы разлогинить
# сотрудника картинкой с этим адресом
@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("public.index"))
