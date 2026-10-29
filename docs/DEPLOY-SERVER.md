# Боевой сервер: установка и сопровождение

Для администратора сервера. Запуск для разработки и команды — в [README.md](../README.md),
тестовый стенд на Render — в [DEPLOY-RENDER.md](../DEPLOY-RENDER.md).

## Выкладка на боевой сервер

Чек-лист для администратора сервера (Linux, nginx, gunicorn, PostgreSQL). Хостинг и
домен для сайта учреждения культуры должны быть российскими. Пути ниже — примеры.

### 1. Переменные окружения

Файл `/etc/filarmonia.env` (права `0640`, владелец `root:filarmonia`); его читает systemd
и команда `purge`. Образец со всеми переменными — `.env.example`.

```
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=postgresql+psycopg://filarmonia:пароль@localhost/filarmonia
UPLOAD_FOLDER=/srv/filarmonia/uploads
SESSION_COOKIE_SECURE=1
TRUST_PROXY=1
SITE_URL=https://smolensk-filarmonia.ru
ADMIN_PASSWORD=<сильный пароль, только для первого seed>
MAIL_SERVER=smtp.yandex.ru
MAIL_USERNAME=...
MAIL_PASSWORD=<пароль приложения>
LOG_FILE=/var/log/filarmonia/site.log
COMPRESS_RESPONSES=0
```

`SITE_NOINDEX` на боевом не ставится. Без `SECRET_KEY` и `SITE_URL` сайт с этими
настройками не запустится — это сделано намеренно.

### 2. gunicorn и systemd

gunicorn слушает **только `127.0.0.1`**, наружу смотрит один nginx. Юнит
`/etc/systemd/system/filarmonia.service`:

```ini
[Unit]
Description=Сайт Смоленской областной филармонии
After=network.target postgresql.service

[Service]
User=filarmonia
Group=filarmonia
WorkingDirectory=/srv/filarmonia/app
EnvironmentFile=/etc/filarmonia.env
ExecStart=/srv/filarmonia/venv/bin/gunicorn -w 3 -b 127.0.0.1:8001 --timeout 120 app:app
Restart=on-failure
UMask=0027

# Ограничения: сайт видит только свой код и каталог загрузок
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=true
CapabilityBoundingSet=
SystemCallFilter=@system-service
# Писать можно только сюда (для SQLite добавьте каталог базы)
ReadWritePaths=/srv/filarmonia/uploads /var/log/filarmonia

[Install]
WantedBy=multi-user.target
```

После правки: `systemctl daemon-reload && systemctl enable --now filarmonia`.
Проверка ограничений: `systemd-analyze security filarmonia`.

### 3. nginx

Общие строки проксирования — в `/etc/nginx/snippets/filarmonia-proxy.conf` (каждый
`location` ниже подключает его сам, поэтому `proxy_pass` в них не повторяется):

```nginx
proxy_pass http://127.0.0.1:8001;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;      # обязательно: приложение берёт адрес из него
proxy_hide_header Server;
```

Сайт `/etc/nginx/conf.d/filarmonia.conf`:

```nginx
limit_req_zone $binary_remote_addr zone=forms:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=site:10m rate=20r/s;

# Запросы с чужим именем сайта отклоняются
server {
    listen 443 ssl default_server;
    ssl_reject_handshake on;
}

# HTTP -> HTTPS
server {
    listen 80;
    server_name smolensk-filarmonia.ru www.smolensk-filarmonia.ru;
    return 301 https://smolensk-filarmonia.ru$request_uri;
}

server {
    listen 443 ssl http2;
    server_name smolensk-filarmonia.ru;
    # ssl_certificate, ssl_certificate_key — сертификат (Let's Encrypt или российский УЦ)
    server_tokens off;
    add_header Strict-Transport-Security "max-age=31536000" always;

    gzip on;
    gzip_types text/css application/javascript application/json application/xml
               text/plain image/svg+xml;

    limit_req zone=site burst=60 nodelay;
    client_max_body_size 1m;                  # по умолчанию маленький; больше — только ниже

    location /static/ {
        alias /srv/filarmonia/app/filarmonia/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        add_header X-Content-Type-Options "nosniff" always;
    }

    # Загруженные файлы только отдаются, ничего не выполняется: каталог вне кода,
    # без fastcgi/uwsgi, а SVG и PDF не могут запускать скрипты на нашем домене
    location /static/uploads/ {
        alias /srv/filarmonia/uploads/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Security-Policy "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; sandbox" always;
    }

    # Вход в панель: не чаще 10 запросов в минуту с адреса
    location = /admin/login {
        # allow 203.0.113.0/24;  deny all;     # по возможности — панель только с адресов учреждения
        client_max_body_size 8k;
        limit_req zone=forms burst=5 nodelay;
        include snippets/filarmonia-proxy.conf;
    }

    # Панель: сюда загружают фото, видео и документы (до 64 МБ)
    location ^~ /admin/ {
        # allow 203.0.113.0/24;  deny all;
        client_max_body_size 70m;
        include snippets/filarmonia-proxy.conf;
    }

    # Интернет-приёмная, анкеты НОК и отчёты браузера: маленькие запросы, редкие
    location = /obrashcheniya {
        client_max_body_size 128k;
        limit_req zone=forms burst=5 nodelay;
        include snippets/filarmonia-proxy.conf;
    }
    location ~ ^/info/[^/]+/anketa/[^/]+$ {
        client_max_body_size 64k;
        limit_req zone=forms burst=5 nodelay;
        include snippets/filarmonia-proxy.conf;
    }
    location = /csp-report {
        client_max_body_size 16k;
        include snippets/filarmonia-proxy.conf;
    }

    location / {
        include snippets/filarmonia-proxy.conf;
    }
}
```

