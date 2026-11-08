"""Persian hotel search, conservative grouping, and explainable ranking.

The catalog contains *observed listing prices*, not live bookable quotes. We
normalize a price only when its basis is known, preserve every source URL, and
never infer that two provider listings are the same hotel from fuzzy names.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .crawlers import IMAGE_HOSTS, valid_snapptrip_property_pin


CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "tehran": ("تهران", "tehran", "teheran"),
    "mashhad": ("مشهد", "mashhad", "mashad"),
    "isfahan": ("اصفهان", "isfahan", "esfahan"),
    "shiraz": ("شیراز", "shiraz"),
    "kish": ("کیش", "kish"),
    "tabriz": ("تبریز", "tabriz"),
    "yazd": ("یزد", "yazd"),
    "rasht": ("رشت", "rasht"),
    "bandar_anzali": ("بندرانزلی", "بندر انزلی", "انزلی", "bandar anzali", "bandar e anzali", "anzali"),
    "lahijan": ("لاهیجان", "lahijan"),
    "astara": ("آستارا", "استارا", "astara"),
    "ramsar": ("رامسر", "ramsar"),
    "chalus": ("چالوس", "chalus"),
    "nowshahr": ("نوشهر", "nowshahr", "noshahr"),
    "gilan": ("گیلان", "gilan"),
    "mazandaran": ("مازندران", "mazandaran"),
    "north": ("شمال ایران", "شمال کشور", "شمال", "north iran", "northern iran"),
}

CITY_LABELS = {
    "tehran": "تهران", "mashhad": "مشهد", "isfahan": "اصفهان",
    "shiraz": "شیراز", "kish": "کیش", "tabriz": "تبریز",
    "yazd": "یزد", "rasht": "رشت", "bandar_anzali": "بندر انزلی",
    "lahijan": "لاهیجان", "astara": "آستارا", "ramsar": "رامسر",
    "chalus": "چالوس", "nowshahr": "نوشهر", "gilan": "گیلان",
    "mazandaran": "مازندران", "north": "شمال ایران",
}

REGION_CITY_IDS: dict[str, frozenset[str]] = {
    "gilan": frozenset({"rasht", "bandar_anzali", "lahijan", "astara"}),
    "mazandaran": frozenset({"ramsar", "chalus", "nowshahr"}),
    "north": frozenset({"rasht", "bandar_anzali", "lahijan", "astara", "ramsar", "chalus", "nowshahr"}),
}

THEME_CITY_IDS: dict[str, frozenset[str]] = {
    "coastal": frozenset({"kish", "bandar_anzali", "astara", "ramsar", "chalus", "nowshahr"}),
    "caspian_coast": frozenset({"bandar_anzali", "astara", "ramsar", "chalus", "nowshahr"}),
    "southern_coast": frozenset({"kish"}),
}

THEME_LABELS = {
    "coastal": "شهرهای ساحلی",
    "caspian_coast": "شهرهای ساحلی خزر",
    "southern_coast": "شهرهای ساحلی جنوب",
}

CONVERSATIONAL_STOPWORDS = {
    "می", "میخوام", "میخواهم", "میخایم", "میخواهیم", "میخوایم", "میخواستم",
    "خوام", "خواهم", "خواستم", "برم", "بریم", "بروم", "برویم", "رفتن",
    "جایی", "جای", "جا", "یه", "یک", "چند", "سمت", "توی", "تو", "اطراف",
    "دلم", "خوب", "قشنگ", "زیبا", "لطفا", "پیدا", "کن", "بهم", "نشون",
    "بده", "want", "go", "somewhere", "near", "by", "the", "a", "to",
}

THEME_TERMS = {
    "کنار", "نزدیک", "لب", "دریا", "دریای", "ساحل", "ساحلی", "سواحل", "رو", "به",
    "خزر", "کاسپین", "جنوب", "خلیج", "فارس", "sea", "beach", "coast",
    "coastal", "seaside", "beachfront", "caspian", "south", "southern",
    "persian", "gulf", "view",
}

NUMBER_WORDS = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}

# Search-only aliases. Grouping depends on explicit canonical IDs in the data.
HOTEL_ALIASES = {
    "اسپیناس پالاس": ("espinas palace", "اسپیناس پالاس"),
    "اسپیناس بلوار": ("espinas boulevard", "اسپیناس بلوار"),
    "درویشی": ("darvishi", "darvishi royal", "درویشی"),
    "قصر طلایی": ("ghasr talaee", "golden palace", "قصر طلایی"),
    "الماس ۲": ("almas 2", "almas ii", "الماس 2"),
}

STOPWORDS = {
    "هتل", "هتلهای", "هتلها", "hotel", "hotels", "در", "با", "برای",
    "قیمت", "قیمتی", "ارزان", "ارزانترین", "بهترین", "اقامت", "اقامتگاه",
    "را", "از", "تا", "زیر", "کمتر", "حداکثر", "سقف", "ستاره",
    "star", "stars", "under", "below", "max", "per", "night",
    "تومان", "تومن", "میلیون", "هزار", "million", "thousand",
    "شبی", "شبانه", "شب", "یا", "حداقل", "بالای", "بیشتر", "های", "in", "of",
}

_DIGIT_TABLE = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)
_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)


def normalize_text(value: Any) -> str:
    """Normalize Arabic/Persian variants, spacing, and digits for matching."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_DIGIT_TABLE)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    text = text.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    text = _DIACRITICS.sub("", text).casefold()
    return re.sub(r"\s+", " ", _NON_WORD.sub(" ", text)).strip()


