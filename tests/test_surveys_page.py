"""Публичная страница «Независимой оценки качества»: разметка анкет, ошибки, «Спасибо», регресс flash."""
import re

import pytest

from conftest import make_app, text
from filarmonia import surveys
from filarmonia.models import db, Page, Setting, SurveyResponse

SLUG = "nezavisimaya-ocenka-kachestva"
PAGE = f"/info/{SLUG}"
URL = f"{PAGE}/anketa/"
CONTACTS = "/info/kontakty-i-shema-proezda"
THANKS = "Спасибо, ваши ответы отправлены."


def add_pages(app):
    with app.app_context():
        db.session.add(Page(title="Независимая оценка качества", slug=SLUG, template="nok", is_published=True))
        db.session.add(Page(title="Контакты", slug="kontakty-i-shema-proezda", template="contacts",
                            content="<p>Как добраться</p>", is_published=True))
        db.session.add(Page(title="Обычная", slug="obychnaya", is_published=True))
        db.session.commit()


@pytest.fixture
def app(tmp_path):
    app = make_app(tmp_path)
    add_pages(app)
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


def card(html, key):
    """HTML одной анкеты: от <section id="anketa-<key>"> до закрывающего </section>."""
    m = re.search(r'<section class="survey[^"]*" id="anketa-%s".*?</section>' % key, html, re.S)
    assert m, f"нет анкеты {key}"
    return m.group(0)


def details_tag(section):
    return re.search(r"<details[^>]*>", section).group(0)


def is_open(section):
    return re.search(r"\bopen\b", details_tag(section)) is not None


# ---------- a) разметка страницы ----------

def test_page_ok_with_external_link_and_qr(app):
    r = app.test_client().get(PAGE)
    html = text(r)
    assert r.status_code == 200
    assert 'href="https://forms.mkrf.ru/e/2579/xTPLeBU7/"' in html
    assert "<svg" in html and "nok__qr" in html


def test_external_link_follows_setting(app):
    with app.app_context():
        db.session.add(Setting(key="nok_survey_url", value="https://example.org/anketa/", kind="text"))
        db.session.commit()
    html = text(app.test_client().get(PAGE))
    assert 'href="https://example.org/anketa/"' in html and "forms.mkrf.ru" not in html


def test_snoc_form_markup(app):
    html = text(app.test_client().get(PAGE))
    sec = card(html, "snoc")
    assert len(surveys.SNOC.questions) == 10
    for q in surveys.SNOC.questions:
        assert q.text in sec.replace("&#34;", '"').replace("&quot;", '"') or q.text[:60] in sec
    assert sec.count('type="radio"') == 20
    assert sec.count('value="yes"') == 10 and sec.count('value="no"') == 10
    assert 'name="csrf_token"' in sec
    assert 'name="website"' in sec and 'tabindex="-1"' in sec and 'autocomplete="off"' in sec
    assert f'action="{PAGE}/anketa/snoc"' in sec
    assert not is_open(sec)  # без ошибок карточка свёрнута


def test_minkult_form_markup(app):
    html = text(app.test_client().get(PAGE))
    sec = card(html, "minkult_so")
    scale = [q for q in surveys.MINKULT_SO.questions if q.kind == "scale"]
    assert len(scale) == 8
    for q in scale:
        assert q.text[:60] in sec
    assert sec.count('type="radio"') == 40
    for n in range(1, 6):
        assert sec.count(f'value="{n}"') == 8
    assert 'name="q9"' in sec  # поле предложений
    assert 'name="csrf_token"' in sec and 'name="website"' in sec
    assert not is_open(sec)


