"""Parse AsaSafar's public Kish hotel city listing.

The card's «starting price / 1 night» is an indicative listing observation.
Its detail-link date is not treated as the date of a confirmed room quote.
The caller must check robots.txt before fetching a listing page.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


PROVIDER = "asasafar"
PROVIDER_NAME = "آسا سفر"
KISH_LISTING_URL = "https://www.asasafar.com/fa/رزرو_هتل_در/هرمزگان/کیش"

# Exact same-city names and detail slugs checked against the bundled hotel
# catalog. Unlisted identities remain AsaSafar-specific; no fuzzy merge.
VERIFIED_KISH_CANONICAL_IDS = {
    "mirage": "tournegar:kish:217",
    "abadgaran-1": "tikhotel:kish:abadgaran",
    "parmida-3": "tikhotel:kish:parmida",
    "toranj": "kish-toranj",
    "goldis-2": "tikhotel:kish:goldis",
    "gambron": "tikhotel:kish:gamberon",
    "vida": "kish-vida",
    "shayan-1": "tournegar:kish:206",
    "shaygan-1": "tournegar:kish:218",
    "ghoghnoos": "tikhotel:kish:ghoghnoos",
}

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ONE_NIGHT_PRICE = re.compile(
    r"شروع\s*قیمت\s*از\s*([\d۰-۹٠-٩,٬]+)\s*/\s*[1۱١]\s*شب\s*تومان"
)


def parse_asasafar(html: str, city: str, listing_url: str, observed_at: str) -> list[dict]:
    """Extract individually linked, priced Kish cards from one SSR city page."""
    if city != "kish" or urlsplit(listing_url).hostname not in {"www.asasafar.com", "asasafar.com"}:
        raise ValueError("AsaSafar parser is restricted to its Kish city listing")
    soup = BeautifulSoup(html, "html.parser")
    offers: list[dict] = []
    seen_slugs: set[str] = set()
    for card in soup.select('a[href^="/fa/hotels/"]'):
        title = card.select_one("h3")
        if title is None:
            continue
        match = _ONE_NIGHT_PRICE.search(card.get_text(" ", strip=True))
        if match is None:
            continue
        digits = match.group(1).translate(_DIGITS).replace(",", "").replace("٬", "")
        if not digits.isdecimal():
            continue
        price = int(digits)
        if price <= 0:
            continue
        linked_url = urljoin(listing_url, card["href"])
        parts = urlsplit(linked_url)
        if parts.hostname not in {"www.asasafar.com", "asasafar.com"} or not parts.path.startswith("/fa/hotels/"):
            continue
        # The card's date query is not a confirmed quote and will become stale.
        # AsaSafar serves these hotel detail pages without any query string.
        source_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        hotel_id = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
        if not hotel_id or hotel_id in seen_slugs:
            continue
        seen_slugs.add(hotel_id)
        name = title.get_text(" ", strip=True)
        if not name:
            continue
        offer = {
            "provider": PROVIDER,
            "provider_name": PROVIDER_NAME,
            "hotel_name": name,
            "hotel_id": hotel_id,
            "canonical_id": VERIFIED_KISH_CANONICAL_IDS.get(hotel_id, f"asasafar:kish:{hotel_id}"),
            "city": city,
            "stars": None,
            "price_toman": price,
            "price_basis": "per_night",
            "stay_nights": 1,
            "checkin": None,
            "checkout": None,
            "occupancy": None,
            "room_type": None,
            "board": None,
            "availability": "unknown",
            "offer_type": "hotel_listing",
            "price_note": "شروع قیمت یک شب در فهرست عمومی آسا سفر؛ نوع اتاق، ظرفیت و موجودی تأیید نشده و قیمت صفحهٔ هتل ممکن است متفاوت باشد.",
            "source_url": source_url,
            "listing_url": listing_url,
            "observed_at": observed_at,
        }
        # The hotel photo is a sibling of the details link in this card. Match
        # its alt text to the exact title so the cashback icon is never used.
        container = card.parent.parent if card.parent else None
        photo = container.find("img", alt=name) if container else None
        if photo and photo.get("src"):
            image_url = urljoin(listing_url, photo["src"])
            image_parts = urlsplit(image_url)
            if (image_parts.scheme == "https" and
                    image_parts.hostname in {"www.asasafar.com", "asasafar.com"} and
                    image_parts.path.startswith("/image/hotel/")):
                offer["image_url"] = image_url
        offers.append(offer)
    return offers
