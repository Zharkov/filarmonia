"""Вход и выход сотрудников, защита от подбора пароля."""
import secrets
import time

from flask import render_template, request, redirect, url_for, flash, session, current_app

from werkzeug.security import check_password_hash, generate_password_hash

from ..models import db, User
from .. import throttle, utils
from . import bp
from .common import CONTROL_CHARS, safe_next


# Предел длины логина в ключе счётчика: колонка throttles.key — 300 знаков, а логин присылает кто угодно
LOGIN_KEY_MAX = 64
_dummy_hash = None


def spend_password_time(password: str) -> None:
    """Проверка пароля «в пустоту» для несуществующего логина.

    Без неё ответ на неизвестный логин приходит заметно быстрее: хеш не считается,
    и по времени ответа можно узнать, какие логины есть. Заглушка строится тем же
    алгоритмом, что и пароли сотрудников, и создаётся при первом использовании.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = generate_password_hash(secrets.token_hex(16))
    check_password_hash(_dummy_hash, password)


# Неудачные попытки входа считаются по паре «логин + адрес» в таблице throttles:
# счётчик общий для всех процессов gunicorn и переживает перезапуск сайта.
def _attempt_key() -> str:
    login_name = request.form.get("login", "").strip().lower()[:LOGIN_KEY_MAX]
    return f"login:{login_name}:{request.remote_addr or ''}"


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

        user = User.query.filter_by(login=CONTROL_CHARS.sub("", request.form.get("login", "")).strip()).first()
        password = request.form.get("password", "")
        if user is None:
            spend_password_time(password)
            password_ok = False
        else:
            # Пароль проверяется и у отключённого сотрудника: время ответа не выдаёт отключение
            password_ok = user.check_password(password)
        if user and user.is_active and password_ok:
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
