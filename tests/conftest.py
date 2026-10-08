"""Общие заготовки для проверок.

Каждая проверка получает своё приложение на временной SQLite и свой каталог
загрузок: рабочая база и файлы сайта не трогаются, проверки не влияют друг на друга.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from filarmonia import create_app  # noqa: E402
from filarmonia.models import db, User, Setting  # noqa: E402

PASSWORD = "secret123"


def make_app(tmp_path, **overrides):
    config = dict(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "test.db"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-key",
    )
    config.update(overrides)
    app = create_app(**config)
    with app.app_context():
        db.create_all()
        for login, role in (("admin", "admin"), ("editor", "editor")):
            user = User(login=login, name=login.capitalize(), role=role)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.add(Setting(key="site_name", value="Филармония", kind="text"))
        db.session.commit()
    return app


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


def login(client, name="admin", password=PASSWORD):
    return client.post("/admin/login", data={"login": name, "password": password},
                       follow_redirects=True)


@pytest.fixture
def admin(app):
    """Клиент, вошедший администратором."""
    client = app.test_client()
    login(client)
    return client


@pytest.fixture
def editor(app):
    """Клиент, вошедший редактором."""
    client = app.test_client()
    login(client, "editor")
    return client


def png(size=(60, 80)) -> io.BytesIO:
    """Картинка в памяти — вместо настоящей афиши или фото."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (120, 40, 40)).save(buf, "PNG")
    buf.seek(0)
    return buf


def create_event(client, **fields):
    data = {
        "title": "Тестовый концерт", "starts_at": "2030-12-31T19:00", "price_min": "500",
        "age_limit": "6+", "is_published": "1", "show_media": "1",
    }
    data.update(fields)
    return client.post("/admin/events/new", data=data, content_type="multipart/form-data",
                       follow_redirects=True)


def text(response) -> str:
    return response.get_data(as_text=True)