Приложение само ограничивает те же адреса (128 КБ, 64 КБ, 16 КБ), nginx отсекает
лишнее раньше. `COMPRESS_RESPONSES=0`, потому что сжимает nginx.

### 4. Права на папки

- Код `/srv/filarmonia/app` — владелец `root`, пользователю `filarmonia` только чтение.
- Загрузки `/srv/filarmonia/uploads` и журнал `/var/log/filarmonia` — владелец `filarmonia`,
  права `0750`; nginx читает загрузки через группу (`www-data` добавить в группу `filarmonia`).
- `/etc/filarmonia.env` и базу SQLite (если она есть) не отдавать никому, кроме `filarmonia`.
- Каталог загрузок не должен лежать внутри каталога, который nginx отдаёт целиком.

### 5. Резервные копии

- База: ежедневно `pg_dump -Fc filarmonia > /backup/filarmonia-$(date +%F).dump`, хранить
  не меньше 30 дней.
- Загрузки: ежедневно `rsync -a /srv/filarmonia/uploads/ /backup/uploads/`.
- Копии хранить **вне сервера** (другой хост или облако в РФ). Раз в квартал проверять,
  что копию можно развернуть на чистой машине.

### 6. После выкладки

1. `python app.py db upgrade` — схема базы до последней версии.
2. `ADMIN_PASSWORD=… python app.py seed` — первичное наполнение (меню, страницы, настройки).
   Сразу после входа сменить пароль администратора и убрать `ADMIN_PASSWORD` из окружения.
3. В «Настройках» заменить заглушку `survey_email` (`test@test.ru`) на настоящую почту,
   проверить `appeals_retention_years` (5) и `surveys_retention_years` (3), указать
   `yandex_metrika_id` (счётчик Яндекс.Метрики), реальные адреса соцсетей.
4. **Удалить демо-контент**: тестовые афиши, новости, коллективов, демо-обращения с ФИО
   (раздел «Обращения граждан» — удалить каждое), демо-документы с адресом `#`.
5. Расписание удаления по сроку хранения. Вариант с systemd-таймером
   (`/etc/systemd/system/filarmonia-purge.service` и `.timer`):

   ```ini
   [Service]
   Type=oneshot
   User=filarmonia
   WorkingDirectory=/srv/filarmonia/app
   EnvironmentFile=/etc/filarmonia.env
   ExecStart=/srv/filarmonia/venv/bin/python app.py purge
   ```
   ```ini
   [Timer]
   OnCalendar=*-*-* 03:30:00
   Persistent=true
   [Install]
   WantedBy=timers.target
   ```

   Либо строка cron (обязательно с теми же переменными окружения: без них команда
   обратится к SQLite по умолчанию, а не к рабочей базе):

   ```
   30 3 * * * filarmonia cd /srv/filarmonia/app && set -a && . /etc/filarmonia.env && set +a && /srv/filarmonia/venv/bin/python app.py purge
   ```
6. Проверить: `https://…/robots.txt` (есть `Sitemap`, нет `Disallow: /`),
   `https://…/sitemap.xml`, заголовок `Strict-Transport-Security`, что `http://` уходит на `https://`,
   что `http://127.0.0.1:8001` недоступен снаружи (порт закрыт файрволом).

### Поисковики после запуска

