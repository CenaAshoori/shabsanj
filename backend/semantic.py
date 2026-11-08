"""Optional, bounded OpenRouter function-call parser for Persian travel queries.

The model only proposes search filters. This module never executes a model
requested operation; the caller applies validated filters to local catalogs.
When the service is unavailable or its response is invalid, callers can use
the existing deterministic search parser.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from typing import Any, Literal

import httpx

from .config import openrouter_key
from .search import CITY_LABELS, REGION_CITY_IDS, THEME_CITY_IDS, normalize_text


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
MAX_QUERY_LENGTH = 500
MAX_RESPONSE_BYTES = 64_000
CACHE_TTL_SECONDS = 20 * 60
CACHE_MAX_ENTRIES = 128

_REGIONS = frozenset(REGION_CITY_IDS)
_CITIES = frozenset(CITY_LABELS) - _REGIONS
_LOCATIONS = _CITIES | _REGIONS
_THEMES = frozenset(THEME_CITY_IDS)
_HOTEL_SORTS = frozenset({"best", "price", "stars", "provider_count"})
_TOUR_SORTS = frozenset({"best", "price", "departure", "hotel_stars"})
_TRANSPORTS = frozenset({"flight", "train", "bus"})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE = re.compile(r"(?<!\d)(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})(?!\d)")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_SUCCESS_CACHE: OrderedDict[tuple[str, str], tuple[float, dict[str, Any]]] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _field(description: str, kind: str = "string", **extra: Any) -> dict[str, Any]:
    return {"type": kind, "description": description, **extra}


_HOTEL_PROPERTIES = {
    "city_id": _field("One explicit destination city or region ID, such as kish, gilan, mazandaran, north.", enum=sorted(_LOCATIONS)),
    "city_ids": _field("Concrete destination city IDs only when the user explicitly requests a union of cities.", "array", items={"type": "string", "enum": sorted(_CITIES)}, minItems=1, maxItems=10),
    "destination_theme": _field("A destination theme only when the user requests coast or sea travel.", enum=sorted(_THEMES)),
    "destination_alternatives": _field("Explicit 'A or B' destination IDs, including supported regions.", "array", items={"type": "string", "enum": sorted(_LOCATIONS)}, minItems=2, maxItems=10),
    "hotel_name_terms": _field("Only meaningful words in a requested hotel name; preserve a number such as ۲ in الماس ۲.", "array", items={"type": "string", "maxLength": 40}, minItems=1, maxItems=8),
    "hotel_name": _field("Requested hotel name if the user named a property, never a generic preference.", maxLength=100),
    "stars": _field("Exact hotel star count when explicitly requested.", "integer", minimum=1, maximum=5),
    "min_stars": _field("Minimum hotel star count when explicitly requested.", "integer", minimum=1, maximum=5),
    "max_price_toman": _field("Explicit maximum price in toman, never an inferred budget.", "integer", minimum=1000, maximum=1000000000000),
    "has_tours": _field("True only when the user asks for hotels with a linked tour; false only when explicitly requested.", "boolean"),
    "sort": _field("Requested ranking order.", enum=sorted(_HOTEL_SORTS)),
}

_TOUR_PROPERTIES = {
    "departure_city": _field("Explicit departure city or region ID.", enum=sorted(_LOCATIONS)),
    "destination_city": _field("One explicit destination city or region ID.", enum=sorted(_LOCATIONS)),
    "destination_city_ids": _field("Concrete destination city IDs only when the user explicitly requests a union of cities.", "array", items={"type": "string", "enum": sorted(_CITIES)}, minItems=1, maxItems=10),
    "destination_theme": _field("A coast or sea destination preference.", enum=sorted(_THEMES)),
    "destination_alternatives": _field("Explicit 'A or B' destination IDs, including supported regions.", "array", items={"type": "string", "enum": sorted(_LOCATIONS)}, minItems=2, maxItems=10),
    "hotel_name": _field("Hotel name requested by the user; omit for generic hotel requests.", maxLength=100),
    "hotel_id": _field("Exact technical hotel ID only if it literally occurs in the user's query.", maxLength=120),
    "service": _field("One requested included tour service, such as صبحانه; do not infer optional services.", maxLength=80),
    "transport": _field("Requested means of outbound travel.", enum=sorted(_TRANSPORTS)),
    "departure_date": _field("Exact departure date in Jalali YYYY/MM/DD only when numerically stated in query.", pattern=r"^1[34]\d{2}/\d{2}/\d{2}$"),
    "departure_from": _field("Earliest departure date in Jalali YYYY/MM/DD only when numerically stated in query.", pattern=r"^1[34]\d{2}/\d{2}/\d{2}$"),
    "hotel_checkin_date": _field("Exact hotel check-in date in Jalali YYYY/MM/DD only when numerically stated in query; this is not the departure date.", pattern=r"^1[34]\d{2}/\d{2}/\d{2}$"),
    "max_price_toman": _field("Explicit maximum package price per person in toman, never an inferred budget.", "integer", minimum=1000, maximum=1000000000000),
    "sort": _field("Requested ranking order.", enum=sorted(_TOUR_SORTS)),
}

_PROPERTIES = {"hotels": _HOTEL_PROPERTIES, "tours": _TOUR_PROPERTIES}
_FUNCTIONS = {"hotels": "plan_hotel_search", "tours": "plan_tour_search"}

_SYSTEM = """Extract search filters from a Persian or English travel query. Call the specified function once.
Use only supported IDs from the schema. Omit every field the user did not request or that cannot be determined confidently; never fill absent fields with null. A city region (gilan, mazandaran, north) differs from a concrete city; 'A یا B' is a union. Coast refers to a destination city theme, not a claim that a particular hotel is beachfront. For hotel searches, has_tours=true means the user asks for a hotel with an available linked tour, as in «هتل با تور»; do not treat «تور» in that phrase as a hotel-name word. Treat hotel star count as exact unless the user asks for 'at least'. Convert explicit budgets to integer toman. A tour's departure date and hotel check-in date differ; include a date only when the query gives a numeric Jalali YYYY/MM/DD date. Hotel-name words must keep meaningful digits. Service means an included service, not an optional add-on. Return no text outside the function call."""


