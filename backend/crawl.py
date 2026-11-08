"""Refresh data/catalog.json from the providers' public city pages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .crawlers import SOURCES, crawl


def retain_failed_sources(data: dict, previous: dict | None) -> dict:
    """Keep last observed offers where a provider/city refresh failed."""
    if not isinstance(previous, dict) or not isinstance(previous.get("offers"), list):
        return data
    previous_offers: dict[tuple[str, str], list[dict]] = {}
    for offer in previous["offers"]:
        if isinstance(offer, dict) and offer.get("provider") and offer.get("city"):
            key = (offer["provider"], offer["city"])
            previous_offers.setdefault(key, []).append(offer)
    previous_status = {
        (item.get("provider"), item.get("city")): item
        for item in previous.get("source_status", [])
        if isinstance(item, dict)
    }
    for status in data["source_status"]:
        if status.get("status") != "error":
            continue
        key = (status.get("provider"), status.get("city"))
        retained = previous_offers.get(key, [])
        if not retained:
            continue
        data["offers"].extend(retained)
        attempted_at = status.get("observed_at")
        old_status = previous_status.get(key, {})
        status.update({
            "status": "retained",
            "offer_count": len(retained),
            "observed_at": old_status.get("observed_at") or retained[0].get("observed_at"),
            "refresh_attempted_at": attempted_at,
        })
    return data


def retain_unselected_providers(data: dict, previous: dict | None, selected: set[str] | None) -> dict:
    """A provider-only refresh must preserve other providers and timestamps."""
    if selected is None or not isinstance(previous, dict):
        return data
    data["offers"].extend(
        offer for offer in previous.get("offers", [])
        if isinstance(offer, dict) and offer.get("provider") not in selected
    )
    data["source_status"].extend(
        status for status in previous.get("source_status", [])
        if isinstance(status, dict) and status.get("provider") not in selected
    )
    return data


def save_catalog(output: Path, data: dict) -> None:
    """Atomically replace one catalog without sharing a temp filename."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/catalog.json")
    parser.add_argument("--max-per-city", type=int, default=40)
    parser.add_argument("--provider", action="append", choices=sorted(SOURCES),
                        help="Refresh only this provider; may be repeated. Other saved providers are retained.")
    args = parser.parse_args()
    if args.max_per_city < 1:
        parser.error("--max-per-city must be positive")
    selected = set(args.provider) if args.provider else None
    data = crawl(max_per_city=args.max_per_city, providers=selected)
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = None
    data = retain_failed_sources(data, previous)
    data = retain_unselected_providers(data, previous, selected)
    if not data["offers"]:
        raise SystemExit("No offers fetched or retained; existing catalog was preserved")
    save_catalog(args.output, data)
    for source in data["source_status"]:
        print(source["provider"], source["city"], source["status"], source["offer_count"],
              source.get("error", ""))
    print(f"Saved {len(data['offers'])} offers to {args.output}")


if __name__ == "__main__":
    main()
