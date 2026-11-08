"""Tournegar public tour-listing adapter for real, indicative package offers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "ShabSanjResearch/0.1 (+public tour catalog comparison)"
TOUR_LISTINGS = (
    ("tehran", "mashhad", "https://tournegar.com/tours/mashhad-tehran", "THR"),
    ("mashhad", "tehran", "https://tournegar.com/tours/tehran-mashhad", "MHD"),
    ("isfahan", "mashhad", "https://tournegar.com/tours/mashhad-isfahan", "IFN"),
    ("shiraz", "tehran", "https://tournegar.com/tours/tehran-shiraz", "SYZ"),
    ("tehran", "kish", "https://tournegar.com/tours/kish-tehran", "THR"),
    ("mashhad", "kish", "https://tournegar.com/tours/kish-mashhad", "MHD"),
    ("isfahan", "kish", "https://tournegar.com/tours/kish-isfahan", "IFN"),
    ("shiraz", "kish", "https://tournegar.com/tours/kish-shiraz", "SYZ"),
    ("rasht", "kish", "https://tournegar.com/tours/kish-rasht", "RAS"),
    ("tehran", "rasht", "https://tournegar.com/tours/rasht-tehran", "THR"),
    ("mashhad", "rasht", "https://tournegar.com/tours/rasht-mashhad", "MHD"),
)
EXTRA_DETAILS = (
    ("shiraz", "mashhad", "https://tournegar.com/tour/almas-2-hotel-mashhad?origin=SYZ", "SYZ"),
    ("isfahan", "mashhad", "https://tournegar.com/tour/almas-2-hotel-mashhad?origin=IFN", "IFN"),
)
CITY_FA = {
    "tehran": "تهران", "mashhad": "مشهد", "isfahan": "اصفهان",
    "shiraz": "شیراز", "kish": "کیش", "rasht": "رشت",
}
ORIGIN_CODES = {
    "tehran": "THR", "mashhad": "MHD", "isfahan": "IFN",
    "shiraz": "SYZ", "kish": "KIH", "rasht": "RAS",
}

# Additional matches to hotels that are present only on another provider's
# current catalog page. Each pairing was checked against the displayed title.
EXPLICIT_HOTEL_MATCHES = {
    ("mashhad", "54"): "mashhad-atlas",
    ("mashhad", "49"): "iranhotelonline:mashhad:هتل-جواد",
    ("mashhad", "69"): "tikhotel:mashhad:boshra",
    # Tournegar Rasht tour pages and the hotel-provider pages name the same
    # properties. The Kadous address was also checked on both providers.
    ("rasht", "5861"): "tikhotel:rasht:kadoosbozorg",
    ("rasht", "5869"): "rasht-shabestan",
    ("rasht", "5877"): "rasht-pamchal",
    ("rasht", "5883"): "rasht-sabouri",
    ("rasht", "5891"): "iranhotelonline:rasht:هتل-پردیس",
    ("rasht", "5907"): "rasht-iran",
    ("rasht", "5915"): "rasht-khan-sabouri",
    ("rasht", "5923"): "iranhotelonline:rasht:هتل-آپارتمان-زیبای-سبزه-میدان",
    ("rasht", "5931"): "tikhotel:rasht:khazarmasal",
    ("rasht", "5941"): "rasht-kacha",
    ("rasht", "5955"): "tikhotel:rasht:gil-khatoon",
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _integer(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    return int(normalized) if normalized.isdecimal() else None


def hotel_index_from_catalog(catalog: dict | None) -> dict[tuple[str, str], str]:
    """Reuse only the existing hotel catalog's explicit provider IDs."""
    index: dict[tuple[str, str], str] = {}
    if not isinstance(catalog, dict):
        return index
    for offer in catalog.get("offers", []):
        if not isinstance(offer, dict) or offer.get("provider") != "tournegar":
            continue
        city = offer.get("city")
        hotel_id = str(offer.get("hotel_id", ""))
        canonical_id = offer.get("canonical_id")
        if city and hotel_id and canonical_id:
            index[(city, hotel_id)] = canonical_id
    return index


def _hotel_name(card, destination_city: str) -> str:
    name = card.get("data-hotel-title", "").strip()
    name = re.sub(r"^تور\s+(?:مشهد|تهران|کیش|رشت)\s+", "", name)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    name = re.sub(r"\s+[۱۲۳۴۵1-5]\s*ستاره\s*$", "", name)
    city_name = CITY_FA[destination_city]
    # A Rasht route page also advertises hotels elsewhere in Gilan (e.g.
    # Masal). Do not claim those properties are physically in Rasht.
    if destination_city != "rasht" and city_name not in name:
        name = f"{name} {city_name}"
    return name


