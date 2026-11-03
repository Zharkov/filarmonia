"""Смоук-тест дельта-релиза: release/ накладывается на копию бэкапа хостинга."""
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
# Дельта поверх: перезаписывает изменённые и кладёт новые файлы
for dirpath, dirnames, filenames in os.walk(os.path.join(root, "release")):
    rel_dir = os.path.relpath(dirpath, os.path.join(root, "release"))
    target = os.path.join(site, rel_dir) if rel_dir != "." else site
    os.makedirs(target, exist_ok=True)
    for name in filenames:
        shutil.copy2(os.path.join(dirpath, name), os.path.join(target, name))

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tmp, "db.sqlite").replace(chr(92), "/")
# Реальная обновлённая база хостинга (копия с применённой 0018)
db_src = os.path.join(root, "tmp", "filarmonia.db")
if os.path.isfile(db_src):
    shutil.copy2(db_src, os.path.join(tmp, "db.sqlite"))
sys.path.insert(0, site)
os.chdir(site)
from filarmonia import create_app  # noqa: E402

app = create_app()
client = app.test_client()
ok = True
for url in ("/", "/afisha", "/kollektivy", "/admin/login", "/info/ob-uchrezhdenii"):
    code = client.get(url).status_code
    print(url, code)
    ok = ok and code == 200
# Проверка CSRF-модуля из дельты
from filarmonia import csrf_cookie  # noqa: E402,F401
print("csrf_cookie:", "подключён")
print("ИТОГ:", "OK" if ok else "ЕСТЬ ОШИБКИ")
