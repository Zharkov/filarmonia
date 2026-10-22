# Архитектура: карта проекта

Справочник для агентов: читайте его вместо изучения кода. Установка, переменные окружения, деплой,
nginx, команды — в `README.md` (не дублируется). История правок — `docs/PROGRESS.md`,
находки аудита — `docs/AUDIT-2026-10-21.md`. Если код расходится с документом, верен код.

## 1. Стек и запуск

- Python, Flask 3.1, Flask-SQLAlchemy 3.1 / SQLAlchemy 2.0, Alembic 1.20, Flask-WTF (только CSRF),
  Jinja2, Pillow, nh3 (очистка HTML), segno (QR), gunicorn. Версии закреплены точно в `requirements.txt`.
- Фронтенд без сборки: ванильный JS и один CSS на часть. Визуальный редактор Jodit лежит в `static/vendor/jodit`.
- БД: SQLite (`filarmonia.db`, рабочая — не трогать), на боевом PostgreSQL (`psycopg`, закомментирован в requirements).
- Запуск: `pip install -r requirements-dev.txt`, `python app.py seed` (демо-данные, вход admin/filarmonia2026),
  `python app.py` (порт 5000). Полный список команд (`run seed test db thumbs cleanup purge`) — README, «Быстрый запуск / Команды».
- Единая точка входа `app.py` (argparse), WSGI-объект `app:app` для gunicorn. Конфиг — `config.py::build_config(**overrides)`,
  всё из переменных окружения (образец `.env.example`).
- CI: `.github/workflows/tests.yml` (`python app.py test` + `pip-audit`), `dependabot.yml`. Тестовый деплой — `render.yaml`
  (демо-данные пересоздаются при каждой сборке), боевой — gunicorn+systemd+nginx по README.

## 2. Структура

### Корень
`app.py` CLI; `config.py` конфиг; `migrations/` Alembic (`versions/0001..0017`); `tests/`; `docs/`; `instance/` и
`filarmonia.db` — рабочие данные (не трогать); `DEPLOY-RENDER.md`, `render.yaml`.

### Пакет `filarmonia/`
| Модуль | За что отвечает |
|---|---|
| `__init__.py` | `create_app()`; JINJA_FILTERS; `site_data()` (кэш настроек+меню 30 с), `reset_site_data()`; `BODY_LIMITS`; before_request: `stand_auth`, `limit_body`, `load_user`; `asset_url`; проверки `check_secret_key`/`check_site_url`; обработчик CSRFError |
| `models.py` | все модели, `db`, свойства Event/Page и т.п.; константы `EVENT_STATUSES`, `DOCUMENT_TEMPLATES`, `FREE_LABEL` |
| `public.py` | blueprint `public`: все публичные страницы, поиск, sitemap/robots, приём обращений и анкет |
| `web.py` | сквозное для запроса/ответа: CSP (`ADMIN_CSP`, `PUBLIC_CSP`, `PUBLIC_CSP_REPORT`), `security_headers`, `cache_headers` (ETag/Last-Modified), `compress`, 404/500, `MOVED_PAGES`, `redirect_for_missing` (таблица Redirect), `site_url()`, логирование, `/healthz`, `/csp-report`, `stand_auth`, `end_idle_session` |
| `schema.py` | JSON-LD Schema.org: `event`, `organization`, `website`, `news_article`, `breadcrumbs`, `offers`, `opening_hours`; в шаблонах `{{ schema.event(ev, settings) \| tojson }}` |
| `utils.py` | даты по-русски (`ru_date`, `to_moscow`, `now_msk`, `utcnow`), `slugify`, `save_upload`/`check_image`/`shrink_image`, `make_variants` (копии `-NNNw.webp`), `srcset`/`image_size`/`delete_uploads`, `clean_html` (nh3), `video_embed`, `parse_dt/parse_date/parse_int`, `map_point`, `yandex_session_id`, `plural`, `strip_tags`, `compact`, `qr_svg`, `like_ci`/`search_norm`, `upload_rules` |
| `surveys.py` | описание анкет НОК как данных (`Survey`, `Question`; `SNOC`, `MINKULT_SO`, `SURVEYS`); `parse`, `dumps/loads`, `rows`, `summary`, CSV |
| `mailer.py` | SMTP через smtplib: `send`, `deliver_survey`, `deliver_survey_later` (фоновый поток при `MAIL_ASYNC`), `parse_recipients`, `enabled()` |
| `throttle.py` | ограничение частоты по ключам в таблице `throttles`: `hit`, `state`, `reset`, `seconds_since` |
| `seed.py` | демо-данные и стартовые настройки (`SETTINGS`, `PAGES`, `MENU`, ...); `run(app, reset, rebuild_menu)` сам вызывает `migrate.upgrade` |
| `migrate.py` | обёртка Alembic: `upgrade/revision/downgrade/current` |
| `maintenance.py` | `make_all_variants` (thumbs), `unused_uploads`/`cleanup`, `purge` (сроки хранения обращений и анкет, для cron) |
| `demo.py` | генерация демо-афиш/фото/PDF/роликов для seed (Pillow, ffmpeg) |

