"""Анкеты «Независимой оценки качества»: приём, письмо, защита от спама, панель."""
import smtplib

import pytest

from conftest import make_app, text
from filarmonia import mailer, surveys
from filarmonia.models import db, ActionLog, Page, Setting, SurveyResponse

URL = "/info/nezavisimaya-ocenka-kachestva/anketa/"


def add_page(app):
    with app.app_context():
        db.session.add(Page(title="Независимая оценка качества", slug="nezavisimaya-ocenka-kachestva",
                            template="nok", is_published=True))
        db.session.commit()


@pytest.fixture
def app(tmp_path):
    app = make_app(tmp_path)
    add_page(app)
    return app


def snoc_form(**over):
    data = {"org": "Филармония", "address": "Смоленск"}
    data.update({q.id: "yes" for q in surveys.SNOC.questions})
    data["q1_note"] = "Всё хорошо"
    data.update(over)
    return data


def minkult_form(**over):
    data = {q.id: "4" for q in surveys.MINKULT_SO.questions if q.kind == "scale"}
    data["q9"] = "Больше концертов"
    data.update(over)
    return data


class FakeSMTP:
    sent = []
    calls = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.calls.append("starttls")

    def login(self, user, password):
        FakeSMTP.calls.append("login")

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_page_shows_both_forms_and_external_link(app):
    html = text(app.test_client().get("/info/nezavisimaya-ocenka-kachestva"))
    assert 'id="anketa-snoc"' in html and 'id="anketa-minkult_so"' in html
    assert "forms.mkrf.ru" in html
    assert 'value="Филармония"' in html  # предзаполнено из site_name


@pytest.mark.parametrize("key,form", [("snoc", snoc_form), ("minkult_so", minkult_form)])
def test_submit_saves_response(app, key, form):
    r = app.test_client().post(URL + key, data=form())
    assert r.status_code == 302 and r.headers["Location"].endswith(f"#anketa-{key}")
    with app.app_context():
        row = SurveyResponse.query.one()
        assert row.survey == key and not row.is_emailed
        assert surveys.loads(row.answers)["q1"] in ("yes", "4")


def test_no_mail_server_does_not_fail(app):
    r = app.test_client().post(URL + "snoc", data=snoc_form(), follow_redirects=True)
    assert "Спасибо, ваши ответы отправлены" in text(r)
    with app.app_context():
        row = SurveyResponse.query.one()
        assert row.is_emailed is False and "MAIL_SERVER" in row.email_error


def test_mail_sent_to_setting(tmp_path, smtp):
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_USERNAME="site@example.ru",
                   MAIL_PASSWORD="x")
    add_page(app)
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    app.test_client().post(URL + "snoc", data=snoc_form())
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["To"] == "boss@example.ru" and msg["From"] == "site@example.ru"
    assert msg["Subject"].startswith("Анкета: Анкета Смоленского научно-образовательного центра")
    body = msg.get_content()
    assert "Довольны ли Вы комфортностью предоставления услуг организацией?" in body
    assert "Ответ: Да" in body and "Пожелания: Всё хорошо" in body
    with app.app_context():
        assert SurveyResponse.query.one().is_emailed is True


def test_empty_recipient_not_sent(tmp_path, smtp):
    """Запасного адреса в коде нет: без настройки survey_email письмо не уходит."""
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_FROM="site@example.ru")
    add_page(app)
    r = app.test_client().post(URL + "minkult_so", data=minkult_form())
    assert r.status_code == 302 and smtp.sent == []
    with app.app_context():
        row = SurveyResponse.query.one()
        assert not row.is_emailed and "получатель не задан" in row.email_error


def test_starttls_path(tmp_path, monkeypatch):
    FakeSMTP.sent, FakeSMTP.calls = [], []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_PORT=587, MAIL_USE_SSL=False,
                   MAIL_USE_TLS=True, MAIL_USERNAME="site@example.ru", MAIL_PASSWORD="x")
    add_page(app)
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    app.test_client().post(URL + "snoc", data=snoc_form())
    assert FakeSMTP.calls == ["starttls", "login"] and len(FakeSMTP.sent) == 1


def test_login_without_encryption_refused(tmp_path, smtp):
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_USE_SSL=False, MAIL_USE_TLS=False,
                   MAIL_USERNAME="site@example.ru", MAIL_PASSWORD="x")
    add_page(app)
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    app.test_client().post(URL + "snoc", data=snoc_form())
    with app.app_context():
        assert "MAIL_USE_SSL" in SurveyResponse.query.one().email_error


