"""Проверка основных сценариев админки на отдельной временной базе.

Запуск: python app.py test
Ничего не трогает в рабочей базе и в каталоге загрузок: приложение
поднимается на временной SQLite и своём каталоге, который затем удаляется.
"""
import io
import os
import shutil
import tempfile

from . import create_app
from .models import db, User, Event, MediaItem, Setting

PASSWORD = "secret123"
RUTUBE_URL = "https://rutube.ru/video/" + "a1b2c3d4" * 4 + "/"


def png() -> io.BytesIO:
    """Маленькая картинка в памяти — вместо настоящей афиши."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 80), (120, 40, 40)).save(buf, "PNG")
    buf.seek(0)
    return buf


class Checks:
    """Печатает результат каждой проверки и считает неудачи."""

    def __init__(self):
        self.failed = 0

    def __call__(self, name: str, passed: bool) -> None:
        if not passed:
            self.failed += 1
        print(("  ✓ " if passed else "  ✗ ") + name)


def run() -> int:
    """Прогоняет проверки. Возвращает число неудачных."""
    tmp = tempfile.mkdtemp()
    try:
        app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(tmp, "test.db"),
            UPLOAD_FOLDER=os.path.join(tmp, "uploads"),
            TESTING=True,
            WTF_CSRF_ENABLED=False,
        )
        with app.app_context():
            db.create_all()
            user = User(login="admin", role="admin")
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.add(Setting(key="site_name", value="Филармония", kind="text"))
            db.session.commit()

        return _scenarios(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _scenarios(app) -> int:
    check = Checks()
    client = app.test_client()
    uploads = app.config["UPLOAD_FOLDER"]

    # вход
    r = client.post("/admin/login", data={"login": "admin", "password": "wrong"},
                    follow_redirects=True)
    check("неверный пароль не пускает", "Неверный логин" in r.get_data(as_text=True))
    r = client.post("/admin/login", data={"login": "admin", "password": PASSWORD},
                    follow_redirects=True)
    check("вход выполнен", "Сводка" in r.get_data(as_text=True))

    # создание события с афишей
    client.post("/admin/events/new", data={
        "title": "Тестовый концерт", "starts_at": "2026-12-31T19:00", "price_min": "500",
        "age_limit": "6+", "is_published": "1", "show_pushkin": "1", "show_benefits": "1",
        "benefits_text": "<p>Пенсионерам 250 руб.</p>",
        "poster": (png(), "afisha.png"),
    }, content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        ev = Event.query.filter_by(title="Тестовый концерт").first()
        check("событие создано", ev is not None)
        check("адрес страницы сгенерирован", ev.slug == "testovyy-koncert")
        check("афиша загружена",
              bool(ev.poster) and os.path.exists(os.path.join(uploads, ev.poster)))
        event_id = ev.id

    # страница события на сайте
    r = client.get("/afisha/testovyy-koncert")
    html = r.get_data(as_text=True)
    check("страница события открывается", r.status_code == 200)
    check("блок льгот показан", "Пенсионерам 250 руб." in html)
    check("блок Пушкинской карты показан", "Пушкинской картой" in html)

    # всплывающий баннер
    client.post(f"/admin/events/{event_id}/badges", data={
        "text": "Пушкинская карта", "hint": "Оплата через Госуслуги Культура",
        "position": "top-left", "style": "brick"}, follow_redirects=True)
    html = client.get("/afisha/testovyy-koncert").get_data(as_text=True)
    check("баннер виден на афише",
          'class="pin pin--brick pin--top-left"' in html and "Госуслуги Культура" in html)

    # галерея: фото пачкой
    client.post("/admin/media/add", data={
        "owner": "event", "owner_id": str(event_id), "kind": "photo",
        "file": [(png(), "foto1.png"), (png(), "foto2.png")]},
        content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        check("две фотографии загружены",
              MediaItem.query.filter_by(event_id=event_id, kind="photo").count() == 2)

    # галерея: видео по ссылке
    client.post("/admin/media/add", data={
        "owner": "event", "owner_id": str(event_id), "kind": "video",
        "url": RUTUBE_URL, "title": "Ролик от артистов"},
        content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        video = MediaItem.query.filter_by(event_id=event_id, kind="video").first()
        check("видео по ссылке добавлено",
              video is not None and "rutube.ru/play/embed" in (video.embed or ""))

    # запрет недопустимого файла
    r = client.post("/admin/media/add", data={
        "owner": "event", "owner_id": str(event_id), "kind": "photo",
        "file": (io.BytesIO(b"MZ"), "virus.exe")},
        content_type="multipart/form-data", follow_redirects=True)
    check("исполняемый файл отклонён", "Недопустимый тип файла" in r.get_data(as_text=True))

    # отключение блока льгот
    client.post(f"/admin/events/{event_id}", data={
        "title": "Тестовый концерт", "starts_at": "2026-12-31T19:00", "is_published": "1"},
        content_type="multipart/form-data", follow_redirects=True)
    html = client.get("/afisha/testovyy-koncert").get_data(as_text=True)
    check("блок льгот выключается галочкой", "Пенсионерам 250 руб." not in html)

    # удаление события
    r = client.post(f"/admin/events/{event_id}/delete", follow_redirects=True)
    with app.app_context():
        check("событие удалено", db.session.get(Event, event_id) is None)

    # закрытость админки
    client.get("/admin/logout")
    r = client.get("/admin/events", follow_redirects=False)
    check("админка закрыта для гостя",
          r.status_code == 302 and "/admin/login" in r.headers["Location"])

    return check.failed