### `filarmonia/admin/` (blueprint `admin`, префикс `/admin`; объявлен в `__init__.py`, модули импортируются оттуда)
`common.py` — общий инструментарий (см. раздел 5, 7); `auth.py` вход/выход; `dashboard.py` главная панели; `events.py` афиша,
значки, копирование, «Изменения в афише»; `content.py` коллективы/новости/страницы/документы новости/`/slug`;
`media.py` галереи (добавление, удаление, порядок); `publishing.py` быстрая публикация; `site.py` меню, документы, баннеры,
перенаправления, справочники; `appeals.py` обращения; `surveys.py` анкеты; `system.py` настройки, сотрудники, журнал.

### Статика (`filarmonia/static/`)
- `css/site.css` — весь сайт (шрифты `@font-face`, переменные, режим для слабовидящих, шапка/меню, hero, календарь, карточки, карусели, формы, футер); `css/admin.css` — панель.
- `js/site.js` — меню, слабовидящие, календарь-лента, карусели (догрузка `/kartochki-afishi`), «Музыкальный маршрут» (`/marshrut`), звук видео, cookie-согласие, окно «Изменения в афише»; `js/pos-widget.js` — виджет «Госуслуги. Решаем вместе» (ленивая вставка); `js/admin.js` — тосты, ajax-формы, автоslug (`/admin/slug`), загрузки.
- `fonts/` woff2, `vendor/jodit/`, `img/logo.png`, `favicon*`, `uploads/` — загруженные файлы (путь из `UPLOAD_FOLDER`).

### Шаблоны (`filarmonia/templates/`)
- `public/`: `base.html` (шапка, меню, футер, flash, мета/OG, JSON-LD), `index`, `afisha`, `event`, `festival`, `collectives`, `collective`,
  `news_list`, `news_item`, `page` (универсальная по `Page.template`, включая НОК, контакты с картой, документы), `documents`, `appeals`,
  `search`, `site_map`, `error`, `csrf`, `sitemap.xml`; фрагменты `_cards`, `_notices`, `_route_result`, `_appeal_form`, `_survey_form`, `_nok`, `_pos_widget`.
- `public/_macros.html`: `img_src(url, sizes)` (srcset), `og_image`, `img_dims`, `buy_button(ev, cls)`, `event_card`, `carousel_nav`, `event_carousel`,
  `news_card`, `event_row`, `daystrip`, `pagination(pager, endpoint, args)`, `breadcrumbs(trail)`, `social_links`, `document_list`, `document_row`,
  `section_icon(slug)`, `icon(name)`.
- `admin/`: `base.html` (меню, flash), по шаблону на раздел (`events`, `event_form`, `news`, `news_form`, `pages`, `page_form`, `collectives`,
  `collective_form`, `menu`, `documents`, `banners`, `redirects`, `refs`, `notices`, `settings`, `users`, `log`, `appeals`, `appeal_view`, `appeal_print`,
  `surveys`, `survey_view`, `survey_summary`, `login`, `dashboard`). Макросы: `_form.html` (`slug_field`, `seo_block`, `file_input`, `form_actions`),
  `_media.html` (`media_manager`), `_table.html` (`sort_th`, `pager`, `publish_toggle`, `keep_sort`, `reset_link`), `_survey_tabs.html` (`tabs`).

## 3. Модели и миграции

Все в `models.py`; время хранится в UTC (`utcnow`), показывается в МСК (`msk`/`to_moscow`).

