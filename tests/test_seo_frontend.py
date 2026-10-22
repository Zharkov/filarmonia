"""Заголовки, описания, картинки для соцсетей, согласие на cookie и сторонние скрипты."""
import os
import re

from conftest import create_event, png, text

from filarmonia import utils
from filarmonia.models import db, Collective, Event, MediaItem, News, Setting

EV_URL = "/afisha/testovyy-koncert"


def _set(app, **values):
    with app.app_context():
        for key, value in values.items():
            Setting.set(key, value)
        db.session.commit()


def _upload(app, name, size=(60, 80)):
    """Кладёт картинку в каталог загрузок: размеры читаются с настоящего файла."""
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as f:
        f.write(png(size).getvalue())


def _title(html):
    return re.search(r"<title>(.*?)</title>", html, re.S).group(1)


def _description(html):
    return re.search(r'<meta name="description" content="(.*?)">', html, re.S).group(1)


def _og_image(html):
    m = re.search(r'<meta property="og:image" content="([^"]*)">', html)
    return m.group(1) if m else None


# Заголовки, описания, H1

def test_home_title_h1_and_slogan(app):
    html = text(app.test_client().get("/"))
    assert "афиша концертов и билеты" in _title(html)
    # Один h1 — название учреждения; слоган оформлен как заголовок, но не h1
    assert html.count("<h1") == 1
    assert re.search(r'<h1 class="visually-hidden">Филармония</h1>', html)
    assert '<p class="hero__title">Музыка на все времена</p>' in html


def test_home_title_from_settings(app):
    _set(app, home_title="Свой заголовок главной")
    assert _title(text(app.test_client().get("/"))).startswith("Свой заголовок главной")


def test_afisha_title_description_and_page_number(app):
    from datetime import datetime, timedelta
    with app.app_context():
        # Больше, чем помещается на странице: иначе второй страницы нет (она отвечает 404)
        for n in range(16):
            db.session.add(Event(title=f"Концерт {n}", slug=f"koncert-{n}",
                                 starts_at=datetime(2030, 1, 1, 19) + timedelta(days=n)))
        db.session.commit()
    client = app.test_client()
    html = text(client.get("/afisha"))
    # Название учреждения уже в заголовке (из настройки site_name), второй раз не дописывается
    assert _title(html) == "Афиша концертов в Смоленске — Филармония"
    assert _description(html).startswith("Афиша концертов Смоленской областной филармонии")
    assert "страница" not in _title(html)
    assert "страница 2" in _title(text(client.get("/afisha?page=2")))


def test_news_list_page_number_in_title(app):
    with app.app_context():
        for n in range(13):
            db.session.add(News(title=f"Новость {n}", slug=f"novost-{n}"))
        db.session.commit()
    client = app.test_client()
    assert "страница" not in _title(text(client.get("/novosti")))
    assert "страница 2" in _title(text(client.get("/novosti?page=2")))


def test_event_title_is_short_with_city(app, admin):
    create_event(admin)
    title = _title(text(app.test_client().get(EV_URL)))
    assert title.startswith("Тестовый концерт — ") and "Смоленск" in title and "2030" in title
    # Название учреждения дописывается, пока заголовок не вышел за ~90 знаков
    assert len(title) <= 100


def test_long_event_title_has_no_site_name_suffix(app, admin):
    create_event(admin, title="Очень длинное название концерта симфонического оркестра с солистами")
    with app.app_context():
        slug = Event.query.first().slug
    title = _title(text(app.test_client().get("/afisha/" + slug)))
    assert title.endswith(", Смоленск")


def test_descriptions_differ_between_page_types(app):
    client = app.test_client()
    default = _description(text(client.get("/")))
    seen = {default}
    for path in ("/novosti", "/kollektivy", "/dokumenty", "/obrashcheniya", "/karta-sajta", "/afisha"):
        description = _description(text(client.get(path)))
        assert description not in seen, path
        seen.add(description)


def test_collective_description_and_og_image(app):
    _upload(app, "logo.png")
    _upload(app, "photo.png")
    with app.app_context():
        c = Collective(name="Оркестр-сео", slug="orkestr-seo", lead="Иванов И. И.",
                       annotation="<p>Симфонический оркестр филармонии</p>", logo="logo.png")
        db.session.add(c)
        db.session.commit()
    client = app.test_client()
    html = text(client.get("/kollektivy/orkestr-seo"))
    assert _description(html) == "Симфонический оркестр филармонии"
    assert _og_image(html).endswith("/static/uploads/logo.png")
    with app.app_context():
        c = Collective.query.first()
        db.session.add(MediaItem(kind="photo", file="photo.png", collective_id=c.id))
        db.session.commit()
    # Первое фото важнее логотипа
    assert _og_image(text(client.get("/kollektivy/orkestr-seo"))).endswith("/static/uploads/photo.png")


# Картинки для соцсетей