class InvalidPlan(ValueError):
    """The model response is not a supported filter plan."""


def _tool(mode: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _FUNCTIONS[mode],
            "description": "Produce only grounded, supported search filters for the user's travel query.",
            "parameters": {"type": "object", "properties": _PROPERTIES[mode], "additionalProperties": False},
        },
    }


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidPlan("Duplicate key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise InvalidPlan("Non-finite JSON value")


def _text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidPlan("Expected text")
    value = unicodedata.normalize("NFKC", value).strip()
    if not value or len(value) > maximum or any(unicodedata.category(char) == "Cc" for char in value):
        raise InvalidPlan("Invalid text")
    return value


def _enum(value: Any, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidPlan("Unsupported identifier")
    return value


def _ids(value: Any, allowed: frozenset[str], *, minimum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= 10:
        raise InvalidPlan("Invalid location list")
    ids = [_enum(item, allowed) for item in value]
    if len(ids) != len(set(ids)):
        raise InvalidPlan("Duplicate location")
    return ids


def _price(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 1_000_000_000_000:
        raise InvalidPlan("Invalid price ceiling")
    return value


def _date_text(year: int, month: int, day: int) -> str:
    if not 1300 <= year <= 1499 or not 1 <= month <= 12 or not 1 <= day <= (31 if month <= 6 else 30):
        raise InvalidPlan("Invalid Jalali date")
    return f"{year:04d}/{month:02d}/{day:02d}"


def _explicit_dates(query: str) -> set[str]:
    return {_date_text(*map(int, match.groups())) for match in _DATE.finditer(query.translate(_DIGITS))}


def _validated_plan(raw: Any, mode: Literal["hotels", "tours"], query: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or any(key not in _PROPERTIES[mode] for key in raw):
        raise InvalidPlan("Unexpected plan fields")
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key in {"city_id", "departure_city", "destination_city"}:
            result[key] = _enum(value, _LOCATIONS)
        elif key in {"city_ids", "destination_city_ids"}:
            result[key] = _ids(value, _CITIES, minimum=1)
        elif key == "destination_alternatives":
            result[key] = _ids(value, _LOCATIONS, minimum=2)
        elif key == "destination_theme":
            result[key] = _enum(value, _THEMES)
        elif key == "transport":
            result[key] = _enum(value, _TRANSPORTS)
        elif key == "sort":
            result[key] = _enum(value, _HOTEL_SORTS if mode == "hotels" else _TOUR_SORTS)
        elif key == "has_tours":
            if not isinstance(value, bool):
                raise InvalidPlan("Invalid linked-tour filter")
            result[key] = value
        elif key in {"stars", "min_stars"}:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise InvalidPlan("Invalid star count")
            result[key] = value
        elif key == "max_price_toman":
            result[key] = _price(value)
        elif key == "hotel_name_terms":
            if not isinstance(value, list) or not 1 <= len(value) <= 8:
                raise InvalidPlan("Invalid hotel words")
            words: list[str] = []
            for item in value:
                words.extend(normalize_text(_text(item, 40)).split())
            if not words or len(words) > 8 or any(len(word) > 40 for word in words):
                raise InvalidPlan("Invalid hotel words")
            result[key] = list(dict.fromkeys(words))
        elif key in {"hotel_name", "service"}:
            result[key] = _text(value, 100 if key == "hotel_name" else 80)
        elif key == "hotel_id":
            hotel_id = _text(value, 120)
            if hotel_id not in query:
                raise InvalidPlan("Hotel ID was not supplied by user")
            result[key] = hotel_id
        elif key in {"departure_date", "departure_from", "hotel_checkin_date"}:
            date_value = _text(value, 10)
            match = _DATE.fullmatch(date_value.translate(_DIGITS))
            if match is None:
                raise InvalidPlan("Invalid date format")
            date_value = _date_text(*map(int, match.groups()))
            if date_value not in _explicit_dates(query):
                raise InvalidPlan("Date was not supplied by user")
            result[key] = date_value
        else:
            raise InvalidPlan("Unsupported field")
    if "stars" in result and "min_stars" in result:
        raise InvalidPlan("Conflicting star filters")
    return result


def _extract_arguments(payload: Any, mode: Literal["hotels", "tours"]) -> Any:
    if not isinstance(payload, dict):
        raise InvalidPlan("Invalid API response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise InvalidPlan("Invalid choices")
    if choices[0].get("finish_reason") == "length":
        raise InvalidPlan("Truncated function call")
    message = choices[0].get("message")
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise InvalidPlan("Missing or multiple function calls")
    call = calls[0]
    function = call.get("function")
    if call.get("type") != "function" or not isinstance(function, dict) or function.get("name") != _FUNCTIONS[mode]:
        raise InvalidPlan("Unexpected function")
    arguments = function.get("arguments")
    if not isinstance(arguments, str) or len(arguments) > 12_000:
        raise InvalidPlan("Invalid function arguments")
    return json.loads(arguments, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)


def _cached(mode: str, query: str) -> dict[str, Any] | None:
    cache_key = (mode, normalize_text(query))
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _SUCCESS_CACHE.get(cache_key)
        if item is None:
            return None
        expires_at, plan = item
        if expires_at <= now:
            del _SUCCESS_CACHE[cache_key]
            return None
        _SUCCESS_CACHE.move_to_end(cache_key)
        # Isolate callers from accidental mutation of nested list filters.
        return {key: value.copy() if isinstance(value, list) else value for key, value in plan.items()}


def _remember(mode: str, query: str, plan: dict[str, Any]) -> None:
    cache_key = (mode, normalize_text(query))
    with _CACHE_LOCK:
        _SUCCESS_CACHE[cache_key] = (
            time.monotonic() + CACHE_TTL_SECONDS,
            {key: value.copy() if isinstance(value, list) else value for key, value in plan.items()},
        )
        _SUCCESS_CACHE.move_to_end(cache_key)
        while len(_SUCCESS_CACHE) > CACHE_MAX_ENTRIES:
            _SUCCESS_CACHE.popitem(last=False)


def plan_query(query: str, mode: Literal["hotels", "tours"]) -> tuple[dict[str, Any] | None, str]:
    """Return validated local search filters or a deterministic-parser fallback.

    The sole outbound request sends the query to OpenRouter when a server key is
    configured. The key and query are neither logged nor saved by this module.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH or mode not in _PROPERTIES:
        return None, "fallback"
    key = openrouter_key()
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
    if not key or not _MODEL.fullmatch(model):
        return None, "fallback"
    cached = _cached(mode, query)
    if cached is not None:
        return cached, "openrouter"
    request = {
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": query}],
        "tools": [_tool(mode)],
        "tool_choice": {"type": "function", "function": {"name": _FUNCTIONS[mode]}},
        "parallel_tool_calls": False,
        "temperature": 0,
        "max_tokens": 500,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False) as client:
            response = client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=request,
            )
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise InvalidPlan("Oversize API response")
            raw = _extract_arguments(response.json(), mode)
            plan = _validated_plan(raw, mode, query)
            _remember(mode, query, plan)
            return plan, "openrouter"
    except Exception:
        # No provider error body, key, or query is emitted to application logs.
        return None, "fallback"
