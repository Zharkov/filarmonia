"""Отладка: куда смотрит база в смоук-тесте дельты."""
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site = os.path.join(tmp, "site")
shutil.copytree(os.path.join(root, "backup"), site,
                ignore=shutil.ignore_patterns("__pycache__", "uploads"))
shutil.rmtree(os.path.join(site, "scripts"), ignore_errors=True)
for dirpath, dirnames, filenames in os.walk(os.path.join(root, "release")):
    rel_dir = os.path.relpath(dirpath, os.path.join(root, "release"))
    target = os.path.join(site, rel_dir) if rel_dir != "." else site
    os.makedirs(target, exist_ok=True)
    for name in filenames:
        shutil.copy2(os.path.join(dirpath, name), os.path.join(target, name))

db_path = os.path.join(tmp, "db.sqlite")
os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace(chr(92), "/")
db_src = os.path.join(root, "tmp", "filarmonia.db")
print("db_src существует:", os.path.isfile(db_src))
shutil.copy2(db_src, db_path)
print("db.sqlite размер:", os.path.getsize(db_path))
sys.path.insert(0, site)
os.chdir(site)
from filarmonia import create_app  # noqa: E402

app = create_app()
print("URI:", app.config["SQLALCHEMY_DATABASE_URI"])
import sqlite3  # noqa: E402
con = sqlite3.connect(db_path)
print("таблицы в db.sqlite:", con.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
con.close()
