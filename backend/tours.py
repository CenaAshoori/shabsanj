"""Search observed tour packages and link hotels by explicit crosswalk only.

Tour prices are public listing observations. The hotel relation is established
only when the crawler supplies a verified canonical_hotel_id for the same city;
similar names never create a link on their own.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Iterable

from .search import (
    CITY_ALIASES, CITY_LABELS, CONVERSATIONAL_STOPWORDS, REGION_CITY_IDS,
    THEME_LABELS, THEME_TERMS, canonical_city, city_alternatives, city_mentions,
    destination_city_ids, extract_destination_theme, normalize_text,
    parse_intent, search_catalog, strip_travel_filler,
)
from .tour_crawlers import EXPLICIT_HOTEL_MATCHES


TOUR_STOPWORDS = {
    "تور", "تورهای", "پکیج", "سفر", "گردش", "گردشگری", "اقامت", "هتل",
    "از", "به", "در", "با", "برای", "همراه", "قیمت", "ارزان", "ارزانترین",
    "بهترین", "تا", "زیر", "کمتر", "حداکثر", "یا", "میلیون", "هزار", "تومان",
    "تومن", "شب", "روزه", "روز", "نفر", "هر", "per", "person", "tour", "tours",
    "travel", "trip", "hotel", "hotels", "flight", "train", "bus", "under", "below",
    "برگشت", "رفت", "هوایی", "زمینی", "پرواز", "قطار", "اتوبوس",
    "ستاره", "نفره", "میلیونی",
}

TRANSPORT_ALIASES = {
    "flight": ("flight", "پرواز", "هواپیما", "هوایی"),
    "train": ("train", "قطار", "ریلی"),
    "bus": ("bus", "اتوبوس", "اتوبوسی"),
}


def _city_id(value: str | None) -> str | None:
    return canonical_city(value)


def _city_from_preposition(query: str, preposition: str) -> str | None:
    clean = normalize_text(query)
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if re.search(rf"(?<!\w){re.escape(preposition)}\s+{re.escape(normalize_text(alias))}(?!\w)", clean):
                return city
    return None


def _extract_cities(query: str) -> tuple[str | None, str | None]:
    departure = _city_from_preposition(query, "از")
    destination = _city_from_preposition(query, "به")
    mentions = [city for _, _, city in city_mentions(normalize_text(query))]
    if destination is None:
        destination = next((city for city in reversed(mentions)
                            if city != departure and city not in REGION_CITY_IDS), None)
        if destination is None:
            destination = next((city for city in reversed(mentions) if city != departure), None)
    if departure is None and len(mentions) >= 2 and destination:
        departure = next((city for city in mentions if city != destination), None)
    return departure, destination


def _transport_from_query(query: str) -> str | None:
    clean = normalize_text(query)
    for transport, aliases in TRANSPORT_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(normalize_text(alias))}(?!\w)", clean) for alias in aliases):
            return transport
    return None


def _query_terms(query: str, locations: set[str | None], theme: str | None) -> tuple[str, ...]:
    clean = strip_travel_filler(normalize_text(query))
    for start, end, city in reversed(city_mentions(clean)):
        if city in locations or any(location in REGION_CITY_IDS.get(city, ()) for location in locations):
            clean = clean[:start] + " " * (end - start) + clean[end:]
    excluded = set(TOUR_STOPWORDS) | CONVERSATIONAL_STOPWORDS
    if theme:
        excluded |= THEME_TERMS
    tokens = clean.split()
    quantity_units = {"شب", "روزه", "روز", "نفر", "نفره", "میلیون", "میلیونی", "هزار", "تومان", "تومن", "ستاره"}
    terms = []
    for index, token in enumerate(tokens):
        if token in excluded:
            continue
        if re.fullmatch(r"[0-9٬,./]+", token):
            next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
            previous_token = tokens[index - 1] if index else ""
            if next_token in quantity_units or previous_token in {"زیر", "حداکثر", "تا", "کمتر"}:
                continue
            # A trailing hotel number is part of its name, e.g. «الماس ۲».
            if not terms:
                continue
        if len(token) > 1 or token.isdecimal():
            terms.append(token)
    return tuple(terms)


def _jalali_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    match = re.fullmatch(r"\s*(1[34]\d\d)[/-](\d{1,2})[/-](\d{1,2})\s*", text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}/{month:02d}/{day:02d}"


def _services(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _hotel_key(tour: dict[str, Any]) -> str:
    city = _city_id(tour.get("destination_city")) or "unknown"
    name = normalize_text(tour.get("hotel_name"))
    return f"{city}:{name}" if name else f"{city}:unlisted"


def _hotel_index(hotel_offers: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    hotels = search_catalog(hotel_offers, limit=10_000)["hotels"]
    return {(hotel["city_id"], hotel["canonical_id"]): {
        "id": hotel["id"],
        "name": hotel["name"],
        "city": hotel["city"],
        "city_id": hotel["city_id"],
        "stars": hotel["stars"],
        "location": hotel.get("location"),
    } for hotel in hotels}


def _provider_hotel_crosswalk(hotel_offers: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], str]:
    index: dict[tuple[str, str, str], str] = {}
    for offer in hotel_offers:
        if not all(offer.get(key) for key in ("provider", "city", "canonical_id")):
            continue
        for hotel_id in (offer.get("hotel_id"), offer.get("provider_numeric_id")):
            if hotel_id is not None and hotel_id != "":
                index[(str(offer["provider"]), _city_id(offer["city"]) or "", str(hotel_id))] = str(offer["canonical_id"])
    return index


def _linked_hotel(
    tour: dict[str, Any],
    hotel_index: dict[tuple[str, str], dict[str, Any]],
    provider_crosswalk: dict[tuple[str, str, str], str],
) -> dict[str, Any] | None:
    canonical = str(tour.get("canonical_hotel_id") or "").strip()
    city = _city_id(tour.get("destination_city"))
    provider_hotel_id = tour.get("provider_hotel_id")
    if not canonical or not city or not provider_hotel_id:
        return None
    if canonical.startswith(f"{city}:"):
        canonical = canonical[len(city) + 1:]
    expected = provider_crosswalk.get((str(tour.get("provider")), city, str(provider_hotel_id)))
    if expected is None and tour.get("provider") == "tournegar":
        expected = EXPLICIT_HOTEL_MATCHES.get((city, str(provider_hotel_id)))
    if expected != canonical:
        return None
    return hotel_index.get((city, canonical))


def linked_tour_counts(
    raw_tours: Iterable[dict[str, Any]], hotel_offers: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Count only distinct tours with a verified provider-ID hotel link."""
    hotel_offers = list(hotel_offers)
    hotel_index = _hotel_index(hotel_offers)
    provider_crosswalk = _provider_hotel_crosswalk(hotel_offers)
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for tour in raw_tours:
        if not isinstance(tour, dict) or not tour.get("provider") or not tour.get("tour_id"):
            continue
        identity = (str(tour["provider"]), str(tour["tour_id"]))
        if identity in seen:
            continue
        seen.add(identity)
        hotel = _linked_hotel(tour, hotel_index, provider_crosswalk)
        if hotel is not None:
            counts[hotel["id"]] += 1
    return dict(counts)


