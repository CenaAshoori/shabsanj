"""Public railway route links from sellers that expose no SSR ticket fares.

This adapter checks robots.txt and validates each seller's route heading. It
deliberately emits unpriced links: the inspected public pages require a travel
date before they display actual tickets, and editorial price ranges are not
bookable fares.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .rail_fares import crawl_rail_fares


USER_AGENT = "ShabSanjResearch/0.1 (+public railway route comparison)"
PROVIDERS = {
    "tikotrip": "تیکو تریپ",
    "mrbilit": "مستربلیط",
    "orienttrips": "اورینت تریپس",
}
CITY_FA = {
    "tehran": "تهران",
    "mashhad": "مشهد",
    "rasht": "رشت",
    "shiraz": "شیراز",
    "isfahan": "اصفهان",
    "tabriz": "تبریز",
    "yazd": "یزد",
    "sari": "ساری",
}
CITY_EN = {
    "tehran": "Tehran",
    "mashhad": "Mashhad",
    "rasht": "Rasht",
    "shiraz": "Shiraz",
    "isfahan": "Isfahan",
    "tabriz": "Tabriz",
    "yazd": "Yazd",
    "sari": "Sari",
}
# These route pages are linked from the seller's public route index or a
# verified reverse-route article. A generated URL alone is not evidence that
# a train journey exists (some sellers render headings even for impossible
# routes). These pages are search entry points, not dated ticket results.
ROUTE_PAGES = (
    ("tikotrip", "tehran", "mashhad", "https://tikotrip.com/train/tehran-mashhad"),
    ("tikotrip", "mashhad", "tehran", "https://tikotrip.com/train/mashhad-tehran"),
    ("tikotrip", "tehran", "isfahan", "https://tikotrip.com/train/tehran-isfahan"),
    ("tikotrip", "isfahan", "tehran", "https://tikotrip.com/train/isfahan-tehran"),
    ("tikotrip", "tehran", "tabriz", "https://tikotrip.com/train/tehran-tabriz"),
    ("tikotrip", "tabriz", "tehran", "https://tikotrip.com/train/tabriz-tehran"),
    ("tikotrip", "tehran", "yazd", "https://tikotrip.com/train/tehran-yazd"),
    ("tikotrip", "yazd", "tehran", "https://tikotrip.com/train/yazd-tehran"),
    ("tikotrip", "tehran", "shiraz", "https://tikotrip.com/train/tehran-shiraz"),
    ("tikotrip", "shiraz", "tehran", "https://tikotrip.com/train/shiraz-tehran"),
    ("mrbilit", "tehran", "mashhad", "https://mrbilit.com/trains/tehran-mashhad"),
    ("mrbilit", "tehran", "isfahan", "https://mrbilit.com/trains/tehran-isfahan"),
    ("mrbilit", "isfahan", "tehran", "https://mrbilit.com/trains/isfahan-tehran"),
    ("mrbilit", "tehran", "tabriz", "https://mrbilit.com/trains/tehran-tabriz"),
    ("mrbilit", "tabriz", "tehran", "https://mrbilit.com/trains/tabriz-tehran"),
    ("mrbilit", "tehran", "yazd", "https://mrbilit.com/trains/tehran-yazd"),
    ("mrbilit", "yazd", "tehran", "https://mrbilit.com/trains/yazd-tehran"),
    ("mrbilit", "tehran", "rasht", "https://mrbilit.com/trains/tehran-rasht"),
    ("mrbilit", "rasht", "tehran", "https://mrbilit.com/trains/rasht-tehran"),
    ("mrbilit", "tehran", "shiraz", "https://mrbilit.com/trains/tehran-shiraz"),
    ("mrbilit", "tehran", "sari", "https://mrbilit.com/trains/tehran-sari"),
    ("mrbilit", "mashhad", "sari", "https://mrbilit.com/trains/mashhad-sari"),
    ("mrbilit", "isfahan", "mashhad", "https://mrbilit.com/trains/isfahan-mashhad"),
    ("mrbilit", "mashhad", "isfahan", "https://mrbilit.com/trains/mashhad-isfahan"),
    ("mrbilit", "tabriz", "mashhad", "https://mrbilit.com/trains/tabriz-mashhad"),
    ("mrbilit", "mashhad", "tabriz", "https://mrbilit.com/trains/mashhad-tabriz"),
    ("orienttrips", "tehran", "mashhad", "https://orienttrips.com/train/tehran/mashhad"),
    ("orienttrips", "mashhad", "tehran", "https://orienttrips.com/train/mashhad/tehran"),
    ("orienttrips", "tehran", "rasht", "https://orienttrips.com/train/tehran/rasht"),
    ("orienttrips", "tehran", "shiraz", "https://orienttrips.com/train/tehran/shiraz"),
    ("orienttrips", "shiraz", "tehran", "https://orienttrips.com/train/shiraz/tehran"),
    ("orienttrips", "tehran", "isfahan", "https://orienttrips.com/train/tehran/isfahan"),
    ("orienttrips", "isfahan", "tehran", "https://orienttrips.com/train/isfahan/tehran"),
    ("orienttrips", "tehran", "tabriz", "https://orienttrips.com/train/tehran/tabriz"),
    ("orienttrips", "tabriz", "tehran", "https://orienttrips.com/train/tabriz/tehran"),
    ("orienttrips", "tehran", "yazd", "https://orienttrips.com/train/tehran/yazd"),
    ("orienttrips", "yazd", "tehran", "https://orienttrips.com/train/yazd/tehran"),
    ("orienttrips", "isfahan", "mashhad", "https://orienttrips.com/train/isfahan/mashhad"),
)


def _route_confirmed(html: str, provider: str, origin: str, destination: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if heading is None:
        return False
    title = " ".join(heading.get_text(" ", strip=True).split()).casefold()
    if provider == "orienttrips":
        article_title = f"Train From {CITY_EN[origin]} To {CITY_EN[destination]}".casefold()
        route_sections = (" ".join(h.get_text(" ", strip=True).split()).casefold() for h in soup.select("h2"))
        return (
            title == f"{CITY_EN[origin]} To {CITY_EN[destination]} Train Tickets".casefold()
            and any(article_title in section for section in route_sections)
        )
    expected = f"بلیط قطار {CITY_FA[origin]} به {CITY_FA[destination]}"
    return title.replace("  ", " ") == expected


def _robots_allowed(client: httpx.Client, url: str, cache: dict[str, RobotFileParser]) -> bool:
    parts = urlsplit(url)
    host = parts.netloc
    if host not in cache:
        response = client.get(f"https://{host}/robots.txt", headers={"Accept": "text/plain"})
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";")[0].strip() not in {"text/plain", ""}:
            raise ValueError(f"Unexpected robots.txt type at {host}")
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        cache[host] = parser
    return cache[host].can_fetch(USER_AGENT, url)


def crawl_trains() -> dict[str, list[dict]]:
    """Return checked route links and publicly displayed dated Fadak fares.

    No private search endpoint is queried. Route links remain unpriced unless
    a public seller page actually displays a dated one-adult fare.
    """
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    offers: list[dict] = []
    source_status: list[dict] = []
    robot_cache: dict[str, RobotFileParser] = {}
    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        for provider, origin, destination, url in ROUTE_PAGES:
            status = {
                "provider": provider,
                "mode": "train",
                "origin": origin,
                "destination": destination,
                "url": url,
                "status": "error",
                "offer_count": 0,
                "observed_at": observed_at,
            }
            try:
                if not _robots_allowed(client, url, robot_cache):
                    raise ValueError("robots.txt disallows this page")
                response = client.get(url)
                response.raise_for_status()
                final_url = urlsplit(str(response.url))
                requested_url = urlsplit(url)
                if final_url.scheme != "https" or final_url.netloc != requested_url.netloc:
                    raise ValueError("Unexpected redirect outside the seller host")
                if not _route_confirmed(response.text, provider, origin, destination):
                    raise ValueError("Page heading does not confirm the requested route")
                offers.append({
                    "mode": "train",
                    "origin": origin,
                    "destination": destination,
                    "provider": provider,
                    "provider_name": PROVIDERS[provider],
                    "price_toman": None,
                    "departure_date": None,
                    "source_url": url,
                    "observed_at": observed_at,
                    "availability": "unknown",
                    "source_type": "route_link",
                    "price_note": "صفحه عمومی این مسیر نرخ و موجودی بلیت را بدون انتخاب تاریخ حرکت نشان نمی‌دهد؛ قیمت را در سایت فروشنده بررسی کنید.",
                })
                status["status"] = "ok"
                status["offer_count"] = 1
                status["fare_status"] = "unpriced_route_link"
            except (httpx.HTTPError, ValueError) as exc:
                status["error"] = str(exc)
            source_status.append(status)
    dated = crawl_rail_fares()
    offers.extend(dated["offers"])
    source_status.extend(dated["source_status"])
    return {"offers": offers, "source_status": source_status}
