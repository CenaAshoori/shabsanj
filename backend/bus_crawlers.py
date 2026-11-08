"""Read bounded public intercity bus pages without claiming live checkout prices.

Redbilit publishes dated, per-seat service cards in its route HTML. Safar724's
public route page hydrates dated cards from its no-auth service host; that same
read-only GET is used here after confirming its separate robots policy. No
seat selection or checkout is requested.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from time import monotonic, sleep
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx
import jdatetime
from bs4 import BeautifulSoup


USER_AGENT = "ShabSanjResearch/0.1 (+public bus route comparison)"
ROUTES = (
    ("tehran", "rasht"),
    ("rasht", "tehran"),
    ("tehran", "mashhad"),
    ("mashhad", "tehran"),
    ("tehran", "lahijan"),
    ("tehran", "sari"),
    ("tehran", "isfahan"), ("isfahan", "tehran"),
    ("tehran", "shiraz"), ("shiraz", "tehran"),
    ("tehran", "tabriz"), ("tabriz", "tehran"),
    ("tehran", "bandar_anzali"), ("bandar_anzali", "tehran"),
    ("tehran", "astara"), ("astara", "tehran"),
    ("tehran", "ramsar"), ("ramsar", "mashhad"),
    ("tehran", "chalus"), ("chalus", "tehran"),
    ("tehran", "nowshahr"), ("sari", "tehran"),
    ("shiraz", "isfahan"), ("isfahan", "shiraz"),
    ("isfahan", "mashhad"),
    ("shiraz", "yazd"), ("yazd", "shiraz"),
    ("yazd", "isfahan"), ("yazd", "mashhad"),
    ("rasht", "tabriz"), ("tabriz", "rasht"),
    ("shiraz", "mashhad"),
    ("tabriz", "isfahan"), ("isfahan", "tabriz"),
    ("tehran", "qaemshahr"), ("tehran", "babolsar"),
    ("ahvaz", "tehran"),
    ("bandar_abbas", "shiraz"),
    ("tehran", "kerman"), ("kerman", "tehran"),
    ("tehran", "hamadan"), ("hamadan", "tehran"),
    ("tehran", "ardabil"), ("ardabil", "tehran"),
    ("ahvaz", "shiraz"), ("shiraz", "ahvaz"),
    ("isfahan", "ahvaz"),
    ("babolsar", "mashhad"), ("bandar_abbas", "yazd"),
    ("tehran", "ahvaz"), ("tehran", "bandar_abbas"),
    ("bandar_abbas", "tehran"),
)
CITY_FA = {
    "tehran": "تهران",
    "rasht": "رشت",
    "mashhad": "مشهد",
    "lahijan": "لاهیجان",
    "sari": "ساری",
    "isfahan": "اصفهان", "shiraz": "شیراز", "tabriz": "تبریز",
    "yazd": "یزد", "bandar_anzali": "بندرانزلی", "astara": "آستارا",
    "ramsar": "رامسر", "chalus": "چالوس", "nowshahr": "نوشهر",
    "qaemshahr": "قائم شهر", "babolsar": "بابلسر", "ahvaz": "اهواز",
    "bandar_abbas": "بندرعباس", "kerman": "کرمان",
    "hamadan": "همدان", "ardabil": "اردبیل",
}
CITY_SLUGS = {
    "isfahan": "esfahan", "bandar_anzali": "bandareanzali",
    "bandar_abbas": "bandarabbas",
}
# Each route below appears on Safar724's public home page. The page HTML gives
# exact public city codes; its hydrated cards come from service.safar724.com.
SAFAR724_ROUTES = (
    ("tehran", "rasht"), ("rasht", "tehran"),
    ("tehran", "mashhad"), ("mashhad", "tehran"),
    ("tehran", "isfahan"), ("isfahan", "tehran"),
    ("tehran", "shiraz"), ("shiraz", "tehran"),
    ("tehran", "tabriz"), ("tabriz", "tehran"),
    ("shiraz", "mashhad"), ("yazd", "mashhad"),
)
SAFAR724_API_HOST = "service.safar724.com"
SAFAR724_CORE_ROUTES = frozenset(SAFAR724_ROUTES[:10])
SAFAR724_CORE_DAY_COUNT = 8  # Today plus seven later days, matching Redbilit.
SAFAR724_OTHER_DAY_COUNT = 2
# Stay below Redbilit's observed rate limit: 52 base routes plus at most 25
# calendar-linked dated pages (77 route requests, 78 including robots.txt).
# Four high-demand route directions get five later dates; five other
# routes get tomorrow. All others retain a route link for date selection.
FUTURE_DATE_ROUTE_DAYS = {
    ("tehran", "rasht"): 5, ("rasht", "tehran"): 5,
    ("tehran", "mashhad"): 5, ("mashhad", "tehran"): 5,
    ("tehran", "isfahan"): 1,
    ("tehran", "shiraz"): 1,
    ("tehran", "tabriz"): 1,
    ("tehran", "bandar_anzali"): 1,
    ("tehran", "qaemshahr"): 1,
}
PERSIAN_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SAFAR_ROUTE_META = re.compile(
    r'\\"origin\\":\{\\"engName\\":\\"([^\\"]+)\\",\\"faName\\":\\"([^\\"]+)\\",\\"code\\":\\"(\d+)\\"\},'
    r'\\"destination\\":\{\\"engName\\":\\"([^\\"]+)\\",\\"faName\\":\\"([^\\"]+)\\",\\"code\\":\\"(\d+)\\"\}'
)


def _number(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    return int(text) if text.isdecimal() else None


def _jalali_date(label: str) -> str:
    normalized = label.translate(_DIGITS)
    match = re.fullmatch(r"\s*(\d{1,2})\s+(\S+)\s+(\d{4})\s*", normalized)
    if not match or match.group(2) not in PERSIAN_MONTHS:
        raise ValueError("Redbilit route page has no verifiable selected date")
    day, month_name, year = match.groups()
    return jdatetime.date(int(year), PERSIAN_MONTHS.index(month_name) + 1, int(day)).togregorian().isoformat()


def _text(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _route_url(provider: str, origin: str, destination: str) -> str:
    return f"https://{provider}.com/bus/{CITY_SLUGS.get(origin, origin)}-{CITY_SLUGS.get(destination, destination)}"


def parse_redbilit_route(
    html: str, origin: str, destination: str, listing_url: str, observed_at: str,
) -> list[dict]:
    """Keep only available bus cards with an exact route and dated seat fare."""
    soup = BeautifulSoup(html, "html.parser")
    heading = _text(soup.select_one("h1"))
    if f"{CITY_FA[origin]} به {CITY_FA[destination]}" not in heading:
        raise ValueError("Redbilit heading does not confirm requested route")
    selected = soup.select_one(".rb-datepicker__value[data-dp-label]")
    departure_date = _jalali_date(_text(selected))
    requested_dates = parse_qs(urlsplit(listing_url).query).get("date", [])
    if requested_dates:
        if len(requested_dates) != 1 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", requested_dates[0]):
            raise ValueError("Redbilit dated route URL has an invalid date")
        year, month, day = map(int, requested_dates[0].split("/"))
        if jdatetime.date(year, month, day).togregorian().isoformat() != departure_date:
            raise ValueError("Redbilit selected date differs from requested date")
    cards = soup.select("article.rb-bus-card")
    if not cards and "سرویسی پیدا نشد" not in _text(soup):
        raise ValueError("Redbilit cards absent without an explicit empty-result message")
    offers: list[dict] = []
    for card in cards:
        from_city = _text(card.select_one(".rb-bus-card__stop.is-from em"))
        to_city = _text(card.select_one(".rb-bus-card__stop.is-to em"))
        if (from_city, to_city) != (CITY_FA[origin], CITY_FA[destination]):
            continue
        seats_text = _text(card.select_one(".rb-bus-card__seats"))
        seats_match = re.search(r"([\d۰-۹٠-٩]+)\s*صندلی خالی", seats_text)
        seats = _number(seats_match.group(1)) if seats_match else None
        if not seats or seats < 1:
            continue
        price = _number(_text(card.select_one(".rb-bus-card__price strong")))
        time_text = _text(card.select_one(".rb-bus-card__when b"))
        departure_time = time_text.translate(_DIGITS)
        card_date = _text(card.select_one(".rb-bus-card__when span")).translate(_DIGITS)
        selected_parts = _text(selected).translate(_DIGITS).split()
        if len(selected_parts) < 2 or f"{selected_parts[0]} {selected_parts[1]}" not in card_date:
            continue
        link = card.select_one('a.rb-bus-card__cta[href]')
        source_url = urljoin(listing_url, link["href"]) if link else ""
        source_parts = urlsplit(source_url)
        service_match = re.fullmatch(r"/bus/service/(\d+)", source_parts.path)
        if (not price or price <= 0 or not re.fullmatch(r"\d{2}:\d{2}", departure_time)
                or source_parts.netloc != "redbilit.com" or not service_match):
            continue
        operator = _text(card.select_one(".rb-bus-card__company-text strong"))
        service_class = _text(card.select_one(".rb-bus-card__company-text small"))
        departure_terminal = _text(card.select_one(".rb-bus-card__stop.is-from small"))
        arrival_terminal = _text(card.select_one(".rb-bus-card__stop.is-to small"))
        offer = {
            "offer_id": f"redbilit:{service_match.group(1)}",
            "mode": "bus",
            "origin": origin,
            "destination": destination,
            "provider": "redbilit",
            "provider_name": "رد بلیط",
            "price_toman": price,
            "source_url": source_url,
            "listing_url": listing_url,
            "observed_at": observed_at,
            "departure_date": departure_date,
            "departure_time": departure_time,
            "operator": operator,
            "service_class": service_class,
            "seats_remaining": seats,
            "price_note": (
                "قیمت هر صندلی برای این سرویس و تاریخ در فهرست عمومی رد بلیط؛ "
                "ظرفیت و مبلغ قابل خرید را پیش از رزرو در صفحه فروشنده دوباره بررسی کنید."
            ),
        }
        if departure_terminal and departure_terminal != from_city:
            offer["departure_terminal"] = departure_terminal
        if arrival_terminal and arrival_terminal != to_city:
            offer["arrival_terminal"] = arrival_terminal
        offers.append(offer)
    return offers


def parse_safar724_route(
    html: str, origin: str, destination: str, listing_url: str, observed_at: str,
) -> dict:
    """Expose a real route link; SEO price ranges are not bookable fares."""
    soup = BeautifulSoup(html, "html.parser")
    heading = re.sub(r"\s+", " ", _text(soup.select_one("h1")))
    expected = rf"\b{re.escape(CITY_FA[origin])}\s+(?:به\s+)?{re.escape(CITY_FA[destination])}\b"
    if "بلیط اتوبوس" not in heading or not re.search(expected, heading):
        raise ValueError("Safar724 heading does not confirm requested route")
    range_text = None
    for label in soup.select("p"):
        label_text = _text(label)
        if ("قیمت بلیط اتوبوس" in label_text and CITY_FA[origin] in label_text
                and CITY_FA[destination] in label_text):
            sibling = label.find_next_sibling("p")
            candidate = _text(sibling)
            if re.fullmatch(r"از\s*[\d۰-۹٠-٩,٬]+\s*تا\s*[\d۰-۹٠-٩,٬]+\s*ریال", candidate):
                range_text = candidate
                break
    note = "صفحه عمومی سفر۷۲۴ این مسیر را نشان می‌دهد؛ سرویس، تاریخ، ظرفیت و نرخ قابل رزرو در HTML عمومی نمایش داده نمی‌شود."
    if range_text:
        note += f" بازه راهنمای منتشرشده: {range_text}؛ این بازه قیمت یک بلیت مشخص نیست."
    return {
        "offer_id": f"safar724:route:{origin}:{destination}",
        "mode": "bus",
        "origin": origin,
        "destination": destination,
        "provider": "safar724",
        "provider_name": "سفر۷۲۴",
        "price_toman": None,
        "source_url": listing_url,
        "observed_at": observed_at,
        "departure_date": None,
        "price_note": note,
    }


def _safar724_route_codes(html: str, origin: str, destination: str) -> tuple[str, str]:
    """Read the exact city codes serialized into the public route page."""
    expected = (
        CITY_SLUGS.get(origin, origin), CITY_FA[origin],
        CITY_SLUGS.get(destination, destination), CITY_FA[destination],
    )
    matching = {
        (origin_code, destination_code)
        for from_slug, from_fa, origin_code, to_slug, to_fa, destination_code
        in _SAFAR_ROUTE_META.findall(html)
        if (from_slug, from_fa, to_slug, to_fa) == expected
    }
    if len(matching) != 1:
        raise ValueError("Safar724 page has no unique verified city-code pair")
    return matching.pop()


def _safar724_dates(count: int) -> list[tuple[str, str]]:
    """Dates visible in the site calendar, using Tehran's local day."""
    today = datetime.now(ZoneInfo("Asia/Tehran")).date()
    dates = []
    for offset in range(count):
        gregorian = today + timedelta(days=offset)
        jalali = jdatetime.date.fromgregorian(date=gregorian)
        dates.append((f"{jalali.year:04d}-{jalali.month:02d}-{jalali.day:02d}", gregorian.isoformat()))
    return dates