def _public_tour(tour: dict[str, Any], hotel: dict[str, Any] | None) -> dict[str, Any]:
    fields = (
        "provider", "provider_name", "tour_id", "title", "departure_city",
        "destination_city", "hotel_name", "provider_hotel_id", "canonical_hotel_id",
        "departure_date", "departure_time", "return_date", "hotel_checkin_date",
        "departure_date_gregorian", "return_date_gregorian",
        "hotel_checkin_date_gregorian", "hotel_checkout_date_gregorian", "return_time",
        "duration_nights", "travelers",
        "rooms", "group_price_toman", "price_toman", "price_basis", "transport", "source_url", "listing_url",
        "observed_at", "availability", "price_note", "source_type", "variants",
        "cta_label",
    )
    result = {field: tour.get(field) for field in fields}
    result["id"] = f"{tour.get('provider') or 'unknown'}:{tour.get('tour_id') or tour.get('source_url') or ''}"
    result["departure_city"] = _city_id(tour.get("departure_city"))
    result["destination_city"] = _city_id(tour.get("destination_city"))
    result["departure_city_label"] = CITY_LABELS.get(result["departure_city"], result["departure_city"])
    result["destination_city_label"] = CITY_LABELS.get(result["destination_city"], result["destination_city"])
    result["hotel_key"] = _hotel_key(tour)
    result["services"] = _services(tour.get("services"))
    result["optional_services"] = _services(tour.get("optional_services"))
    result["hotel"] = hotel
    return result


