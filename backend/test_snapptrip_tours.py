"""Snapptrip SSR package basis and exact hotel-ID join tests."""

import base64
import json
import unittest

from .snapptrip_tours import parse_snapptrip_tour_listing, snapptrip_hotel_index


URL = "https://www.snapptrip.com/tour/THR/KIH"


def page(*, group_price="۳۴,۹۱۷,۰۰۰", hotel_name="هتل پالاس"):
    metadata = {"metadata": {"hotel": {"checkIn": "2026-11-08", "checkOut": "2026-11-10"}}}
    solution = {
        "solutionId": base64.urlsafe_b64encode(json.dumps(metadata).encode()).decode(),
        "hotel": {"id": 2507, "name": hotel_name},
        "pricing": {"priceOff": 349_170_000},
        "fromDate": "2026-11-08", "toDate": "2026-11-10",
        "departureFlight": {"originCode": "THR", "destinationCode": "KIH", "departureDateTime": "2026-11-08T16:10"},
        "returningFlight": {"originCode": "KIH", "destinationCode": "THR", "departureDateTime": "2026-11-10T17:20"},
    }
    payload = {
        "query": {"origin": "THR", "dest": "KIH"},
        "props": {"pageProps": {
            "originData": {"iata_code": "THR"}, "destData": {"iata_code": "KIH"},
            "ssrResults": {"solutions": [solution]},
        }},
    }
    return (
        '<h1>تور جزیره کیش از تهران</h1>'
        '<div class="shadow-1 bg-background"><h2>هتل پالاس</h2>'
        '<div>شامل پرواز رفت و برگشت</div>'
        '<div>قیمت ۱ نفر (بلیط + اقامت) از</div>'
        '<div class="text-subtitle-1">۱۷,۴۵۸,۵۰۰ تومان</div>'
        f'<div>برای ۲ نفر <div class="text-body-2">{group_price} تومان</div></div>'
        '</div><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload, ensure_ascii=False) + '</script>'
    )


class SnapptripTourTests(unittest.TestCase):
    def test_visible_per_person_price_dates_and_exact_numeric_hotel_join(self):
        catalog = {"offers": [{
            "provider": "snapptrip", "city": "kish", "provider_numeric_id": 2507,
            "hotel_id": "هتل-پالاس", "canonical_id": "kish-palas",
        }]}
        index = snapptrip_hotel_index(catalog)
        tours = parse_snapptrip_tour_listing(page(), "tehran", "kish", "THR", "KIH", URL,
                                             "2026-11-05T00:00:00+00:00", index)
        self.assertEqual(len(tours), 1)
        tour = tours[0]
        self.assertEqual((tour["price_toman"], tour["group_price_toman"], tour["price_basis"]),
                         (17_458_500, 34_917_000, "per_person"))
        self.assertEqual((tour["departure_date"], tour["return_date"], tour["hotel_checkin_date"]),
                         ("1405/08/17", "1405/08/19", "1405/08/17"))
        self.assertEqual(tour["canonical_hotel_id"], "kish-palas")
        self.assertEqual(tour["source_url"], URL)
        self.assertEqual(tour["services"], ["پرواز رفت و برگشت", "اقامت 2 شب"])

    def test_rejects_unverified_price_or_route(self):
        with self.assertRaisesRegex(ValueError, "prices do not agree"):
            parse_snapptrip_tour_listing(page(group_price="۳۵,۰۰۰,۰۰۰"), "tehran", "kish", "THR", "KIH", URL,
                                         "2026-11-05T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "heading"):
            parse_snapptrip_tour_listing(page(), "mashhad", "kish", "MHD", "KIH", URL,
                                         "2026-11-05T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
