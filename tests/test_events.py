"""Афиша: события, баннеры на афише, фото и видео, копирование."""
import io
import os

from conftest import create_event, png, text

from filarmonia.models import db, Event, MediaItem, EventBadge, Setting

RUTUBE_URL = "https://rutube.ru/video/" + "a1b2c3d4" * 4 + "/"


def event_id(app, title="Тестовый концерт"):
    with app.app_context():
        return Event.query.filter_by(title=title).first().id


def test_create_event_with_poster(app, admin):
    create_event(admin, show_pushkin="1", show_benefits="1",
                 benefits_text="<p>Пенсионерам 250 руб.</p>", poster=(png(), "afisha.png"))
    with app.app_context():
        ev = Event.query.filter_by(title="Тестовый концерт").first()
        assert ev.slug == "testovyy-koncert"
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], ev.poster))

    html = text(admin.get("/afisha/testovyy-koncert"))
    assert "Пенсионерам 250 руб." in html
    assert "Пушкинской картой" in html
    # Кнопки «Купить билет» и «Заказать по телефону» со страницы события убраны
    assert "Заказать по телефону" not in html and 'class="btn btn--primary"' not in html


def test_blocks_switch_off(app, admin):
    create_event(admin, show_benefits="1", benefits_text="<p>Пенсионерам 250 руб.</p>")
    eid = event_id(app)
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "photo",
                                         "file": (png(), "f.png")}, content_type="multipart/form-data")
    assert "Фото и видео" in text(admin.get("/afisha/testovyy-koncert"))

    admin.post(f"/admin/events/{eid}", data={"title": "Тестовый концерт", "starts_at": "2030-12-31T19:00",
                                             "is_published": "1"}, content_type="multipart/form-data")
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert "Пенсионерам 250 руб." not in html
    assert "Фото и видео" not in html


def test_badge_on_poster(app, admin):
    create_event(admin)
    eid = event_id(app)
    admin.post(f"/admin/events/{eid}/badges", data={
        "text": "Пушкинская карта", "hint": "Оплата через Госуслуги Культура",
        "position": "top-left", "style": "brick"})
    admin.post(f"/admin/events/{eid}/badges", data={"text": "Премьера", "position": "top-left"})
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert 'class="pin pin--brick"' in html and "Госуслуги Культура" in html
    # Два баннера в одном углу — в одном столбике, а не друг на друге
    assert html.count('class="pins pins--top-left"') == 1 and "Премьера" in html


def test_media_photos_and_video(app, admin):
    create_event(admin)
    eid = event_id(app)
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "photo",
                                         "file": [(png(), "a.png"), (png(), "b.png")]},
               content_type="multipart/form-data")
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "video",
                                         "url": RUTUBE_URL, "title": "Ролик"},
               content_type="multipart/form-data")
    with app.app_context():
        assert MediaItem.query.filter_by(event_id=eid, kind="photo").count() == 2
        video = MediaItem.query.filter_by(event_id=eid, kind="video").first()
        assert "rutube.ru/play/embed" in video.embed


def test_executable_rejected(app, admin):
    create_event(admin)
    r = admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(event_id(app)),
                                             "kind": "photo", "file": (io.BytesIO(b"MZ"), "virus.exe")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert "Недопустимый тип файла" in text(r)


def test_media_reorder(app, admin):
    create_event(admin)
    eid = event_id(app)
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "photo",
                                         "file": [(png(), "first.png"), (png(), "second.png")]},
               content_type="multipart/form-data")
    with app.app_context():
        first, second = MediaItem.query.filter_by(event_id=eid).order_by(MediaItem.sort).all()
        first_id, second_id = first.id, second.id
    admin.post(f"/admin/media/{second_id}/move", data={"dir": "up"})
    with app.app_context():
        order = [m.id for m in MediaItem.query.filter_by(event_id=eid).order_by(MediaItem.sort)]
    assert order == [second_id, first_id]


def test_copy_event(app, admin):
    create_event(admin, show_pushkin="1")
    eid = event_id(app)
    admin.post(f"/admin/events/{eid}/badges", data={"text": "Премьера"})
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "photo",
                                         "file": (png(), "f.png")}, content_type="multipart/form-data")
    r = admin.post(f"/admin/events/{eid}/copy", follow_redirects=True)
    assert "Копия создана и пока скрыта" in text(r)
    with app.app_context():
        copies = Event.query.filter_by(title="Тестовый концерт").order_by(Event.id).all()
        assert len(copies) == 2
        copy = copies[1]
        assert copy.slug != copies[0].slug
        assert not copy.is_published and copy.show_pushkin
        assert [b.text for b in copy.badges] == ["Премьера"]
        assert copy.media[0].file == copies[0].media[0].file


def test_hall_widget_only_admin(app, admin, editor):
    create_event(admin, hall_widget='<div id="hall-scheme"></div>')
    eid = event_id(app)
    assert 'id="hall-scheme"' in text(admin.get("/afisha/testovyy-koncert"))
    editor.post(f"/admin/events/{eid}", data={
        "title": "Тестовый концерт", "starts_at": "2030-12-31T19:00", "is_published": "1",
        "hall_widget": "<script>alert(1)</script>"}, content_type="multipart/form-data")
    with app.app_context():
        assert db.session.get(Event, eid).hall_widget == '<div id="hall-scheme"></div>'


