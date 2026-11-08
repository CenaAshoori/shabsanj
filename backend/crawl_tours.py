"""Refresh data/tours.json from bounded public tour route pages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .crawl import save_catalog
from .snapptrip_tours import ROUTES as SNAPPTRIP_ROUTES, crawl_snapptrip_tours
from .tour_crawlers import crawl_tours


def retain_failed_routes(data: dict, previous: dict | None) -> dict:
    """Keep previously observed route offers if a route fails to refresh."""
    if not isinstance(previous, dict) or not isinstance(previous.get("tours"), list):
        return data
    previous_tours: dict[tuple[str, str], list[dict]] = {}
    for tour in previous["tours"]:
        if isinstance(tour, dict) and tour.get("provider") and tour.get("listing_url"):
            key = (tour["provider"], tour["listing_url"])
            previous_tours.setdefault(key, []).append(tour)
    previous_status = {
        (item.get("provider"), item.get("url")): item
        for item in previous.get("source_status", [])
        if isinstance(item, dict)
    }
    for status in data["source_status"]:
        if status.get("status") != "error":
            continue
        key = (status.get("provider"), status.get("url"))
        existing_ids = {tour.get("tour_id") for tour in data["tours"]}
        retained = [tour for tour in previous_tours.get(key, [])
                    if tour.get("tour_id") not in existing_ids]
        if not retained:
            continue
        data["tours"].extend(retained)
        attempted_at = status.get("observed_at")
        status.update({
            "status": "retained", "tour_count": len(retained),
            "observed_at": previous_status.get(key, {}).get("observed_at") or retained[0].get("observed_at"),
            "refresh_attempted_at": attempted_at,
        })
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--output", type=Path, default=root / "data/tours.json")
    parser.add_argument("--hotel-catalog", type=Path, default=root / "data/catalog.json")
    parser.add_argument("--max-hotels-per-route", type=int, default=20)
    args = parser.parse_args()
    if args.max_hotels_per_route < 1:
        parser.error("--max-hotels-per-route must be positive")
    try:
        hotel_catalog = json.loads(args.hotel_catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        hotel_catalog = None
    data = crawl_tours(hotel_catalog, max_hotels_per_route=args.max_hotels_per_route)
    try:
        snapptrip = crawl_snapptrip_tours(hotel_catalog)
    except Exception as exc:
        # A robots or network failure must not erase an existing provider.
        snapptrip = {
            "source_status": [{
                "provider": "snapptrip", "departure_city": origin,
                "destination_city": destination, "url": url,
                "source_type": "route_listing", "status": "error", "tour_count": 0,
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": f"{type(exc).__name__}: {exc}"[:200],
            } for origin, destination, _origin_code, _destination_code, url in SNAPPTRIP_ROUTES],
            "tours": [],
        }
    data["source_status"].extend(snapptrip["source_status"])
    data["tours"].extend(snapptrip["tours"])
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = None
    data = retain_failed_routes(data, previous)
    data["tours"] = list({(tour["provider"], tour["tour_id"]): tour for tour in data["tours"]}.values())
    if not data["tours"]:
        raise SystemExit("No tours fetched or retained; existing snapshot was preserved")
    save_catalog(args.output, data)
    for status in data["source_status"]:
        print(status["departure_city"], status["destination_city"], status["status"],
              status["tour_count"], status.get("error", ""))
    print(f"Saved {len(data['tours'])} tours to {args.output}")


if __name__ == "__main__":
    main()
