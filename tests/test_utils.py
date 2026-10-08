"""Вспомогательные функции: видео, очистка HTML, уменьшенные копии, обслуживание."""
import os

from conftest import png

from filarmonia import maintenance, utils
from filarmonia.models import db, MediaItem

RUTUBE_URL = "https://rutube.ru/video/" + "a1b2c3d4" * 4 + "/"


def test_video_link_quote_escaped():
    embed = utils.video_embed('https://vk.com/video_ext.php" onload="alert(1)')
    assert 'onload="alert' not in embed


def test_rutube_recognised():
    assert "rutube.ru/play/embed" in utils.video_embed(RUTUBE_URL)


def test_clean_html_keeps_text_markup():
    html = ('<h2>Заголовок</h2><p><strong>жирный</strong> <a href="https://x.ru">ссылка</a></p>'
            '<table><tr><td colspan="2">ячейка</td></tr></table>')
    cleaned = utils.clean_html(html)
    for part in ("<h2>", "<strong>", 'href="https://x.ru"', 'colspan="2"'):
        assert part in cleaned


def test_clean_html_removes_dangerous():
    cleaned = utils.clean_html('<img src="x" onerror="alert(1)"><iframe src="https://evil"></iframe>'
                               '<a href="javascript:alert(1)">x</a><style>body{}</style>')
    for part in ("onerror", "iframe", "javascript:", "<style"):
        assert part not in cleaned


def test_variants_and_srcset(app):
    with app.app_context():
        folder = app.config["UPLOAD_FOLDER"]
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "big.jpg")
        from PIL import Image
        Image.open(png((1600, 1000))).convert("RGB").save(path)
        assert utils.make_variants(path) == 3
        srcset = utils.srcset("/static/uploads/big.jpg")
        for part in ("big-400w.webp 400w", "big-800w.webp 800w", "big-1200w.webp 1200w", "big.jpg 1600w"):
            assert part in srcset
        # Копию шире оригинала не делаем
        Image.open(png((500, 300))).convert("RGB").save(os.path.join(folder, "small.jpg"))
        assert utils.make_variants(os.path.join(folder, "small.jpg")) == 1


def test_delete_uploads_refuses_paths(app):
    with app.app_context():
        assert utils.delete_uploads(["../config.py", "..\\config.py"]) == 0


def test_cleanup_keeps_used_files(app):
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    for name in ("used.jpg", "used-400w.webp", "orphan.jpg"):
        open(os.path.join(folder, name), "wb").close()
    with app.app_context():
        db.session.add(MediaItem(kind="photo", file="used.jpg"))
        db.session.commit()
    assert maintenance.cleanup(app, dry_run=True) == ["orphan.jpg"]
    assert os.path.exists(os.path.join(folder, "orphan.jpg"))
    maintenance.cleanup(app)
    assert sorted(os.listdir(folder)) == ["used-400w.webp", "used.jpg"]


def test_migrations_build_same_schema(tmp_path):
    """База, собранная миграциями, совпадает с моделями — иначе забыли `db revision`."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from conftest import make_app
    from filarmonia import migrate

    app = make_app(tmp_path)
    with app.app_context():
        db.drop_all()
    migrate.upgrade(app)
    with app.app_context(), db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), db.metadata)
    assert diff == []


def test_map_point():
    from filarmonia.utils import map_point
    # Из Яндекс Карт координаты копируются как «широта, долгота», виджету нужен обратный порядок
    assert map_point("54.781496, 32.048407") == "32.048407,54.781496"
    assert map_point("54.78,32.05") == "32.050000,54.780000"
    assert map_point("") == "" and map_point("ул. Глинки") == "" and map_point("200, 32") == ""
