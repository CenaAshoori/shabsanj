"""Compare public one-way ticket observations by route, mode, and date."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .outbound import cta_url
from .search import CITY_LABELS, REGION_CITY_IDS


MODES = {"flight": "هواپیما", "bus": "اتوبوس", "train": "قطار"}
DATED_FARE_MAX_AGE = timedelta(hours=12)
CITIES = {key: label for key, label in CITY_LABELS.items() if key not in REGION_CITY_IDS}
CITIES.update({
    "sari": "ساری", "qaemshahr": "قائم‌شهر", "babolsar": "بابلسر",
    "ahvaz": "اهواز", "bandar_abbas": "بندرعباس", "kerman": "کرمان",
    "hamadan": "همدان", "ardabil": "اردبیل",
})

# Use the provincial capital for catalog cities without a passenger airport.
# Ramsar and Nowshahr have their own airports, as does Kish.
CAPITAL_AIRPORTS = {
    "bandar_anzali": "rasht",
    "lahijan": "rasht",
    "astara": "rasht",
    "chalus": "sari",
    "babolsar": "sari",
    "qaemshahr": "sari",
}


def _fare(row: dict) -> int | None:
    amount = row.get("price_toman")
    return amount if type(amount) is int and amount > 0 else None


def _public_ticket(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    mode, origin, destination = (row.get(key) for key in ("mode", "origin", "destination"))
    if (mode not in MODES or origin not in CITIES or destination not in CITIES
            or origin == destination):
        return None
    fields = (
        "mode", "origin", "destination", "provider", "provider_name", "source_url",
        "observed_at", "departure_date", "departure_time", "arrival_time", "operator",
        "service_number", "service_class", "departure_terminal", "arrival_terminal", "duration_minutes",
        "seats_remaining", "seats_lower_bound", "availability", "offer_id", "price_note",
    )
    ticket = {key: row.get(key) for key in fields}
    ticket["stale"] = row.get("retained") is True
    ticket["price_toman"] = _fare(row)
    try:
        datetime.fromisoformat(ticket["observed_at"])
        if ticket["departure_date"] is not None:
            if date.fromisoformat(ticket["departure_date"]).isoformat() != ticket["departure_date"]:
                return None
    except (TypeError, ValueError):
        return None
    if ticket["price_toman"] is None and row.get("price_toman") is not None:
        return None
    seats = ticket["seats_remaining"]
    ticket["seats_remaining"] = seats if type(seats) is int and seats >= 0 else None
    lower_bound = ticket["seats_lower_bound"]
    ticket["seats_lower_bound"] = lower_bound if type(lower_bound) is int and lower_bound > 0 else None
    if ticket["availability"] not in ("available", "sold_out", "unknown"):
        ticket["availability"] = "available" if ticket["seats_remaining"] or ticket["seats_lower_bound"] else "unknown"
    ticket["outbound_url"] = cta_url("ticket", ticket)
    return ticket if ticket["outbound_url"] else None


def _tickets(catalog: dict) -> list[dict]:
    return [ticket for row in catalog["offers"] if (ticket := _public_ticket(row))]


def ticket_routes(catalog: dict) -> dict:
    routes: dict[tuple[str, str], set[str]] = {}
    for ticket in _tickets(catalog):
        routes.setdefault((ticket["origin"], ticket["destination"]), set()).add(ticket["mode"])
    return {
        "cities": [{"id": key, "label": label, "airport_city": CAPITAL_AIRPORTS.get(key, key)}
                   for key, label in CITIES.items()],
        "routes": [
            {"origin": origin, "destination": destination, "modes": sorted(modes)}
            for (origin, destination), modes in sorted(routes.items())
        ],
        "generated_at": catalog.get("generated_at"),
    }


def _rank(offers: list[dict], departure_date: str | None) -> dict:
    sellers: dict[str, dict] = {}
    for ticket in sorted(offers, key=lambda row: (row.get("stale", False), row["price_toman"], row["provider"])):
        sellers.setdefault(ticket["provider"], ticket)
    ranked = list(sellers.values())
    return {
        "basis": "dated" if departure_date else "route_starting_price",
        "departure_date": departure_date,
        "seller_count": len(ranked),
        "fresh_seller_count": sum(not row.get("stale") for row in ranked),
        "offers": ranked,
        "departures": sorted(
            (row for row in offers if departure_date and row["departure_time"]),
            key=lambda row: (row["departure_time"], row["price_toman"], row["provider"]),
        ),
    }


def search_tickets(catalog: dict, origin: str, destination: str,
                   departure_date: date | None = None, mode: str | None = None) -> dict:
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    today = now.date().isoformat()
    chosen = departure_date.isoformat() if departure_date else None
    tickets = _tickets(catalog)
    date_comparisons: dict[str, int] = {}
    results = []
    for kind, label in MODES.items():
        if mode and kind != mode:
            continue
        start, end = origin, destination
        if kind == "flight":
            start = CAPITAL_AIRPORTS.get(origin, origin)
            end = CAPITAL_AIRPORTS.get(destination, destination)
        route = (ticket for ticket in tickets if ticket["mode"] == kind
                 and ticket["origin"] == start and ticket["destination"] == end)
        sellers: dict[str, dict] = {}
        floors = []
        by_date: dict[str, list[dict]] = {}
        for ticket in route:
            day = ticket["departure_date"]
            if day is None:
                sellers[ticket["provider"]] = ticket
            if (ticket["price_toman"] is None or ticket["availability"] == "sold_out"
                    or ticket["seats_remaining"] == 0):
                continue
            if day is None:
                floors.append(ticket)
            elif day >= today and (day != today or _not_departed(ticket, now.time())):
                observed = datetime.fromisoformat(ticket["observed_at"])
                ticket["stale"] = ticket["stale"] or (
                    now - observed.replace(tzinfo=observed.tzinfo or timezone.utc) > DATED_FARE_MAX_AGE
                )
                by_date.setdefault(day, []).append(ticket)
        fresh_counts = {day: len({offer["provider"] for offer in offers if not offer["stale"]})
                        for day, offers in by_date.items()}
        for day, count in fresh_counts.items():
            date_comparisons[day] = max(date_comparisons.get(day, 0), count)
        default_day = min(by_date, key=lambda day: (-(min(fresh_counts[day], 2)), day), default=None)
        selected_day = chosen or default_day
        groups = []
        if selected_day in by_date:
            groups.append(_rank(by_date[selected_day], selected_day))
        if floors:
            groups.append(_rank(floors, None))
        # A seller link is useful when a dated fare is unavailable. Keep it
        # separate from the ranked set and favor the undated route page.
        ranked_providers = {ticket["provider"] for group in groups for ticket in group["offers"]}
        links = [ticket for key, ticket in sellers.items() if key not in ranked_providers]
        result = {"mode": kind, "label": label, "groups": groups, "links": links}
        if kind == "flight":
            result["airport_route"] = {
                "origin": start, "origin_label": CITIES[start],
                "destination": end, "destination_label": CITIES[end],
            }
        results.append(result)
    return {
        "origin": origin, "origin_label": CITIES[origin],
        "destination": destination, "destination_label": CITIES[destination],
        "date": chosen, "available_dates": sorted(date_comparisons),
        "compared_dates": sorted(day for day, count in date_comparisons.items() if count > 1),
        "modes": results, "generated_at": catalog.get("generated_at"),
    }


def _not_departed(ticket: dict, now: time) -> bool:
    value = ticket.get("departure_time")
    try:
        return not value or time.fromisoformat(value).replace(tzinfo=None) >= now
    except (TypeError, ValueError):
        return True
