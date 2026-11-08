"""Checks that published Fadak fares match the visible public ticket cards."""

import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import httpx

from backend.rail_fares import ROUTES, crawl_rail_fares, parse_fadak, route_url


def page(*, price="۳٬۵۹۰٬۰۰۰", departure="2026-11-07T00:00:00", rows=True,
         seats=None, visible_seats=None):
    ticket = {
        "origin": "تهران", "destination": "مشهد",
        "goingDate": "2026-11-06", "goingExitDate": departure,
        "originMoveTime": "01:40", "timeOfArrivalToDestination": "12:15",
        "discountPrice": 35900000, "price": 40000000,
        "ownerName": "فدک", "wagonName": "اکونومی", "travelDuration": 635,
    }
    if seats is not None:
        ticket["seatCount"] = seats
    state = {"props": {"pageProps": {
        "route": {"originKey": "tehran", "destinationKey": "mashhad"},
        "available": [ticket] if rows else [],
        "calendarDates": [{"goingDate": "2026-11-07", "label": "شنبه ۱۶ آبان"}],
    }}}
    capacity = f" ظرفیت: {visible_seats} صندلی" if visible_seats is not None else ""
    card = (f'<div class="available-card">شنبه ۱۶ آبان 01:40 تهران '
            f'12:15 مشهد اکونومی{capacity} هر نفر {price} تومان</div>') if rows else ""
    return ("<h1>بلیط قطار تهران مشهد</h1>"
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(state, ensure_ascii=False)}</script>'
            + card)


class FadakFareTests(unittest.TestCase):
    def test_departure_date_is_going_exit_date_and_price_is_per_person_toman(self):
        offers = parse_fadak(page(), "tehran", "mashhad", route_url("tehran", "mashhad"),
                             "2026-11-06T00:00:00Z", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["departure_date"], "2026-11-07")
        self.assertEqual(offers[0]["price_toman"], 3590000)
        self.assertEqual(offers[0]["departure_time"], "01:40")
        self.assertEqual(offers[0]["source_type"], "dated_ticket_listing")
        self.assertNotIn("seats_remaining", offers[0])

    def test_visible_price_disagreement_rejects_ticket(self):
        with self.assertRaisesRegex(ValueError, "visible-card validation"):
            parse_fadak(page(price="۳٬۵۰۰٬۰۰۰"), "tehran", "mashhad",
                         route_url("tehran", "mashhad"), "2026-11-06T00:00:00Z",
                         today=date(2026, 11, 6))

    def test_exact_visible_seats_match_embedded_count(self):
        offers = parse_fadak(page(seats=4, visible_seats="۴"), "tehran", "mashhad",
                             route_url("tehran", "mashhad"), "2026-11-06T00:00:00Z",
                             today=date(2026, 11, 6))
        self.assertEqual(offers[0]["seats_remaining"], 4)
        self.assertEqual(offers[0]["availability"], "available")
        self.assertNotIn("seats_lower_bound", offers[0])

    def test_capped_visible_seats_only_publish_lower_bound(self):
        offers = parse_fadak(page(seats=61, visible_seats="۲۴+"), "tehran", "mashhad",
                             route_url("tehran", "mashhad"), "2026-11-06T00:00:00Z",
                             today=date(2026, 11, 6))
        self.assertEqual(offers[0]["seats_lower_bound"], 24)
        self.assertEqual(offers[0]["availability"], "available")
        self.assertNotIn("seats_remaining", offers[0])

    def test_mismatched_seats_are_not_published(self):
        offers = parse_fadak(page(seats=5, visible_seats="۴"), "tehran", "mashhad",
                             route_url("tehran", "mashhad"), "2026-11-06T00:00:00Z",
                             today=date(2026, 11, 6))
        self.assertNotIn("seats_remaining", offers[0])
        self.assertEqual(offers[0]["availability"], "unknown")

    def test_no_current_cards_produces_no_fare(self):
        self.assertEqual(parse_fadak(page(rows=False), "tehran", "mashhad",
                                     route_url("tehran", "mashhad"), "2026-11-06T00:00:00Z",
                                     today=date(2026, 11, 6)), [])

    def test_robots_fetch_failure_returns_error_statuses(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.side_effect = httpx.ConnectError("offline")
        with patch("backend.rail_fares.httpx.Client", return_value=client):
            result = crawl_rail_fares()
        self.assertEqual(result["offers"], [])
        self.assertEqual(len(result["source_status"]), len(ROUTES))
        self.assertTrue(all(row["status"] == "error" for row in result["source_status"]))


if __name__ == "__main__":
    unittest.main()
