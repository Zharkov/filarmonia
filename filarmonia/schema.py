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

# Статус концерта в базе -> eventStatus в Schema.org
EVENT_STATUS_URLS = {
    "scheduled": "https://schema.org/EventScheduled",
    "cancelled": "https://schema.org/EventCancelled",
    "rescheduled": "https://schema.org/EventRescheduled",
    "postponed": "https://schema.org/EventPostponed",
}

# Дни недели для разбора режима работы: сокращение -> название в Schema.org
WEEKDAYS = [("пн", "Monday"), ("вт", "Tuesday"), ("ср", "Wednesday"), ("чт", "Thursday"),
            ("пт", "Friday"), ("сб", "Saturday"), ("вс", "Sunday")]
DAY_RE = "|".join(short for short, _ in WEEKDAYS)
HOURS_RE = re.compile(
    rf"^(?:(?P<all>ежедневно)|(?P<d1>{DAY_RE})(?:\s*[–—-]\s*(?P<d2>{DAY_RE}))?)\s+"
    r"(?P<o>\d{1,2}:\d{2})\s*[–—-]\s*(?P<c>\d{1,2}:\d{2})$",
    re.I,
)


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


def _time(value: str) -> str:
    hours, minutes = (int(x) for x in value.split(":"))
    if not (0 <= hours <= 24 and 0 <= minutes <= 59) or (hours == 24 and minutes):
        raise ValueError(value)
    return f"{hours:02d}:{minutes:02d}"


def opening_hours(text: str) -> list:
    """Режим работы «Пн–пт 9:00–18:00; сб 10:00–15:00» -> openingHoursSpecification.

    Разбирается только строка целиком и в строгом виде: дни (диапазон «пн–пт», один день
    или «ежедневно»), пробел, время «9:00–18:00»; несколько расписаний — через «;» или
    с новой строки. Любой другой текст (например, «Касса ежедневно 11:00–19:00» рядом
    с расписанием отделов) разбирать не берёмся — вернётся пустой список, а в разметку
    не попадёт неверная информация.
    """
    names = [short for short, _ in WEEKDAYS]
    out = []
    parts = [p.strip() for p in re.split(r"[;\n]+", (text or "").strip().rstrip(".")) if p.strip()]
    for part in parts:
        m = HOURS_RE.match(part)
        if not m:
            return []
        try:
            opens, closes = _time(m.group("o")), _time(m.group("c"))
        except ValueError:
            return []
        if m.group("all"):
            days = list(range(7))
        else:
            first = names.index(m.group("d1").lower())
            last = names.index((m.group("d2") or m.group("d1")).lower())
            days = [(first + i) % 7 for i in range((last - first) % 7 + 1)]
        out.append({"@type": "OpeningHoursSpecification",
                    "dayOfWeek": [WEEKDAYS[i][1] for i in days], "opens": opens, "closes": closes})
    return out


def geo(point: str) -> dict:
    """«54.78, 32.04» (широта, долгота) из настроек -> GeoCoordinates; неразборчивое — пусто."""
    parts = re.findall(r"-?\d+(?:\.\d+)?", point or "")
    if len(parts) != 2:
        return {}
    lat, lon = (float(p) for p in parts)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {}
    return {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}


def organization(settings: dict) -> dict:
    """Филармония как организация: карточка в поиске, адрес, телефон, часы работы, соцсети."""
    name = settings.get("site_name") or DEFAULT_NAME
    full_name = (settings.get("site_full_name") or "").strip()
    return clean({
        "@context": "https://schema.org",
        "@type": "PerformingArtsTheater",
        "@id": site_url("/#organization"),
        "name": name,
        "alternateName": full_name if full_name and full_name != name else None,
        "url": site_url("/"),
        "logo": site_url("/static/img/logo.png"),
        "image": site_url("/static/img/logo.png"),
        "telephone": settings.get("phone_raw"),
        "email": settings.get("email"),
        "address": postal_address(settings.get("address")),
        "geo": geo(settings.get("map_point")),
        "openingHoursSpecification": opening_hours(settings.get("work_hours")),
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
    """Наличие билетов — только если оно названо в поле «Наличие билетов»; иначе не утверждаем."""
    text = ev.tickets_left or ""
    if not text.strip():
        return ""
    if SOLD_OUT_RE.search(text):
        return "https://schema.org/SoldOut"
    if "осталось" in text.lower():
        return "https://schema.org/LimitedAvailability"
    return "https://schema.org/InStock"


def offers(ev) -> dict:
    """Билеты: бесплатный концерт — Offer с ценой 0; диапазон цен — AggregateOffer;
    одна цена — Offer; цена не указана — предложения нет вовсе."""
    base = {
        "priceCurrency": "RUB",
        "url": site_url(ev.ticket_url) if (ev.ticket_url or "").startswith("/") else (ev.ticket_url or site_url(ev.url)),
        "availability": availability(ev),
        "validFrom": utils.iso_msk(utils.to_moscow(ev.created_at)) if ev.created_at else None,
    }
    if ev.is_free:
        return {"@type": "Offer", "price": 0, **base}
    if ev.price_min and ev.price_max and ev.price_max != ev.price_min:
        return {"@type": "AggregateOffer", "lowPrice": ev.price_min, "highPrice": ev.price_max, **base}
    if ev.price_min:
        return {"@type": "Offer", "price": ev.price_min, **base}
    return {}


def event(ev, settings: dict) -> dict:
    """Концерт: даты с поясом, статус, площадка с адресом, исполнители, билеты."""
    ends = ev.starts_at + timedelta(minutes=ev.duration_min) if ev.duration_min and ev.starts_at else None
    images = [site_url(path) for path in (ev.card_image, "/static/uploads/" + ev.poster if ev.poster else "")
              if path]
    org_name = settings.get("site_name") or DEFAULT_NAME
    venue = ev.venue
    if venue:
        location = {"@type": "Place", "name": venue.name,
                    "address": postal_address(venue.address) or postal_address(settings.get("address"))}
    else:
        # Площадка не выбрана: концерт проходит по адресу организации
        location = {"@type": "Place", "name": org_name, "address": postal_address(settings.get("address"))}
    performers = [{"@type": "PerformingGroup", "name": c.name, "url": site_url(c.url)}
                  for c in ev.collectives if c.is_published]
    if not performers and ev.performers:
        performers = [{"@type": "PerformingGroup", "name": utils.strip_tags(ev.performers, 300)}]
    if ev.organizer and ev.organizer.strip() != org_name:
        organizer = {"@type": "Organization", "name": ev.organizer}
    else:
        # Организатор — сама филармония: тот же узел, что описан на главной (organization)
        organizer = {"@type": "Organization", "@id": site_url("/#organization"), "name": org_name,
                     "url": site_url("/")}
    status = ev.status if ev.status in EVENT_STATUS_URLS else "scheduled"
    return clean({
        "@context": "https://schema.org",
        "@type": "Event",
        "name": ev.title,
        "url": site_url(ev.url),
        "startDate": utils.iso_msk(ev.starts_at),
        "endDate": utils.iso_msk(ends),
        "eventStatus": EVENT_STATUS_URLS[status],
        "previousStartDate": utils.iso_msk(ev.previous_starts_at) if status == "rescheduled" else None,
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "isAccessibleForFree": True if ev.is_free else None,
        "description": ev.seo_description or ev.annotation or utils.strip_tags(ev.description, 300),
        "image": list(dict.fromkeys(images)),
        "typicalAgeRange": ev.age_limit,
        "location": location,
        "performer": performers,
        "organizer": organizer,
        "offers": offers(ev),
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
        "description": item.seo_description or item.lead,
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
