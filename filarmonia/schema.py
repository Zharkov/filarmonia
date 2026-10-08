"""Микроразметка Schema.org (JSON-LD) для поисковиков.

Функции возвращают словари; шаблон выводит их фильтром `tojson` внутри
<script type="application/ld+json">. Пустые поля убираются, чтобы валидатор
не ругался на null.
"""
import re
from datetime import timedelta
from urllib.parse import urlsplit

from . import utils
from .web import site_url

DEFAULT_NAME = "Смоленская областная филармония"
CITY = "Смоленск"
REGION = "Смоленская область"
SOCIAL_KEYS = ("social_vk", "social_tg", "social_ok", "social_max")
# По тексту «Наличие билетов» — распроданы ли они
SOLD_OUT_RE = re.compile(r"нет\s+билет|распрода|продажа\s+закрыт", re.I)


def clean(value):
    """Убирает из словарей и списков пустые значения."""
    if isinstance(value, dict):
        out = {k: clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [v for v in (clean(v) for v in value) if v not in (None, "", [], {})]
    return value


def postal_address(text: str) -> dict:
    """«214000, г. Смоленск, ул. Глинки, д. 3» -> PostalAddress."""
    text = (text or "").strip()
    if not text:
        return {}
    m = re.match(r"\s*(\d{6})\s*,?\s*", text)
    postal_code = m.group(1) if m else ""
    street = text[m.end():] if m else text
    # Город отдельным полем, в улице его не повторяем
    street = re.sub(r"^(г\.\s*)?Смоленск\s*,\s*", "", street, flags=re.I)
    return {
        "@type": "PostalAddress",
        "streetAddress": street,
        "addressLocality": CITY,
        "addressRegion": REGION,
        "postalCode": postal_code,
        "addressCountry": "RU",
    }


def social_profiles(settings: dict) -> list:
    """Адреса страниц в соцсетях — только настоящие, не заглушки «https://vk.com/»,
    и только те, что показываются на сайте (галочка «Показывать» в «Настройках»)."""
    out = []
    for key in SOCIAL_KEYS:
        url = (settings.get(key) or "").strip()
        if settings.get(key + "_show") == "":
            continue
        if url and urlsplit(url).path.strip("/"):
            out.append(url)
    return out


def organization(settings: dict) -> dict:
    """Филармония как организация: карточка в поиске, адрес, телефон, соцсети."""
    return clean({
        "@context": "https://schema.org",
        "@type": "PerformingArtsTheater",
        "@id": site_url("/#organization"),
        "name": settings.get("site_name") or DEFAULT_NAME,
        "url": site_url("/"),
        "logo": site_url("/static/img/logo.png"),
        "image": site_url("/static/img/logo.png"),
        "telephone": settings.get("phone_raw"),
        "email": settings.get("email"),
        "address": postal_address(settings.get("address")),
        "sameAs": social_profiles(settings),
    })


def website(settings: dict) -> dict:
    """Сайт с поиском: поисковик может показать строку поиска по сайту."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": settings.get("site_name") or DEFAULT_NAME,
        "url": site_url("/"),
        "potentialAction": {
            "@type": "SearchAction",
            "target": site_url("/poisk") + "?q={search_term_string}",
            "query-input": "required name=search_term_string",
        },
    }


def availability(ev) -> str:
    text = ev.tickets_left or ""
    if SOLD_OUT_RE.search(text):
        return "https://schema.org/SoldOut"
    if "осталось" in text.lower():
        return "https://schema.org/LimitedAvailability"
    return "https://schema.org/InStock"


def event(ev, settings: dict) -> dict:
    """Концерт: даты с поясом, площадка с адресом, исполнители, билеты."""
    ends = ev.starts_at + timedelta(minutes=ev.duration_min) if ev.duration_min and ev.starts_at else None
    images = [site_url(path) for path in (ev.card_image, "/static/uploads/" + ev.poster if ev.poster else "")
              if path]
    venue = ev.venue
    location = {
        "@type": "Place",
        "name": venue.name,
        "address": postal_address(venue.address) or postal_address(settings.get("address")),
    } if venue else None
    performers = [{"@type": "PerformingGroup", "name": c.name, "url": site_url(c.url)}
                  for c in ev.collectives if c.is_published]
    offer = {
        "@type": "Offer",
        "price": ev.price_min,
        "priceCurrency": "RUB",
        "url": ev.ticket_url or site_url(ev.url),
        "availability": availability(ev),
        "validFrom": utils.iso_msk(utils.to_moscow(ev.created_at)) if ev.created_at else None,
    } if ev.price_min else None
    org_name = settings.get("site_name") or DEFAULT_NAME
    return clean({
        "@context": "https://schema.org",
        "@type": "Event",
        "name": ev.title,
        "url": site_url(ev.url),
        "startDate": utils.iso_msk(ev.starts_at),
        "endDate": utils.iso_msk(ends),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "description": ev.annotation or utils.strip_tags(ev.description, 300),
        "image": list(dict.fromkeys(images)),
        "typicalAgeRange": ev.age_limit,
        "location": location,
        "performer": performers,
        "organizer": {"@type": "Organization", "name": ev.organizer or org_name,
                      "url": None if ev.organizer else site_url("/")},
        "offers": offer,
    })


def news_article(item, settings: dict) -> dict:
    org_name = settings.get("site_name") or DEFAULT_NAME
    image = site_url("/static/uploads/" + item.image) if item.image and item.show_media else None
    return clean({
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": item.title[:110],
        "url": site_url(item.url),
        "mainEntityOfPage": site_url(item.url),
        "datePublished": utils.iso_msk(item.published_at),
        "dateModified": utils.iso_msk(utils.to_moscow(item.updated_at)) if item.updated_at else None,
        "description": item.lead,
        "image": [image] if image else [],
        "publisher": {"@type": "Organization", "name": org_name,
                      "logo": {"@type": "ImageObject", "url": site_url("/static/img/logo.png")}},
        "author": {"@type": "Organization", "name": org_name, "url": site_url("/")},
    })


def breadcrumbs(trail) -> dict:
    """trail — [(название, адрес), …]; у последнего пункта адрес можно не указывать."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            clean({"@type": "ListItem", "position": i, "name": title,
                   "item": site_url(href) if href else None})
            for i, (title, href) in enumerate(trail, start=1)
        ],
    }