| Модель | Таблица | Ключевое |
|---|---|---|
| User | users | `login`, `password_hash`, `role` (`admin`/`editor`), `is_active`, `is_admin`, `set_password/check_password` |
| Setting | settings | PK `key`; `value`, `title`, `group`, `kind` (text/textarea/html/file/bool); `Setting.get(key, default)` (пустое значение = default), `Setting.set` |
| Page | pages | `slug` (url `/info/<slug>`), `content`, `parent_id` (дерево), `is_published`, `show_in_menu`, `template` = page / documents / documents_years / nok / contacts / pushkin / benefits, `seo_description`; `has_documents` (`DOCUMENT_TEMPLATES`); media |
| MenuItem | menu_items | `title`, `url` либо `page_id`, `parent_id`, `sort`, `href` |
| Event | events | `slug`, `starts_at`, `status` (scheduled/cancelled/rescheduled/postponed), `previous_starts_at`, `is_free`, `price_min/max`, `ticket_url`, `yandex_id`, `hall_widget`, `show_pushkin/benefits(+_text)`, `show_media`, `is_published/is_new/is_featured`, `seo_title/description`; свойства `url`, `is_past`, `card_image`, `price_label`, `status_label`, `is_cancelled`, `sells_tickets`, `can_buy`, `age_number`; связи venue, category, collectives (M2M), festivals (M2M), media, badges |
| EventBadge | event_badges | значок на афише: `text`, `hint`, `url`, `position`, `style` (brick/gold/ink/light), `icon` |
| AfishaNotice | afisha_notices | «Изменения в афише» (всплывающее окно): `kind`, `text`, `url`, `event_id` (SET NULL), `show_until`, `active()`, `link` |
| Venue / Category / Festival | venues / categories / festivals | справочники; у Category `route_tags` (ключи ROUTE_TAGS для «Музыкального маршрута») |
| Collective | collectives | `name`, `slug`, `logo`, `lead`, `contacts`, seo_*, media |
| News | news | `slug`, `published_at`, `lead`, `content`, `image`, `show_media`, seo_*, media, documents |
| Document | documents | `file` либо `url`, `category` (совпадает с заголовком страницы-раздела), `year`, `news_id` (документ новости, не в общих списках), `href/ext/viewable/is_image` |
| MediaItem | media_items | фото/видео (`kind`, `file`/`url`/`embed`, `preview`); один из `event_id/collective_id/news_id/page_id`; миксин `HasMedia` даёт `photos`, `videos` |
| Banner | banners | `place` partners/main/footer |
| Appeal | appeals | обращение гражданина; `consent`, `consent_version`, `consent_at`, `is_processed`, `note` |
| SurveyResponse | survey_responses | `survey` (ключ из surveys.py), `answers` (JSON-текст), `is_emailed`, `email_error` |
| ActionLog | action_log | `action` (create/update/delete/...), `object_type`, `object_id`, `title`, `details` |
| Throttle | throttles | PK `key` вида `login:логин:адрес`, `appeal:адрес`, `survey:...`; `count`, `last_at` |
| Redirect | redirects | `old_path` (unique) -> `new_url`, `hits` |

### Миграции (`migrations/versions/NNNN_*.py`, ревизии цепочкой; последняя `b7d1e6a39c42`)
Схему создают миграции, а не `create_all` (в тестах — `create_all`). Файлы 0001–0009: начальная схема, yandex_id, правки аудита и заказчика,
страница НОК, контакты, hero/метрика. С 0010:
- 0010 `a7d2b5e8f441` — данные: виджет ПОС встроен в шаблон, удалены его настройка и баннеры «main».
- 0011 `b8e3c6f9a552` — данные: настройка заголовка окна «Изменения в афише» (insert-if-missing).
- 0012 `c9f4d7a1b663` — схема: `afisha_notices.event_id` (FK SET NULL).
- 0013 `d2b6f1a8c995` — схема: таблица `survey_responses`.
- 0014 `e3c7a2b9d106` — данные: настройка `survey_email` (по умолчанию `test@test.ru`), новые подписи/группа настроек карты.
- 0015 `f4d8b3c1e207` — данные: срок хранения анкет (3 года).
- 0016 `a5e9c4d2f318` — схема: `events.status/previous_starts_at/is_free/seo_*`, seo_* у collectives и news, `appeals.consent_version/consent_at`; страница согласия (проект текста).
- 0017 `b7d1e6a39c42` — данные: обезличивание старых записей журнала по обращениям («Обращение № N»).

## 4. Маршруты