def canonical_city(value: str | None) -> str | None:
    """Resolve a city or supported region label without substring matching."""
    if not value:
        return None
    clean = normalize_text(value)
    for city_id, aliases in CITY_ALIASES.items():
        if clean == city_id or any(clean == normalize_text(alias) for alias in aliases):
            return city_id
    return clean


def city_mentions(clean_query: str) -> list[tuple[int, int, str]]:
    """Find whole-word location aliases, preferring the longest overlap."""
    candidates: list[tuple[int, int, str]] = []
    for city_id, aliases in CITY_ALIASES.items():
        for alias in (city_id, *aliases):
            for match in re.finditer(rf"(?<!\w){re.escape(normalize_text(alias))}(?!\w)", clean_query):
                candidates.append((match.start(), match.end(), city_id))
    chosen: list[tuple[int, int, str]] = []
    for candidate in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
        if not any(candidate[0] < end and start < candidate[1] for start, end, _ in chosen):
            chosen.append(candidate)
    return sorted(chosen)


def city_alternatives(clean_query: str) -> tuple[str, ...]:
    """Recognize an explicit «A یا B» between location mentions."""
    mentions = city_mentions(clean_query)
    linked: list[str] = []
    for left, right in zip(mentions, mentions[1:]):
        if re.search(r"(?<!\w)یا(?!\w)|(?<!\w)or(?!\w)", clean_query[left[1]:right[0]]):
            linked.extend((left[2], right[2]))
    return tuple(dict.fromkeys(linked)) if len(set(linked)) >= 2 else ()


def strip_travel_filler(clean_query: str) -> str:
    """Remove conversational clauses without dropping standalone hotel names."""
    clean_query = re.sub(r"(?<!\w)(?:من\s+)?دوست\s+دارم\s+(?:برم|بریم|بروم|برویم)(?!\w)", " ", clean_query)
    clean_query = re.sub(r"(?<!\w)جایی\s+که(?=\s+(?:دریا|دریای|ساحل))", " ", clean_query)
    clean_query = re.sub(r"(?<!\w)(دریا|دریای|ساحل)\s+(?:داشته\s+(?:باشه|باشد)|داره)(?!\w)", r"\1", clean_query)
    return re.sub(r"\s+", " ", clean_query).strip()


