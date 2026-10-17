"""Правки заказчика: документы, новости с документами, фестивали, шапка, контакты, карта сайта."""
import io
import os

from conftest import create_event, text

from filarmonia.models import db, Appeal, Document, Event, Festival, MenuItem, News, Page


def pdf() -> io.BytesIO:
    return io.BytesIO(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")


def make_page(admin, title, template="documents"):
    admin.post("/admin/pages/new", data={"title": title, "template": template, "is_published": "1"})


def add_document(admin, title, category, year="2026", name="doc.pdf"):
    admin.post("/admin/documents", data={"title": title, "category": category, "year": year,
                                         "is_published": "1", "file": (pdf(), name)},
               content_type="multipart/form-data")


def test_documents_index_shows_only_sections(app, admin):
    make_page(admin, "Учредительные документы")
    make_page(admin, "Антитеррор")
    add_document(admin, "Устав учреждения", "Учредительные документы")
    with app.app_context():
        parent = MenuItem(title="Документы", url="/dokumenty", sort=60)
        db.session.add(parent)
        db.session.flush()
        for i, title in enumerate(("Учредительные документы", "Антитеррор")):
            page = Page.query.filter_by(title=title).first()
            db.session.add(MenuItem(title=title, page_id=page.id, parent_id=parent.id, sort=i))
        db.session.commit()
    html = text(admin.get("/dokumenty"))
    assert "Учредительные документы" in html and "Антитеррор" in html
    assert "/info/antiterror" in html and "section-icon" in html
    # Сами документы — только внутри подраздела
    assert "Устав учреждения" not in html


def test_documents_index_without_menu_lists_document_pages(admin):
    make_page(admin, "Доступная среда")
    make_page(admin, "Обычная страница", template="page")
    html = text(admin.get("/dokumenty"))
    assert "Доступная среда" in html and "Обычная страница" not in html


def test_document_page_pdf_opens_without_download(admin):
    make_page(admin, "Учредительные документы")
    add_document(admin, "Устав учреждения", "Учредительные документы")
    html = text(admin.get("/info/uchreditelnye-dokumenty"))
    assert "Устав учреждения" in html and "data-doc-view" in html
    assert "Открыть" in html and "Скачать" in html and "Тип файла: pdf" in html
    assert "<h2>Документы</h2>" not in html and "Обновлено" not in html
    # Хлебные крошки ведут через раздел «Документы»
    assert 'href="/dokumenty"' in html
    assert 'id="doc-viewer"' in html


def test_word_document_is_download_only(admin):
    make_page(admin, "Локальные нормативные акты")
    add_document(admin, "Положение об отделе", "Локальные нормативные акты", name="polozhenie.docx")
    html = text(admin.get("/info/lokalnye-normativnye-akty"))
    assert "Положение об отделе" in html and "Тип файла: docx" in html
    assert "data-doc-view" not in html


def test_documents_grouped_by_year(admin):
    make_page(admin, "Государственное задание", template="documents_years")
    add_document(admin, "Задание на 2025 год", "Государственное задание", year="2025")
    add_document(admin, "Задание на 2026 год", "Государственное задание", year="2026")
    html = text(admin.get("/info/gosudarstvennoe-zadanie"))
    assert html.index(">2026</h2>") < html.index("Задание на 2026 год") < html.index(">2025</h2>") \
        < html.index("Задание на 2025 год")


def test_renamed_page_keeps_documents(app, admin):
    make_page(admin, "Нормативные правовые акты")
    add_document(admin, "Приказ", "Нормативные правовые акты")
    with app.app_context():
        page_id = Page.query.filter_by(title="Нормативные правовые акты").first().id
    admin.post(f"/admin/pages/{page_id}", data={"title": "Локальные нормативные акты", "slug": "lna",
                                                "template": "documents", "is_published": "1"})
    assert "Приказ" in text(admin.get("/info/lna"))


def test_news_documents(app, admin):
    admin.post("/admin/news/new", data={"title": "Новость с приказом", "content": "<p>Текст</p>",
                                        "is_published": "1"})
    with app.app_context():
        news_id = News.query.filter_by(title="Новость с приказом").first().id
    admin.post(f"/admin/news/{news_id}/documents", data={"title": "Приказ о сезоне", "file": (pdf(), "p.pdf")},
               content_type="multipart/form-data")
    html = text(admin.get("/novosti/novost-s-prikazom"))
    assert "Приказ о сезоне" in html and "data-doc-view" in html
    # В общий список документов приложение к новости не попадает
    assert "Приказ о сезоне" not in text(admin.get("/admin/documents"))
    assert "Приказ о сезоне" in text(admin.get(f"/admin/news/{news_id}"))
    with app.app_context():
        doc = Document.query.filter_by(title="Приказ о сезоне").first()
        doc_id, path = doc.id, os.path.join(app.config["UPLOAD_FOLDER"], doc.file)
    assert os.path.exists(path)
    admin.post(f"/admin/news/documents/{doc_id}/delete")
    assert "Приказ о сезоне" not in text(admin.get("/novosti/novost-s-prikazom"))
    assert not os.path.exists(path)


def test_news_document_needs_file_or_link(app, admin):
    admin.post("/admin/news/new", data={"title": "Пустая", "is_published": "1"})
    with app.app_context():
        news_id = News.query.filter_by(title="Пустая").first().id
    html = text(admin.post(f"/admin/news/{news_id}/documents", data={"title": "Без файла"},
                           follow_redirects=True))
    assert "выберите файл" in html
    with app.app_context():
        assert Document.query.count() == 0


def test_deleting_news_removes_its_documents(app, admin):
    admin.post("/admin/news/new", data={"title": "Удаляемая", "is_published": "1"})
    with app.app_context():
        news_id = News.query.filter_by(title="Удаляемая").first().id
    admin.post(f"/admin/news/{news_id}/documents", data={"file": (pdf(), "prilozhenie.pdf")},
               content_type="multipart/form-data")
    with app.app_context():
        doc = Document.query.first()
        assert doc.title == "prilozhenie"
        path = os.path.join(app.config["UPLOAD_FOLDER"], doc.file)
    admin.post(f"/admin/news/{news_id}/delete")
    with app.app_context():
        assert Document.query.count() == 0
    assert not os.path.exists(path)


def test_festival_labels(app, admin):
    admin.post("/admin/refs", data={"kind": "festival", "name": "Фестиваль имени М. И. Глинки", "sort": "10"})
    with app.app_context():
        fest_id = Festival.query.first().id
    create_event(admin, festivals=str(fest_id))
    assert "Фестиваль имени М. И. Глинки" in text(admin.get("/afisha"))
    assert "Фестиваль имени М. И. Глинки" in text(admin.get("/"))
    assert "Фестиваль имени М. И. Глинки" in text(admin.get("/afisha/testovyy-koncert"))
    # Отмеченный у события фестиваль удалить нельзя
    admin.post(f"/admin/refs/festival/{fest_id}/delete")
    with app.app_context():
        assert db.session.get(Festival, fest_id) is not None
        event_id = Event.query.first().id
    admin.post(f"/admin/events/{event_id}/copy")
    with app.app_context():
        copy = Event.query.filter(Event.id != event_id).first()
        assert [f.name for f in copy.festivals] == ["Фестиваль имени М. И. Глинки"]


def test_pushkin_and_benefits_flags_are_links(admin):
    create_event(admin, show_pushkin="1", show_benefits="1")
    for url in ("/", "/afisha"):
        html = text(admin.get(url))
        assert 'href="/info/pushkinskaya-karta">Пушкинская карта' in html
        assert 'href="/info/lgotnoe-poseschenie">Есть льготы' in html


def test_header(app):
    html = text(app.test_client().get("/"))
    assert "Обращения граждан" not in html
    assert "/info/nezavisimaya-ocenka-kachestva" in html
    assert 'aria-label="Версия для слабовидящих"' in html
    assert 'href="/karta-sajta"' in html


def test_contacts_page_feedback(app, admin):
    make_page(admin, "Контакты", template="contacts")
    html = text(admin.get("/info/kontakty"))
    assert 'id="feedback"' in html and 'name="back" value="/info/kontakty"' in html
    client = app.test_client()
    r = client.post("/obrashcheniya", data={"name": "Иван", "email": "ivan@example.ru", "message": "Вопрос",
                                            "consent": "1", "back": "/info/kontakty"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/info/kontakty#feedback")
    with app.app_context():
        assert Appeal.query.count() == 1


def test_appeal_requires_email(app):
    """Ответ на обращение направляется на почту — без адреса обращение не принимается."""
    r = app.test_client().post("/obrashcheniya", data={"name": "Иван", "message": "Вопрос", "consent": "1"},
                               follow_redirects=True)
    assert "Укажите адрес электронной почты" in text(r)
    with app.app_context():
        assert Appeal.query.count() == 0


def test_contacts_back_must_be_local(app):
    r = app.test_client().post("/obrashcheniya", data={"name": "Иван", "message": "Вопрос", "consent": "1",
                                                       "back": "https://evil.example/info/"})
    assert r.headers["Location"].endswith("/obrashcheniya")


def test_site_map(admin):
    make_page(admin, "Политика конфиденциальности", template="page")
    html = text(admin.get("/karta-sajta"))
    assert "Карта сайта" in html and "Политика конфиденциальности" in html
    assert "/karta-sajta" in text(admin.get("/sitemap.xml"))


def test_festival_page(app, admin):
    admin.post("/admin/refs", data={"kind": "festival", "name": "Фестиваль имени М. И. Глинки", "sort": "10",
                                    "description": "<p>Фестиваль на родине композитора</p>"})
    with app.app_context():
        fest = Festival.query.first()
        fest_id, url = fest.id, fest.url
    create_event(admin, festivals=str(fest_id))
    create_event(admin, title="Концерт вне фестиваля")
    # Метка на карточках и на странице события ведёт на страницу фестиваля
    for page in ("/", "/afisha", "/afisha/testovyy-koncert"):
        assert f'href="{url}"' in text(admin.get(page))
    html = text(app.test_client().get(url))
    assert "Фестиваль на родине композитора" in html and "Тестовый концерт" in html
    assert "Концерт вне фестиваля" not in html
    assert url in text(admin.get("/sitemap.xml")) and url in text(admin.get("/karta-sajta"))
    assert app.test_client().get("/festivali/net-takogo").status_code == 404
    assert "Фестиваль на родине композитора" in text(admin.get(f"/admin/refs?festival={fest_id}"))


def add_notice(admin, **fields):
    data = {"kind": "cancel", "text": "Концерт 20 октября отменён", "is_published": "1"}
    data.update(fields)
    return admin.post("/admin/notices", data=data, follow_redirects=True)


def test_afisha_notices(app, admin):
    client = app.test_client()
    assert "Изменения в афише" not in text(client.get("/"))
    add_notice(admin, url="/afisha/testovyy-koncert")
    for page in ("/", "/afisha"):
        html = text(client.get(page))
        assert "Изменения в афише" in html and "Концерт 20 октября отменён" in html
        assert 'href="/afisha/testovyy-koncert"' in html and "Отмена" in html
    # На остальных страницах плашки нет
    assert "Концерт 20 октября отменён" not in text(client.get("/novosti"))
    assert "Концерт 20 октября отменён" in text(admin.get("/admin/notices"))


def test_afisha_notice_expires_and_hides(app, admin):
    from filarmonia.models import AfishaNotice
    add_notice(admin, show_until="2000-01-01")
    add_notice(admin, text="Скрытое изменение", is_published="")
    html = text(app.test_client().get("/"))
    assert "Концерт 20 октября отменён" not in html and "Скрытое изменение" not in html
    assert "срок истёк" in text(admin.get("/admin/notices"))
    with app.app_context():
        notice = AfishaNotice.query.filter_by(text="Скрытое изменение").first()
        assert notice.show_until is None
        notice_id = notice.id
    admin.post(f"/admin/publish/notice/{notice_id}")
    assert "Скрытое изменение" in text(app.test_client().get("/"))
    admin.post(f"/admin/notices/{notice_id}/delete")
    with app.app_context():
        assert db.session.get(AfishaNotice, notice_id) is None


def test_afisha_notice_rejects_script_link(app, admin):
    from filarmonia.models import AfishaNotice
    html = text(add_notice(admin, url="javascript:alert(1)"))
    assert "Ссылка не сохранена" in html
    with app.app_context():
        assert AfishaNotice.query.first().url == ""
    assert "javascript:" not in text(app.test_client().get("/"))


def test_nok_is_not_in_documents_section(app, admin):
    make_page(admin, "Учредительные документы")
    make_page(admin, "Независимая оценка качества")
    with app.app_context():
        parent = MenuItem(title="Документы", url="/dokumenty", sort=60)
        db.session.add(parent)
        db.session.flush()
        page = Page.query.filter_by(title="Учредительные документы").first()
        db.session.add(MenuItem(title=page.title, page_id=page.id, parent_id=parent.id, sort=10))
        db.session.commit()
    assert 'href="/dokumenty"' in text(admin.get("/info/uchreditelnye-dokumenty")).split('id="main"')[1]
    nok = text(admin.get("/info/nezavisimaya-ocenka-kachestva")).split('id="main"')[1]
    assert 'href="/dokumenty"' not in nok.split("</footer>")[0].split("<footer")[0]
    assert "Независимая оценка качества" not in text(admin.get("/dokumenty")).split('id="main"')[1].split("<footer")[0]


def test_nok_page_survey_and_qr(app, admin):
    make_page(admin, "Независимая оценка качества", template="nok")
    add_document(admin, "Результаты независимой оценки за 2025 год", "Независимая оценка качества", year="2025")
    html = text(app.test_client().get("/info/nezavisimaya-ocenka-kachestva"))
    assert "Оцените работу филармонии" in html and "Концертная организация, концертный коллектив" in html
    assert 'href="https://forms.mkrf.ru/e/2579/xTPLeBU7/"' in html
    assert '<svg class="qr"' in html and 'fill="#000"' in html
    assert "Результаты независимой оценки за 2025 год" in html and ">2025</h2>" in html
    # Ссылка на анкету из «Настроек» — QR-код перестраивается под неё
    with app.app_context():
        from filarmonia.models import Setting
        Setting.set("nok_survey_url", "https://forms.mkrf.ru/e/2579/xTPLeBU7/?ap_orgcode=123")
        db.session.commit()
    from filarmonia import reset_site_data
    with app.app_context():
        reset_site_data()
    html2 = text(app.test_client().get("/info/nezavisimaya-ocenka-kachestva"))
    assert "ap_orgcode=123" in html2
    assert html2.split('<svg class="qr"')[1][:3000] != html.split('<svg class="qr"')[1][:3000]


def test_image_document_opens_in_photo_viewer(admin):
    from PIL import Image
    make_page(admin, "Учредительные документы")
    for name, fmt in (("skan.jpg", "JPEG"), ("skan.png", "PNG")):
        picture = io.BytesIO()
        Image.new("RGB", (40, 60), "white").save(picture, fmt)
        picture.seek(0)
        admin.post("/admin/documents", data={"title": f"Скан {fmt}", "category": "Учредительные документы",
                                             "is_published": "1", "file": (picture, name)},
                   content_type="multipart/form-data")
    html = text(admin.get("/info/uchreditelnye-dokumenty"))
    assert "Скан JPEG" in html and "Скан PNG" in html
    assert html.count("doc__icon--img") == 2 and ">JPG<" in html and ">PNG<" in html
    assert 'data-photo="/static/uploads/' in html and "data-doc-view" not in html
    assert "Тип файла: png" in html and "Открыть" in html