1. **Яндекс.Вебмастер**: добавить сайт, подтвердить права (мета-тег или файл — код вставляется
   в настройках/шаблоне), загрузить `sitemap.xml`, указать регион «Смоленск», проверить
   главное зеркало (с `www` или без — одно, второе перенаправляется на него).
2. **Google Search Console**: добавить ресурс, подтвердить права, отправить `sitemap.xml`.
3. **Яндекс.Бизнес и 2ГИС**: завести карточки организации; название, адрес и телефон
   (NAP) — ровно как в «Настройках» сайта.
4. **Тестовый стенд**: убедиться, что он не попал в выдачу (в Вебмастере и запросом
   `site:адрес-стенда` в поиске); если попал — оставить `SITE_NOINDEX=1`, задать
   `STAND_USER`/`STAND_PASSWORD`, запросить удаление страниц.

## Переменные окружения

Все параметры читаются из переменных окружения — см. `.env.example` и `config.py`.
Файл `.env` приложение само не читает: переменные задаёт systemd (`EnvironmentFile`),
панель хостинга или оболочка.

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | подпись сессий |
| `DATABASE_URL` | SQLite рядом с `config.py` | строка подключения к базе |
| `UPLOAD_FOLDER` | `filarmonia/static/uploads` | каталог загруженных файлов |
| `SESSION_COOKIE_SECURE` | `0` | `1` — cookie только по HTTPS |
| `TRUST_PROXY` | `0` | `1` — брать протокол и адрес клиента из `X-Forwarded-*` |
| `SITE_NOINDEX` | `0` | `1` — закрыть сайт от поисковиков (для тестовых копий): `noindex` в страницах и заголовок `X-Robots-Tag: noindex, nofollow` на все ответы; `robots.txt` обход не запрещает, иначе робот не увидел бы запрет |
| `STAND_USER`, `STAND_PASSWORD` | — | при `SITE_NOINDEX=1` закрывают весь тестовый сайт паролем (basic-auth; `/static` и `/healthz` открыты). Без них стенд открыт всем, и приём обращений и анкет на нём отключён: персональные данные на открытый стенд попадать не должны |
| `ADMIN_PASSWORD` | `filarmonia2026` | пароль администратора при создании базы командой `seed` |
| `IMAGE_MAX_SIDE` | `2000` | максимальный размер загружаемых фотографий в пикселях |
| `IMAGE_QUALITY` | `85` | качество пересохранения фотографий |
| `LOGIN_MAX_ATTEMPTS` | `5` | неудачных попыток входа до блокировки |
| `LOGIN_LOCKOUT_SECONDS` | `900` | на сколько запирать вход после них |
| `APPEAL_INTERVAL_SECONDS` | `60` | пауза между обращениями с одного адреса |
| `SURVEY_INTERVAL_SECONDS` | `15` | пауза между отправками одной анкеты НОК с одного адреса |
| `MAIL_SERVER` | — | SMTP-сервер; пусто — письма не отправляются, анкеты только сохраняются |
| `MAIL_PORT` | `465` | порт SMTP-сервера |
| `MAIL_USE_SSL` | `1` | соединение сразу по SSL (порт 465) |
| `MAIL_USE_TLS` | `0` | STARTTLS (порт 587); при нём `MAIL_USE_SSL=0` |
| `MAIL_USERNAME` | — | логин почтового ящика (полный адрес) |
| `MAIL_PASSWORD` | — | пароль приложения почтового ящика |
| `MAIL_FROM` | — | адрес отправителя; пусто — берётся `MAIL_USERNAME` |
| `MAIL_TIMEOUT` | `5` | таймаут соединения с почтовым сервером, секунды |
| `MAIL_ASYNC` | `1` | `1` — письма уходят в фоновом потоке, посетитель не ждёт |
| `SITE_URL` | — | адрес сайта (`https://smolensk-filarmonia.ru`) для канонических ссылок, карты сайта и микроразметки. **На боевом сервере задать обязательно**: с `SESSION_COOKIE_SECURE=1` или `TRUST_PROXY=1` без него сайт не запустится (иначе адреса в карте сайта и `canonical` строились бы из заголовка `Host`, который подставляет кто угодно). На Render, если пусто, берётся `RENDER_EXTERNAL_URL`. Если вместе с заданным `SITE_URL` стоит `SITE_NOINDEX=1`, при запуске пишется предупреждение |
| `SESSION_HOURS` | `8` | наибольшая длительность сеанса сотрудника |
| `SESSION_IDLE_MINUTES` | `60` | сеанс завершается после стольких минут бездействия |
| `COMPRESS_RESPONSES` | `1` | `0` — не сжимать ответы в приложении (если сжимает nginx) |
| `LOG_FILE` | — | файл журнала с ротацией по 5 МБ; без него журнал идёт в поток ошибок |