def extract_destination_theme(query: str, city: str | None = None) -> str | None:
    """Map sea-related travel language to city scope, not beachfront hotels."""
    clean = normalize_text(query)
    strong = bool(re.search(
        r"(?:کنار|نزدیک|لب|رو به)\s+(?:دریا|دریای|ساحل)|"
        r"(?:دریای|ساحل|سواحل)\s+(?:خزر|شمال|جنوب)|"
        r"(?:north|south)\s+coast|"
        r"(?:ساحلی|سواحل|خزر|کاسپین|خلیج فارس|coastal|seaside|beachfront|caspian|"
        r"near beach|by (?:the )?sea|persian gulf)", clean,
    ))
    bare = bool(re.search(r"(?<!\w)(?:دریا|ساحل|sea|beach|coast)(?!\w)", clean))
    travel = bool(re.search(r"(?:می\s*خوام|می\s*خواهم|برم|بریم|سفر|مقصد|برویم|رفتن|"
                            r"want|go|trip|travel)", clean))
    budget = bool(re.search(r"(?<!\w)(?:زیر|حداکثر|کمتر|تا|under|below|max)(?!\w)\s*\d", clean))
    hotel_name = bool(re.search(r"(?:^|\s)(?:هتل|hotel)\s+(?:دریا|ساحل|sea|beach)(?:\s|$)", clean))
    if not strong and not (bare and (travel or budget or clean in {"دریا", "ساحل", "sea", "beach", "coast"}) and not hotel_name):
        return None
    northern = bool(re.search(r"(?<!\w)(?:شمال|خزر|کاسپین|caspian|north|northern)(?!\w)", clean))
    southern = bool(re.search(r"(?<!\w)(?:جنوب|کیش|خلیج فارس|south|southern|kish|persian gulf)(?!\w)", clean))
    city_id = canonical_city(city)
    northern = northern or city_id in {"north", "gilan", "mazandaran"}
    southern = southern or city_id == "kish"
    if northern and not southern:
        return "caspian_coast"
    if southern and not northern:
        return "southern_coast"
    return "coastal"


def destination_city_ids(city: str | None, theme: str | None) -> frozenset[str] | None:
    """Intersect an exact city or region with a theme; None means unrestricted."""
    city_id = canonical_city(city)
    scope = REGION_CITY_IDS.get(city_id, frozenset({city_id})) if city_id else None
    themed = THEME_CITY_IDS.get(theme) if theme else None
    if scope is None:
        return themed
    return scope & themed if themed is not None else scope


def _number(token: str) -> float | None:
    normalized = normalize_text(token)
    if normalized in NUMBER_WORDS:
        return float(NUMBER_WORDS[normalized])
    numeric = str(token).translate(_DIGIT_TABLE).replace("٬", "").replace(",", "")
    try:
        return float(numeric)
    except ValueError:
        return None


def _budget_from_query(query: str) -> int | None:
    numeric_query = unicodedata.normalize("NFKC", query).translate(_DIGIT_TABLE)
    numeric_query = numeric_query.replace("ي", "ی").replace("ك", "ک")
    marker = r"(?:زیر|کمتر\s+از|حداکثر|تا\s+سقف|تا|under|below|max)"
    amount = r"(\d[\d,٬]*(?:\.\d+)?|یک|دو|سه|چهار|پنج)"
    unit = r"(میلیون|هزار|million|thousand|m|تومان|تومن)?"
    match = re.search(rf"{marker}\s*{amount}\s*{unit}", numeric_query, re.I)
    if not match:
        return None
    value = _number(match.group(1))
    if value is None:
        return None
    unit_value = normalize_text(match.group(2) or "")
    if unit_value in {"میلیون", "million", "m"}:
        value *= 1_000_000
    elif unit_value in {"هزار", "thousand"}:
        value *= 1_000
    elif value < 1_000:
        return None  # An unqualified "3" is not a credible price ceiling.
    return round(value)