### Публичные (`public.py`)
| Адрес | Функция | Шаблон |
|---|---|---|
| `/` | index | index (hero, календарь, карусели, новости, маршрут) |
| `/marshrut` | route | `_route_result` (фрагмент для fetch; noindex) |
| `/afisha` | afisha (фильтры venue/category/price/q/дата, пагинация 15) | afisha |
| `/afisha/<slug>` | event | event |
| `/festivali/<slug>` | festival | festival |
| `/kartochki-afishi` | more_cards (догрузка карусели, noindex) | `_cards` |
| `/kollektivy`, `/kollektivy/<slug>` | collectives / collective | collectives / collective |
| `/novosti`, `/novosti/<slug>` | news_list / news_item | news_list / news_item |
| `/info/<slug>` | page (`MOVED_PAGES` -> 301) | page |
| `/dokumenty` | documents | documents |
| `/karta-sajta` | site_map | site_map |
| `/obrashcheniya` GET/POST | appeals | appeals (+`_appeal_form`) |
| `/info/<slug>/anketa/<key>` POST | survey_submit | page (при ошибке) или redirect |
| `/poisk` | search (noindex) | search |
| `/sitemap.xml`, `/robots.txt`, `/favicon.ico` | sitemap, robots, favicon | sitemap.xml / text |

Черновики (`check_published`): аноним получает 404, вошедший сотрудник видит страницу с плашкой и ссылкой «править».

### Служебные (`web.py`, `__init__.py`)
`/healthz` (без БД и пароля стенда), `/csp-report` POST (без CSRF, лимит 16 КБ, noindex), обработчики 403/404/405/413/500 (`public/error.html`), `CSRFError` -> `public/csrf.html`.

### Админка (`/admin/...`; `login_required` = admin+editor, `admin_required` = только admin, иначе 403)
| Раздел | Адреса | Права |
|---|---|---|
| Вход | `/login` GET/POST, `/logout` POST | — |
| Панель | `/` | оба |
| Афиша | `/events`, `/events/new`, `/events/<id>` (+`/copy`, `/badges`, `/delete`), `/badges/<id>/delete`, `/notices` (+`/<id>/delete`) | оба |
| Контент | `/collectives`, `/news` (+`/<id>/documents`, `/documents/<id>/delete`), `/pages` — каждый со списком, `new`, `<id>`, `<id>/delete`; `/slug` (ajax-подсказка адреса) | оба |
| Галереи | `/media/add`, `/media/<id>/delete`, `/media/<id>/move` | оба |
| Публикация | `/publish/<kind>/<id>` POST | оба |
| Сайт | `/menu`, `/documents`, `/banners`, `/redirects`, `/refs` (+`/refs/<kind>/<id>/delete`), удаление `menu|documents|banners|redirects/<id>/delete` | оба |
| Анкеты НОК | `/surveys`, `/surveys/summary`, `/surveys/export.csv`, `/surveys/<id>` | оба (просмотр) |
| | `/surveys/<id>/delete`, `/surveys/<id>/resend`, `/surveys/resend-unsent` | admin |
| Обращения | `/appeals`, `/appeals/<id>`, `/appeals/<id>/print`, `/appeals/<id>/delete` | только admin |
| Система | `/settings`, `/users` (+`/<id>/delete`), `/log` | только admin |

## 5. Сквозные механизмы

- **Настройки.** `Setting.get(key, default)` в коде, в шаблонах — словарь `settings` (context processor). `site_data()` держит настройки и меню в памяти процесса 30 с;
  `admin.common.log()` и `save()` сбрасывают (`reset_site_data()`), другие процессы gunicorn узнают не позже чем через 30 с. В тестах (`app.testing`) сброс на каждый запрос.
  **Новая настройка** = строка в `seed.SETTINGS` (ключ, значение, подпись, группа, kind) + миграция, вставляющая её только если ключа нет (образец — `0014`/`0015`: `sa.table(...)`, `select ... first() is None`, `insert`; `downgrade` удаляет). Редактор значение не затирается.
- **Безопасность.** CSRF глобально (`CSRFProtect`; в тестах `WTF_CSRF_ENABLED=False`), `/csp-report` исключён. URL из форм — только через `admin.common.safe_url` (None = невалидно, `BAD_URL_TEXT` в flash), адрес возврата после входа — `safe_next`. HTML от редактора — `utils.clean_html`.
  `BODY_LIMITS` (по endpoint: анкета 64 КБ, обращение 128 КБ, csp_report 16 КБ; остальное 64 МБ) применяется в `limit_body` до CSRF. `throttle`: вход (`LOGIN_MAX_ATTEMPTS/LOCKOUT`), обращения и анкеты (`*_INTERVAL_SECONDS`), honeypot-поле `website` в анкете.
  Роли admin/editor (`login_required`/`admin_required`; права проверяются на каждом запросе в `load_user`, сеанс гаснет после `SESSION_IDLE_SECONDS`). CSP: админка — строгая и обязательная, сайт — `PUBLIC_CSP` + полная `PUBLIC_CSP_REPORT` только в режиме Report-Only. `stand_auth` — Basic-auth на тестовом стенде при `SITE_NOINDEX=1` + `STAND_USER/PASSWORD`; без пароля `stand_closed()` отключает приём обращений/анкет. `check_secret_key`/`check_site_url` обрывают запуск боевого окружения без `SECRET_KEY`/`SITE_URL`.