def _all_options(tours: list[dict[str, Any]]) -> dict[str, Any]:
    departure = {_city_id(t.get("departure_city")) for t in tours}
    destination = {_city_id(t.get("destination_city")) for t in tours}
    departure.discard(None)
    destination.discard(None)
    hotels: dict[str, dict[str, Any]] = {}
    for tour in tours:
        if not tour.get("hotel_name"):
            continue
        key = tour["hotel_key"]
        linked = tour.get("hotel")
        hotels.setdefault(key, {
            "key": key,
            "name": tour["hotel_name"],
            "city": tour["destination_city"],
            "city_label": tour["destination_city_label"],
            "linked_hotel_id": linked["id"] if linked else None,
        })
    dates = {_jalali_date(t.get("departure_date")) for t in tours}
    dates.discard(None)
    checkin_dates = {_jalali_date(t.get("hotel_checkin_date")) for t in tours}
    checkin_dates.discard(None)
    services = {item for tour in tours for item in tour["services"]}
    return {
        "departure_cities": [{"id": city, "label": CITY_LABELS.get(city, city)} for city in sorted(departure)],
        "destination_cities": [{"id": city, "label": CITY_LABELS.get(city, city)} for city in sorted(destination)],
        "hotels": sorted(hotels.values(), key=lambda item: (item["city"] or "", item["name"])),
        "departure_dates": sorted(dates),
        "hotel_checkin_dates": sorted(checkin_dates),
        "services": sorted(services),
    }