def _has_tours_query(query: str) -> bool:
    clean = normalize_text(query)
    return bool(re.search(
        r"(?<!\w)هتل(?:\s+(?:های|ها))?\s+(?:با|دارای|همراه)\s+تور(?!\w)|"
        r"(?<!\w)هتل(?:\s+(?:های|ها))?(?:\s+\w+){0,4}\s+تور\s+(?:دارد|دارند)(?!\w)|"
        r"(?<!\w)hotels?\s+with\s+tours?(?!\w)", clean,
    ))


@dataclass(frozen=True)
class Intent:
    city: str | None
    stars: int | None
    min_stars: int | None
    max_price_toman: int | None
    name_terms: tuple[str, ...]
    destination_theme: str | None
    matched_city_ids: frozenset[str] | None
    destination_alternatives: tuple[str, ...]
    hotel_name: str | None = None
    has_tours: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "city": CITY_LABELS.get(self.city, self.city) if self.city else None,
            "city_id": self.city,
            "city_label": CITY_LABELS.get(self.city) if self.city else None,
            "stars": self.stars,
            "min_stars": self.min_stars,
            "max_price_toman": self.max_price_toman,
            "name_terms": list(self.name_terms),
            "destination_theme": self.destination_theme,
            "destination_theme_label": THEME_LABELS.get(self.destination_theme) if self.destination_theme else None,
            "matched_city_ids": sorted(self.matched_city_ids) if self.matched_city_ids is not None else None,
            "destination_alternatives": list(self.destination_alternatives),
            "hotel_name": self.hotel_name,
            "has_tours": self.has_tours,
        }


def parse_intent(
    query: str = "",
    *,
    city: str | None = None,
    stars: int | None = None,
    min_stars: int | None = None,
    max_price_toman: int | None = None,
    has_tours: bool | None = None,
) -> Intent:
    clean = normalize_text(query)
    mentions = city_mentions(clean)
    specific = [match for match in mentions if match[2] not in REGION_CITY_IDS]
    inferred_city = (specific or mentions)[-1][2] if mentions else None
    explicit_city = canonical_city(city)
    detected_city = (inferred_city if explicit_city in REGION_CITY_IDS and
                     inferred_city in REGION_CITY_IDS[explicit_city]
                     else explicit_city or inferred_city)
    theme = extract_destination_theme(query, detected_city)
    alternatives = city_alternatives(clean) if theme and not explicit_city else ()
    if alternatives:
        detected_city = None
        theme = extract_destination_theme(query)

    # Keep a different city word when it could be part of the hotel's name:
    # «هتل تهران در مشهد» is a search for a Mashhad hotel named Tehran.
    removable = [match for match in mentions if match[2] in alternatives or match[2] == detected_city or
                 (match[2] in REGION_CITY_IDS and detected_city in REGION_CITY_IDS[match[2]])]
    for start, end, _ in reversed(removable):
        clean = clean[:start] + " " * (end - start) + clean[end:]
    clean = strip_travel_filler(clean)
    matched_city_ids = (frozenset().union(*(destination_city_ids(alt, theme) or frozenset()
                                            for alt in alternatives)) if alternatives
                        else destination_city_ids(detected_city, theme))

    word = r"(\d|یک|دو|سه|چهار|پنج|one|two|three|four|five)"
    star_match = re.search(rf"(?:حداقل\s+|بالای\s+|بیشتر\s+از\s+)?{word}\s*(?:ستاره|star|stars)\b", clean)
    if not star_match:
        star_match = re.search(rf"(?:ستاره|star|stars)\s*{word}\b", clean)
    parsed_stars = None
    parsed_min_stars = None
    if star_match:
        value = _number(star_match.group(1))
        if value is not None and 1 <= value <= 5:
            if star_match.group(0).startswith("حداقل"):
                parsed_min_stars = int(value)
            elif star_match.group(0).startswith(("بالای", "بیشتر")):
                parsed_min_stars = int(value) + 1
            else:
                parsed_stars = int(value)
    if stars is not None:
        parsed_stars = stars
        parsed_min_stars = None
    if min_stars is not None:
        parsed_min_stars = min_stars
        parsed_stars = None

    phrase_has_tours = _has_tours_query(query)
    has_tours_intent = has_tours if has_tours is not None else phrase_has_tours
    excluded = set(STOPWORDS) | CONVERSATIONAL_STOPWORDS
    if phrase_has_tours:
        excluded.update({"تور", "تورهای", "دارای", "دارد", "دارند", "همراه", "with", "tour", "tours"})
    if theme:
        excluded |= THEME_TERMS
    excluded.update(NUMBER_WORDS)
    tokens = clean.split()
    terms: list[str] = []
    quantity_units = {"ستاره", "میلیون", "هزار", "تومان", "تومن", "شب", "شبی", "روز", "نفر"}
    for index, token in enumerate(tokens):
        if token in excluded:
            continue
        if re.fullmatch(r"[0-9٬,./]+", token):
            next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
            previous_token = tokens[index - 1] if index else ""
            if next_token in quantity_units or previous_token in {"زیر", "حداکثر", "تا", "کمتر"} or not terms:
                continue
        if len(token) >= 2 or token.isdecimal():
            terms.append(token)
    return Intent(
        city=detected_city,
        stars=parsed_stars,
        min_stars=parsed_min_stars,
        max_price_toman=max_price_toman if max_price_toman is not None else _budget_from_query(query),
        name_terms=tuple(terms),
        destination_theme=theme,
        matched_city_ids=matched_city_ids,
        destination_alternatives=alternatives,
        has_tours=has_tours_intent,
    )


