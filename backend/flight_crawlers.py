"""Read public SSR flight routes, calendars, and bounded dated flight cards.

Only fixed route pages and at most three linked dates per core Rahig route are
requested after robots.txt checks. Published fares and seat counts are snapshots,
not reserved seats or checkout quotes.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx
import jdatetime
from bs4 import BeautifulSoup


USER_AGENT = "ShabSanjResearch/0.1 (+public route fare comparison)"
CITY_FA = {
    "tehran": "تهران", "mashhad": "مشهد", "shiraz": "شیراز", "kish": "کیش",
    "rasht": "رشت", "ramsar": "رامسر", "nowshahr": "نوشهر", "sari": "ساری",
}
PROVIDER_NAMES = {"rahig": "رهیگ", "tikotrip": "تیکو تریپ"}
ROUTES = {
    "rahig": {
        ("tehran", "kish"): "https://rahig.com/flights/THR-KIH",
        ("kish", "tehran"): "https://rahig.com/flights/KIH-THR",
        ("tehran", "mashhad"): "https://rahig.com/flights/THR-MHD",
        ("mashhad", "tehran"): "https://rahig.com/flights/MHD-THR",
        ("tehran", "shiraz"): "https://rahig.com/flights/THR-SYZ",
        ("shiraz", "tehran"): "https://rahig.com/flights/SYZ-THR",
        ("mashhad", "kish"): "https://rahig.com/flights/MHD-KIH",
        ("kish", "mashhad"): "https://rahig.com/flights/KIH-MHD",
        ("shiraz", "kish"): "https://rahig.com/flights/SYZ-KIH",
        ("tehran", "rasht"): "https://rahig.com/flights/THR-RAS",
        ("rasht", "tehran"): "https://rahig.com/flights/RAS-THR",
        ("mashhad", "rasht"): "https://rahig.com/flights/MHD-RAS",
        ("rasht", "mashhad"): "https://rahig.com/flights/RAS-MHD",
        ("kish", "rasht"): "https://rahig.com/flights/KIH-RAS",
        ("rasht", "kish"): "https://rahig.com/flights/RAS-KIH",
        ("mashhad", "nowshahr"): "https://rahig.com/flights/MHD-NSH",
        ("nowshahr", "mashhad"): "https://rahig.com/flights/NSH-MHD",
        ("mashhad", "ramsar"): "https://rahig.com/flights/MHD-RZR",
        ("ramsar", "mashhad"): "https://rahig.com/flights/RZR-MHD",
        ("tehran", "sari"): "https://rahig.com/flights/THR-SRY",
        ("sari", "tehran"): "https://rahig.com/flights/SRY-THR",
        ("mashhad", "sari"): "https://rahig.com/flights/MHD-SRY",
        ("sari", "mashhad"): "https://rahig.com/flights/SRY-MHD",
    },
    "tikotrip": {
        ("tehran", "kish"): "https://tikotrip.com/flights/tehran-kish",
        ("kish", "tehran"): "https://tikotrip.com/flights/kish-tehran",
        ("tehran", "mashhad"): "https://tikotrip.com/flights/tehran-mashhad",
        ("mashhad", "tehran"): "https://tikotrip.com/flights/mashhad-tehran",
        ("tehran", "shiraz"): "https://tikotrip.com/flights/tehran-shiraz",
        ("shiraz", "tehran"): "https://tikotrip.com/flights/shiraz-tehran",
        ("mashhad", "kish"): "https://tikotrip.com/flights/mashhad-kish",
        ("kish", "mashhad"): "https://tikotrip.com/flights/kish-mashhad",
    },
}

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PRICE = re.compile(r"([\d۰-۹٠-٩,٬]+)\s*تومان")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JALALI_DAY = re.compile(
    r"([\d۰-۹٠-٩]{1,2})\s+"
    r"(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)"
)
_JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
_TIME = re.compile(r"^\d{2}:\d{2}$")
_SEATS = re.compile(r"([\d۰-۹٠-٩,٬]+)\s+صندلی\s+با\s+این\s+نرخ")
_IATA = {
    "tehran": "THR", "mashhad": "MHD", "shiraz": "SYZ", "kish": "KIH",
    "rasht": "RAS", "ramsar": "RZR", "nowshahr": "NSH", "sari": "SRY",
}
_LINK_ONLY_ROUTES = frozenset({
    ("tehran", "sari"), ("sari", "tehran"),
    ("mashhad", "sari"), ("sari", "mashhad"),
})
_CORE_DETAIL_ROUTES = frozenset({
    ("tehran", "mashhad"), ("mashhad", "tehran"),
    ("tehran", "kish"), ("kish", "tehran"),
})


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("ي", "ی").replace("ك", "ک")).strip()


def _amount(value: str) -> int | None:
    value = value.translate(_DIGITS).replace(",", "").replace("٬", "")
    return int(value) if value.isdecimal() and int(value) > 0 else None


def _route_title(soup: BeautifulSoup, origin: str, destination: str) -> None:
    heading = soup.find("h1")
    expected = f"بلیط هواپیما {CITY_FA[origin]} به {CITY_FA[destination]}"
    if heading is None or _plain(heading.get_text(" ", strip=True)) != expected:
        raise ValueError("Route heading does not match the requested origin and destination")


def _offer(
    provider: str, origin: str, destination: str, price: int | None,
    source_url: str, observed_at: str, departure_date: str | None,
    price_note: str,
) -> dict:
    return {
        "mode": "flight",
        "origin": origin,
        "destination": destination,
        "provider": provider,
        "provider_name": PROVIDER_NAMES[provider],
        "price_toman": price,
        "source_url": source_url,
        "observed_at": observed_at,
        "departure_date": departure_date,
        "price_note": price_note,
    }


def _dated_link(href: str, base_url: str, origin: str, destination: str, today: date) -> tuple[str, str] | None:
    full = urljoin(base_url, href)
    parts = urlsplit(full)
    if parts.hostname != urlsplit(base_url).hostname:
        return None
    params = parse_qs(parts.query)
    day_text = params.get("date", [None])[0]
    if not isinstance(day_text, str) or not _ISO.fullmatch(day_text):
        return None
    try:
        departure_day = date.fromisoformat(day_text)
    except ValueError:
        return None
    if not today <= departure_day <= today + timedelta(days=61):
        return None
    if urlsplit(base_url).hostname == "rahig.com":
        if parts.path != urlsplit(base_url).path:
            return None
    else:
        if parts.path != "/results":
            return None
        if (params.get("origin") != [_IATA[origin]] or
                params.get("destination") != [_IATA[destination]] or
                params.get("adults") != ["1"] or
                params.get("children") != ["0"] or
                params.get("infants") != ["0"]):
            return None
    return day_text, full


def _rahig_calendar_proof(soup: BeautifulSoup, date_label: str, price: int) -> str:
    """Check the linked headline day against a priced SSR calendar button."""
    date_match = _JALALI_DAY.search(date_label)
    if date_match is None:
        return "missing"
    day = int(date_match.group(1).translate(_DIGITS))
    month = date_match.group(2)
    estimated = False
    for button in soup.select("button[aria-label]"):
        label_match = _JALALI_DAY.search(button.get("aria-label", ""))
        if label_match is None or (int(label_match.group(1).translate(_DIGITS)), label_match.group(2)) != (day, month):
            continue
        strong = button.find("strong")
        price_match = _PRICE.search(strong.get_text(" ", strip=True)) if strong else None
        if price_match is None or _amount(price_match.group(1)) != price:
            continue
        if "~" in button.get_text(" ", strip=True) or "تخمینی" in button.get("aria-label", ""):
            estimated = True
        else:
            return "confirmed"
    return "estimated" if estimated else "missing"


def _rahig_calendar_date(button: BeautifulSoup) -> date | None:
    """Use the displayed Jalali month/year, never infer a date from position."""
    month_container = button.find_parent("div", class_="R_CMEa_days")
    heading = month_container.parent.select_one(".R_CMEa_monthHeader h4") if month_container else None
    label = button.get("aria-label", "")
    day_match = _JALALI_DAY.search(label)
    month_match = re.fullmatch(r"(\S+)\s+(\d{4})", _plain(heading.get_text(" ", strip=True)).translate(_DIGITS)) if heading else None
    if not day_match or not month_match or day_match.group(2) != month_match.group(1):
        return None
    if month_match.group(1) not in _JALALI_MONTHS:
        return None
    try:
        return jdatetime.date(
            int(month_match.group(2)), _JALALI_MONTHS.index(month_match.group(1)) + 1,
            int(day_match.group(1).translate(_DIGITS)),
        ).togregorian()
    except ValueError:
        return None


def _rahig_calendar_rows(soup: BeautifulSoup, listing_url: str, today: date) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for button in soup.select("#price-calendar button.R_CMEa_day[aria-label]"):
        day = _rahig_calendar_date(button)
        if day is None or not today <= day <= today + timedelta(days=61):
            continue
        label = button.get("aria-label", "")
        if "حدود" in label or "~" in button.get_text(" ", strip=True):
            continue
        strong = button.find("strong")
        match = _PRICE.search(strong.get_text(" ", strip=True)) if strong else None
        amount = _amount(match.group(1)) if match else None
        if amount is None:
            continue
        url = f"{listing_url}?date={day.isoformat()}#flight-results"
        rows.append((day.isoformat(), amount, url))
    return sorted(rows)


def _rahig_recorded_at(soup: BeautifulSoup, observed_at: str) -> str:
    """Age the calendar snapshot when Rahig states how old its rates are."""
    note = soup.select_one("#price-calendar p.R_CMEa_note span")
    match = re.fullmatch(r"([\d۰-۹٠-٩]+)\s+(دقیقه|ساعت|روز)\s+پیش", _plain(note.get_text(" ", strip=True))) if note else None
    if match is None:
        return observed_at
    amount = _amount(match.group(1))
    if amount is None or amount > 90:
        return observed_at
    units = {"دقیقه": "minutes", "ساعت": "hours", "روز": "days"}
    try:
        instant = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return observed_at
    return (instant - timedelta(**{units[match.group(2)]: amount})).isoformat(timespec="seconds")


def parse_rahig(
    html: str, origin: str, destination: str, listing_url: str,
    observed_at: str, *, today: date | None = None,
    include_dated: bool = True,
    max_dated_days: int = 1,
) -> list[dict]:
    """Parse the route floor and non-estimated public calendar rates."""
    if listing_url != ROUTES["rahig"].get((origin, destination)):
        raise ValueError("Unsupported Rahig route")
    soup = BeautifulSoup(html, "html.parser")
    _route_title(soup, origin, destination)
    if "۱ مسافر" not in soup.get_text(" ", strip=True):
        raise ValueError("One-passenger search context is missing")
    marker = "ارزان‌ترین نرخ ۶۰ روز آینده"
    price_paragraph = next((p for p in soup.find_all("p") if
                            marker in _plain(p.get_text(" ", strip=True)) and p.find("strong")), None)
    if price_paragraph is None:
        if (origin, destination) in _LINK_ONLY_ROUTES:
            return [_offer(
                "rahig", origin, destination, None, listing_url, observed_at, None,
                "صفحهٔ عمومی این مسیر در رهیگ باز می‌شود، اما در زمان مشاهده هیچ نرخ بلیت منتشر نشده بود؛ قیمت و موجودی باید در سایت فروشنده بررسی شود.",
            )]
        raise ValueError("No 60-day route minimum was published")
    strong = price_paragraph.find("strong")
    match = _PRICE.search(strong.get_text(" ", strip=True)) if strong else None
    price = _amount(match.group(1)) if match else None
    if price is None:
        raise ValueError("Invalid 60-day route minimum")
    date_link = price_paragraph.find("a", href=True)
    today = today or datetime.now(ZoneInfo("Asia/Tehran")).date()
    linked = _dated_link(date_link["href"], listing_url, origin, destination, today) if date_link else None
    proof = _rahig_calendar_proof(soup, date_link.get_text(" ", strip=True), price) if linked and date_link else "missing"
    note = "کمترین نرخ منتشرشدهٔ مسیر در ۶۰ روز آینده برای یک مسافر و پرواز یک‌طرفه؛ موجودی و مبلغ نهایی هنگام خرید بررسی شود."
    if proof == "estimated":
        note += " نرخِ روزِ معرفی‌شده در تقویم با علامت ~ تخمینی است."
    elif proof == "missing":
        note += " نرخِ تاریخ معرفی‌شده در تقویم عمومی تأیید نشد."
    recorded_at = _rahig_recorded_at(soup, observed_at)
    offers = [_offer("rahig", origin, destination, price, listing_url, recorded_at, None, note)]
    if not include_dated or max_dated_days <= 0:
        return offers
    calendar = _rahig_calendar_rows(soup, listing_url, today)
    if calendar:
        for day, daily_price, date_url in calendar[:max_dated_days]:
            offers.append(_offer(
                "rahig", origin, destination, daily_price, date_url, recorded_at, day,
                "نرخ ثبت‌شدهٔ بدون علامت تخمین در تقویم عمومی برای این روز و یک مسافر؛ ظرفیت صندلی و مبلغ نهایی تأیید نشده.",
            ))
    elif linked is not None and proof == "confirmed":
        day, date_url = linked
        offers.append(_offer(
            "rahig", origin, destination, price, date_url, recorded_at, day,
            "کمترین نرخ روزِ مشخص‌شده در سربرگ مسیر برای یک مسافر و پرواز یک‌طرفه؛ پرواز، صندلی و مبلغ نهایی تأیید نشده.",
        ))
    return offers


def parse_rahig_cards(
    html: str, origin: str, destination: str, listing_url: str,
    dated_url: str, observed_at: str, *, today: date | None = None,
) -> list[dict]:
    """Read published SSR cards for one selected day, without claiming checkout availability."""
    today = today or datetime.now(ZoneInfo("Asia/Tehran")).date()
    linked = _dated_link(dated_url, listing_url, origin, destination, today)
    if listing_url != ROUTES["rahig"].get((origin, destination)) or linked is None:
        raise ValueError("Unsupported Rahig dated route")
    selected_day = date.fromisoformat(linked[0])
    soup = BeautifulSoup(html, "html.parser")
    _route_title(soup, origin, destination)
    if "۱ مسافر" not in soup.get_text(" ", strip=True):
        raise ValueError("One-passenger search context is missing")
    selected_button = soup.select_one('#price-calendar button.R_CMEa_day[aria-current="date"]')
    if selected_button is None or _rahig_calendar_date(selected_button) != selected_day:
        raise ValueError("Rahig selected day does not match dated URL")
    recorded_at = _rahig_recorded_at(soup, observed_at)
    cards: list[dict] = []
    for article in soup.select('#flight-results article[data-compact-flight="true"]'):
        if article.get("data-sold-out") != "false":
            continue
        journey = article.select("._iRDvq_journey ._iRDvq_time")
        if len(journey) != 2:
            continue
        origin_code = journey[0].select_one("bdi")
        destination_code = journey[1].select_one("bdi")
        if (origin_code is None or destination_code is None or
                origin_code.get_text("", strip=True) != _IATA[origin] or
                destination_code.get_text("", strip=True) != _IATA[destination]):
            continue
        departure_tag, arrival_tag = (item.select_one("strong") for item in journey)
        departure_time = departure_tag.get_text("", strip=True).translate(_DIGITS) if departure_tag else ""
        arrival_time = arrival_tag.get_text("", strip=True).translate(_DIGITS) if arrival_tag else ""
        if not _TIME.fullmatch(departure_time) or not _TIME.fullmatch(arrival_time):
            continue
        fare_tag = article.select_one("._iRDvq_amount strong")
        price = _amount(fare_tag.get_text("", strip=True)) if fare_tag else None
        seats = next((match for tag in article.select("._iRDvq_meta span")
                      if (match := _SEATS.search(_plain(tag.get_text(" ", strip=True))))), None)
        seat_count = _amount(seats.group(1)) if seats else None
        if price is None or seat_count is None:
            continue
        operator_tag = article.select_one("._iRDvq_airlineText strong")
        number_tag = article.select_one('._iRDvq_airlineText span[dir="ltr"]')
        operator = _plain(operator_tag.get_text(" ", strip=True)) if operator_tag else ""
        number = re.sub(r"\s+", "", number_tag.get_text(" ", strip=True).translate(_DIGITS)) if number_tag else ""
        if not operator or not number:
            continue
        offer = _offer(
            "rahig", origin, destination, price, linked[1], recorded_at, linked[0],
            "قیمت و تعداد صندلیِ درج‌شده در کارت عمومی این پرواز هنگام ثبت؛ صفحه در حال تأیید زندهٔ نرخ و ظرفیت بود و امکان انتخاب پرواز تا پایان تأیید فعال نبود. مبلغ و موجودی نهایی در فروشنده بررسی شود.",
        )
        offer.update({
            "departure_time": departure_time, "arrival_time": arrival_time,
            "operator": operator, "service_number": number,
            "seats_remaining": seat_count,
            "availability": "unknown", "source_type": "published_flight_card",
            "offer_id": f"rahig:{origin}:{destination}:{linked[0]}:{number}:{departure_time}",
        })
        ticket_type = article.select_one("._iRDvq_corner")
        if ticket_type:
            offer["service_class"] = _plain(ticket_type.get_text(" ", strip=True))
        cards.append(offer)
    return cards


def _tikotrip_updated_at(soup: BeautifulSoup, fallback: str) -> str:
    updated = soup.select_one('[data-test="landing-fares-updated"] time[datetime]')
    if updated is None:
        return fallback
    try:
        moment = datetime.fromisoformat(updated["datetime"].replace("Z", "+00:00"))
        captured = datetime.fromisoformat(fallback.replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return fallback
    if moment.tzinfo is None or captured.tzinfo is None or moment > captured + timedelta(minutes=5):
        return fallback
    return moment.isoformat(timespec="seconds")


def _tikotrip_tomorrow_flights(
    soup: BeautifulSoup, origin: str, destination: str, listing_url: str,
    observed_at: str, today: date,
) -> list[dict]:
    """Read flight rows only when the public summary confirms seats and minimum."""
    section = soup.select_one('[data-test="landing-fares-summary"]')
    updated = section.select_one('[data-test="landing-fares-updated"] time[datetime]') if section else None
    answer = section.select_one('[data-test="landing-fares-answer"]') if section else None
    table = section.select_one('table[data-test="landing-flights-table"]') if section else None
    if updated is None or answer is None or table is None:
        return []
    summary = _plain(answer.get_text(" ", strip=True))
    count_match = re.search(r"فردا\s+([\d۰-۹٠-٩]+)\s+پرواز\s+با\s+صندلی\s+خالی", summary)
    minimum_match = re.search(r"ارزان‌ترین\s+آن\s+([\d۰-۹٠-٩,٬]+)\s+تومان", summary)
    count = _amount(count_match.group(1)) if count_match else None
    minimum = _amount(minimum_match.group(1)) if minimum_match else None
    caption = table.find("caption")
    expected = f"پروازهای فردا {CITY_FA[origin]} به {CITY_FA[destination]}"
    if count is None or count > 100 or minimum is None or caption is None or _plain(caption.get_text(" ", strip=True)) != expected:
        return []
    day = (today + timedelta(days=1)).isoformat()
    ticket_rows = table.select('tr[data-test="landing-flight-row"]')
    if len(ticket_rows) != count:
        return []
    rows: list[dict] = []
    for row in ticket_rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) != 5:
            return []
        operator = _plain(cells[0].get_text(" ", strip=True))
        flight_number = re.sub(r"\s+", "", cells[1].get_text(" ", strip=True).translate(_DIGITS))
        departure_time = cells[2].get_text("", strip=True).translate(_DIGITS)
        service_class = _plain(cells[3].get_text(" ", strip=True))
        anchor = cells[4].find("a", href=True)
        linked = _dated_link(anchor["href"], listing_url, origin, destination, today) if anchor else None
        price_match = _PRICE.search(anchor.get_text(" ", strip=True)) if anchor else None
        price = _amount(price_match.group(1)) if price_match else None
        if (not operator or not flight_number or not _TIME.fullmatch(departure_time)
                or not service_class or linked is None or linked[0] != day or price is None):
            return []
        offer = _offer(
            "tikotrip", origin, destination, price, linked[1], observed_at, day,
            "پرواز فردا در جدول عمومی فروشنده با صندلی خالی، ساعت و نرخ هر بزرگسال ثبت شده؛ موجودی و مبلغ نهایی هنگام خرید دوباره بررسی شود.",
        )
        offer.update({
            "departure_time": departure_time, "operator": operator,
            "service_number": flight_number,
            "service_class": service_class, "availability": "available",
            "source_type": "dated_flight_listing",
            "offer_id": f"tikotrip:{origin}:{destination}:{day}:{flight_number}:{departure_time}",
        })
        rows.append(offer)
    return rows if min(row["price_toman"] for row in rows) == minimum else []


def parse_tikotrip(
    html: str, origin: str, destination: str, listing_url: str,
    observed_at: str, *, today: date | None = None,
    max_dated_days: int = 14,
) -> list[dict]:
    """Parse the route floor plus bounded exact-date calendar minima."""
    if listing_url != ROUTES["tikotrip"].get((origin, destination)):
        raise ValueError("Unsupported TikoTrip route")
    soup = BeautifulSoup(html, "html.parser")
    _route_title(soup, origin, destination)
    page_text = soup.get_text(" ", strip=True)
    if "قیمت‌ها برای یک بزرگسال" not in page_text:
        raise ValueError("One-adult price basis is missing")
    route_name = f"بلیط هواپیما {CITY_FA[origin]} به {CITY_FA[destination]}"
    pattern = re.compile(rf"ارزان‌ترین\s+{re.escape(route_name)}\s+در\s+۶۰\s+روز\s+آینده\s+([\d۰-۹٠-٩,٬]+)\s+تومان")
    paragraph = next((p for p in soup.find_all("p") if pattern.search(_plain(p.get_text(" ", strip=True)))), None)
    match = pattern.search(_plain(paragraph.get_text(" ", strip=True))) if paragraph else None
    price = _amount(match.group(1)) if match else None
    if price is None:
        raise ValueError("No 60-day route minimum was published")
    note = "کمترین نرخ منتشرشدهٔ مسیر در ۶۰ روز آینده برای یک بزرگسال و پرواز یک‌طرفه؛ موجودی و مبلغ نهایی هنگام خرید بررسی شود."
    recorded_at = _tikotrip_updated_at(soup, observed_at)
    offers = [_offer("tikotrip", origin, destination, price, listing_url, recorded_at, None, note)]
    if max_dated_days <= 0:
        return offers
    today = today or datetime.now(ZoneInfo("Asia/Tehran")).date()
    calendar: list[tuple[str, int, str]] = []
    for anchor in soup.select('a[data-test="blog-route-fare-day"][href][aria-label]'):
        linked = _dated_link(anchor["href"], listing_url, origin, destination, today)
        match = _PRICE.search(anchor["aria-label"])
        daily_price = _amount(match.group(1)) if match else None
        if linked is not None and daily_price is not None:
            calendar.append((linked[0], daily_price, linked[1]))
    calendar.sort(key=lambda row: row[0])
    seen_days: set[str] = set()
    for day, daily_price, date_url in calendar:
        if day in seen_days:
            continue
        seen_days.add(day)
        offers.append(_offer(
            "tikotrip", origin, destination, daily_price, date_url, recorded_at, day,
            "کمترین نرخ تقویم عمومی این روز برای یک بزرگسال و پرواز یک‌طرفه؛ شمارهٔ پرواز، صندلی و مبلغ نهایی تأیید نشده.",
        ))
        if len(seen_days) >= max_dated_days:
            break
    tomorrow = (today + timedelta(days=1)).isoformat()
    if tomorrow in seen_days or len(seen_days) < max_dated_days:
        flights = _tikotrip_tomorrow_flights(soup, origin, destination, listing_url, recorded_at, today)
        if flights:
            offers = [offer for offer in offers if offer["departure_date"] != tomorrow]
            offers.extend(flights)
    return offers


PARSERS = {"rahig": parse_rahig, "tikotrip": parse_tikotrip}


def crawl_flights(max_dated_days_per_route: int = 14) -> dict:
    """Fetch fixed public route pages and a bounded set of dated Rahig pages."""
    if not 0 <= max_dated_days_per_route <= 60:
        raise ValueError("max_dated_days_per_route must be between 0 and 60")
    offers: list[dict] = []
    source_status: list[dict] = []
    robots_cache: dict[str, RobotFileParser] = {}
    with httpx.Client(
        follow_redirects=True, timeout=20.0,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        for provider, routes in ROUTES.items():
            for (origin, destination), url in routes.items():
                status = {"provider": provider, "mode": "flight", "origin": origin,
                          "destination": destination, "url": url}
                try:
                    parts = urlsplit(url)
                    site = f"{parts.scheme}://{parts.netloc}"
                    if site not in robots_cache:
                        robots_response = client.get(urljoin(site, "/robots.txt"), headers={"Accept": "text/plain"})
                        robots_response.raise_for_status()
                        robots = RobotFileParser()
                        robots.parse(robots_response.text.splitlines())
                        robots_cache[site] = robots
                    if not robots_cache[site].can_fetch(USER_AGENT, url):
                        raise PermissionError("robots.txt does not permit this public route page")
                    response = client.get(url)
                    response.raise_for_status()
                    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    if provider == "tikotrip":
                        parsed = parse_tikotrip(response.text, origin, destination, url, observed_at,
                                                 max_dated_days=max_dated_days_per_route)
                    else:
                        parsed = parse_rahig(response.text, origin, destination, url, observed_at,
                                              include_dated=max_dated_days_per_route > 0,
                                              max_dated_days=max_dated_days_per_route)
                        detail_limit = 3 if (origin, destination) in _CORE_DETAIL_ROUTES else 1
                        detail_checks = []
                        for dated in (item for item in parsed if item["departure_date"]):
                            if len(detail_checks) >= detail_limit:
                                break
                            detail_url = dated["source_url"]
                            check = {"date": dated["departure_date"], "url": detail_url,
                                     "status": "error", "card_count": 0}
                            try:
                                if not robots_cache[site].can_fetch(USER_AGENT, detail_url):
                                    raise PermissionError("robots.txt does not permit the dated route page")
                                detail = client.get(detail_url.split("#", 1)[0])
                                detail.raise_for_status()
                                if urlsplit(str(detail.url)).hostname != parts.hostname:
                                    raise ValueError("Dated route redirected to another host")
                                detail_observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
                                cards = parse_rahig_cards(
                                    detail.text, origin, destination, url, detail_url, detail_observed,
                                )
                                if cards:
                                    parsed = [item for item in parsed if item["departure_date"] != dated["departure_date"]]
                                    parsed.extend(cards)
                                check.update({"status": "ok", "card_count": len(cards)})
                            except (httpx.HTTPError, PermissionError, ValueError) as exc:
                                check["error"] = str(exc)
                            detail_checks.append(check)
                            time.sleep(0.2)
                        if detail_checks:
                            status["detail_checks"] = detail_checks
                    offers.extend(parsed)
                    status.update({"status": "ok", "offer_count": len(parsed), "observed_at": observed_at})
                except (httpx.HTTPError, PermissionError, ValueError) as exc:
                    status.update({"status": "error", "offer_count": 0, "error": str(exc)})
                source_status.append(status)
                time.sleep(0.2)
    return {"offers": offers, "source_status": source_status}
