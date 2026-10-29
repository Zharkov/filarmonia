# Прогресс

## 2026-10-21 — правки заказчика
- Баннер на главной: `.hero` в пропорции 1902×737 (было 16:9); поля `.hero__inner` теперь
  `clamp(...)` и сжимаются на средних ширинах, чтобы текст помещался в новую высоту.
- «Контакты»: убран блок «Площадки» (шаблон, загрузка в `public.py`, CSS `.venues/.venue`).
  Добавлена карта на всю ширину между адресом и текстом страницы (`page.html`).
  С главной карта убрана совсем; настройка `history_map` теперь управляет картой в «Контактах».
- Иконка MAX в `_macros.html` заменена на логотип с maxicons.ru (одноцветный, `currentColor`).
- Тесты: 138 passed.

## 2026-10-21 — tester: проверка правок заказчика
- Новый файл `tests/test_contacts_map.py` (10 проверок): «Контакты» — 200, iframe `yandex.ru/map-widget`,
  `map--wide`, нет «Площадки»/`class="venues"` и названий площадок из БД; карта следует `map_point`;
  своя `history_map` заменяет iframe; на главной и обычной странице нет карты (даже при заданной `history_map`);
  в афише остался фильтр `select name="venue"`; значок MAX (`fill-rule="evenodd"`, `currentColor`, без `rect`),
  скрыт при `social_max_show=''` и без адреса; в `site.css` у `.hero` `aspect-ratio: 1902 / 737`.
- Заметка: настройки кешируются в памяти процесса на 30 с (`_site_data`), поэтому в файле есть autouse-сброс
  `reset_site_data()` и `put_setting` с коммитом. Эту же особенность стоит учитывать в других тестах настроек.
- Результат: `python -m pytest -q` — 148 passed, 0 failed.

## 2026-10-21 — backend-dev: анкеты «Независимой оценки качества»
- Две анкеты на странице НОК (`snoc`, `minkult_so`); описание вопросов — один модуль `filarmonia/surveys.py`
  (форма, проверка, письмо, просмотр, сводка и CSV строятся из него). Внешняя анкета Минкультуры РФ осталась.
- Модель `SurveyResponse` (`survey_responses`), миграция `0013_survey_responses.py` (`d2b6f1a8c995`, down_revision `c9f4d7a1b663`).
  Проверена на временной SQLite (upgrade и downgrade); рабочая база не тронута.
- Приём: `POST /info/<slug>/anketa/<key>` (CSRF, проверка значений и длин, honeypot `website`, пауза
  `SURVEY_INTERVAL_SECONDS`=60 с на пару «анкета + адрес»). При ошибке страница показывается заново с введёнными ответами.
- Почта: `filarmonia/mailer.py` (smtplib), настройки `MAIL_*` в `config.py` и `.env.example`; получатель — настройка
  `survey_email` (по умолчанию test@test.ru, добавлена в `seed.py`). Пустой `MAIL_SERVER` — только сохранение.
  Письмо уходит синхронно (таймаут 10 с), сбой пишется в `email_error`, ответ посетителя не страдает.
- Админка «Анкеты НОК» (`admin/surveys.py`): список, просмотр, сводка (доля «Да» / средний балл), CSV (UTF-8 BOM, «;»),
  удаление только администратором с записью в журнал.
- `seed.py`: описания и группа `map_point`, `history_map` обновлены на «Контакты» (у уже созданных настроек в базе остаются старые:
  seed только добавляет отсутствующие).
- Тесты: `tests/test_surveys.py`; `python -m pytest -q` — 172 passed.

## 2026-10-21 — frontend-dev: оформление анкет на странице НОК
- Под блоком Минкультуры РФ — секция «Региональные анкеты» (`_nok.html`) и две карточки (`_survey_form.html`, `<details>`):
  в свёрнутом виде ведомство, название, «Вопросов: N · анонимно · около 3 минут» и кнопка «Заполнить анкету»;
  раскрытая анкета занимает всю ширину. Без скрипта раскрывается штатно (details).