def test_description_sanitized(app, editor):
    create_event(editor, description='<p onclick="steal()">Текст<script>alert(1)</script></p>'
                                     '<a href="javascript:alert(1)">ссылка</a>')
    with app.app_context():
        html = Event.query.first().description
    assert "Текст" in html
    assert "script" not in html and "onclick" not in html and "javascript:" not in html


def test_delete_event_removes_files(app, admin):
    create_event(admin, poster=(png((900, 1200)), "poster.png"))
    eid = event_id(app)
    with app.app_context():
        poster = db.session.get(Event, eid).poster
    folder = app.config["UPLOAD_FOLDER"]
    assert os.path.exists(os.path.join(folder, poster))
    assert any(name.endswith("-400w.webp") for name in os.listdir(folder))
    admin.post(f"/admin/events/{eid}/delete")
    with app.app_context():
        assert db.session.get(Event, eid) is None
    assert os.listdir(folder) == []


def test_shared_file_survives_copy_deletion(app, admin):
    create_event(admin)
    eid = event_id(app)
    admin.post("/admin/media/add", data={"owner": "event", "owner_id": str(eid), "kind": "photo",
                                         "file": (png(), "f.png")}, content_type="multipart/form-data")
    admin.post(f"/admin/events/{eid}/copy")
    with app.app_context():
        copy_id = Event.query.order_by(Event.id.desc()).first().id
        shared = MediaItem.query.filter_by(event_id=eid).first().file
    admin.post(f"/admin/events/{copy_id}/delete")
    assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], shared))


def test_replaced_poster_removed(app, admin):
    create_event(admin, poster=(png(), "old.png"))
    eid = event_id(app)
    with app.app_context():
        old = db.session.get(Event, eid).poster
    admin.post(f"/admin/events/{eid}", data={
        "title": "Тестовый концерт", "starts_at": "2030-12-31T19:00", "poster": (png(), "new.png")},
        content_type="multipart/form-data")
    assert not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], old))


def test_toggle_publish_from_list(app, admin):
    create_event(admin)
    eid = event_id(app)
    guest = app.test_client()
    assert guest.get("/afisha/testovyy-koncert").status_code == 200

    back = "/admin/events?scope=all&sort=title&dir=desc"
    r = admin.post(f"/admin/publish/event/{eid}", data={"next": back})
    assert r.headers["Location"].endswith(f"{back}#row-{eid}")
    with app.app_context():
        assert not db.session.get(Event, eid).is_published
    assert guest.get("/afisha/testovyy-koncert").status_code == 404

    r = admin.post(f"/admin/publish/event/{eid}", data={"next": "https://evil.example/"})
    assert "evil.example" not in r.headers["Location"]
    with app.app_context():
        assert db.session.get(Event, eid).is_published
    html = text(admin.get("/admin/events?scope=all"))
    assert f'action="/admin/publish/event/{eid}"' in html

    # Скрипт админки получает ответ без перезагрузки страницы
    r = admin.post(f"/admin/publish/event/{eid}", headers={"X-Requested-With": "fetch"})
    assert r.is_json and r.json["published"] is False and "скрыто с сайта" in r.json["message"]
    # Сообщение не должно всплыть ещё раз при следующем открытии страницы
    assert "скрыто с сайта" not in text(admin.get("/admin/events?scope=all"))


def test_yandex_session_id(app, admin):
    snippet = ("<button onclick=\"window['YandexTicketsDealer'].push(['getDealer', function(dealer) "
               "{ dealer.open({ id: 'ticketsteam-825@496249', type: 'session' }) }])\">Купить билет</button>")
    create_event(admin, yandex_id=snippet, performers="<p>Симфонический оркестр</p>")
    with app.app_context():
        assert Event.query.first().yandex_id == "ticketsteam-825@496249"

    with app.app_context():
        Setting.set("yandex_client_key", "test-key")
        db.session.commit()
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert 'data-ya-session="ticketsteam-825@496249"' in html
    assert 'data-ya-widget="ticketsteam-825@496249"' in html and 'data-ya-key="test-key"' in html
    # «Исполнители» — строка в таблице фактов, а не отдельный блок
    assert "Исполнители" in html and "принимают участие" not in html

    afisha = text(admin.get("/afisha"))
    assert 'data-ya-session="ticketsteam-825@496249"' in afisha and "Подробнее" in afisha
    assert "Симфонический оркестр" in afisha

    r = create_event(admin, title="Другой концерт", yandex_id="не тот код")
    assert "ID сеанса Яндекс Афиши выглядит так" in text(r)


def test_carousel_loads_more(app, admin):
    for day in range(1, 9):
        create_event(admin, title=f"Концерт {day}", starts_at=f"2030-12-{day:02d}T19:00",
                     show_pushkin="1" if day % 2 else "")
    home = text(admin.get("/"))
    assert "data-ecarousel" in home and "Концерт 6" in home and "Концерт 7" not in home

    more = text(admin.get("/kartochki-afishi?offset=6"))
    assert "Концерт 7" in more and "Концерт 8" in more and "Концерт 6" not in more
    assert text(admin.get("/kartochki-afishi?offset=60")).strip() == ""

    pushkin = text(admin.get("/kartochki-afishi?flag=pushkin&offset=0"))
    assert "Концерт 1" in pushkin and "Концерт 2" not in pushkin


def test_draft_visible_only_to_staff(app, admin):
    create_event(admin, is_published="")
    assert app.test_client().get("/afisha/testovyy-koncert").status_code == 404
    html = text(admin.get("/afisha/testovyy-koncert"))
    assert "Скрыто с сайта." in html and "noindex" in html