def planned_hotel_intent(
    plan: dict[str, Any], *, city: str | None = None,
    stars: int | None = None, min_stars: int | None = None,
    max_price_toman: int | None = None,
    has_tours: bool | None = None,
) -> Intent:
    """Apply a validated query plan without reparsing generated prose."""
    explicit_city = canonical_city(city)
    planned_city = canonical_city(plan.get("city_id"))
    theme = plan.get("destination_theme") if plan.get("destination_theme") in THEME_CITY_IDS else None
    alternatives = tuple(plan.get("destination_alternatives") or ()) if not explicit_city else ()
    if explicit_city:
        city_id = explicit_city
        city_scope = destination_city_ids(city_id, theme)
    else:
        city_id = None if alternatives else planned_city
        scope = destination_city_ids(city_id, theme)
        city_ids = plan.get("city_ids")
        if isinstance(city_ids, list):
            supplied = frozenset(city_ids)
            city_scope = supplied & scope if scope is not None else supplied
        elif alternatives:
            city_scope = frozenset().union(*(destination_city_ids(alt, theme) or frozenset()
                                             for alt in alternatives))
        else:
            city_scope = scope
    planned_stars = plan.get("stars") if stars is None and min_stars is None else None
    planned_min_stars = plan.get("min_stars") if stars is None and min_stars is None else None
    exact_stars = stars if stars is not None else planned_stars
    minimum_stars = min_stars if min_stars is not None else planned_min_stars
    if exact_stars is not None:
        minimum_stars = None
    raw_terms = plan.get("hotel_name_terms") or []
    terms = tuple(token for part in raw_terms for token in normalize_text(part).split())
    hotel_name = str(plan.get("hotel_name") or "").strip() or None
    return Intent(
        city=city_id,
        stars=exact_stars,
        min_stars=minimum_stars,
        max_price_toman=max_price_toman if max_price_toman is not None else plan.get("max_price_toman"),
        name_terms=terms,
        destination_theme=theme,
        matched_city_ids=city_scope,
        destination_alternatives=alternatives,
        hotel_name=hotel_name,
        has_tours=has_tours if has_tours is not None else plan.get("has_tours"),
    )


