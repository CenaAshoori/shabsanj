"""Dated first-party Fadak rail fares from public route-page SSR HTML.

Only the fixed routes below are fetched after a robots.txt check. Fares come
from the page's embedded Next.js state and are accepted only when the matching
visible ticket card repeats the date, departure time, and per-person price.
No search, account, or private API endpoint is called.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup


PROVIDER = "fadak"
PROVIDER_NAME = "قطارهای فدک"
USER_AGENT = "ShabSanjResearch/0.1 (+public dated rail fare comparison)"
HOST = "www.fadaktrains.com"
CITY_FA = {
    "tehran": "تهران", "mashhad": "مشهد", "rasht": "رشت",
    "sari": "ساری", "shiraz": "شیراز", "isfahan": "اصفهان",
    "tabriz": "تبریز", "yazd": "یزد",
}

# These routes appear in Fadak's public sitemap-train.xml. Availability can
# change: pages with no current cards produce no priced offer.
ROUTES = (
    ("tehran", "mashhad"), ("mashhad", "tehran"),
    ("tehran", "isfahan"), ("isfahan", "tehran"),
    ("mashhad", "isfahan"), ("isfahan", "mashhad"),
    ("tehran", "tabriz"), ("tabriz", "tehran"),
    ("mashhad", "tabriz"), ("tabriz", "mashhad"),
    ("tehran", "yazd"), ("yazd", "tehran"),
    ("mashhad", "yazd"), ("yazd", "mashhad"),
    ("tehran", "rasht"), ("rasht", "tehran"),
    ("mashhad", "rasht"), ("rasht", "mashhad"),
    ("tehran", "sari"), ("sari", "tehran"),
    ("mashhad", "sari"), ("sari", "mashhad"),
    ("tehran", "shiraz"), ("shiraz", "tehran"),
    ("mashhad", "shiraz"), ("shiraz", "mashhad"),
)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PERSON_PRICE = re.compile(r"هر\s*نفر\s*([\d۰-۹٠-٩,٬]+)\s*تومان")
_VISIBLE_SEATS = re.compile(r"ظرفیت\s*:\s*([\d۰-۹٠-٩,٬]+)(\+)?\s*صندلی")
_TIME = re.compile(r"^\d{2}:\d{2}$")


def route_url(origin: str, destination: str) -> str:
    return f"https://{HOST}/train/{destination}/{origin}-{destination}"


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def _number(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).translate(_DIGITS).replace(",", "").replace("٬", "")
    return int(normalized) if normalized.isdecimal() and int(normalized) > 0 else None


def _iso_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _visible_person_price(card: BeautifulSoup) -> int | None:
    match = _PERSON_PRICE.search(card.get_text(" ", strip=True))
    return _number(match.group(1)) if match else None


def parse_fadak(
    html: str, origin: str, destination: str, source_url: str,
    observed_at: str, *, today: date | None = None,
) -> list[dict]:
    """Parse one public SSR route page, rejecting inconsistent ticket rows."""
    if (origin, destination) not in ROUTES or source_url != route_url(origin, destination):
        raise ValueError("Unsupported Fadak route")
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    if heading is None or _plain(heading.get_text(" ", strip=True)) != f"بلیط قطار {CITY_FA[origin]} {CITY_FA[destination]}":
        raise ValueError("Fadak heading does not confirm this route")
    state_tag = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if state_tag is None or not state_tag.string:
        raise ValueError("Fadak SSR ticket state is missing")
    try:
        page = json.loads(state_tag.string)["props"]["pageProps"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Fadak SSR ticket state is invalid") from exc
    route = page.get("route")
    rows = page.get("available")
    calendar = page.get("calendarDates")
    if (not isinstance(route, dict) or route.get("originKey") != origin or
            route.get("destinationKey") != destination or
            not isinstance(rows, list) or not isinstance(calendar, list)):
        raise ValueError("Fadak SSR route or ticket list does not match")
    cards = soup.select("div.available-card")
    if len(cards) != len(rows):
        raise ValueError("Fadak visible cards do not match SSR ticket rows")
    date_labels = {
        item.get("goingDate"): _plain(item.get("label", ""))
        for item in calendar if isinstance(item, dict) and isinstance(item.get("goingDate"), str)
    }
    today = today or datetime.now(ZoneInfo("Asia/Tehran")).date()
    offers: list[dict] = []
    for row, card in zip(rows, cards):
        if not isinstance(row, dict) or row.get("origin") != CITY_FA[origin] or row.get("destination") != CITY_FA[destination]:
            continue
        departure_day = _iso_day(row.get("goingExitDate"))
        if departure_day is None or not today <= departure_day <= today + timedelta(days=60):
            continue
        departure_date = departure_day.isoformat()
        date_label = date_labels.get(departure_date)
        departure_time = row.get("originMoveTime")
        arrival_time = row.get("timeOfArrivalToDestination")
        card_text = _plain(card.get_text(" ", strip=True))
        if (not date_label or date_label not in card_text or
                not isinstance(departure_time, str) or not _TIME.fullmatch(departure_time) or
                departure_time not in card_text or
                not isinstance(arrival_time, str) or not _TIME.fullmatch(arrival_time) or
                arrival_time not in card_text):
            continue
        displayed_toman = _visible_person_price(card)
        raw_rial = _number(row.get("discountPrice")) or _number(row.get("price"))
        if displayed_toman is None or raw_rial is None or raw_rial % 10 or raw_rial // 10 != displayed_toman:
            continue
        offer = {
            "mode": "train",
            "origin": origin,
            "destination": destination,
            "provider": PROVIDER,
            "provider_name": PROVIDER_NAME,
            "price_toman": displayed_toman,
            "departure_date": departure_date,
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "source_url": source_url,
            "observed_at": observed_at,
            "availability": "unknown",
            "source_type": "dated_ticket_listing",
            "price_note": "نرخ نمایش‌داده‌شده برای هر نفر در کارت عمومی فدک؛ تاریخ، ساعت و مبلغ با دادهٔ همان صفحه تطبیق داده شد. موجودی و مبلغ نهایی هنگام خرید بررسی شود.",
        }
        operator = row.get("ownerName")
        if isinstance(operator, str) and operator.strip():
            offer["operator"] = operator.strip()
        service_class = row.get("wagonName")
        if isinstance(service_class, str) and service_class.strip() and _plain(service_class) in card_text:
            offer["service_class"] = service_class.strip()
        duration = row.get("travelDuration")
        if isinstance(duration, int) and not isinstance(duration, bool) and 0 < duration <= 2880:
            offer["duration_minutes"] = duration
        # The public card caps large inventories at "24+". Publish an exact
        # count only when visible; otherwise publish the visible lower bound.
        seats = row.get("seatCount")
        visible_seats = _VISIBLE_SEATS.search(card_text)
        if isinstance(seats, int) and not isinstance(seats, bool) and seats > 0 and visible_seats:
            shown = _number(visible_seats.group(1))
            if visible_seats.group(2) and shown is not None and seats >= shown:
                offer["seats_lower_bound"] = shown
                offer["availability"] = "available"
            elif not visible_seats.group(2) and shown == seats:
                offer["seats_remaining"] = seats
                offer["availability"] = "available"
        offers.append(offer)
    if rows and not offers:
        raise ValueError("Published Fadak tickets failed visible-card validation")
    return offers


def crawl_rail_fares() -> dict[str, list[dict]]:
    """Fetch verified first-party route pages, checking robots first."""
    offers: list[dict] = []
    source_status: list[dict] = []
    with httpx.Client(
        timeout=20.0, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        try:
            robots_response = client.get(f"https://{HOST}/robots.txt", headers={"Accept": "text/plain"})
            robots_response.raise_for_status()
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
        except httpx.HTTPError as exc:
            return {"offers": [], "source_status": [
                {"provider": PROVIDER, "mode": "train", "origin": origin,
                 "destination": destination, "url": route_url(origin, destination),
                 "status": "error", "offer_count": 0,
                 "error": f"Could not verify robots.txt: {exc}"}
                for origin, destination in ROUTES
            ]}
        for origin, destination in ROUTES:
            url = route_url(origin, destination)
            status = {"provider": PROVIDER, "mode": "train", "origin": origin,
                      "destination": destination, "url": url, "status": "error", "offer_count": 0}
            try:
                if not robots.can_fetch(USER_AGENT, url):
                    raise ValueError("robots.txt does not allow this public route page")
                response = client.get(url)
                response.raise_for_status()
                final = urlsplit(str(response.url))
                if final.scheme != "https" or final.netloc != HOST or "text/html" not in response.headers.get("content-type", ""):
                    raise ValueError("Unexpected route-page redirect or response type")
                observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                parsed = parse_fadak(response.text, origin, destination, url, observed_at)
                offers.extend(parsed)
                status.update({"status": "ok", "offer_count": len(parsed), "observed_at": observed_at,
                               "fare_status": "dated_fares" if parsed else "no_current_fares"})
            except (httpx.HTTPError, ValueError) as exc:
                status["error"] = str(exc)
            source_status.append(status)
            time.sleep(0.2)
    return {"offers": offers, "source_status": source_status}
