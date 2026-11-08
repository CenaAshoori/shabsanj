"""Ticket comparison contract using fixed public observations, without crawling."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from .app import app
from .outbound import ClickCounter
from .tickets import search_tickets, ticket_routes


def ticket(provider: str, price: int | None, *, departure_date: str | None = None,
           mode: str = "flight", suffix: str = "route") -> dict:
    return {
        "mode": mode, "origin": "tehran", "destination": "kish",
        "provider": provider, "provider_name": provider,
        "source_url": f"https://{provider}.com/tickets/{suffix}",
        "observed_at": "2026-11-06T08:00:00+00:00",
        "departure_date": departure_date, "departure_time": None,
        "operator": None, "service_class": None,
        "price_toman": price, "price_note": None,
    }


class TicketSearchTests(unittest.TestCase):
    def test_ground_departures_keep_times_and_sort_by_departure(self):
        rail = {**ticket("fadak", 3_590_000, mode="train", departure_date="2099-01-10"),
                "destination": "sari", "source_url": "https://www.fadaktrains.com/train/example",
                "departure_time": "19:50", "arrival_time": "21:10", "duration_minutes": 80}
        catalog = {"offers": [
            rail,
            {**rail, "price_toman": 3_650_000, "departure_time": "01:40",
             "arrival_time": "03:00"},
        ]}
        result = search_tickets(catalog, "tehran", "sari")
        group = result["modes"][2]["groups"][0]
        self.assertEqual(group["seller_count"], 1)
        self.assertEqual(group["offers"][0]["departure_time"], "19:50")
        self.assertEqual([row["departure_time"] for row in group["departures"]], ["01:40", "19:50"])
        self.assertEqual(group["departures"][0]["duration_minutes"], 80)
        cities = {row["id"]: row["airport_city"] for row in ticket_routes(catalog)["cities"]}
        self.assertEqual(cities["babolsar"], "sari")

    def test_capital_airports_resolve_both_ends_for_flights_only(self):
        catalog = {"offers": [
            {**ticket("rahig", 2_000_000), "origin": "rasht", "destination": "sari"},
            {**ticket("redbilit", 500_000, mode="bus"), "origin": "bandar_anzali", "destination": "chalus"},
            {**ticket("redbilit", 200_000, mode="bus"), "origin": "rasht", "destination": "sari"},
        ]}
        result = search_tickets(catalog, "bandar_anzali", "chalus")
        self.assertEqual((result["origin"], result["destination"]), ("bandar_anzali", "chalus"))
        flight, bus, train = result["modes"]
        self.assertEqual(flight["airport_route"], {
            "origin": "rasht", "origin_label": "رشت",
            "destination": "sari", "destination_label": "ساری",
        })
        self.assertEqual(flight["groups"][0]["offers"][0]["origin"], "rasht")
        self.assertEqual(bus["groups"][0]["offers"][0]["price_toman"], 500_000)
        self.assertNotIn("airport_route", bus)
        self.assertNotIn("airport_route", train)

    def test_shared_airport_and_cities_with_local_airports(self):
        result = search_tickets({"offers": []}, "lahijan", "astara", mode="flight")
        flight = result["modes"][0]
        self.assertEqual(flight["airport_route"]["origin"], "rasht")
        self.assertEqual(flight["airport_route"]["destination"], "rasht")
        self.assertEqual(flight["groups"], [])
        by_city = {row["id"]: row["airport_city"] for row in ticket_routes({"offers": []})["cities"]}
        self.assertEqual(by_city["bandar_anzali"], "rasht")
        self.assertEqual(by_city["chalus"], "sari")
        for city in ("kish", "rasht", "ramsar", "nowshahr", "tehran", "mashhad"):
            self.assertEqual(by_city[city], city)

    def test_dated_fares_and_route_starting_prices_remain_separate(self):
        catalog = {"offers": [
            ticket("rahig", 2_000_000, departure_date="2099-01-10", suffix="dated"),
            ticket("tikotrip", 1_700_000, departure_date="2099-01-12", suffix="later"),
            ticket("redbilit", 900_000, suffix="undated"),
        ]}
        default = search_tickets(catalog, "tehran", "kish")
        flight = default["modes"][0]
        self.assertEqual(default["available_dates"], ["2099-01-10", "2099-01-12"])
        self.assertEqual([(group["basis"], group["departure_date"])
                          for group in flight["groups"]],
                         [("dated", "2099-01-10"), ("route_starting_price", None)])
        self.assertEqual([offer["price_toman"] for group in flight["groups"]
                          for offer in group["offers"]], [2_000_000, 900_000])

        chosen = search_tickets(catalog, "tehran", "kish", date(2099, 1, 12))
        self.assertEqual(chosen["modes"][0]["groups"][0]["offers"][0]["provider"], "tikotrip")
        self.assertEqual(chosen["modes"][0]["groups"][1]["basis"], "route_starting_price")

    def test_cheapest_offer_per_seller_is_ranked_within_each_group(self):
        catalog = {"offers": [
            ticket("rahig", 2_000_000, departure_date="2099-01-10", suffix="high"),
            ticket("rahig", 1_600_000, departure_date="2099-01-10", suffix="low"),
            ticket("tikotrip", 1_800_000, departure_date="2099-01-10"),
            ticket("rahig", 1_200_000, suffix="route-high"),
            ticket("rahig", 1_100_000, suffix="route-low"),
        ]}
        groups = search_tickets(catalog, "tehran", "kish")["modes"][0]["groups"]
        self.assertEqual(groups[0]["seller_count"], 2)
        self.assertEqual([(offer["provider"], offer["price_toman"])
                          for offer in groups[0]["offers"]],
                         [("rahig", 1_600_000), ("tikotrip", 1_800_000)])
        self.assertEqual(groups[1]["seller_count"], 1)
        self.assertEqual(groups[1]["offers"][0]["price_toman"], 1_100_000)

    def test_unpriced_provider_is_a_link_never_a_ranked_offer(self):
        catalog = {"offers": [
            ticket("rahig", None, suffix="unpriced"),
            ticket("tikotrip", 1_500_000, departure_date="2099-01-10"),
        ]}
        flight = search_tickets(catalog, "tehran", "kish")["modes"][0]
        self.assertEqual([offer["provider"] for group in flight["groups"]
                          for offer in group["offers"]], ["tikotrip"])
        self.assertEqual([offer["provider"] for offer in flight["links"]], ["rahig"])
        self.assertIsNone(flight["links"][0]["price_toman"])
        self.assertTrue(flight["links"][0]["outbound_url"].startswith("/go/ticket/"))

    def test_only_recent_available_offers_count_towards_a_dated_comparison(self):
        now = datetime.now(timezone.utc)
        day = "2099-01-10"
        redbilit = ticket("redbilit", 700_000, mode="bus", departure_date=day)
        safar = ticket("safar724", 800_000, mode="bus", departure_date=day)
        catalog = {"offers": [
            {**redbilit, "observed_at": (now - timedelta(hours=13)).isoformat(), "seats_remaining": 5},
            {**safar, "observed_at": now.isoformat(), "seats_remaining": 2},
            {**safar, "observed_at": now.isoformat(), "seats_remaining": 0, "price_toman": 300_000},
            {**safar, "observed_at": now.isoformat(), "availability": "sold_out", "price_toman": 100_000},
        ]}
        result = search_tickets(catalog, "tehran", "kish", mode="bus")
        group = result["modes"][0]["groups"][0]
        self.assertEqual(result["compared_dates"], [])
        self.assertEqual(group["fresh_seller_count"], 1)
        self.assertEqual([row["price_toman"] for row in group["offers"]], [800_000, 700_000])
        self.assertTrue(group["offers"][1]["stale"])

        catalog["offers"][0].update(observed_at=now.isoformat(), retained=True)
        result = search_tickets(catalog, "tehran", "kish", mode="bus")
        self.assertEqual(result["compared_dates"], [])

        catalog["offers"][0].pop("retained")
        result = search_tickets(catalog, "tehran", "kish", mode="bus")
        self.assertEqual(result["compared_dates"], [day])
        self.assertEqual(result["modes"][0]["groups"][0]["offers"][0]["price_toman"], 700_000)

    def test_ticket_redirect_records_click_in_isolated_database(self):
        catalog = {"offers": [ticket("rahig", 1_500_000, suffix="click")]}
        with TemporaryDirectory() as directory:
            db = Path(directory) / "analytics.sqlite3"
            with patch("backend.app.load_ticket_catalog", return_value=catalog), \
                    patch("backend.app.CLICK_COUNTER", ClickCounter(db)), \
                    TestClient(app) as client:
                offer = client.get("/api/tickets", params={
                    "origin": "tehran", "destination": "kish",
                }).json()["modes"][0]["groups"][0]["offers"][0]
                response = client.get(offer["outbound_url"], follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], offer["source_url"])
                stats = client.get("/api/analytics/outbound").json()
                self.assertEqual(stats["by_kind"]["ticket"], 1)
                self.assertEqual(stats["total"], 1)


if __name__ == "__main__":
    unittest.main()