def test_csrf_token_non_empty_when_enabled(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    add_pages(app)
    html = text(app.test_client().get(PAGE))
    tokens = re.findall(r'name="csrf_token" value="([^"]+)"', card(html, "snoc"))
    assert tokens and all(len(t) > 20 for t in tokens)


def test_unpublished_nok_page_hides_forms_and_post(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        db.session.add(Page(title="НОК", slug=SLUG, template="nok", is_published=False))
        db.session.commit()
    client = app.test_client()
    assert client.get(PAGE).status_code in (302, 403, 404)
    assert client.post(URL + "snoc", data=snoc_form()).status_code in (302, 403, 404)
    with app.app_context():
        assert SurveyResponse.query.count() == 0


# ---------- b) пропущенный вопрос ----------

def test_missing_answer_shows_errors_and_opens_form(app):
    form = snoc_form()
    del form["q3"]
    r = app.test_client().post(URL + "snoc", data=form)
    html = text(r)
    assert r.status_code == 200
    sec = card(html, "snoc")
    assert is_open(sec) and "survey is-open" in sec
    assert "Анкету не удалось отправить" in sec and "Ответьте на вопрос 3." in sec
    assert 'role="alert"' in sec
    # другая анкета осталась свёрнутой и без ошибок
    other = card(html, "minkult_so")
    assert not is_open(other) and "Анкету не удалось отправить" not in other
    # введённые ответы сохранены: 9 из 10 отмечены, поля и пожелания на месте
    assert len(re.findall(r'value="yes"\s+checked', sec)) == 9
    assert 'value="Филармония"' in sec and 'value="Смоленск"' in sec and "Всё хорошо" in sec
    # aria-invalid ровно у вопроса 3
    fieldsets = re.findall(r"<fieldset.*?</fieldset>", sec, re.S)
    assert len(fieldsets) == 10
    invalid = [f for f in fieldsets if 'aria-invalid="true"' in f]
    assert len(invalid) == 1 and 'survey__num">3<' in invalid[0]
    assert "Выберите ответ на этот вопрос." in invalid[0]
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_missing_scale_answers_keep_checked_and_flag_only_missing(app):
    form = minkult_form()
    del form["q2"], form["q5"]
    sec = card(text(app.test_client().post(URL + "minkult_so", data=form)), "minkult_so")
    assert is_open(sec)
    assert "Ответьте на вопрос 2." in sec and "Ответьте на вопрос 5." in sec
    assert len(re.findall(r'value="4"\s+checked', sec)) == 6
    assert sec.count('aria-invalid="true"') == 2
    assert "Больше концертов" in sec


def test_invalid_value_marks_question_invalid(app):
    sec = card(text(app.test_client().post(URL + "minkult_so", data=minkult_form(q2="7"))), "minkult_so")
    assert "выберите один из предложенных вариантов" in sec
    assert sec.count('aria-invalid="true"') == 1


def test_all_missing_flags_all_questions(app):
    sec = card(text(app.test_client().post(URL + "snoc", data={})), "snoc")
    assert sec.count('aria-invalid="true"') == 10
    assert len(re.findall(r"Ответьте на вопрос \d+\.", sec)) == 10


# ---------- c) успех, «Спасибо», регресс flash ----------

@pytest.mark.parametrize("key,form", [("snoc", snoc_form), ("minkult_so", minkult_form)])
def test_success_redirects_to_anchor_and_shows_thanks(app, key, form):
    client = app.test_client()
    r = client.post(URL + key, data=form())
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"{PAGE}#anketa-{key}")
    html = text(client.get(PAGE))
    assert THANKS in html
    assert html.count(THANKS) <= 2            # общий flash из base.html на странице НОК скрыт
    assert THANKS in card(html, key)          # выводится внутри карточки отправленной анкеты
    # одноразово: при следующем заходе сообщения нет
    assert THANKS not in text(client.get(PAGE))


def test_thanks_only_in_submitted_card(app):
    """БАГ: _survey_form.html выводит все flash в КАЖДОЙ карточке, «Спасибо» дублируется в чужой анкете."""
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    html = text(client.get(PAGE))
    assert THANKS in card(html, "snoc")
    assert THANKS not in card(html, "minkult_so")
    assert html.count(THANKS) == 1


def test_thanks_via_follow_redirects(app):
    r = app.test_client().post(URL + "snoc", data=snoc_form(), follow_redirects=True)
    assert r.status_code == 200 and THANKS in text(r)


def test_general_flash_still_shown_on_contacts_page(app):
    client = app.test_client()
    r = client.post("/obrashcheniya", data={
        "name": "Иван", "email": "ivan@example.ru", "message": "Здравствуйте", "consent": "1",
        "back": CONTACTS}, follow_redirects=True)
    html = text(r)
    assert r.status_code == 200
    assert html.count("Обращение принято") == 1
    assert '<div class="flash ' in html or 'class="flash"' in html
    with app.app_context():
        from filarmonia.models import Appeal
        assert Appeal.query.count() == 1


def test_general_flash_error_on_contacts_page(app):
    r = app.test_client().post("/obrashcheniya", data={
        "name": "Иван", "email": "ivan@example.ru", "message": "Текст", "back": CONTACTS},
        follow_redirects=True)
    html = text(r)
    assert "Без согласия на обработку персональных данных" in html
    assert "flash--error" in html


def test_general_flash_on_standalone_appeals_page(app):
    r = app.test_client().post("/obrashcheniya", data={"name": "Иван"}, follow_redirects=True)
    assert "Без согласия" in text(r)


def test_survey_thanks_not_leaked_to_other_pages(app):
    """Flash анкеты потребляется страницей НОК; на соседних страницах его нет."""
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    html = text(client.get("/info/obychnaya"))
    # если страница НОК не открывалась, сообщение показывается общим flash (как у любых других сообщений)
    assert html.count(THANKS) <= 1
    assert THANKS not in text(client.get(PAGE))


def test_flash_not_hidden_on_non_nok_pages(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s["_flashes"] = [("ok", "Проверочное сообщение")]
    html = text(client.get("/info/obychnaya"))
    assert "Проверочное сообщение" in html


# ---------- d) пауза ----------

def test_second_survey_not_blocked_by_first(app):
    client = app.test_client()
    assert client.post(URL + "snoc", data=snoc_form()).status_code == 302
    assert client.post(URL + "minkult_so", data=minkult_form()).status_code == 302
    with app.app_context():
        assert sorted(r.survey for r in SurveyResponse.query) == ["minkult_so", "snoc"]


def test_same_survey_blocked_within_interval(app):
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    r = client.post(URL + "snoc", data=snoc_form())
    assert r.status_code == 200
    sec = card(text(r), "snoc")
    assert "Анкета уже отправлена" in sec and "через" in sec and is_open(sec)
    # ответы не потеряны и вопросы не помечены ошибочными
    assert len(re.findall(r'value="yes"\s+checked', sec)) == 10
    assert 'aria-invalid="true"' not in sec
    with app.app_context():
        assert SurveyResponse.query.count() == 1


def test_same_survey_allowed_when_interval_zero(tmp_path):
    app = make_app(tmp_path, SURVEY_INTERVAL_SECONDS=0)
    add_pages(app)
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form())
    client.post(URL + "snoc", data=snoc_form())
    with app.app_context():
        assert SurveyResponse.query.count() == 2


def test_failed_validation_does_not_start_pause(app):
    client = app.test_client()
    client.post(URL + "snoc", data={})
    assert client.post(URL + "snoc", data=snoc_form()).status_code == 302
    with app.app_context():
        assert SurveyResponse.query.count() == 1


# ---------- e) 404 ----------

@pytest.mark.parametrize("path", ["/info/obychnaya", CONTACTS, "/info/net-takoy"])
def test_post_on_non_nok_page_404(app, path):
    r = app.test_client().post(f"{path}/anketa/snoc", data=snoc_form())
    assert r.status_code == 404
    with app.app_context():
        assert SurveyResponse.query.count() == 0


@pytest.mark.parametrize("key", ["nope", "SNOC", "minkult", "snoc%20", "..", "q1"])
def test_unknown_survey_key_404(app, key):
    assert app.test_client().post(URL + key, data=snoc_form()).status_code == 404


def test_get_on_submit_url_not_allowed(app):
    assert app.test_client().get(URL + "snoc").status_code == 405


# ---------- f) honeypot ----------

@pytest.mark.parametrize("key,form", [("snoc", snoc_form), ("minkult_so", minkult_form)])
def test_honeypot_looks_like_success_but_saves_nothing(app, key, form):
    client = app.test_client()
    r = client.post(URL + key, data=form(website="http://spam.example"))
    assert r.status_code == 302 and r.headers["Location"].endswith(f"{PAGE}#anketa-{key}")
    assert THANKS in text(client.get(PAGE))
    with app.app_context():
        assert SurveyResponse.query.count() == 0


def test_honeypot_does_not_start_pause(app):
    client = app.test_client()
    client.post(URL + "snoc", data=snoc_form(website="x"))
    assert client.post(URL + "snoc", data=snoc_form()).status_code == 302
    with app.app_context():
        assert SurveyResponse.query.count() == 1


def test_honeypot_with_incomplete_form_still_looks_like_success(app):
    r = app.test_client().post(URL + "snoc", data={"website": "x"})
    assert r.status_code == 302
    with app.app_context():
        assert SurveyResponse.query.count() == 0


# ---------- XSS в отражённых значениях ----------

def test_reflected_values_escaped(app):
    form = snoc_form(org='"><script>alert(1)</script>', q1_note="</textarea><script>alert(2)</script>")
    del form["q3"]
    html = text(app.test_client().post(URL + "snoc", data=form))
    assert "<script>alert(1)</script>" not in html and "<script>alert(2)</script>" not in html