def test_event_og_image_prefers_cover_over_poster(app, admin):
    _upload(app, "poster.png", (60, 80))
    _upload(app, "cover.png", (160, 90))
    create_event(admin)
    with app.app_context():
        ev = Event.query.first()
        ev.poster, ev.cover = "poster.png", "cover.png"
        db.session.commit()
    html = text(app.test_client().get(EV_URL))
    assert _og_image(html).endswith("/static/uploads/cover.png")
    assert 'name="twitter:card" content="summary_large_image"' in html


def test_event_og_image_falls_back_to_poster(app, admin):
    _upload(app, "poster.png")
    create_event(admin)
    with app.app_context():
        Event.query.first().poster = "poster.png"
        db.session.commit()
    assert _og_image(text(app.test_client().get(EV_URL))).endswith("/static/uploads/poster.png")


def test_no_image_means_summary_card_and_default_from_settings(app, admin):
    create_event(admin)
    client = app.test_client()
    html = text(client.get(EV_URL))
    assert _og_image(html) is None and 'name="twitter:card" content="summary"' in html
    _set(app, og_image="share.png")
    html = text(client.get("/"))
    assert _og_image(html).endswith("/static/uploads/share.png")
    assert 'content="summary_large_image"' in html


def test_og_image_size_when_filter_registered(app, admin):
    # Фильтр image_size подключает приложение (этап B); здесь — как будет после подключения
    app.jinja_env.filters.setdefault("image_size", utils.image_size)
    _upload(app, "cover.png", (160, 90))
    create_event(admin)
    with app.app_context():
        Event.query.first().cover = "cover.png"
        db.session.commit()
    html = text(app.test_client().get(EV_URL))
    assert 'property="og:image:width" content="160"' in html
    assert 'property="og:image:height" content="90"' in html


# Соцсети, подтверждения, значки

def test_social_stubs_are_not_rendered(app):
    _set(app, social_vk="https://vk.com/", social_ok="https://ok.ru", social_tg="https://t.me/filarmonia",
         social_max="")
    html = text(app.test_client().get("/"))
    assert 'aria-label="ВКонтакте"' not in html and 'aria-label="Одноклассники"' not in html
    assert 'href="https://t.me/filarmonia"' in html
    _set(app, social_vk="https://vk.com/club123")
    assert 'href="https://vk.com/club123"' in text(app.test_client().get("/"))


def test_verification_meta_only_when_set(app):
    client = app.test_client()
    html = text(client.get("/"))
    assert "yandex-verification" not in html and "google-site-verification" not in html
    _set(app, yandex_verification="abc123", google_site_verification="xyz789")
    html = text(client.get("/"))
    assert '<meta name="yandex-verification" content="abc123">' in html
    assert '<meta name="google-site-verification" content="xyz789">' in html


def test_favicons_linked_and_present(app):
    html = text(app.test_client().get("/"))
    for name in ("favicon-32.png", "favicon-120.png", "apple-touch-icon.png"):
        assert name in html
        assert os.path.exists(os.path.join(app.static_folder, name))
    assert 'rel="apple-touch-icon"' in html


def test_photo_viewer_has_no_empty_src(app):
    html = text(app.test_client().get("/"))
    assert 'src=""' not in html


# Сторонние скрипты и cookie

def test_appeals_page_has_no_dealer_triggers_and_has_breadcrumbs(app):
    _set(app, yandex_client_key="test-key")
    html = text(app.test_client().get("/obrashcheniya"))
    # Скрипт Яндекс Афиши site.js подключает только при кнопке покупки или виджете — их тут нет
    assert "data-ya-session" not in html and "data-ya-widget" not in html
    assert '"@type": "BreadcrumbList"' in html or '"BreadcrumbList"' in html


def test_dealer_loaded_lazily_by_script():
    js = open(os.path.join(os.path.dirname(__file__), "..", "filarmonia", "static", "js", "site.js"),
              encoding="utf-8").read()
    assert js.count("dealer.js") == 1
    # Адрес скрипта продавца — только внутри loadDealer, которую зовут при появлении кнопок
    assert js.index("function loadDealer") < js.index("dealer.js") < js.index("function bindYandex")
    assert "if (buttons.length) loadDealer();" in js


def test_event_with_session_has_dealer_trigger(app, admin):
    _set(app, yandex_client_key="test-key")
    create_event(admin, yandex_id="ticketsteam-825@496249")
    assert "data-ya-session=" in text(app.test_client().get(EV_URL))


def test_cookie_banner_only_with_metrika_for_visitors(app, admin):
    client = app.test_client()
    assert "data-cookie" not in text(client.get("/"))
    _set(app, yandex_metrika_id="12345678")
    html = text(client.get("/"))
    assert "data-cookie" in html and 'role="region"' in html
    assert 'data-cookie-choice="all"' in html and 'data-cookie-choice="necessary"' in html
    assert "Принять" in html and "Только необходимые" in html and "politika-konfidencialnosti" in html
    # Скрипт Метрики в разметку не вставлен: его запускает site.js после согласия
    assert "mc.yandex.ru" not in html
    assert "data-cookie" not in text(admin.get("/"))


