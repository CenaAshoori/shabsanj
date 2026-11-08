"""Bounded public Snapptrip Kish tour route adapter.

Only the ten server-rendered cards on each clean, robots-permitted route URL
are used. The visible one-person and two-person amounts must agree with each
other and with the matching Next.js solution before a tour is emitted.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import json
import re
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx
import jdatetime

from .search import normalize_text


USER_AGENT = "ShabSanjResearch/0.1 (+public tour catalog comparison)"
ROUTES = (
    ("tehran", "kish", "THR", "KIH", "https://www.snapptrip.com/tour/THR/KIH"),
    ("mashhad", "kish", "MHD", "KIH", "https://www.snapptrip.com/tour/MHD/KIH"),
    ("shiraz", "kish", "SYZ", "KIH", "https://www.snapptrip.com/tour/SYZ/KIH"),
)
CITY_FA = {"tehran": "تهران", "mashhad": "مشهد", "shiraz": "شیراز", "kish": "کیش"}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AMOUNT = re.compile(r"([\d,٬]+)\s*تومان")


def _toman(text: str) -> int | None:
    amounts = _AMOUNT.findall(text.translate(_DIGITS))
    if len(amounts) != 1:
        return None
    digits = amounts[0].replace(",", "").replace("٬", "")
    return int(digits) if digits.isdecimal() else None


def _stay_dates(solution: dict) -> tuple[str, str]:
    """Confirm that the public package's dates are hotel stay dates."""
    encoded = solution.get("solutionId")
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 20_000:
        raise ValueError("Snapptrip solution has no bounded stay metadata")
    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(decoded) > 20_000:
        raise ValueError("Snapptrip stay metadata is oversized")
    metadata = json.loads(decoded).get("metadata") or {}
    stay = metadata.get("hotel") or {}
    checkin, checkout = stay.get("checkIn"), stay.get("checkOut")
    if not isinstance(checkin, str) or not isinstance(checkout, str):
        raise ValueError("Snapptrip package has no hotel stay dates")
    date.fromisoformat(checkin)
    date.fromisoformat(checkout)
    return checkin, checkout


def snapptrip_hotel_index(catalog: dict | None) -> dict[tuple[str, str], str]:
    """Join only the provider's verified numeric hotel ID and city."""
    index: dict[tuple[str, str], str] = {}
    if not isinstance(catalog, dict):
        return index
    for offer in catalog.get("offers", []):
        if not isinstance(offer, dict) or offer.get("provider") != "snapptrip":
            continue
        numeric_id = offer.get("provider_numeric_id")
        if isinstance(numeric_id, int) and numeric_id > 0 and offer.get("city") and offer.get("canonical_id"):
            index[(offer["city"], str(numeric_id))] = str(offer["canonical_id"])
    return index


