"""Фоновое видео главной: загрузка через панель -> автонарезка в HLS."""
import io
import os

from filarmonia import hero_video
from filarmonia.models import db, Setting


def test_is_hls_value():
    assert hero_video.is_hls_value("hero-16d7fb41e626/master.m3u8")
    assert not hero_video.is_hls_value("hero.mp4")
    assert not hero_video.is_hls_value("uploads/master.m3u8")
    assert not hero_video.is_hls_value("")


def test_slug_stable_and_short(tmp_path):
    a = tmp_path / "a.webm"
    a.write_bytes(b"same content")
    b = tmp_path / "b.webm"
    b.write_bytes(b"same content")
    assert hero_video.slug_for(str(a)) == hero_video.slug_for(str(b))
    assert hero_video.slug_for(str(a)).startswith("hero-")
    assert len(hero_video.slug_for(str(a))) == 5 + 12


def test_prepare_without_ffmpeg(app, tmp_path, monkeypatch):
    """Нет ffmpeg — prepare() честно возвращает пусто."""
    monkeypatch.setattr(hero_video, "find_ffmpeg", lambda: "")
    upload = tmp_path / "clip.mp4"
    upload.write_bytes(b"x" * 1024)
    with app.app_context():
        assert hero_video.prepare(app, str(upload)) == ""
    assert not (tmp_path / hero_video.slug_for(str(upload))).exists()


def _webm_part():
    """Поле формы: (поток, имя файла) — как присылает браузер."""
    return (io.BytesIO(b"\x1aE\xdf\xa3" + b"0" * 2048), "clip.webm")


def test_settings_upload_autoslices(app, admin, monkeypatch):
    """Загрузка видео в «Настройках» запускает нарезку и меняет hero_video.

    В тестовой базе настроек нет (seed не запускается) — создаём hero_video сами;
    именно её строку с kind='file' обработчик и должен увидеть в форме.
    """
    with app.app_context():
        db.session.add(Setting(key="hero_video", value="", title="Видео на главной",
                               group="Главная страница", kind="file"))
        db.session.commit()

    calls = []
    # Настоящий multipart до save_upload в тесте не доходит (werkzeug требует
    # настоящего потока с .stream), поэтому имитируем сохранение на диск
    monkeypatch.setattr("filarmonia.admin.system.uploaded_name",
                        lambda field, kinds=("image",): "clip-hash.webm" if field == "f_hero_video" else "")
    monkeypatch.setattr("filarmonia.admin.system.hero_prepare",
                        lambda a, name: calls.append(name) or "hero-deadbeef12ab/master.m3u8")
    r = admin.post("/admin/settings", data={"f_hero_video": _webm_part()},
                   content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert calls == ["clip-hash.webm"], "prepare() не вызван для загруженного видео"
    with app.app_context():
        assert Setting.get("hero_video") == "hero-deadbeef12ab/master.m3u8"
    assert "нарезается" in r.get_data(as_text=True)


def test_settings_without_video_untouched(app, admin):
    with app.app_context():
        s = db.session.get(Setting, "hero_video")
        if not s:
            s = Setting(key="hero_video", value="", kind="file")
            db.session.add(s)
        s.value = "hero-abc123/master.m3u8"
        db.session.commit()
    # Файл не выбран — поля f_hero_video нет в форме, значение остаётся
    admin.post("/admin/settings", data={"site_name": "Филармония"},
               content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        assert Setting.get("hero_video") == "hero-abc123/master.m3u8"