- Вопросы: fieldset + legend с номером; Да/Нет — два сегмента, оценки 1–5 — пять кружков с подписями «1 — плохо / 5 — отлично»
  (радиокнопки спрятаны, но доступны с клавиатуры, виден фокус). «Ваши пожелания» — компактная textarea.
- Ошибки: список сверху формы (`role="alert"`) + отметка неотвеченного вопроса (`aria-invalid`, `aria-describedby`);
  бэкенд отдаёт ошибки только общим списком, поэтому вопрос определяется по введённым значениям в шаблоне.
- `site.js`: раскрытие по `#anketa-<ключ>`, прокрутка к ошибкам после неудачной отправки, счётчик «Отвечено N из M».
- Flash «Спасибо…» уходит с категорией `survey-<ключ>` (`public.py`, обе ветки); анкета выводит только свою категорию,
  `base.html` такие сообщения пропускает, остальные flash выводятся там как раньше (на всех страницах).
- Стили `.surveys*`/`.survey*` в `site.css`: адаптив (360 px), темы `html[data-theme]` (рамки), `prefers-reduced-motion`.
- Имена полей, маршрут и серверная логика не менялись. Тесты: 172 passed.

## 2026-10-21 — backend-dev: доработки анкет по замечаниям ревью
- Письмо отправляется в фоновом потоке (`mailer.deliver_survey_later`; в тестах и при `MAIL_ASYNC=0` — сразу),
  `MAIL_TIMEOUT` по умолчанию 5. Пауза отмечается (`throttle.hit`) сразу после проверки, до сохранения;
  `SURVEY_INTERVAL_SECONDS` по умолчанию 15, текст ошибки считает остаток секунд.
- Запасного адреса в коде нет: пустой `survey_email` → не отправлено, `email_error` «получатель не задан».
- Админка: «Отправить ещё раз» у ответа и «Отправить неотправленные» в списке (POST, CSRF, только admin, журнал).
- Миграция `0014_survey_email_setting.py` (`e3c7a2b9d106`, после `d2b6f1a8c995`): настройка `survey_email`,
  новые подписи/группа у `map_point` и `history_map`; downgrade возвращает прежнее.
- Мелочи: mailer не шлёт логин без SSL/TLS, ловит ValueError; шапка сводки не зависит от типа первого вопроса;
  запрос анкеты ограничен 64 КБ (`before_request` до CSRF в `__init__.py`).
- README: переменные, `TRUST_PROXY=1` за nginx, раздел «Анкеты НОК и почта», пункт «Почта».

## 2026-10-21 — tester: публичная страница анкет НОК
- Добавлен `tests/test_surveys_page.py` (38 проверок): разметка страницы НОК (ссылка и QR Минкультуры РФ, обе анкеты, все 10 и 8 вопросов,
  значения yes/no и 1..5, csrf, поле-ловушка), пропущенные вопросы (список ошибок, `open`, сохранённые `checked`, `aria-invalid` только у нужных),
  успех (редирект на `#anketa-<ключ>`, «Спасибо» выводится один раз и одноразово), регресс общего flash на «Контактах» и обычных страницах,
  паузы (разные анкеты независимы, одна и та же блокируется), 404 (не-НОК страница, неизвестный ключ), honeypot, экранирование.
- Итог до добавления: 181 passed (952 с). Новый файл: 37 passed, 1 failed.
- БАГ (frontend-dev): `_survey_form.html:10-14` выводит все flash в каждой карточке — «Спасибо» дублируется в чужой анкете.
  Тест: `test_thanks_only_in_submitted_card`.

## 2026-10-21 — frontend-dev: правки заказчика по странице события
- `event.html`: после верха (афиша, цена, факты) блоки на всю ширину в порядке: Фото и видео -> «О концерте» (описание + «Участвуют») ->
  схема зала (`#bilety` виджет Яндекс Афиши, заголовок «Схема зала и покупка билетов»; иначе `#hall`) -> Льготы и Пушкинская карта
  (`.event__terms`, две колонки при обоих блоках, на узком экране друг под другом) -> Как добраться -> Ближайшие концерты.
  Правая колонка теперь только цена и факты. Атрибуты виджета и `.event__deal` (buybar) не тронуты; кнопки покупки на `#bilety` не ведут.