def normalized_nightly_price(offer: dict[str, Any]) -> int | None:
    amount = offer.get("price_toman")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return None
    basis = offer.get("price_basis")
    if basis in {"per_night", "nightly"}:
        return round(amount)
    if basis == "stay_total":
        nights = offer.get("stay_nights")
        if isinstance(nights, int) and nights > 0:
            return round(amount / nights)
    return None


HOTEL_IMAGE_HOSTS = {
    **IMAGE_HOSTS,
    "asasafar": {"www.asasafar.com"},
}


def _published_image_url(offer: dict[str, Any]) -> str | None:
    url = offer.get("image_url")
    if not isinstance(url, str) or any(char in url for char in "\\\r\n\t"):
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname in HOTEL_IMAGE_HOSTS.get(offer.get("provider"), set())
                and parts.username is None and parts.password is None and parts.port in (None, 443)):
            return url
    except ValueError:
        pass
    return None


def _safe_offer(offer: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "provider", "provider_name", "hotel_name", "hotel_id", "canonical_id",
        "city", "stars", "price_toman", "price_basis", "stay_nights",
        "checkin", "checkout", "occupancy", "room_type", "board",
        "source_url", "observed_at", "availability", "price_note",
    )
    result = {field: offer.get(field) for field in fields}
    result["image_url"] = _published_image_url(offer)
    result["source_price_basis"] = result["price_basis"]
    if result["price_basis"] == "per_night":
        result["price_basis"] = "nightly"
    result["price_per_night_toman"] = normalized_nightly_price(offer)
    return result


def _verified_property_location(offer: dict[str, Any]) -> dict[str, Any] | None:
    """Expose only Snapptrip's joined property pin, never an inferred city pin."""
    if offer.get("provider") != "snapptrip" or offer.get("location_accuracy") != "property":
        return None
    numeric_id = offer.get("provider_numeric_id")
    latitude = offer.get("latitude")
    longitude = offer.get("longitude")
    if (not isinstance(numeric_id, int) or isinstance(numeric_id, bool) or numeric_id <= 0
            or not valid_snapptrip_property_pin(str(offer.get("city") or ""), latitude, longitude)):
        return None
    source_url = str(offer.get("source_url") or "")
    parts = urlsplit(source_url)
    if parts.scheme != "https" or parts.netloc != "www.snapptrip.com" or parts.query:
        return None
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "provider": "snapptrip",
        "source_url": source_url,
        "accuracy": "property",
    }