def _safar724_fare_url(jalali_date: str, origin_code: str, destination_code: str) -> str:
    query = urlencode({
        "date": jalali_date, "origin": origin_code,
        "destination": destination_code, "vehicleType": "Bus",
    })
    return f"https://{SAFAR724_API_HOST}/cs/api/bus/route?{query}"


def parse_safar724_fares(
    payload: dict, origin: str, destination: str, origin_code: str,
    destination_code: str, jalali_date: str, departure_date: str,
    page_url: str, api_url: str, observed_at: str,
) -> list[dict]:
    """Keep exact-route available bus seats with explicit per-seat rial fares."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Safar724 fare response has no service list")
    expected = (
        jalali_date, origin_code, destination_code,
        CITY_SLUGS.get(origin, origin), CITY_SLUGS.get(destination, destination),
        CITY_FA[origin], CITY_FA[destination],
    )
    actual = tuple(payload.get(key) for key in (
        "date", "originCode", "destinationCode", "originEnglishName",
        "destinationEnglishName", "originPersianName", "destinationPersianName",
    ))
    if actual != expected:
        raise ValueError("Safar724 fare response does not confirm requested route and date")
    offers: list[dict] = []
    seen_ids: set[int] = set()
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        service_id = item.get("id")
        rial = item.get("price")
        seats = item.get("availableSeatCount")
        departure_time = item.get("departureTime")
        if (type(service_id) is not int or service_id <= 0 or service_id in seen_ids
                or type(rial) is not int or rial <= 0 or rial % 10
                or type(seats) is not int or seats <= 0
                or item.get("status") != "Available" or item.get("vehicleType") != "Bus"
                or item.get("departureDate") != jalali_date.replace("-", "/")
                or item.get("destinationCode") != destination_code
                or item.get("originCode") not in (None, origin_code)
                or not isinstance(departure_time, str)
                or not re.fullmatch(r"\d{2}:\d{2}", departure_time)):
            continue
        seen_ids.add(service_id)
        offer = {
            "offer_id": f"safar724:{service_id}",
            "mode": "bus", "origin": origin, "destination": destination,
            "provider": "safar724", "provider_name": "سفر۷۲۴",
            "price_toman": rial // 10,
            "source_url": page_url, "listing_url": api_url,
            "observed_at": observed_at,
            "departure_date": departure_date, "departure_time": departure_time,
            "seats_remaining": seats,
            "price_note": (
                "قیمت هر صندلی این سرویس در فهرست عمومی سفر۷۲۴ به ریال منتشر و به تومان تبدیل شده است؛ "
                "ظرفیت و مبلغ نهایی را پیش از رزرو در صفحه فروشنده دوباره بررسی کنید."
            ),
        }
        if isinstance(item.get("companyPersianName"), str) and item["companyPersianName"].strip():
            offer["operator"] = item["companyPersianName"].strip()
        if isinstance(item.get("busType"), str) and item["busType"].strip():
            offer["service_class"] = item["busType"].strip()
        for source_key, target_key in (
            ("originTerminalPersianName", "departure_terminal"),
            ("destinationTerminalPersianName", "arrival_terminal"),
        ):
            value = item.get(source_key)
            if isinstance(value, str) and value.strip():
                offer[target_key] = value.strip()
        offers.append(offer)
    return offers


def _redbilit_route_link(origin: str, destination: str, listing_url: str, observed_at: str) -> dict:
    return {
        "offer_id": f"redbilit:route:{origin}:{destination}",
        "mode": "bus",
        "origin": origin,
        "destination": destination,
        "provider": "redbilit",
        "provider_name": "رد بلیط",
        "price_toman": None,
        "source_url": listing_url,
        "observed_at": observed_at,
        "departure_date": None,
        "price_note": "صفحه مسیر رد بلیط برای دیدن تاریخ‌ها و سرویس‌های دیگر؛ این لینک خودش نرخ مشخصی ندارد.",
    }


def _future_redbilit_date_links(html: str, listing_url: str, limit: int) -> list[str]:
    """Use at most ten later dates linked by the public route calendar."""
    base = urlsplit(listing_url)
    soup = BeautifulSoup(html, "html.parser")
    selected = soup.select_one(".rb-datepicker__value[data-dp-label]")
    selected_day = date.fromisoformat(_jalali_date(_text(selected)))
    links: list[str] = []
    for link in soup.select("a.rb-dates__day[href]"):
        candidate = urljoin(listing_url, link["href"])
        parts = urlsplit(candidate)
        raw_dates = parse_qs(parts.query).get("date", [])
        if (parts.scheme != "https" or parts.netloc != base.netloc
                or parts.path != base.path or len(raw_dates) != 1
                or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", raw_dates[0])):
            continue
        year, month, day = map(int, raw_dates[0].split("/"))
        try:
            departure_day = jdatetime.date(year, month, day).togregorian()
        except ValueError:
            continue
        if departure_day > selected_day and candidate not in links:
            links.append(candidate)
        if len(links) >= min(limit, 10):
            break
    return links


def _robots_parser(client: httpx.Client, host: str) -> RobotFileParser:
    robots_url = f"https://{host}/robots.txt"
    response = client.get(robots_url)
    parser = RobotFileParser()
    parser.set_url(robots_url)
    if response.status_code == 404:
        # RFC 9309 section 2.3.1.3: an unavailable robots file permits access.
        parser.allow_all = True
        return parser
    response.raise_for_status()
    parser.parse(response.text.splitlines())
    return parser


class _HostStopped(ValueError):
    """A provider returned 429; later checks must preserve prior observations."""


class _HostRequestGate:
    """Serialize and pace one host; never launch another GET after its 429."""

    def __init__(self, host: str, min_gap_seconds: float = 1.0) -> None:
        self.host = host
        self.min_gap_seconds = min_gap_seconds
        self._lock = Lock()
        self._next_at = 0.0
        self._stopped = False

    def get(self, client: httpx.Client, url: str) -> httpx.Response:
        with self._lock:
            if self._stopped:
                raise _HostStopped(f"{self.host} returned HTTP 429; remaining checks skipped")
            delay = self._next_at - monotonic()
            if delay > 0:
                sleep(delay)
            response = client.get(url)
            self._next_at = monotonic() + self.min_gap_seconds
            if response.status_code == 429:
                self._stopped = True
            return response


def _fetch_public_route(
    client: httpx.Client, robots: RobotFileParser | None,
    robots_error: str | None, host: str, url: str,
    gate: _HostRequestGate | None = None,
) -> httpx.Response:
    if robots is None:
        raise ValueError(robots_error or "robots.txt unavailable")
    if not robots.can_fetch(USER_AGENT, url):
        raise ValueError("robots.txt disallows route page")
    response = gate.get(client, url) if gate else client.get(url)
    response.raise_for_status()
    final = urlsplit(str(response.url))
    if final.scheme != "https" or final.netloc != host:
        raise ValueError("Unexpected route-page redirect host")
    return response


def _crawl_route(
    client: httpx.Client, robots: RobotFileParser | None,
    robots_error: str | None, provider: str, host: str,
    origin: str, destination: str,
    api_robots: RobotFileParser | None = None,
    api_robots_error: str | None = None,
    safar_dates: list[tuple[str, str]] | None = None,
    redbilit_gate: _HostRequestGate | None = None,
) -> tuple[list[dict], list[dict]]:
    url = _route_url(provider, origin, destination)
    offers: list[dict] = []
    statuses: list[dict] = []
    status = {
        "provider": provider, "mode": "bus", "origin": origin,
        "destination": destination, "url": url,
    }
    try:
        response = _fetch_public_route(
            client, robots, robots_error, host, url,
            redbilit_gate if provider == "redbilit" else None,
        )
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if provider == "redbilit":
            dated = parse_redbilit_route(response.text, origin, destination, url, observed_at)
            offers.extend(dated)
            offers.append(_redbilit_route_link(origin, destination, url, observed_at))
            status["offer_count"] = len(dated) + 1
        else:
            offers.append(parse_safar724_route(response.text, origin, destination, url, observed_at))
            status["offer_count"] = 1
        status["status"] = "ok"
        status["observed_at"] = observed_at
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        status["status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
    statuses.append(status)
    if status["status"] != "ok":
        return offers, statuses
    if provider == "safar724":
        try:
            origin_code, destination_code = _safar724_route_codes(
                response.text, origin, destination,
            )
        except ValueError as exc:
            statuses.append({
                "provider": provider, "mode": "bus", "origin": origin,
                "destination": destination, "url": url,
                "status": "error", "error": f"{type(exc).__name__}: {exc}"[:200],
            })
            return offers, statuses
        day_count = (
            SAFAR724_CORE_DAY_COUNT if (origin, destination) in SAFAR724_CORE_ROUTES
            else SAFAR724_OTHER_DAY_COUNT
        )
        for jalali_date, departure_date in (safar_dates or _safar724_dates(day_count))[:day_count]:
            api_url = _safar724_fare_url(jalali_date, origin_code, destination_code)
            dated_page_url = f"{url}?date={jalali_date}"
            api_status = {
                "provider": provider, "mode": "bus", "origin": origin,
                "destination": destination, "url": api_url,
            }
            rate_limited = False
            try:
                api_response = _fetch_public_route(
                    client, api_robots, api_robots_error, SAFAR724_API_HOST, api_url,
                )
                api_observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                dated = parse_safar724_fares(
                    api_response.json(), origin, destination, origin_code,
                    destination_code, jalali_date, departure_date,
                    dated_page_url, api_url, api_observed_at,
                )
                offers.extend(dated)
                api_status.update({
                    "status": "ok", "offer_count": len(dated),
                    "observed_at": api_observed_at,
                })
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                api_status["status"] = "error"
                api_status["error"] = f"{type(exc).__name__}: {exc}"[:200]
                rate_limited = (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code == 429
                )
            statuses.append(api_status)
            if api_robots is None or rate_limited:
                break
        return offers, statuses

    future_limit = FUTURE_DATE_ROUTE_DAYS.get((origin, destination), 0)
    for future_url in _future_redbilit_date_links(response.text, url, future_limit) if future_limit else ():
        future_status = {
            "provider": provider, "mode": "bus", "origin": origin,
            "destination": destination, "url": future_url,
        }
        try:
            future_response = _fetch_public_route(
                client, robots, robots_error, host, future_url, redbilit_gate,
            )
            future_observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            future_offers = parse_redbilit_route(
                future_response.text, origin, destination, future_url, future_observed_at,
            )
            offers.extend(future_offers)
            future_status.update({
                "status": "ok", "offer_count": len(future_offers),
                "observed_at": future_observed_at,
            })
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            future_status["status"] = "error"
            future_status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        statuses.append(future_status)
    return offers, statuses


def crawl_buses() -> dict[str, list[dict]]:
    """Read verified public route pages with four requests in flight at most."""
    offers: list[dict] = []
    source_status: list[dict] = []
    sources = (
        ("redbilit", "redbilit.com", ROUTES),
        ("safar724", "safar724.com", SAFAR724_ROUTES),
    )
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
    ) as client:
        safar_dates = _safar724_dates(SAFAR724_CORE_DAY_COUNT)
        redbilit_gate = _HostRequestGate("redbilit.com")
        for provider, host, routes in sources:
            try:
                robots = _robots_parser(client, host)
                robots_error = None
            except (httpx.HTTPError, ValueError) as exc:
                robots = None
                robots_error = f"robots.txt unavailable: {type(exc).__name__}: {exc}"[:200]
            api_robots = None
            api_robots_error = None
            if provider == "safar724":
                try:
                    api_robots = _robots_parser(client, SAFAR724_API_HOST)
                except (httpx.HTTPError, ValueError) as exc:
                    api_robots_error = f"robots.txt unavailable: {type(exc).__name__}: {exc}"[:200]
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = executor.map(
                    lambda pair: _crawl_route(
                        client, robots, robots_error, provider, host, pair[0], pair[1],
                        api_robots, api_robots_error, safar_dates, redbilit_gate,
                    ),
                    routes,
                )
                for route_offers, route_statuses in results:
                    offers.extend(route_offers)
                    source_status.extend(route_statuses)
    return {"offers": offers, "source_status": source_status}