def test_metrika_starts_only_after_consent():
    js = open(os.path.join(os.path.dirname(__file__), "..", "filarmonia", "static", "js", "site.js"),
              encoding="utf-8").read()
    assert js.count("metrika/tag.js") == 1
    assert js.index("function startMetrika") < js.index("metrika/tag.js") < js.index('consent === "all"')
    assert 'if (choice === "all") startMetrika();' in js


# Согласие в форме обращения

def test_appeal_form_links_consent_page(app):
    html = text(app.test_client().get("/obrashcheniya"))
    assert 'href="/info/soglasie-na-obrabotku-personalnyh-dannyh"' in html
    assert "Я даю" in html and "согласие на обработку персональных данных" in html
    assert "politika-konfidencialnosti" in html and 'name="consent"' in html


# Госуслуги

def test_pos_widget_is_deferred_to_script_file(app):
    html = text(app.test_client().get("/"))
    assert "data-pos-widget" in html and 'data-pos-id="243684"' in html
    assert "js/pos-widget.js" in html
    # Ни внешнего скрипта, ни встроенного кода в разметке: их вставляет pos-widget.js при показе блока
    assert "script.min.js\"></script>" not in html and "window.onunload" not in html
    js = open(os.path.join(app.static_folder, "js", "pos-widget.js"), encoding="utf-8").read()
    # Выданный код сохранён целиком, но исполняется только при показе блока (внутри initBanner)
    assert "IntersectionObserver" in js and "window.onunload=function" in js
    assert js.index("function initBanner") < js.index("window.onunload=function") < js.index("function start")


# Скорость и CLS

def test_event_poster_reserves_space_and_loads_first(app, admin):
    app.jinja_env.filters.setdefault("image_size", utils.image_size)
    _upload(app, "poster.png", (60, 80))
    create_event(admin)
    with app.app_context():
        Event.query.first().poster = "poster.png"
        db.session.commit()
    html = text(app.test_client().get(EV_URL))
    tag = re.search(r'<img class="event__poster"[^>]*>', html).group(0)
    assert 'width="60"' in tag and 'height="80"' in tag
    assert 'fetchpriority="high"' in tag and "lazy" not in tag
    css = open(os.path.join(app.static_folder, "css", "site.css"), encoding="utf-8").read()
    assert ".event__poster:not([width]) { aspect-ratio" in css


def test_news_image_and_video_attributes(app, admin):
    app.jinja_env.filters.setdefault("image_size", utils.image_size)
    _upload(app, "n.png", (160, 90))
    with app.app_context():
        item = News(title="Новость-сео", slug="novost-seo", image="n.png", content="<p>Текст</p>")
        db.session.add(item)
        db.session.flush()
        db.session.add(MediaItem(kind="video", file="clip.mp4", news_id=item.id))
        db.session.commit()
    html = text(app.test_client().get("/novosti/novost-seo"))
    assert re.search(r'<img class="article__hero"[^>]*width="160" height="90"', html)
    assert '<video controls preload="metadata" src="/static/uploads/clip.mp4">' in html


def test_cards_have_alt_with_title(app, admin):
    _upload(app, "cover.png", (160, 90))
    _upload(app, "n.png", (160, 90))
    create_event(admin)
    with app.app_context():
        Event.query.first().cover = "cover.png"
        db.session.add(News(title="Новость-карточка", slug="novost-kartochka", image="n.png"))
        db.session.commit()
    html = text(app.test_client().get("/"))
    assert 'alt="Тестовый концерт"' in html and 'alt="Новость-карточка"' in html
    # Ссылка-картинка скрыта от диктора, чтобы название не читалось дважды
    assert 'class="ecard__media" href="/afisha/testovyy-koncert" tabindex="-1" aria-hidden="true"' in html


def test_video_players_are_lazy_and_titled():
    hex32 = "0123456789abcdef" * 2
    players = [
        utils.video_embed("https://vk.com/video-123_456"),
        utils.video_embed(f"https://rutube.ru/video/{hex32}/"),
        utils.video_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        utils.video_embed("https://dzen.ru/video/watch/abc123"),
    ]
    for tag in players:
        assert tag.startswith("<iframe") and 'loading="lazy"' in tag and ' title="Видео ' in tag


def test_dealer_also_loads_for_pasted_editor_code():
    js = open(os.path.join(os.path.dirname(__file__), "..", "filarmonia", "static", "js", "site.js"),
              encoding="utf-8").read()
    # Кнопки из вставленного кода (схема зала, страницы) зовут YandexTicketsDealer напрямую
    assert "[onclick*=\"' + YA + '\"], #hall" in js


def test_cookie_banner_follows_skip_link_and_returns_focus(app):
    _set(app, yandex_metrika_id="12345678")
    html = text(app.test_client().get("/"))
    assert html.index('class="skip-link"') < html.index("data-cookie") < html.index('class="header"')
    js = open(os.path.join(app.static_folder, "js", "site.js"), encoding="utf-8").read()
    assert 'mainBlock.focus({ preventScroll: true })' in js
