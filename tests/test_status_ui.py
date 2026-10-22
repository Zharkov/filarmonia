"""Этап C2: оформление статуса концерта — плашка на странице, метка в карточке и строке афиши."""
import pytest
from conftest import create_event, text
from test_stage_b import EVENT, edit_event

STATUSES = ["cancelled", "rescheduled", "postponed"]


@pytest.fixture
def ev_admin(app, admin):
    create_event(admin, ticket_url="https://tickets.example/1", yandex_id="123456")
    return admin


@pytest.mark.parametrize("status", STATUSES)
def test_status_plate_everywhere(app, ev_admin, status):
    extra = {"previous_starts_at": "2030-11-05T18:30"} if status == "rescheduled" else {}
    edit_event(ev_admin, app, status=status, yandex_id="123456", **extra)
    page = text(ev_admin.get(EVENT))
    assert f"event__status event__status--{status}" in page and 'role="status"' in page
    assert f"eventrow__status--{status}" in text(ev_admin.get("/afisha"))
    assert f"ecard__status ecard__status--{status}" in text(ev_admin.get("/"))
    if status == "rescheduled":
        assert "прежняя дата — 5 ноября" in text(ev_admin.get("/afisha"))
        assert "Прежняя дата: 5 ноября" in page


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_no_buy_controls_when_stopped(app, ev_admin, status):
    edit_event(ev_admin, app, status=status, yandex_id="123456")
    page = text(ev_admin.get(EVENT))
    assert "Продажа билетов остановлена" in page and "event__buy" not in page
    for url in ("/afisha", "/"):
        html = text(ev_admin.get(url))
        assert "Купить билет" not in html and "ecard__buy" not in html, url
    assert "Подробнее" in text(ev_admin.get("/afisha"))


def test_cancelled_is_dimmed_and_rescheduled_keeps_buying(app, ev_admin):
    edit_event(ev_admin, app, status="cancelled")
    assert "ecard--cancelled" in text(ev_admin.get("/"))
    assert "eventrow--cancelled" in text(ev_admin.get("/afisha"))
    assert "event__price--off" in text(ev_admin.get(EVENT))
    edit_event(ev_admin, app, status="rescheduled", previous_starts_at="2030-11-05T18:30")
    page = text(ev_admin.get(EVENT))
    assert "Купить билет" in page and "Продажа билетов остановлена" not in page
    assert "ecard--cancelled" not in text(ev_admin.get("/"))


def test_scheduled_has_no_plate(app, ev_admin):
    for url in (EVENT, "/afisha", "/"):
        html = text(ev_admin.get(url))
        for cls in ("event__status", "eventrow__status", "ecard__status", "--cancelled", "Продажа билетов остановлена"):
            assert cls not in html, (url, cls)


def test_admin_list_badge(app, ev_admin):
    edit_event(ev_admin, app, status="cancelled")
    assert "badge--stop" in text(ev_admin.get("/admin/events"))
    edit_event(ev_admin, app, status="postponed")
    assert "badge--warn" in text(ev_admin.get("/admin/events"))


def test_unknown_price_label_modifier(app, admin):
    create_event(admin, price_min="")
    assert "Цена уточняется" in text(admin.get(EVENT))
    assert "event__price--text" in text(admin.get(EVENT))
    assert "eventrow__price--text" in text(admin.get("/afisha"))


def test_consent_draft_note_is_highlighted(app):
    client = app.test_client()
    from filarmonia import seed
    from filarmonia.models import Page, db
    with app.app_context():
        pg = Page.query.filter_by(slug="soglasie-na-obrabotku-personalnyh-dannyh").first()
        if pg is None:
            pg = Page(title="Согласие", slug="soglasie-na-obrabotku-personalnyh-dannyh", is_published=True)
            db.session.add(pg)
        pg.content = seed.consent_text()
        db.session.commit()
    html = text(client.get("/info/soglasie-na-obrabotku-personalnyh-dannyh"))
    assert "prose--draft" in html