def parse_snapptrip_tour_listing(
    html: str, departure_city: str, destination_city: str,
    origin_code: str, destination_code: str, listing_url: str,
    observed_at: str, hotel_index: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if not heading or f"تور جزیره {CITY_FA[destination_city]} از {CITY_FA[departure_city]}" not in heading.get_text(" ", strip=True):
        raise ValueError("Snapptrip route heading does not match requested cities")
    script = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if not script or not script.string:
        raise ValueError("Snapptrip route has no server-rendered tour data")
    payload = json.loads(script.string)
    page = payload.get("props", {}).get("pageProps", {})
    if (payload.get("query", {}).get("origin") != origin_code
            or payload.get("query", {}).get("dest") != destination_code
            or page.get("originData", {}).get("iata_code") != origin_code
            or page.get("destData", {}).get("iata_code") != destination_code):
        raise ValueError("Snapptrip structured route data does not match requested cities")
    solutions = page.get("ssrResults", {}).get("solutions")
    if not isinstance(solutions, list) or not 1 <= len(solutions) <= 10:
        raise ValueError("Snapptrip route has no bounded SSR solution page")
    cards = [card for card in soup.select("div.shadow-1.bg-background")
             if card.select_one("h2") and "قیمت" in card.get_text(" ", strip=True)]
    if len(cards) != len(solutions):
        raise ValueError("Snapptrip visible cards and structured solutions differ")
    hotel_index = hotel_index or {}
    tours: list[dict] = []
    for solution, card in zip(solutions, cards):
        hotel = solution.get("hotel") or {}
        hotel_id = hotel.get("id")
        hotel_name = str(hotel.get("name") or "").strip()
        card_name = card.select_one("h2").get_text(" ", strip=True)
        if (not isinstance(hotel_id, int) or hotel_id <= 0 or not hotel_name
                or normalize_text(card_name) != normalize_text(hotel_name)):
            raise ValueError("Snapptrip card hotel does not match structured hotel ID/name")
        card_text = normalize_text(card.get_text(" ", strip=True))
        if ("قیمت 1 نفر" not in card_text or "بلیط اقامت" not in card_text
                or "برای 2 نفر" not in card_text or "شامل پرواز رفت و برگشت" not in card_text):
            raise ValueError("Snapptrip card does not prove the flight package price basis")
        per_person_node = card.select_one("div.text-subtitle-1")
        group_node = next((node for node in card.select("div.text-body-2")
                           if "تومان" in node.get_text(" ", strip=True)
                           and "برای 2 نفر" in normalize_text(node.parent.get_text(" ", strip=True))), None)
        per_person = _toman(per_person_node.get_text(" ", strip=True)) if per_person_node else None
        group_price = _toman(group_node.get_text(" ", strip=True)) if group_node else None
        advertised = solution.get("pricing", {}).get("priceOff")
        if (not per_person or not group_price or not isinstance(advertised, (int, float))
                or isinstance(advertised, bool) or advertised <= 0
                or abs(2 * per_person - group_price) > 1
                or abs(advertised / 10 - group_price) > 1):
            raise ValueError("Snapptrip visible and structured prices do not agree")
        departure_flight = solution.get("departureFlight") or {}
        return_flight = solution.get("returningFlight") or {}
        if (departure_flight.get("originCode") != origin_code
                or departure_flight.get("destinationCode") != destination_code
                or return_flight.get("originCode") != destination_code
                or return_flight.get("destinationCode") != origin_code):
            raise ValueError("Snapptrip card flight route does not match listing")
        from_date = date.fromisoformat(str(solution.get("fromDate")))
        to_date = date.fromisoformat(str(solution.get("toDate")))
        stay_checkin, stay_checkout = _stay_dates(solution)
        departure_at = datetime.fromisoformat(str(departure_flight.get("departureDateTime")))
        return_at = datetime.fromisoformat(str(return_flight.get("departureDateTime")))
        nights = (to_date - from_date).days
        if (not 1 <= nights <= 30 or stay_checkin != from_date.isoformat()
                or stay_checkout != to_date.isoformat() or departure_at.date() != from_date
                or return_at.date() != to_date):
            raise ValueError("Snapptrip package dates do not agree with its flights")
        departure_jalali = jdatetime.date.fromgregorian(date=from_date).strftime("%Y/%m/%d")
        return_jalali = jdatetime.date.fromgregorian(date=to_date).strftime("%Y/%m/%d")
        full_hotel_name = hotel_name if CITY_FA[destination_city] in hotel_name else f"{hotel_name} {CITY_FA[destination_city]}"
        tours.append({
            "provider": "snapptrip", "provider_name": "اسنپ‌تریپ",
            "tour_id": f"snapptrip:{departure_city}:{destination_city}:{hotel_id}:{from_date}:{departure_at:%H%M}",
            "title": f"تور {CITY_FA[destination_city]} از {CITY_FA[departure_city]}؛ {full_hotel_name} (هوایی)",
            "departure_city": departure_city, "destination_city": destination_city,
            "provider_hotel_id": str(hotel_id), "hotel_name": full_hotel_name,
            "canonical_hotel_id": hotel_index.get((destination_city, str(hotel_id))),
            "departure_date": departure_jalali, "return_date": return_jalali,
            "hotel_checkin_date": departure_jalali,
            "departure_date_gregorian": from_date.isoformat(),
            "return_date_gregorian": to_date.isoformat(),
            "hotel_checkin_date_gregorian": stay_checkin,
            "hotel_checkout_date_gregorian": stay_checkout,
            "departure_time": departure_at.strftime("%H:%M"),
            "return_time": return_at.strftime("%H:%M"),
            "duration_nights": nights,
            "travelers": 2, "rooms": 1,
            "price_toman": per_person, "group_price_toman": group_price,
            "price_basis": "per_person",
            "services": ["پرواز رفت و برگشت", f"اقامت {nights} شب"],
            "optional_services": [], "transport": "flight",
            "source_url": listing_url, "listing_url": listing_url,
            "observed_at": observed_at, "availability": "unknown",
            "source_type": "route_listing",
            "cta_label": "مشاهده تورهای مسیر در اسنپ‌تریپ",
            "price_note": (
                f"نرخ شروع یک نفر (بلیط + اقامت) در کارت عمومی اسنپ‌تریپ؛ "
                f"مجموع نشان‌داده‌شده برای ۲ نفر {group_price:,} تومان و اقامت {nights} شب است. "
                "تاریخ‌های حرکت و اقامت از دادهٔ همین بسته به شمسی تبدیل شده‌اند و نسخهٔ میلادی منبع نیز ثبت شده است؛ "
                "قیمت و ظرفیت نهایی را در سایت فروشنده بررسی کنید."
            ),
        })
    return tours


def crawl_snapptrip_tours(hotel_catalog: dict | None = None) -> dict:
    """Fetch only three clean public routes after checking robots.txt."""
    hotel_index = snapptrip_hotel_index(hotel_catalog)
    tours: list[dict] = []
    statuses: list[dict] = []
    with httpx.Client(
        follow_redirects=False, timeout=httpx.Timeout(20.0, connect=5.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        robots = client.get("https://www.snapptrip.com/robots.txt", headers={"Accept": "text/plain"})
        robots.raise_for_status()
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        for departure_city, destination_city, origin_code, destination_code, listing_url in ROUTES:
            observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            status = {
                "provider": "snapptrip", "departure_city": departure_city,
                "destination_city": destination_city, "url": listing_url,
                "source_type": "route_listing", "observed_at": observed_at,
            }
            try:
                if not parser.can_fetch(USER_AGENT, listing_url):
                    raise PermissionError("robots.txt does not allow this tour route")
                response = client.get(listing_url)
                response.raise_for_status()
                parsed = parse_snapptrip_tour_listing(
                    response.text, departure_city, destination_city,
                    origin_code, destination_code, listing_url, observed_at, hotel_index,
                )
                tours.extend(parsed)
                status.update({"status": "ok", "http_status": response.status_code,
                               "tour_count": len(parsed)})
            except Exception as exc:
                status.update({"status": "error", "tour_count": 0,
                               "error": f"{type(exc).__name__}: {exc}"[:200]})
            statuses.append(status)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_status": statuses,
        "tours": tours,
    }