- **Кэш.** `web.cache_headers`: версионная статика и `uploads/` — год immutable; страницы — слабый ETag + `Last-Modified` из `g.last_modified` (обработчики кладут `updated_at`; галереи/связи обновляют его через `common.touch`). `compress` — gzip, если нет nginx. Ссылки на CSS/JS — `asset_url('css/site.css')` (версия = mtime).
- **Картинки.** Загрузка `utils.save_upload` -> `check_image` (формат, лимит пикселей) -> `shrink_image` (`IMAGE_MAX_SIDE`) -> `make_variants` (копии `имя-400w/800w/1200w…webp` рядом с файлом). В шаблонах — макрос `img_src(url, sizes)` (srcset) и `img_dims`/`image_size`; миниатюры для старых фото — `python app.py thumbs`. Удаление файлов — `utils.delete_uploads` / `common.release_files`/`replace_file`; висячие файлы — `python app.py cleanup`.
- **Flash-категории.** Панель: `ok` / `error`. Публичная часть: категория `survey-<key>` — сообщения анкеты выводятся только в своей форме (`_survey_form.html`, `category_filter`), иначе «Спасибо» попадёт в общий блок `base.html`; не переименовывать без правки обоих шаблонов.
- **Журнал действий.** `common.log(action, item, details, object_type)` (+`OBJECT_TYPES`, `ACTION_LABELS`), коммитится вместе с правкой; `save()` пишет create/update сам, `delete_record()` — delete. Для Appeal в журнал идёт только «Обращение № N» (ПДн не попадают, `title_of`). Просмотр — `/admin/log`.
- **Перенаправления.** Три слоя: `web.MOVED_PAGES` (код, 301, исключены из меню и sitemap); таблица `Redirect` (панель «Перенаправления», счётчик `hits`, срабатывает на 404 в `redirect_for_missing`); автосоздание при смене slug опубликованной записи — `common.keep_old_address` (переписывает цепочки, убирает петли).
- **JSON-LD.** `schema.py` отдаёт словари, в шаблоне `| tojson`; события учитывают `status` (EventStatusType) и `is_free`.
- **Почта.** Только для анкет НОК: настройка `survey_email` (несколько адресов через запятую) + `MAIL_*`. Пустой `MAIL_SERVER` — письмо не шлётся, ответ сохраняется. `MAIL_ASYNC=1` — фоновый поток (`deliver_survey_later`); итог в `SurveyResponse.is_emailed/email_error`, повтор — `/admin/surveys/<id>/resend`. Обращения по почте не уходят.
- **Сроки хранения.** Настройки `appeals_retention_years` (5), `surveys_retention_years` (3); удаление — `python app.py purge` (cron) и кнопка в панели.
- **Slug.** `utils.slugify` (транслит) + `common.unique_slug`; авто-подсказка в форме — `/admin/slug`.
- **Публикация.** Кнопки формы шлют `publish=1|0` (`common.publish_choice`); новая запись — черновик.

## 6. Тесты

`python -m pytest -q -n auto` (или `python app.py test`; нужен `requirements-dev.txt`). Каждый тест получает своё приложение на временной SQLite (`tmp_path`), рабочая БД не затрагивается.

`tests/conftest.py`: `make_app(tmp_path, **overrides)` (TESTING, без CSRF, `create_all`, пользователи `admin`/`editor` с паролем `secret123`, настройка `site_name`), фикстуры `app`, `admin`, `editor` (вошедшие клиенты), хелперы `login`, `png()`, `create_event(client, **fields)`, `text(response)`.
Настройки в тестах: `put_setting(app, key, value)` и autouse-фикстура со `reset_site_data()` (кэш 30 с) объявлены **только в `test_contacts_map.py`**, не в conftest; в других файлах правку настроек делайте через `Setting.set` + commit и вызывайте `reset_site_data()` (импорт из `filarmonia`).