def search_tours(
    raw_tours: Iterable[dict[str, Any]],
    hotel_offers: Iterable[dict[str, Any]],
    query: str = "",
    *,
    departure_city: str | None = None,
    destination_city: str | None = None,
    hotel_id: str | None = None,
    hotel_name: str | None = None,
    hotel_key: str | None = None,
    departure_date: str | None = None,
    departure_from: str | None = None,
    hotel_checkin_date: str | None = None,
    service: str | None = None,
    transport: str | None = None,
    max_price_toman: int | None = None,
    sort: str = "best",
    limit: int = 200,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hotel_offers = list(hotel_offers)
    index = _hotel_index(hotel_offers)
    provider_crosswalk = _provider_hotel_crosswalk(hotel_offers)
    all_tours = [_public_tour(raw, _linked_hotel(raw, index, provider_crosswalk))
                 for raw in raw_tours if isinstance(raw, dict) and raw.get("title") and raw.get("provider")]
    options = _all_options(all_tours)
    inferred_departure, inferred_destination = (
        (_city_id(plan.get("departure_city")), _city_id(plan.get("destination_city")))
        if plan is not None else _extract_cities(query)
    )
    filters = {
        "departure_city": _city_id(departure_city) if departure_city else inferred_departure,
        "destination_city": _city_id(destination_city) if destination_city else inferred_destination,
        "hotel_id": hotel_id if hotel_id is not None else plan.get("hotel_id") if plan is not None else None,
        "hotel_name": hotel_name if hotel_name is not None else plan.get("hotel_name") if plan is not None else None,
        "hotel_key": hotel_key,
        "departure_date": _jalali_date(departure_date if departure_date is not None else plan.get("departure_date") if plan is not None else None),
        "departure_from": _jalali_date(departure_from if departure_from is not None else plan.get("departure_from") if plan is not None else None),
        "hotel_checkin_date": _jalali_date(hotel_checkin_date if hotel_checkin_date is not None else plan.get("hotel_checkin_date") if plan is not None else None),
        "service": service if service is not None else plan.get("service") if plan is not None else None,
        "transport": transport if transport is not None else plan.get("transport") if plan is not None else _transport_from_query(query),
        "max_price_toman": max_price_toman if max_price_toman is not None else plan.get("max_price_toman") if plan is not None else parse_intent(query).max_price_toman,
    }
    theme = (plan.get("destination_theme") if plan is not None
             else extract_destination_theme(query, filters["destination_city"]))
    alternatives = (tuple(plan.get("destination_alternatives") or ()) if plan is not None
                    else city_alternatives(normalize_text(query)) if theme else ()) if not destination_city else ()
    if alternatives:
        filters["destination_city"] = None
        if plan is None and not departure_city and not _city_from_preposition(query, "از"):
            filters["departure_city"] = None
        if plan is None:
            theme = extract_destination_theme(query)
    if destination_city:
        allowed_destinations = destination_city_ids(filters["destination_city"], theme)
    elif plan is not None and isinstance(plan.get("destination_city_ids"), list):
        supplied = frozenset(plan["destination_city_ids"])
        scope = (frozenset().union(*(destination_city_ids(alt, theme) or frozenset()
                                     for alt in alternatives)) if alternatives
                 else destination_city_ids(filters["destination_city"], theme))
        allowed_destinations = supplied & scope if scope is not None else supplied
    else:
        allowed_destinations = (frozenset().union(*(destination_city_ids(alt, theme) or frozenset()
                                                    for alt in alternatives)) if alternatives
                                else destination_city_ids(filters["destination_city"], theme))
    filters["destination_theme"] = theme
    filters["destination_theme_label"] = THEME_LABELS.get(theme) if theme else None
    filters["matched_city_ids"] = sorted(allowed_destinations) if allowed_destinations is not None else None
    filters["destination_alternatives"] = list(alternatives)
    terms = (tuple(token for part in (plan.get("hotel_name_terms") or [])
                   for token in normalize_text(part).split()) if plan is not None
             else _query_terms(query, {filters["departure_city"], filters["destination_city"], *alternatives}, theme))
    matching: list[dict[str, Any]] = []
    for tour in all_tours:
        if filters["departure_city"] and tour["departure_city"] not in REGION_CITY_IDS.get(filters["departure_city"], frozenset({filters["departure_city"]})):
            continue
        if allowed_destinations is not None and tour["destination_city"] not in allowed_destinations:
            continue
        if filters["hotel_id"] and (not tour["hotel"] or tour["hotel"]["id"] != filters["hotel_id"]):
            continue
        if filters["hotel_name"]:
            requested_name = normalize_text(filters["hotel_name"])
            observed_name = normalize_text(tour["hotel_name"])
            if hotel_name is not None:
                if observed_name != requested_name:
                    continue
            elif not re.search(rf"(?<!\w){re.escape(requested_name)}(?!\w)", observed_name):
                continue
        if filters["hotel_key"] and tour["hotel_key"] != filters["hotel_key"]:
            continue
        tour_date = _jalali_date(tour.get("departure_date"))
        if filters["departure_date"] and tour_date != filters["departure_date"]:
            continue
        if filters["departure_from"] and (tour_date is None or tour_date < filters["departure_from"]):
            continue
        if filters["hotel_checkin_date"] and _jalali_date(tour.get("hotel_checkin_date")) != filters["hotel_checkin_date"]:
            continue
        if filters["service"] and not any(
            re.search(rf"(?<!\w){re.escape(normalize_text(filters['service']))}(?!\w)", normalize_text(item))
            for item in tour["services"]
        ):
            continue
        if filters["transport"] and tour.get("transport") != filters["transport"]:
            continue
        price = tour.get("price_toman")
        if filters["max_price_toman"] is not None and (
            not isinstance(price, (int, float)) or isinstance(price, bool) or price > filters["max_price_toman"]
        ):
            continue
        haystack = normalize_text(" ".join((tour.get("title") or "", tour.get("hotel_name") or "")))
        if terms and not all(term in set(haystack.split()) for term in terms):
            continue
        reasons = []
        if filters["destination_city"]:
            reasons.append(f"مقصد {CITY_LABELS.get(filters['destination_city'], filters['destination_city'])}")
        if alternatives:
            reasons.append("مقصد " + " یا ".join(CITY_LABELS.get(city, city) for city in alternatives))
        if theme:
            reasons.append(f"مقصد در {THEME_LABELS[theme]}")
        if filters["departure_city"]:
            reasons.append(f"از {CITY_LABELS.get(filters['departure_city'], filters['departure_city'])}")
        if terms:
            reasons.append(f"مطابق «{' '.join(terms)}»")
        if filters["hotel_id"] or filters["hotel_name"] or filters["hotel_key"]:
            reasons.append(f"هتل {tour['hotel_name']}")
        if filters["departure_date"]:
            reasons.append(f"حرکت {filters['departure_date']}")
        if filters["hotel_checkin_date"]:
            reasons.append(f"ورود به هتل {filters['hotel_checkin_date']}")
        if filters["service"]:
            reasons.append(f"خدمت {filters['service']}")
        tour["match_explanation"] = "؛ ".join(reasons) if reasons else "تور ثبت‌شده از منبع عمومی"
        tour["relevance_score"] = 50 + 10 * len(terms) + (15 if tour["hotel"] else 0)
        matching.append(tour)

    def priced(tour: dict[str, Any]) -> int:
        value = tour.get("price_toman")
        return value if isinstance(value, int) and value > 0 else 10**18

    if sort in {"price", "best_price", "price_asc"}:
        matching.sort(key=lambda t: (priced(t), t.get("departure_date") or "9999", t["id"]))
    elif sort in {"departure", "departure_asc"}:
        matching.sort(key=lambda t: (t.get("departure_date") or "9999", priced(t), t["id"]))
    elif sort in {"hotel_stars", "stars"}:
        matching.sort(key=lambda t: (-(t["hotel"]["stars"] or 0) if t["hotel"] else 0, priced(t), t["id"]))
    else:
        matching.sort(key=lambda t: (-t["relevance_score"], priced(t), t.get("departure_date") or "9999", t["id"]))

    linked_ids = {tour["hotel"]["id"] for tour in all_tours if tour["hotel"]}
    return {
        "query": query,
        "parsed_intent": {**filters, "name_terms": list(terms)},
        "sort": sort,
        "total": len(matching),
        "tours": matching[:limit],
        "filters": options,
        "counts": {
            "tour_count": len(all_tours),
            "provider_count": len({tour["provider"] for tour in all_tours}),
            "hotel_count": len(options["hotels"]),
            "linked_hotel_count": len(linked_ids),
        },
        "price_disclaimer": "قیمت تور، نرخ عمومی ثبت‌شده برای هر نفر است؛ موجودی، تاریخ، خدمات و مبلغ نهایی را در سایت ارائه‌دهنده بررسی کنید.",
        "location_disclaimer": "جست‌وجوی ساحلی بر پایهٔ شهر مقصد است؛ فاصلهٔ هتل تا ساحل بررسی نشده است." if theme else None,
    }
