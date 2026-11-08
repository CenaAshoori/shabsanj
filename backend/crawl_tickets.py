"""Refresh the public ticket snapshot without changing hotel or tour data."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path

from .bus_crawlers import crawl_buses
from .crawl import save_catalog
from .flight_crawlers import crawl_flights
from .train_crawlers import crawl_trains


def _source(row: dict) -> tuple:
    return tuple(row.get(field) for field in ("mode", "provider", "origin", "destination"))


def _retained_rows(status: dict, previous_offers: list[dict]) -> list[dict]:
    if not status.get("provider"):
        return [row for row in previous_offers if row.get("mode") == status["mode"]]
    url = status.get("url", "")
    return [
        row for row in previous_offers
        if _source(row) == _source(status)
        and ("?" not in url or row.get("listing_url") == url)
    ]


def _crawl_mode(mode: str, fetch) -> dict:
    try:
        return fetch()
    except Exception as exc:
        return {"offers": [], "source_status": [
            {"mode": mode, "status": "error", "error": str(exc), "offer_count": 0},
        ]}


def _refresh(output: Path, modes: list[str], crawlers: dict, *, quiet: bool) -> None:
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=len(modes)) as pool:
        futures = [pool.submit(_crawl_mode, mode, crawlers[mode]) for mode in modes]
        batches = [future.result() for future in futures]
    offers = [offer for batch in batches for offer in batch["offers"]]
    statuses = [status for batch in batches for status in batch["source_status"]]
    if not any(status["status"] == "ok" for status in statuses):
        failures = Counter((row.get("provider") or row["mode"], row.get("error", "")) for row in statuses)
        for (source, reason), count in failures.most_common(8):
            print(f"{started_at} {source} failed ({count} checks) {reason}")
        raise SystemExit("No ticket source completed successfully. Keeping the previous snapshot.")
    try:
        previous = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if isinstance(previous, dict):
        previous_offers = [row for row in previous.get("offers", []) if isinstance(row, dict)]
        for status in statuses:
            if status["status"] != "error":
                continue
            retained = _retained_rows(status, previous_offers)
            if retained:
                offers.extend({**row, "retained": True} for row in retained)
                status.update(status="retained", offer_count=len(retained))
        offers.extend(row for row in previous_offers if row.get("mode") not in modes)
        statuses.extend(row for row in previous.get("source_status", [])
                        if isinstance(row, dict) and row.get("mode") not in modes)
    if not offers:
        raise SystemExit("No ticket observations or seller links were collected.")
    snapshot = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "offers": offers, "source_status": statuses}
    save_catalog(output, snapshot)
    if not quiet:
        for status in statuses:
            print(status["mode"], status.get("provider", ""), status.get("origin", ""),
                  status.get("destination", ""), status["status"], status.get("offer_count", ""),
                  status.get("error", ""))
    checks = Counter(row["status"] for row in statuses if row["mode"] in modes)
    priced = sum(offer["price_toman"] is not None for offer in offers)
    print(f"{snapshot['generated_at']} {', '.join(modes)} checks {dict(checks)}. "
          f"Saved {priced} priced observations and {len(offers) - priced} seller links to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/tickets.json")
    crawlers = {
        "flight": lambda: crawl_flights(max_dated_days_per_route=60),
        "bus": crawl_buses,
        "train": crawl_trains,
    }
    parser.add_argument("--mode", action="append", choices=crawlers,
                        help="Refresh one mode. Repeat to refresh multiple modes.")
    parser.add_argument("--quiet", action="store_true", help="Only log a refresh summary.")
    args = parser.parse_args()
    modes = list(dict.fromkeys(args.mode or crawlers))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock file in place so later processes lock the same inode.
    with output.with_name(f".{output.name}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"Ticket refresh already running for {output}. Skipping this run.")
            return
        _refresh(output, modes, crawlers, quiet=args.quiet)


if __name__ == "__main__":
    main()