def _group_offers(offers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for offer in offers:
        if not isinstance(offer, dict) or not offer.get("hotel_name") or not offer.get("provider"):
            continue
        city = normalize_text(offer.get("city"))
        canonical = str(offer.get("canonical_id") or "").strip()
        if not canonical:
            # A name similarity is not proof that two listings are one hotel.
            provider_id = str(offer.get("hotel_id") or offer.get("source_url") or offer["hotel_name"])
            canonical = f"{offer['provider']}:{provider_id}"
        groups.setdefault((city, canonical), []).append(offer)

    hotels = []
    for (city, canonical), group in groups.items():
        names = [str(offer["hotel_name"]).strip() for offer in group]
        name = max(Counter(names).items(), key=lambda item: (item[1], len(item[0])))[0]
        valid_stars = [value for value in (offer.get("stars") for offer in group)
                       if isinstance(value, int) and 1 <= value <= 5]
        star_counts = Counter(valid_stars)
        stars = star_counts.most_common(1)[0][0] if star_counts else None
        safe_offers = [_safe_offer(offer) for offer in group]
        location = next((pin for offer in group if (pin := _verified_property_location(offer))), None)
        safe_offers.sort(key=lambda offer: (
            offer["price_per_night_toman"] is None,
            offer["price_per_night_toman"] or float("inf"),
            str(offer.get("provider_name") or offer.get("provider") or ""),
        ))
        best_offer = next((offer for offer in safe_offers if offer["price_per_night_toman"] is not None), None)
        image_url = next((offer["image_url"] for offer in safe_offers if offer["image_url"]), None)
        observed = [str(offer.get("observed_at")) for offer in group if offer.get("observed_at")]
        hotels.append({
            "id": f"{city}:{canonical}",
            "canonical_id": canonical,
            "name": name,
            "city": city,
            "city_label": CITY_LABELS.get(city, city),
            "stars": stars,
            "star_conflict": len(star_counts) > 1,
            "provider_count": len({offer.get("provider") for offer in group}),
            "offer_count": len(safe_offers),
            "best_offer": best_offer,
            "image_url": image_url,
            "offers": safe_offers,
            "observed_at": max(observed) if observed else None,
            "location": location,
            "_names": names,
        })
    return hotels


def _name_match(terms: tuple[str, ...], hotel: dict[str, Any], phrase: str | None = None) -> tuple[bool, str | None, int]:
    if not terms and not phrase:
        return True, None, 0
    names = {normalize_text(name) for name in hotel["_names"]}
    for name in tuple(names):
        for key, aliases in HOTEL_ALIASES.items():
            if normalize_text(key) in name:
                names.update(normalize_text(alias) for alias in aliases)
    for name in names:
        words = set(name.split())
        normalized_phrase = normalize_text(phrase) if phrase else ""
        if normalized_phrase:
            if re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", name):
                return True, name, 100 if name == normalized_phrase else 75
        elif all(term in words for term in terms):
            exact = name == " ".join(terms)
            return True, name, 100 if exact else 60 + 5 * len(terms)
    return False, None, 0


def search_catalog(
    offers: Iterable[dict[str, Any]],
    query: str = "",
    *,
    city: str | None = None,
    stars: int | None = None,
    min_stars: int | None = None,
    max_price_toman: int | None = None,
    has_tours: bool | None = None,
    tour_counts: Mapping[str, int] | None = None,
    sort: str = "best",
    limit: int = 50,
    offset: int = 0,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent = (planned_hotel_intent(plan, city=city, stars=stars, min_stars=min_stars,
                                   max_price_toman=max_price_toman, has_tours=has_tours) if plan is not None
              else parse_intent(query, city=city, stars=stars, min_stars=min_stars,
                                max_price_toman=max_price_toman, has_tours=has_tours))
    matching: list[dict[str, Any]] = []
    for hotel in _group_offers(offers):
        hotel["tour_count"] = tour_counts.get(hotel["id"], 0) if tour_counts is not None else None
        if intent.has_tours and not hotel["tour_count"]:
            continue
        if intent.matched_city_ids is not None and hotel["city"] not in intent.matched_city_ids:
            continue
        if intent.stars is not None and hotel["stars"] != intent.stars:
            continue
        if intent.min_stars is not None and (hotel["stars"] is None or hotel["stars"] < intent.min_stars):
            continue
        matched, matched_on, relevance = _name_match(intent.name_terms, hotel, intent.hotel_name)
        if not matched:
            continue
        if intent.max_price_toman is not None:
            filtered = [offer for offer in hotel["offers"]
                        if offer["price_per_night_toman"] is not None
                        and offer["price_per_night_toman"] <= intent.max_price_toman]
            if not filtered:
                continue
            hotel["offers"] = filtered
            hotel["best_offer"] = filtered[0]
            hotel["offer_count"] = len(filtered)
            hotel["provider_count"] = len({offer["provider"] for offer in filtered})
        reasons = []
        if matched_on:
            reasons.append(f"نام هتل با «{intent.hotel_name or ' '.join(intent.name_terms)}» مطابقت دارد")
        if intent.city:
            reasons.append(f"در {hotel['city_label']}")
        if intent.destination_theme:
            reasons.append(f"شهر مقصد در {THEME_LABELS[intent.destination_theme]}")
        if intent.has_tours:
            reasons.append(f"{hotel['tour_count']} تور ثبت‌شده برای این هتل")
        if intent.stars is not None:
            reasons.append(f"{intent.stars} ستاره")
        elif intent.min_stars is not None:
            reasons.append(f"حداقل {intent.min_stars} ستاره")
        if intent.max_price_toman is not None:
            reasons.append(f"قیمت نمایشی هر شب تا {intent.max_price_toman:,} تومان")
        hotel["matched_on"] = matched_on
        hotel["match_explanation"] = "؛ ".join(reasons) if reasons else "همهٔ هتل‌های ثبت‌شده"
        hotel["relevance_score"] = relevance
        hotel["city_id"] = hotel["city"]
        hotel["city"] = hotel["city_label"]
        del hotel["_names"]
        matching.append(hotel)

    def price(hotel: dict[str, Any]) -> float:
        best = hotel.get("best_offer")
        return best["price_per_night_toman"] if best else float("inf")

    if sort in {"best_price", "price", "price_asc"}:
        matching.sort(key=lambda h: (price(h), -h["provider_count"], -(h["stars"] or 0), h["name"]))
    elif sort in {"stars", "stars_desc"}:
        matching.sort(key=lambda h: (-(h["stars"] or 0), -h["provider_count"], price(h), h["name"]))
    elif sort in {"provider_count", "providers", "providers_desc"}:
        matching.sort(key=lambda h: (-h["provider_count"], -(h["stars"] or 0), price(h), h["name"]))
    else:
        matching.sort(key=lambda h: (-h["relevance_score"], -h["provider_count"], -(h["stars"] or 0), price(h), h["name"]))
        if intent.destination_theme:
            first_by_city: dict[str, dict[str, Any]] = {}
            remaining = []
            for hotel in matching:
                city_id = hotel["city_id"]
                if city_id in first_by_city:
                    remaining.append(hotel)
                else:
                    first_by_city[city_id] = hotel
            matching = [*first_by_city.values(), *remaining]
    return {
        "query": query,
        "parsed_intent": intent.as_dict(),
        "sort": sort,
        "total": len(matching),
        "offset": offset,
        "limit": limit,
        "hotels": matching[offset:offset + limit],
        "price_disclaimer": "قیمت‌ها از صفحات عمومی ثبت شده‌اند و قیمت قطعی یا موجودی قابل رزرو نیستند؛ نوع اتاق، تاریخ و شرایط را در منبع بررسی کنید.",
        "location_disclaimer": "جست‌وجوی ساحلی بر پایهٔ شهر است؛ فاصلهٔ هتل تا ساحل بررسی نشده است." if intent.destination_theme else None,
    }


def catalog_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    offers = catalog.get("offers", []) if isinstance(catalog, dict) else []
    valid = [offer for offer in offers if isinstance(offer, dict)]
    grouped = _group_offers(valid)
    cities = Counter(str(offer.get("city")) for offer in valid if offer.get("city"))
    providers = Counter(str(offer.get("provider")) for offer in valid if offer.get("provider"))
    latest = max((str(offer.get("observed_at")) for offer in valid if offer.get("observed_at")), default=None)
    return {
        "generated_at": catalog.get("generated_at") if isinstance(catalog, dict) else None,
        "last_updated": catalog.get("generated_at") if isinstance(catalog, dict) else None,
        "last_observed_at": latest,
        "hotel_count": len(grouped),
        "offer_count": len(valid),
        "priced_offer_count": sum(normalized_nightly_price(offer) is not None for offer in valid),
        "cities": [{"id": key, "city": key, "label": CITY_LABELS.get(key, key), "name": CITY_LABELS.get(key, key), "offer_count": count}
                   for key, count in sorted(cities.items())],
        "provider_count": len(providers),
        "providers": [{"id": key, "provider": key, "name": next(
            (str(offer.get("provider_name")) for offer in valid if offer.get("provider") == key and offer.get("provider_name")), key
        ), "offer_count": count} for key, count in sorted(providers.items())],
    }