def test_smtp_failure_keeps_answer(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise smtplib.SMTPException("отказ")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", boom)
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_FROM="site@example.ru")
    add_page(app)
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    r = app.test_client().post(URL + "snoc", data=snoc_form(), follow_redirects=True)
    assert "Спасибо" in text(r)
    with app.app_context():
        row = SurveyResponse.query.one()
        assert not row.is_emailed and "отказ" in row.email_error


def test_header_injection_stripped():
    assert "\n" not in mailer.one_line("Тема\r\nBcc: evil@example.ru")
    assert mailer.parse_recipients("a@b.ru\nBcc: x@y.ru, bad") == []


def test_missing_required_answer(app):
    form = snoc_form()
    del form["q3"]
    r = app.test_client().post(URL + "snoc", data=form)
    html = text(r)
    assert r.status_code == 200 and "Ответьте на вопрос 3." in html
    assert 'value="Филармония"' in html and "Всё хорошо" in html  # введённое сохранено
    with app.app_context():
        assert SurveyResponse.query.count() == 0


@pytest.mark.parametrize("key,form,field,bad", [
    ("minkult_so", minkult_form, "q2", "7"),
    ("minkult_so", minkult_form, "q2", "0"),
    ("snoc", snoc_form, "q4", "может быть"),
])
def test_invalid_value_rejected(app, key, form, field, bad):
    r = app.test_client().post(URL + key, data=form(**{field: bad}))
    assert r.status_code == 200 and "выберите один из предложенных вариантов" in text(r)
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_unknown_survey_and_page(app):
    assert app.test_client().post(URL + "nope", data={}).status_code == 404
    assert app.test_client().post("/info/net/anketa/snoc", data={}).status_code == 404


def test_long_text_truncated(app):
    app.test_client().post(URL + "minkult_so", data=minkult_form(q9="я" * 5000))
    with app.app_context():
        assert len(surveys.loads(SurveyResponse.query.one().answers)["q9"]) == surveys.NOTE_MAX


def test_throttle(app):
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    r = client.post(URL + "snoc", data=snoc_form())
    assert "уже отправлена" in text(r) and "через" in text(r)
    with app.app_context():
        assert SurveyResponse.query.count() == 1
    # другая анкета не блокируется
    client.post(URL + "minkult_so", data=minkult_form())
    with app.app_context():
        assert SurveyResponse.query.count() == 2


def test_honeypot(app):
    r = app.test_client().post(URL + "snoc", data=snoc_form(website="http://spam"))
    assert r.status_code == 302
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_csrf_required(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    add_page(app)
    assert app.test_client().post(URL + "snoc", data=snoc_form()).status_code == 400


def seed_responses(app):
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form(q2="no"))
    client.post(URL + "minkult_so", data=minkult_form(q1="5", q9="=cmd"))
    with app.app_context():
        return [r.id for r in SurveyResponse.query.order_by(SurveyResponse.id)]


def test_admin_views(app, admin):
    ids = seed_responses(app)
    html = text(admin.get("/admin/surveys"))
    assert "Анкета Министерства культуры" in html and "не отправлено" in html
    assert "Довольны ли Вы комфортностью" in text(admin.get(f"/admin/surveys/{ids[0]}"))
    summary = text(admin.get("/admin/surveys/summary?survey=snoc"))
    assert "Ответов: 1" in summary and "100 %" in summary and "0 %" in summary
    page = text(admin.get("/admin/surveys/summary?survey=minkult_so"))
    assert "<td>5.0</td>" in page and "<td>4.0</td>" in page


def test_csv_export(app, admin):
    seed_responses(app)
    r = admin.get("/admin/surveys/export.csv?survey=minkult_so")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    raw = r.get_data()
    assert raw.startswith("﻿".encode("utf-8"))
    body = raw.decode("utf-8-sig")
    assert "Как Вы оцениваете информирование" in body and "'=cmd" in body and ";5;" in body


def test_delete_admin_only_and_logged(app, admin, editor):
    ids = seed_responses(app)
    assert editor.get(f"/admin/surveys/{ids[0]}").status_code == 200
    assert editor.post(f"/admin/surveys/{ids[0]}/delete").status_code == 403
    admin.post(f"/admin/surveys/{ids[0]}/delete")
    with app.app_context():
        assert SurveyResponse.query.count() == 1
        assert ActionLog.query.filter_by(object_type="survey", action="delete").count() == 1


@pytest.mark.parametrize("path", ["/admin/surveys", "/admin/surveys/summary", "/admin/surveys/export.csv",
                                  "/admin/surveys/1"])