def _with_origin(url: str, origin_code: str) -> str:
    """Keep a provider tour link tied to the route whose rate was displayed."""
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["origin"] = origin_code
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def parse_tournegar_listing(
    html: str, departure_city: str, destination_city: str,
    listing_url: str, observed_at: str,
    hotel_index: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    selected_origin = soup.select_one("#tourOriginSelect option[selected]")
    expected_origin = ORIGIN_CODES[departure_city]
    if not selected_origin or selected_origin.get("value") != expected_origin:
        raise ValueError("Missing or unexpected selected origin on tour listing")
    route_origin = re.search(r'window\.TOUR_ORIGIN_IATA\s*=\s*"([A-Z]+)"', html)
    route_destination = re.search(r'window\.TOUR_DESTINATION_IATA\s*=\s*"([A-Z]+)"', html)
    if not route_origin or route_origin.group(1) != expected_origin:
        raise ValueError("Route script does not confirm the requested origin")
    if not route_destination or route_destination.group(1) != ORIGIN_CODES[destination_city]:
        raise ValueError("Route script does not confirm the requested destination")
    heading = soup.select_one("h1")
    if not heading or f"تور {CITY_FA[destination_city]} از {CITY_FA[departure_city]}" not in heading.get_text(" ", strip=True):
        raise ValueError("Route heading does not confirm origin and destination")
    selected_checkin = soup.select_one("#tourCheckInSelect option[selected]")
    hotel_checkin_date = selected_checkin.get("value") if selected_checkin else None
    selected_nights = soup.select_one("#tourNightsSelect option[selected]")
    selected_duration = _integer(selected_nights.get("value")) if selected_nights else None
    hotel_index = hotel_index or {}
    tours = []
    for card in soup.select(".packages .package-block-two[data-tournegar-id]"):
        hotel_id = str(card.get("data-accommodation-id") or card["data-tournegar-id"])
        link = card.select_one('a[href*="/tour/"]')
        if not link or not link.get("href"):
            continue
        source_url = _with_origin(urljoin(listing_url, link["href"]), expected_origin)
        hotel_name = _hotel_name(card, destination_city)
        canonical_id = hotel_index.get((destination_city, hotel_id))
        canonical_id = canonical_id or EXPLICIT_HOTEL_MATCHES.get((destination_city, hotel_id))
        card_services = [tag.get_text(" ", strip=True) for tag in card.select(".pkg-offer-label")]
        badge = card.select_one(".b-title.featured")
        if badge and "رایگان" in badge.get_text(" ", strip=True):
            card_services.append(badge.get_text(" ", strip=True))
        priced = False
        for block in card.select(".price .mb-1"):
            label_tag = block.select_one("span.text-muted")
            amount_tag = block.select_one("span.amount")
            if not label_tag or not amount_tag:
                continue
            label = label_tag.get_text(" ", strip=True)
            if "شروع نرخ هر نفر" not in label:
                continue
            transport = "flight" if "هوایی" in label else "train" if "قطار" in label else None
            price = _integer(amount_tag.get_text(" ", strip=True))
            if not transport or not price or price <= 0:
                continue
            priced = True
            duration_match = re.search(r"پکیج\s*([\d۰-۹٠-٩]+)\s*شب", label)
            duration = _integer(duration_match.group(1)) if duration_match else selected_duration
            if selected_duration and duration and selected_duration != duration:
                continue
            mode_fa = "هوایی" if transport == "flight" else "ریلی"
            services = [f"اقامت {duration} شب" if duration else "اقامت در هتل"]
            services.extend(card_services)
            # Preserve order while avoiding repeated facility labels.
            services = list(dict.fromkeys(services))
            tours.append({
                "provider": "tournegar",
                "provider_name": "تورنگار",
                "tour_id": f"tournegar:{departure_city}:{destination_city}:{hotel_id}:{transport}",
                "title": f"تور {CITY_FA[destination_city]} از {CITY_FA[departure_city]}؛ {hotel_name} ({mode_fa})",
                "departure_city": departure_city,
                "destination_city": destination_city,
                "provider_hotel_id": hotel_id,
                "hotel_name": hotel_name,
                "canonical_hotel_id": canonical_id,
                "departure_date": None,
                "return_date": None,
                "hotel_checkin_date": hotel_checkin_date,
                "duration_nights": duration,
                "price_toman": price,
                "price_basis": "per_person",
                "services": services,
                "optional_services": [],
                "transport": transport,
                "source_url": source_url,
                "listing_url": listing_url,
                "observed_at": observed_at,
                "availability": "unknown",
                "source_type": "route_listing",
                "price_note": (
                    f"شروع نرخ هر نفر برای پکیج {duration} شب {mode_fa} در فهرست تورنگار. "
                    "تاریخ نشان‌داده‌شده تاریخ ورود به هتل است؛ زمان حرکت، نوع اتاق و ظرفیت باید در سایت فروشنده بررسی شود."
                ),
            })
        if not priced and destination_city == "rasht" and "تماس با تیم فروش جهت اطلاع از قیمت" in card.get_text(" ", strip=True):
            # These are real named tour listings, but the provider publishes no
            # price or transport choice for them. They must stay unpriced.
            duration = selected_duration
            services = ([f"اقامت {duration} شب"] if duration else ["اقامت در هتل"]) + card_services
            tours.append({
                "provider": "tournegar",
                "provider_name": "تورنگار",
                "tour_id": f"tournegar:{departure_city}:{destination_city}:{hotel_id}:contact",
                "title": f"تور {CITY_FA[destination_city]} از {CITY_FA[departure_city]}؛ {hotel_name}",
                "departure_city": departure_city,
                "destination_city": destination_city,
                "provider_hotel_id": hotel_id,
                "hotel_name": hotel_name,
                "canonical_hotel_id": canonical_id,
                "departure_date": None,
                "return_date": None,
                "hotel_checkin_date": None,
                "duration_nights": duration,
                "price_toman": None,
                "price_basis": None,
                "services": list(dict.fromkeys(services)),
                "optional_services": [],
                "transport": None,
                "source_url": source_url,
                "listing_url": listing_url,
                "observed_at": observed_at,
                "availability": "contact_required",
                "source_type": "route_listing_contact_price",
                "price_note": "تورنگار برای این پکیج «تماس با تیم فروش جهت اطلاع از قیمت» نمایش می‌دهد؛ قیمت، وسیله سفر و ظرفیت تأیید نشده‌اند.",
            })
    return tours


def parse_tournegar_detail(
    html: str, departure_city: str, destination_city: str,
    source_url: str, observed_at: str,
    hotel_index: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    """Read only origin-specific starting rates and explicitly named services."""
    origin_code = ORIGIN_CODES[departure_city]
    destination_code = ORIGIN_CODES[destination_city]
    origin_match = re.search(r'window\.TOUR_SINGLE_ORIGIN\s*=\s*"([A-Z]+)"', html)
    destination_match = re.search(r'window\.TOUR_SINGLE_DEST\s*=\s*"([A-Z]+)"', html)
    id_match = re.search(r'window\.TOUR_SINGLE_ACC_ID\s*=\s*(\d+)', html)
    if not origin_match or origin_match.group(1) != origin_code:
        raise ValueError("Detail page does not confirm the requested origin")
    if not destination_match or destination_match.group(1) != destination_code:
        raise ValueError("Detail page does not confirm the requested destination")
    if not id_match:
        raise ValueError("Detail page has no accommodation ID")
    hotel_id = id_match.group(1)
    soup = BeautifulSoup(html, "html.parser")
    table_head = soup.select_one(".tnOrg-head")
    if not table_head or "شروع نرخ هر نفر" not in table_head.get_text(" ", strip=True):
        raise ValueError("Detail page does not label table rates per person")
    row = soup.select_one(f'.tnOrg-row[data-origin="{origin_code}"]')
    if not row:
        raise ValueError("Detail page has no starting rates for requested origin")
    heading = soup.select_one("h1")
    if not heading:
        raise ValueError("Detail page has no hotel title")
    hotel_name = heading.get_text(" ", strip=True)
    if CITY_FA[destination_city] not in hotel_name:
        hotel_name += f" {CITY_FA[destination_city]}"
    duration_match = re.search(r'window\.TOUR_SINGLE_NIGHTS\s*=\s*(\d+)', html)
    duration = _integer(duration_match.group(1)) if duration_match else None
    facilities = [tag.get_text(" ", strip=True)
                  for tag in soup.select(".tour-page__description-facilities span")]
    hotel_index = hotel_index or {}
    canonical_id = hotel_index.get((destination_city, hotel_id))
    canonical_id = canonical_id or EXPLICIT_HOTEL_MATCHES.get((destination_city, hotel_id))
    tours = []
    for transport, selector, ticket_phrase, mode_fa in (
        ("flight", ".tnOrg-f strong", "بلیت رفت و برگشت با هواپیما", "هوایی"),
        ("train", ".tnOrg-t strong", "بلیت رفت و برگشت با قطار", "ریلی"),
    ):
        amount = row.select_one(selector)
        price = _integer(amount.get_text(" ", strip=True)) if amount else None
        if not price or price <= 0:
            continue
        services = [item for item in facilities if (
            "رایگان" in item or "ترانسفر استقبال" in item
            or "اقامت در هتل" in item or item == ticket_phrase
        )]
        tours.append({
            "provider": "tournegar",
            "provider_name": "تورنگار",
            "tour_id": f"tournegar:{departure_city}:{destination_city}:{hotel_id}:{transport}",
            "title": f"تور {CITY_FA[destination_city]} از {CITY_FA[departure_city]}؛ {hotel_name} ({mode_fa})",
            "departure_city": departure_city,
            "destination_city": destination_city,
            "provider_hotel_id": hotel_id,
            "hotel_name": hotel_name,
            "canonical_hotel_id": canonical_id,
            "departure_date": None,
            "return_date": None,
            "hotel_checkin_date": None,
            "duration_nights": duration,
            "price_toman": price,
            "price_basis": "per_person",
            "services": list(dict.fromkeys(services)),
            "optional_services": [],
            "transport": transport,
            "source_url": _with_origin(source_url, origin_code),
            "listing_url": _with_origin(source_url, origin_code),
            "observed_at": observed_at,
            "availability": "unknown",
            "source_type": "hotel_tour_detail",
            "price_note": (
                "شروع نرخ هر نفر در جدول شهرهای مبدأ صفحهٔ جزئیات تورنگار. "
                "این جدول نرخ قطعی تاریخ انتخابی، نوع اتاق یا ظرفیت لحظه‌ای را نشان نمی‌دهد."
            ),
        })
    return tours


def crawl_tours(hotel_catalog: dict | None = None, max_hotels_per_route: int = 20) -> dict:
    """Fetch verified public route listings after checking Tournegar's robots.txt."""
    hotel_index = hotel_index_from_catalog(hotel_catalog)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tours: list[dict] = []
    source_status: list[dict] = []
    with httpx.Client(
        follow_redirects=True, timeout=35.0,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        robots_url = "https://tournegar.com/robots.txt"
        robots = client.get(robots_url, headers={"Accept": "text/plain"})
        robots.raise_for_status()
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        for departure_city, destination_city, listing_url, _origin_code in TOUR_LISTINGS:
            status = {
                "provider": "tournegar", "departure_city": departure_city,
                "destination_city": destination_city, "url": listing_url,
                "source_type": "route_listing",
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            try:
                if not parser.can_fetch(USER_AGENT, listing_url):
                    raise PermissionError("robots.txt does not allow this tour listing")
                response = client.get(listing_url)
                response.raise_for_status()
                observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                parsed = parse_tournegar_listing(
                    response.text, departure_city, destination_city,
                    listing_url, observed_at, hotel_index,
                )
                hotel_ids = list(dict.fromkeys(tour["provider_hotel_id"] for tour in parsed))
                allowed_ids = set(hotel_ids[:max_hotels_per_route])
                parsed = [tour for tour in parsed if tour["provider_hotel_id"] in allowed_ids]
                if not parsed:
                    raise ValueError("No priced tour cards found; provider markup may have changed")
                tours.extend(parsed)
                status.update({"status": "ok", "http_status": response.status_code,
                               "tour_count": len(parsed), "observed_at": observed_at})
            except (httpx.HTTPError, PermissionError, ValueError) as exc:
                status.update({"status": "error", "tour_count": 0, "error": str(exc)})
            source_status.append(status)
        for departure_city, destination_city, detail_url, _origin_code in EXTRA_DETAILS:
            status = {
                "provider": "tournegar", "departure_city": departure_city,
                "destination_city": destination_city, "url": detail_url,
                "source_type": "hotel_tour_detail",
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            try:
                if not parser.can_fetch(USER_AGENT, detail_url):
                    raise PermissionError("robots.txt does not allow this tour detail")
                response = client.get(detail_url)
                response.raise_for_status()
                observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                parsed = parse_tournegar_detail(
                    response.text, departure_city, destination_city,
                    detail_url, observed_at, hotel_index,
                )
                if not parsed:
                    raise ValueError("No origin-specific per-person rates found")
                existing_ids = {tour["tour_id"] for tour in tours}
                parsed = [tour for tour in parsed if tour["tour_id"] not in existing_ids]
                if not parsed:
                    status.update({"status": "covered_by_listing", "http_status": response.status_code,
                                   "tour_count": 0, "observed_at": observed_at})
                    source_status.append(status)
                    continue
                tours.extend(parsed)
                status.update({"status": "ok", "http_status": response.status_code,
                               "tour_count": len(parsed), "observed_at": observed_at})
            except (httpx.HTTPError, PermissionError, ValueError) as exc:
                status.update({"status": "error", "tour_count": 0, "error": str(exc)})
            source_status.append(status)
    return {"generated_at": now, "source_status": source_status, "tours": tours}
