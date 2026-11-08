"""Provenance checks for the public bus-card adapter."""

from __future__ import annotations

import json
import unittest
from urllib.robotparser import RobotFileParser

import httpx

from backend.bus_crawlers import (
    _HostRequestGate,
    _crawl_route,
    _future_redbilit_date_links,
    _route_url,
    _safar724_route_codes,
    parse_redbilit_route,
    parse_safar724_fares,
)


class BusCrawlerTests(unittest.TestCase):
    def test_redbilit_card_requires_a_dated_exact_route_and_preserves_stops(self):
        html = """
            <h1>بلیط اتوبوس تهران به اصفهان</h1>
            <span class="rb-datepicker__value" data-dp-label>۱۵ آبان ۱۴۰۵</span>
            <article class="rb-bus-card">
              <div class="rb-bus-card__stop is-from"><em>تهران</em><small>بیهقی</small></div>
              <div class="rb-bus-card__stop is-to"><em>اصفهان</em><small>شهرضا</small></div>
              <div class="rb-bus-card__when"><b>۰۶:۰۰</b><span>جمعه ۱۵ آبان</span></div>
              <div class="rb-bus-card__company-text"><strong>همسفر</strong><small>مان V.I.P</small></div>
              <div class="rb-bus-card__seats">۲۶ صندلی خالی</div>
              <div class="rb-bus-card__price"><strong>۷۱۲,۰۰۰</strong></div>
              <a class="rb-bus-card__cta" href="/bus/service/552664">ادامه رزرو</a>
            </article>
            <article class="rb-bus-card">
              <div class="rb-bus-card__stop is-from"><em>تهران</em></div>
              <div class="rb-bus-card__stop is-to"><em>شیراز</em></div>
              <div class="rb-bus-card__when"><b>۰۷:۰۰</b><span>جمعه ۱۵ آبان</span></div>
              <div class="rb-bus-card__seats">۲۰ صندلی خالی</div>
              <div class="rb-bus-card__price"><strong>۵۰۰,۰۰۰</strong></div>
              <a class="rb-bus-card__cta" href="/bus/service/123">ادامه رزرو</a>
            </article>
        """
        offers = parse_redbilit_route(
            html, "tehran", "isfahan", _route_url("redbilit", "tehran", "isfahan"),
            "2026-11-06T09:00:00+00:00",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["departure_date"], "2026-11-06")
        self.assertEqual(offers[0]["price_toman"], 712000)
        self.assertEqual(offers[0]["seats_remaining"], 26)
        self.assertEqual(offers[0]["departure_terminal"], "بیهقی")
        self.assertEqual(offers[0]["arrival_terminal"], "شهرضا")
        self.assertEqual(offers[0]["source_url"], "https://redbilit.com/bus/service/552664")

    def test_future_links_are_same_route_later_dates_and_capped(self):
        url = _route_url("redbilit", "tehran", "isfahan")
        html = """
            <span class="rb-datepicker__value" data-dp-label>۱۵ آبان ۱۴۰۵</span>
            <a class="rb-dates__day" href="?date=1405%2F08%2F15">today</a>
            <a class="rb-dates__day" href="https://elsewhere.example/bus/tehran-esfahan?date=1405%2F08%2F16">foreign</a>
            <a class="rb-dates__day" href="?date=1405%2F08%2F16">tomorrow</a>
            <a class="rb-dates__day" href="?date=1405%2F08%2F17">day after</a>
            <a class="rb-dates__day" href="?date=1405%2F08%2F18">later</a>
        """
        self.assertEqual(
            _future_redbilit_date_links(html, url, 3),
            [
                f"{url}?date=1405%2F08%2F16",
                f"{url}?date=1405%2F08%2F17",
                f"{url}?date=1405%2F08%2F18",
            ],
        )

    def test_safar724_city_codes_are_verified_against_route_page(self):
        metadata = {
            "origin": {"engName": "tehran", "faName": "تهران", "code": "11320000"},
            "destination": {"engName": "mashhad", "faName": "مشهد", "code": "31310000"},
        }
        page = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).replace('"', r'\"')
        self.assertEqual(
            _safar724_route_codes(page, "tehran", "mashhad"),
            ("11320000", "31310000"),
        )
        with self.assertRaises(ValueError):
            _safar724_route_codes(page, "mashhad", "tehran")

    def test_safar724_fares_require_exact_date_destination_seats_and_rial_units(self):
        payload = {
            "date": "1405-08-16", "originCode": "11320000",
            "destinationCode": "31310000", "originEnglishName": "tehran",
            "destinationEnglishName": "mashhad", "originPersianName": "تهران",
            "destinationPersianName": "مشهد", "items": [],
        }
        valid = {
            "id": 40439834, "price": 13150000, "availableSeatCount": 22,
            "status": "Available", "vehicleType": "Bus", "departureDate": "1405/08/16",
            "departureTime": "06:00", "destinationCode": "31310000", "originCode": None,
            "companyPersianName": "گیتی نورد", "busType": "VIP",
            "originTerminalPersianName": "جنوب", "destinationTerminalPersianName": "امام رضا",
        }
        payload["items"] = [
            valid,
            {**valid, "id": 2, "availableSeatCount": 0},
            {**valid, "id": 3, "destinationCode": "31360000"},
            {**valid, "id": 4, "departureDate": "1405/08/17"},
            {**valid, "id": 5, "price": 13150001},
        ]
        page_url = "https://safar724.com/bus/tehran-mashhad?date=1405-08-16"
        api_url = "https://service.safar724.com/cs/api/bus/route?date=1405-08-16&origin=11320000&destination=31310000&vehicleType=Bus"
        offers = parse_safar724_fares(
            payload, "tehran", "mashhad", "11320000", "31310000",
            "1405-08-16", "2026-11-07", page_url, api_url,
            "2026-11-06T09:00:00+00:00",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price_toman"], 1315000)
        self.assertEqual(offers[0]["seats_remaining"], 22)
        self.assertEqual(offers[0]["departure_date"], "2026-11-07")
        self.assertEqual(offers[0]["source_url"], page_url)

    def test_redbilit_429_stops_host_and_marks_remaining_checks_as_errors(self):
        url = _route_url("redbilit", "tehran", "rasht")
        html = """
            <h1>بلیط اتوبوس تهران به رشت</h1>
            <span class="rb-datepicker__value" data-dp-label>۱۵ آبان ۱۴۰۵</span>
            <p>سرویسی پیدا نشد</p>
            <a class="rb-dates__day" href="?date=1405%2F08%2F16">شنبه</a>
            <a class="rb-dates__day" href="?date=1405%2F08%2F17">یکشنبه</a>
        """
        calls = []

        def respond(request):
            calls.append(str(request.url))
            return httpx.Response(200, text=html) if not request.url.query else httpx.Response(429)

        robots = RobotFileParser()
        robots.allow_all = True
        gate = _HostRequestGate("redbilit.com", min_gap_seconds=0)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            offers, statuses = _crawl_route(
                client, robots, None, "redbilit", "redbilit.com",
                "tehran", "rasht", redbilit_gate=gate,
            )
            _, skipped_statuses = _crawl_route(
                client, robots, None, "redbilit", "redbilit.com",
                "rasht", "tehran", redbilit_gate=gate,
            )
        self.assertEqual(calls, [url, f"{url}?date=1405%2F08%2F16"])
        self.assertEqual([row["status"] for row in statuses], ["ok", "error", "error"])
        self.assertEqual(statuses[2]["url"], f"{url}?date=1405%2F08%2F17")
        self.assertEqual(skipped_statuses[0]["status"], "error")
        self.assertEqual(len(offers), 1)  # The route landing link survives.


if __name__ == "__main__":
    unittest.main()