| Файл | Покрытие |
|---|---|
| test_site | публичная часть: главная, маршрут, страницы, новости, поиск |
| test_events | афиша, баннеры, фото/видео, копирование события |
| test_event_page | страница события: порядок блоков, бесплатный, стрелки каруселей |
| test_status_ui | плашки статуса концерта в карточке/строке/странице |
| test_sections | документы, новости с документами, фестивали, шапка, контакты, карта сайта |
| test_contacts_map | карта «Контактов», значок MAX, баннер |
| test_admin | таблицы панели, правка, защита удаления, журнал |
| test_auth | вход, права, блокировки |
| test_security | технический аудит: ошибки, перенаправления, сжатие |
| test_audit_security | аудит 2026-10-21 этап A: ссылки, размеры тела, доступ, сроки хранения, стенд, robots/sitemap |
| test_stage_b | этап B: статус, «бесплатно», SEO-поля, согласие, JSON-LD, redirect при смене адреса, миграция 0016 |
| test_review_fixes | Last-Modified, перенаправления, миграция 0017, strip_tags, 413 |
| test_seo_frontend | title/description, OG, cookie-согласие, сторонние скрипты |
| test_surveys / test_surveys_page | анкеты НОК: приём, письмо, спам, панель / разметка страницы, ошибки, flash |
| test_utils | видео, clean_html, копии картинок, maintenance |

Всего 446 тестов (2026-10-21). Во время работы — только затронутые файлы; в конце — весь набор один раз: `python -m pytest -q -n auto` (~35 с).

## 7. Соглашения кода

Здесь только то, что нельзя нарушать.
- Язык: комментарии, docstring, тексты интерфейса, имена тестов-описаний — по-русски. Комментарий объясняет «почему» (какую ошибку предотвращает, что решил заказчик), а не «что». Модули начинаются с docstring в одну-две строки.
- Имена: код и поля — английские snake_case; адреса публичных страниц — транслит (`/afisha`, `/kollektivy`, `/novosti`, `/info/<slug>`).
- Админ-маршруты — функции `bp.route` в модуле раздела, `@login_required` / `@admin_required`; запись — `get_or_404`, `unique_slug`, `safe_url`, `rich()` (HTML через clean_html), `set_seo`, `keep_old_address`, `save(item, "Сообщение.")`, `log(...)`; удаление — `delete_record`. Не изобретать свои аналоги.
- Новая настройка = seed + миграция insert-if-missing. Изменение схемы = новая миграция `NNNN_кратко.py` (следующая 0018, `down_revision = 'b7d1e6a39c42'`), проверять upgrade/downgrade на временной SQLite; изменения схемы согласуются с пользователем.
- HTML от редактора — только `clean_html`; URL-поля — только `safe_url`; новые POST-маршруты без CSRF не делать; публичные POST с телом от посетителей — добавлять в `BODY_LIMITS`.
- Новый публичный маршрут: учесть черновики (`check_published`), `g.last_modified`, sitemap/noindex (`NOINDEX_ENDPOINTS`) и JSON-LD.
- Картинки в шаблонах — через макрос `img_src`, стили/скрипты — через `asset_url`.
- Правило проекта: не запускать `git` (пользователь делает сам), не изменять рабочую БД `filarmonia.db` — только временную SQLite в тестах/проверках. Секреты только в `.env`. Записи о проделанном — в `docs/PROGRESS.md`.

## 8. Известные ограничения и отложенное

- **С-2** — пароль администратора по умолчанию `filarmonia2026` (seed, README); сознательно не меняется до выкладки. Менять при боевом запуске через `ADMIN_LOGIN/ADMIN_PASSWORD`.
- **С-14** — CSP сайта только Report-Only; перед enforce вынести inline-скрипты и собрать источники виджетов по отчётам `/csp-report`.
- **SEO-1** — перенаправления со старого Drupal-сайта (~1000 адресов, импорт CSV) отложены до переезда; механизм таблицы Redirect готов.
- **Заглушка `test@test.ru`** — значение `survey_email` по умолчанию (миграция 0014, seed); реальный адрес задать в «Настройках» и вписать `MAIL_*` в `.env`.
- Юридические тексты (политика, согласие на ПДн, 152-ФЗ — С-4) — проекты, нужен юрист. Билетная система — только ссылка/виджет Яндекс Афиши. Обращения граждан по почте не дублируются. См. README «Что осталось сделать».
- Демо-деплой на Render пересоздаёт данные при каждой сборке (SQLite эфемерна).
- Остальное и «жёлтые/зелёные» находки — `docs/AUDIT-2026-10-21.md`.