- `models.py` `price_label`: «Бесплатные пригласительные билеты в кассе филармонии»; для длинной фразы модификаторы
  `--text` у `.event__price`, `.ecard__price`, `.eventrow__price`, `.buybar__price` (мельче шрифт). `schema.py` от строки не зависит.
- Карусели: стрелки вынесены в строку заголовка раздела. Макрос `carousel_nav(cid)` рядом с `event_carousel(..., cid)`, связь по id
  (`data-ecarousel-nav`, `aria-controls`), `hidden` до `is-ready`; `site.js` ищет стрелки по id. Главная: стрелки рядом с «Вся афиша»
  (`.section__tools`). Подключено в index, event, page, collective. Мобильное скрытие сохранено.
- Тесты: `tests/test_event_page.py` (7).

## 2026-10-21 — tester: страница события, free-текст, стрелки каруселей
- `tests/test_event_page.py`: 7 -> 22 тестов. Добавлено: события без медиа/описания/схемы/льгот (нет пустых секций и h2);
  льготы без текста; только Пушкинская карта; только «Участвуют»; прошедшее событие с yandex_id (нет #bilety, buybar);
  стрелки и aria-controls на страницах Пушкинской карты, льгот, коллектива (и отсутствие при пустом списке), уникальность id;
  `/kartochki-afishi` с новым текстом; админ-список событий; JSON-LD для бесплатного и платного.
- `node --check site.js` — OK.
- Полный прогон до добавления: 226 passed. Новый тест
  `test_past_event_with_hall_widget_and_yandex_id_shows_hall` ПАДАЕТ: `event.html:181` `elif ev.hall_widget and not ev.yandex_id` —
  у прошедшего события с yandex_id схема зала (hall_widget) не показывается. Чинить: frontend-dev.

## 2026-10-21 — frontend-dev: доработка по замечаниям tester/reviewer
- `event.html`: `{% elif ev.hall_widget %}` — у прошедшего события с yandex_id показывается `#hall`.
- `site.js`: `autoplay(box, advance, delay, extra)` — стрелки в заголовке ставят паузу (hover/focus) и сбрасывают таймер (click/pointerdown).
- Уникальные `cid`: home-events, event-similar, page-events, collective-events.
- `aria-controls` оставлен на обёртке `.ecarousel` (id там же): тесты tester'а проверяют `<div class="ecarousel" id=...>`; обёртка содержит ленту, это допустимо.
- `site.css`: отступ над подвалом учитывает скрытую последнюю секцию (`[hidden]`).
- `index.html`: посетителю «Ближайшие концерты скоро появятся в афише.», подсказка про админку — только при `g.user`.
- Тесты: комментарий «слева от кнопки», проверка закрытия сетки через регулярку `</div>\s*</div>`; id главной `home-events`.

## 2026-10-21 — frontend-dev, этап C1 (аудит: шаблоны, скорость, приватность в интерфейсе)
- С-12: `site.js` — скрипт Яндекс Афиши (`dealer.js`) грузит `loadDealer()` только при кнопке с `data-ya-session`, виджете `data-ya-widget`
  или кнопках, подгруженных позже (маршрут, «Ещё концерты»); на `/obrashcheniya` и т.п. не грузится. Плашка о cookie
  (`base.html`, `.cookie` в `site.css`): `role="region"`, «Принять» / «Только необходимые», ссылка на политику; показывается только когда
  есть номер Метрики и посетитель не сотрудник. Метрика (`startMetrika`) стартует после «Принять»; выбор в `localStorage` (`cookie-consent`).
  Над панелью покупки на телефоне плашка сдвигается (`body.has-buybar .cookie`).
- С-14 / SEO-16: `_pos_widget.html` — контейнер с параметрами (`data-pos-*`, 243684 не менялся) + `static/js/pos-widget.js` (выданный код целиком, включая `window.onunload`; вставка по IntersectionObserver, без него — после load).
- С-4: `_appeal_form.html` — «Я даю согласие на обработку персональных данных» -> `/info/soglasie-na-obrabotku-personalnyh-dannyh` + политика.
- SEO-5/6/7: description у collective/afisha/news_list/collectives/documents/appeals/site_map; title главной, афиши («страница N»), события
  («Название — дата, Смоленск»; `base.html` не дописывает имя учреждения, если оно уже в заголовке или итог > 90 знаков); у главной h1 —
  название учреждения (visually-hidden), слоган — `p.hero__title`.
- SEO-9/18/20/23/26/27/28: макрос `og_image` (+ размеры при наличии фильтра `image_size`), `img_dims`, запасная картинка `settings.og_image`,
  `twitter:card` по наличию картинки; афиша события `fetchpriority="high"` и размеры; ленивые плееры с `title` в `utils.video_embed`;
  `utils.image_size`; соцсети без заглушек (`schema.social_profiles`); meta verification; favicon-32/120, apple-touch-icon, favicon.ico;
  `alt` у карточек; `preload="metadata"` у видео новости; пустой `src` в окне фото убран; крошки `appeals.html` через макрос.
- Найден и исправлен баг: `pagination()` в `_macros.html` падал (500) на `/afisha?page=2` — дубль параметра `page`.
- Плашка cookie стоит в разметке сразу за skip-link; после выбора фокус уходит на `#main`. `loadDealer()` также при `[onclick*=YandexTicketsDealer]` и `#hall`.
- Тесты: `tests/test_seo_frontend.py` (29), `test_site.py::test_pos_widget_on_home_page` обновлён под `data-pos-*`.

## 2026-10-21 — backend-dev: этап A аудита (безопасность и серверное SEO)
- С-1: `admin/common.py` `safe_url` (`/путь`, `#якорь`, https/http/mailto/tel; управляющие символы и `//`, `/\` — отказ) применён к меню, баннерам,
  документам (и документам новости), `ticket_url`, значку афиши, цели перенаправления; `notice_link` отсекает управляющие символы.
  Невалидная ссылка — flash/ошибка формы, запись и файл не сохраняются.
- С-3: `BODY_LIMITS` в `__init__.py` (анкета 64 КБ, обращения 128 КБ, `/csp-report` 16 КБ); message обращения до 10 000, остальные поля по колонкам, NUL
  вычищается; csp-report чистит управляющие символы (`web.LOG_UNSAFE`).
- SEO-2: `check_site_url` (отказ запуска при SECURE/TRUST_PROXY без SITE_URL; предупреждение при NOINDEX + явном SITE_URL); `config.site_url_from_env`:
  SITE_URL -> RENDER_EXTERNAL_URL -> https://RENDER_EXTERNAL_HOSTNAME.
- С-5: `safe_next` (urlsplit + управляющие символы). С-6: Pillow 13.0.0 (установлен, тесты зелёные). С-7: `title_of(Appeal)` = «Обращение № id».
- С-8: `admin_required` на обращениях, кнопка и маршрут удаления (с журналом), меню/сводка/счётчик скрыты от редактора.
- С-9: `python app.py purge` (`maintenance.purge`), настройка `surveys_retention_years` (seed + миграция `0015_surveys_retention_setting`, ревизия f4d8b3c1e207).
- С-11/SEO-4: basic-auth стенда (`web.stand_auth`, STAND_USER/STAND_PASSWORD), `/healthz`, `X-Robots-Tag: noindex, nofollow` при SITE_NOINDEX, robots `Allow: /`;
  без пароля стенд закрывает приём обращений и анкет. render.yaml: healthCheckPath `/healthz`, STAND_* `sync: false`.
- SEO-13 (Clean-param), SEO-14 (301 `/info/internet-priemnaya` -> `/obrashcheniya`, вне sitemap/карты сайта, меню ведёт сразу на новый адрес),
  SEO-15 (пустые разделы документов вне sitemap), SEO-21 (404 за пределами пагинации), SEO-24 (Last-Modified/304 у событий и новостей), SEO-25 (`strip_tags`).
- С-16/С-17: проверка пароля-заглушки для неизвестного логина (и для отключённого сотрудника), логин в ключе throttle до 64 знаков.
- С-15/С-22: README «Выкладка на боевой сервер» и «Поисковики после запуска»; `.env.example`, DEPLOY-RENDER.md.
- Тесты: `tests/test_audit_security.py` (92).

## 2026-10-21 — backend-dev: этап B аудита (схема БД и серверная часть)
- Миграция `0016_event_status_seo_consent` (ревизия `a5e9c4d2f318`, предыдущая `f4d8b3c1e207`; `batch_alter_table`, проверена на SQLite:
  upgrade с 0015, downgrade, повторный upgrade, база после seed): `events.status/previous_starts_at/is_free/seo_title/seo_description`,
  `collectives` и `news` — `seo_title/seo_description`, `appeals.consent_version/consent_at`. Данные: `is_free=true` у концертов без «от» и «до»;
  настройки `og_image` (file), `yandex_verification`, `google_site_verification`, `home_title`, `consent_version` (2026-10-21), `site_full_name`;
  страница «Согласие на обработку персональных данных» (ПРОЕКТ текста по ст. 9 152-ФЗ, пометка «согласовать с юристом»). Всё «если нет». Тот же текст в `seed.py`.
- Модель `Event`: `price_label` (бесплатно только при `is_free`, иначе «Цена уточняется»), `status_label`, `is_cancelled`, `sells_tickets`, `can_buy`.
- Админка: статус (select), прежняя дата (только для «Перенесён», скрипт в `admin.js`), «Бесплатный концерт» (цены обнуляются), блок «Для поисковиков»
  у событий/коллективов/новостей (`common.set_seo`, обрезка 200/300); копия события сбрасывает статус; «Изменения в афише» — подсказка со ссылкой
  на событие (статус молча не меняется). Список событий показывает статус.
- Публичные шаблоны (минимум): `buy_button` не выводится при `sells_tickets` ложном; `event.html` — плашка `.event__status`, `can_buy` для кнопки/панели,
  `#bilety`/`#hall` скрыты у отменённого/отложенного; пометки `.ecard__status`, `.eventrow__status`; `seo_title`/`seo_description` в title/description.
- `schema.py`: eventStatus, previousStartDate, Offer/AggregateOffer/бесплатно (цена 0 + isAccessibleForFree), availability только при заполненном
  «Наличии билетов», location из адреса организации, performer из текста, organizer `@id /#organization`; Organization: alternateName, geo, строгий разбор
  режима работы, реальные sameAs.
- Согласие: `consent_version` (из настройки) и `consent_at` сохраняются с обращением, видны в карточке в админке.
- C1: фильтр `image_size` в JINJA_FILTERS, маршрут `/favicon.ico`. Месяц в контексте афиши не добавлялся (описание уже учитывает день).
- SEO-12: `common.keep_old_address` — при смене slug опубликованного события, новости, коллектива, страницы создаётся Redirect (без цепочек, без петель,
  ручное правило не перезаписывается). Фестиваль: slug после создания не меняется.
- SEO-17: `VARIANT_WIDTHS = (400, 800, 1200, 1600, 1920)`; пересборка недостающих копий — существующая `python app.py thumbs`.
- Тесты: `tests/test_stage_b.py` (53), правки `tests/test_event_page.py` под «Цена уточняется» и цену 0 в JSON-LD. README обновлён.
- Миграция: «без цены» для is_free включает 0 (в форме он выглядит пустым полем); дата согласия в карточке обращения показывается по Москве.

## 2026-10-21 — frontend-dev: этап C2 (оформление статуса концерта)
- `site.css`: плашка `.event__status` (отменён — кирпичная, перенесён/отложен — золотая; слева рамка 5px, текст тёмный на светлом фоне, контраст AA); `.ecard__status` — метка на фото слева над строкой времени (не пересекается с датой и `.ecard__flags`, те сверху); `.eventrow__status` — метка под названием. Отменённый: афиша карточки/строки приглушена, дата и цена зачёркнуты (`.ecard--cancelled`, `.eventrow--cancelled`, `*__price--off`). Версия для слабовидящих (`html[data-theme]`): белая/чёрная плашка с рамкой, у отменённого двойная.
- `event.html`: у концерта без продажи (отменён/отложен, не прошедший) вместо кнопки строка «Продажа билетов остановлена.» (`.event__note--stop`); `_macros.html`: модификаторы `--cancelled`/`--off`.
- `page.html` + CSS: если в тексте страницы есть «Проект текста.» — `.prose--draft`, первый абзац выделяется как предупреждение (данные не менялись).
- Админка: значок статуса в списке событий — `badge--stop` (отменён) / `badge--warn`; форма события уже на существующих `.grid`/`.field`/`.checkline`, правок не потребовалось.
- Тесты: `tests/test_status_ui.py` (10).

## 2026-10-21 — backend-dev: доработки по ревью (reviewer + security-auditor)
- render.yaml: `seed` при сборке идёт с `TRUST_PROXY=0 SESSION_COOKIE_SECURE=0` (проверка SITE_URL при запуске gunicorn осталась); DEPLOY-RENDER.md: строка про SITE_URL, опечатка в адресе.
- Миграция 0016 (правка на месте): `is_free` только при пустых/нулевых ценах И пустых `yandex_id`/`ticket_url`; downgrade данные не удаляет (только колонки: страницу согласия и настройки редактор мог изменить). Seed: демо-концерты с ссылкой на билеты — `is_free=False`.
- Новая миграция `0017_depersonalize_appeal_log` (ревизия b7d1e6a39c42, предыдущая a5e9c4d2f318): `action_log.title = 'Обращение № ' || CAST(object_id AS VARCHAR)` для `object_type='appeal'`; downgrade — no-op.
- Last-Modified: `utils.to_utc`; `common.touch`; updated_at владельца обновляется при `media_add/delete/move`, `badge_add/delete`, сохранении события (площадка, коллективы, фестивали), правке площадки (все её события). Событие после начала: `max(updated_at, to_utc(starts_at))`; новость без updated_at — `to_utc(published_at)`.
- Копия события: `updated_at` не копируется (как и `created_at`).
- `strip_tags`: `html.unescape` результата (выход по-прежнему экранируется шаблоном и tojson). `schema.offers`: относительный `ticket_url` -> абсолютный через `site_url()`.
- Страница: `seo_description` через `seo_text(..., 400)` + `maxlength="400"`. 413: у публичных форм своё сообщение, у админки прежнее (64 МБ). Seed: `consent_at` в UTC. Вход: управляющие символы в логине вычищаются. `_appeal_back` отклоняет управляющие символы.
- Перенаправления: ручное правило проверяется по цепочке таблицы (петля любой длины — отказ); автоперенаправление перезаписывает правило для старого адреса, если оно вело не на текущую запись (docstring `keep_old_address` и тест `test_stale_rule_for_old_address_rewritten...` обновлены).
- Тесты: `tests/test_review_fixes.py` (+правки `test_stage_b.py`). Полный прогон: 446 passed.

## 2026-10-22 — README сокращён
- README: 630 -> 69 строк (запуск, команды, обновление, проверки, ссылки, что осталось).
- Боевой сервер (systemd, nginx, права, бэкапы, после выкладки, поисковики), таблица переменных окружения, почта,
  изображения, кэш/CSP, обновление Jodit — без изменений текста перенесены в `docs/DEPLOY-SERVER.md`.
- Описания функций (статусы, SEO-поля, согласие, безопасность) убраны из README — они есть в `docs/ARCHITECTURE.md`.
- Ссылки на README обновлены: DEPLOY-RENDER.md, render.yaml, комментарий в `filarmonia/__init__.py`, ARCHITECTURE.md.