**`SECRET_KEY` обязателен на боевом сервере.** Если он не задан, а включён
`SESSION_COOKIE_SECURE` или `TRUST_PROXY`, приложение не запустится: с ключом
из репозитория кто угодно подделает сессионную куку и войдёт администратором.
Локально выводится только предупреждение.

## Сопровождение

### Почта (анкеты НОК)

- Адрес получателя — настройка «Почта, на которую приходят заполненные анкеты»
  (`survey_email`, группа «Независимая оценка качества»); без неё письма не уходят.
- Отправитель задаётся в `.env`: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`.
  Яндекс 360: `smtp.yandex.ru`, порт 465; Mail.ru: `smtp.mail.ru`, порт 465.
  В `MAIL_PASSWORD` нужен **пароль приложения** (создаётся в настройках безопасности
  почты), а не пароль для входа.
- Если письмо не ушло, ответ всё равно сохранён; в панели его можно отправить заново
  («Отправить ещё раз» и «Отправить неотправленные»).
- После обновления кода выполните `python app.py db upgrade`: появится таблица ответов
  и настройка получателя. Сразу впишите в неё настоящий адрес — по умолчанию там
  `test@test.ru`.

### Загрузка изображений

Фотографии, загруженные через панель администратора, автоматически уменьшаются до 2000 px по
длинной стороне и пересохраняются с качеством 85: снимок с телефона весит 8–12 МБ,
а в вёрстке нигде не крупнее 2000 px. Пороги меняются переменными `IMAGE_MAX_SIDE`
и `IMAGE_QUALITY`. GIF не трогается, чтобы не потерять анимацию.

Рядом с каждым фото сохраняются копии шириной 400, 800, 1200, 1600 и 1920 px в WebP (копию
шире самого фото не делают), и страница отдаёт их через `srcset`: телефон скачивает картинку
под свой экран, а широкий монитор — 1600/1920 вместо оригинала JPEG.
Копии для уже загруженных фото (в том числе новые 1600 и 1920 после обновления сайта)
делает команда `python app.py thumbs`: она идемпотентна — создаёт только недостающие копии,
существующие не трогает. После неё перезапустите сайт: набор копий для `srcset` запоминается
в памяти процесса по времени изменения оригинала.

Принимаются только JPEG, PNG, WebP и GIF, причём формат проверяется по содержимому,
а не по расширению: файл другого формата, переименованный в `.jpg`, отклоняется.
При удалении записи её файлы удаляются с диска, если на них больше никто не ссылается
(копия события делит фото с оригиналом).

### Кэш, сжатие, CSP

Стили и скрипты подключаются с номером версии (`site.css?v=…`), имена загруженных
файлов уникальны — поэтому такая статика кэшируется на год. Страницы отдаются
с `ETag`: браузер перепроверяет их и получает ответ 304 без тела, если ничего не менялось.

Приложение само сжимает текстовые ответы (gzip) и ставит заголовки безопасности:
`Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`,
`Referrer-Policy`, а при `SESSION_COOKIE_SECURE=1` — `Strict-Transport-Security`.
Для панели администратора политика строгая. Для сайта строгая только её часть
(запрет встраивания в чужие сайты, `<object>`, подмены `<base>`), а полная политика
пока работает в режиме наблюдения (`Report-Only`): нарушения пишутся в журнал
с пометкой `CSP:`. Когда за пару недель в журнале соберутся все источники виджетов
Госуслуг и карт, полную политику можно включить, перенеся её из
`PUBLIC_CSP_REPORT` в `PUBLIC_CSP` (`filarmonia/web.py`).

За таким nginx сжатие в приложении можно выключить: `COMPRESS_RESPONSES=0`.
Без nginx статику отдаёт само приложение с теми же сроками кэширования.

**За nginx `TRUST_PROXY=1` обязателен.** Без него все посетители выглядят для
приложения одним адресом (адресом nginx): пауза между обращениями и анкетами и
блокировка подбора пароля будут действовать на всех сразу.

### Визуальный редактор Jodit

Лежит в `filarmonia/static/vendor/jodit/` — версия 4.17.1, пакет npm `jodit`
(лицензия MIT). Обновление: скачать новую версию (`npm pack jodit@<версия>`),
заменить `jodit.min.js` и `jodit.min.css` файлами из сборки пакета, обновить версию
в этом абзаце, проверить редактор в формах события и новости. Раз в квартал
сверять версию с базой уязвимостей: <https://osv.dev/list?ecosystem=npm&q=jodit>.
