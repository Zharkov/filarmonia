"""Отправка писем по SMTP на стандартной библиотеке.

Настройки берутся из MAIL_* (см. config.py и .env.example). Пустой MAIL_SERVER —
почта выключена: письмо не отправляется, и это не считается ошибкой сайта.
"""
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app

ADDRESS_RE = re.compile(r"^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$")


class MailError(Exception):
    """Письмо не отправлено; текст ошибки можно показать сотруднику."""


def one_line(value: str) -> str:
    """Значение для заголовка письма: переводы строк превращают его в пару заголовков."""
    return " ".join(str(value).split())


def parse_recipients(raw: str) -> list:
    """Адреса из настройки «через запятую». Негодные отбрасываются."""
    parts = [p.strip() for p in re.split(r"[,;]", raw or "")]
    return [p for p in parts if ADDRESS_RE.match(p)]


def enabled() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def send(to: str, subject: str, body: str) -> None:
    """Отправляет текстовое письмо. При сбое бросает MailError.

    Вызывающий код сам решает, что делать с ошибкой: ответ на анкету к этому
    моменту уже сохранён, и посетитель сбоя почты видеть не должен.
    """
    cfg = current_app.config
    recipients = parse_recipients(to)
    if not recipients:
        raise MailError("не задан корректный адрес получателя")
    sender = one_line(cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME") or "")
    if not ADDRESS_RE.match(sender):
        raise MailError("не задан корректный адрес отправителя (MAIL_FROM или MAIL_USERNAME)")

    if cfg.get("MAIL_USERNAME") and not (cfg["MAIL_USE_SSL"] or cfg["MAIL_USE_TLS"]):
        # Логин и пароль без шифрования ушли бы по сети открытым текстом
        raise MailError("для входа на почтовый сервер нужен MAIL_USE_SSL или MAIL_USE_TLS")

    host, port, timeout = cfg["MAIL_SERVER"], cfg["MAIL_PORT"], cfg["MAIL_TIMEOUT"]
    try:
        message = EmailMessage()
        message["Subject"] = one_line(subject)
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(body, charset="utf-8")
        if cfg["MAIL_USE_SSL"]:
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
        with smtp:
            if cfg["MAIL_USE_TLS"] and not cfg["MAIL_USE_SSL"]:
                smtp.starttls(context=ssl.create_default_context())
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD", ""))
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as error:   # ValueError включает UnicodeError
        raise MailError(f"{type(error).__name__}: {error}"[:400]) from error


def deliver_survey(response_id: int) -> bool:
    """Отправляет письмо с ответом на анкету и отмечает результат в записи.

    Ответ к этому моменту уже в базе, поэтому любой сбой только пишется в журнал
    и в поле email_error: посетитель его не видит. Возвращает, ушло ли письмо.
    """
    from .models import db, SurveyResponse, Setting
    from . import surveys, utils

    row = db.session.get(SurveyResponse, response_id)
    survey = surveys.get(row.survey) if row else None
    if row is None or survey is None:
        return False
    recipient = Setting.get("survey_email", "")
    if not enabled():
        error = "Почта не настроена (MAIL_SERVER пуст)"
    elif not recipient.strip():
        error = "получатель не задан (настройка survey_email)"
    else:
        when = utils.to_moscow(row.created_at)
        lines = [survey.title, survey.subtitle, f"Получено: {utils.ru_datetime(when)} (МСК)", ""]
        for label, value, note in surveys.rows(survey, surveys.loads(row.answers)):
            lines += [label, f"  Ответ: {value}"]
            if note:
                lines.append(f"  Пожелания: {note}")
            lines.append("")
        try:
            send(recipient, f"Анкета: {survey.title} — {utils.ru_date(when)}", chr(10).join(lines))
            error = ""
        except Exception as exc:  # noqa: BLE001 — сбой почты не должен ломать ответ посетителю
            current_app.logger.warning("Анкета %s: письмо не отправлено: %s", row.id, exc)
            error = str(exc)[:400]
    row.is_emailed, row.email_error = not error, error
    db.session.commit()
    return not error


def deliver_survey_later(response_id: int) -> None:
    """Отправка письма в фоне, чтобы посетитель не ждал почтовый сервер.

    В проверках (TESTING) и при MAIL_ASYNC=0 письмо уходит сразу: результат
    должен быть известен к концу запроса.
    """
    app = current_app._get_current_object()
    if app.testing or not app.config.get("MAIL_ASYNC", True):
        deliver_survey(response_id)
        return

    def work():
        with app.app_context():
            try:
                deliver_survey(response_id)
            except Exception:  # noqa: BLE001
                app.logger.exception("Анкета %s: ошибка при отправке письма", response_id)
            finally:
                from .models import db
                db.session.remove()

    threading.Thread(target=work, name=f"survey-mail-{response_id}", daemon=True).start()