def test_anonymous_redirected(app, path):
    r = app.test_client().get(path)
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    assert app.test_client().post("/admin/surveys/1/delete").status_code == 302


def test_request_size_limited(app):
    r = app.test_client().post(URL + "snoc", data={"q1_note": "я" * 200_000})
    assert r.status_code == 413
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_script_in_note_escaped_in_admin(app, admin):
    app.test_client().post(URL + "snoc", data=snoc_form(q1_note="<script>alert(1)</script>"))
    html = text(admin.get("/admin/surveys/1"))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_resend_button_admin_only(tmp_path, smtp):
    app = make_app(tmp_path)
    add_page(app)
    app.test_client().post(URL + "snoc", data=snoc_form())
    app.config.update(MAIL_SERVER="smtp.example.ru", MAIL_FROM="site@example.ru")
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    from conftest import login
    editor = app.test_client()
    login(editor, "editor")
    assert "Отправить ещё раз" not in text(editor.get("/admin/surveys/1"))
    assert editor.post("/admin/surveys/1/resend").status_code == 403
    assert editor.post("/admin/surveys/resend-unsent").status_code == 403
    assert smtp.sent == []
    admin = app.test_client()
    login(admin)
    assert "Отправить ещё раз" in text(admin.get("/admin/surveys/1"))
    admin.post("/admin/surveys/1/resend")
    assert len(smtp.sent) == 1
    with app.app_context():
        assert SurveyResponse.query.one().is_emailed is True
        assert ActionLog.query.filter_by(object_type="survey", action="update").count() == 1
    assert "Отправить ещё раз" not in text(admin.get("/admin/surveys/1"))


def test_resend_unsent_all(tmp_path, smtp):
    app = make_app(tmp_path, SURVEY_INTERVAL_SECONDS=0)
    add_page(app)
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    client.post(URL + "minkult_so", data=minkult_form())
    app.config.update(MAIL_SERVER="smtp.example.ru", MAIL_FROM="site@example.ru")
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    from conftest import login
    admin = app.test_client()
    login(admin)
    r = admin.post("/admin/surveys/resend-unsent", follow_redirects=True)
    assert "Отправлено писем: 2" in text(r) and len(smtp.sent) == 2


def test_summary_header_per_question_kind(app, admin):
    seed_responses(app)
    html = text(admin.get("/admin/surveys/summary?survey=snoc"))
    assert "Доля «Да»" in html
    assert "Средний балл" in text(admin.get("/admin/surveys/summary?survey=minkult_so"))


def test_migration_0014_adds_setting_and_relabels_map(tmp_path):
    from alembic import command
    from filarmonia import migrate
    import os
    from filarmonia import create_app
    from sqlalchemy import text as sql
    os.makedirs(tmp_path / "mig", exist_ok=True)
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "mig" / "m.db"),
                     UPLOAD_FOLDER=str(tmp_path / "mig" / "u"), TESTING=True, SECRET_KEY="k")
    cfg = migrate.alembic_config(app)
    command.upgrade(cfg, "d2b6f1a8c995")
    with app.app_context():
        db.session.execute(sql("INSERT INTO settings (key, value, title, \"group\", kind) VALUES "
                               "('map_point', '54.7, 32.0', 'Блок о здании: метка', 'Главная страница', 'text')"))
        db.session.commit()
    command.upgrade(cfg, "head")
    with app.app_context():
        email = db.session.get(Setting, "survey_email")
        point = db.session.get(Setting, "map_point")
        assert email.value == "test@test.ru" and email.group == "Независимая оценка качества"
        assert point.value == "54.7, 32.0" and point.group == "Контакты" and point.title.startswith("Контакты:")
    command.downgrade(cfg, "d2b6f1a8c995")
    with app.app_context():
        db.session.expire_all()
        assert db.session.get(Setting, "survey_email") is None
        assert db.session.get(Setting, "map_point").group == "Главная страница"


def test_mail_sent_in_background_thread(tmp_path, smtp):
    import threading
    app = make_app(tmp_path, MAIL_SERVER="smtp.example.ru", MAIL_FROM="site@example.ru")
    add_page(app)
    with app.app_context():
        db.session.add(Setting(key="survey_email", value="boss@example.ru"))
        db.session.commit()
    app.config["TESTING"] = False   # вне проверок письмо уходит в потоке
    r = app.test_client().post(URL + "snoc", data=snoc_form())
    assert r.status_code == 302
    for t in threading.enumerate():
        if t.name.startswith("survey-mail-"):
            t.join(10)
    assert len(smtp.sent) == 1
    with app.app_context():
        assert SurveyResponse.query.one().is_emailed is True
