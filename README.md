# Сайт Смоленской областной филармонии

Flask + SQLAlchemy + собственная панель администратора. База — SQLite для разработки,
PostgreSQL на боевом сервере.

## Запуск

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py seed --reset      # база и демо-контент
python app.py                   # http://127.0.0.1:8000
```

Панель: <http://127.0.0.1:8000/admin> — логин `admin`, пароль `filarmonia2026`
(на боевом задаётся через `ADMIN_PASSWORD` и меняется сразу после входа).

Настройки — переменные окружения, образец в `.env.example`. Файл `.env` приложение само
не читает: переменные задаёт systemd, панель хостинга или оболочка.

## Команды

| Команда | Что делает |
|---|---|
| `python app.py` | сайт на порту 8000 (`--port`, `--host`, `--debug`) |
| `python app.py seed` | обновляет схему и добавляет недостающее, введённое не трогает |
| `python app.py seed --reset` | очищает базу и наполняет заново |
| `python app.py seed --menu` | пересобирает главное меню |
| `python app.py test` | проверки (pytest); `test -n auto` — в несколько потоков |
| `python app.py db upgrade` | схема базы до последней версии |
| `python app.py db revision "что изменено"` | новая миграция после правки моделей |
| `python app.py thumbs` | уменьшенные копии для всех фото |
| `python app.py cleanup [--dry-run]` | удаляет загруженные файлы, на которые никто не ссылается |
| `python app.py purge` | удаляет обращения и анкеты старше срока хранения (по расписанию) |

## Обновление кода на сервере

```bash
python app.py db upgrade
python app.py seed
python app.py thumbs
```

Изменили модель — запишите миграцию (`db revision`) и добавьте файл из `migrations/versions`
в репозиторий; иначе упадёт проверка `test_migrations_build_same_schema`.

## Проверки

```bash
pip install -r requirements-dev.txt
python -m pytest -q -n auto
```

Тесты работают на временной базе и запускаются на GitHub при каждой отправке кода.

## Документация

- [docs/DEPLOY-SERVER.md](docs/DEPLOY-SERVER.md) — боевой сервер: переменные окружения,
  gunicorn/systemd, nginx, резервные копии, действия после выкладки, почта, поисковики.
- [DEPLOY-RENDER.md](DEPLOY-RENDER.md) — тестовый стенд на Render.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — устройство кода.
- [docs/PROGRESS.md](docs/PROGRESS.md) — история правок.

## Что осталось сделать

1. **Перенос контента** со старого сайта (Drupal 7) и перенаправления старых адресов.
2. **Юридические тексты** — политика и согласие на обработку ПДн (проект), согласовать с юристом.
3. **Почта** — завести ящик отправителя, вписать `MAIL_*`, заменить `survey_email` (`test@test.ru`).
4. **Билетная система** — сейчас ссылка и виджет Яндекс Афиши; другой оператор — отдельная задача.
