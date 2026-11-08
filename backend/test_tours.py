"""Tour search contract and conservative hotel linking tests."""

import unittest

from .tours import linked_tour_counts, search_tours


HOTELS = [
    {
        "provider": "tournegar", "provider_name": "تورنگار",
        "hotel_id": "423", "canonical_id": "tehran-espinas-boulevard",
        "hotel_name": "هتل اسپیناس بلوار تهران", "city": "tehran", "stars": 5,
        "price_toman": 9_532_000, "price_basis": "per_night",
        "source_url": "https://example.org/hotel/423",
    },
]


def tour(tour_id, *, hotel_id="423", canonical="tehran-espinas-boulevard", hotel_name="هتل اسپیناس بلوار تهران", price=12_000_000, checkin="1405/08/16", transport="flight"):
    return {
        "provider": "tournegar", "provider_name": "تورنگار", "tour_id": tour_id,
        "title": f"تور تهران از مشهد {hotel_name}",
        "departure_city": "mashhad", "destination_city": "tehran",
        "provider_hotel_id": hotel_id, "canonical_hotel_id": canonical,
        "hotel_name": hotel_name,
        "departure_date": None, "return_date": None,
        "hotel_checkin_date": checkin, "duration_nights": 2,
        "price_toman": price, "price_basis": "per_person",
        "services": ["صبحانه", "ترانسفر"], "optional_services": ["گشت شهری"],
        "transport": transport,
        "source_url": f"https://example.org/tour/{tour_id}",
        "observed_at": "2026-11-05T08:00:00Z", "availability": "unknown",
    }


class TourSearchTests(unittest.TestCase):
    def test_exact_provider_hotel_crosswalk_and_city(self):
        tours = [
            tour("good"),
            tour("wrong-id", hotel_id="999"),
            tour("wrong-canonical", canonical="tehran-other"),
            tour("missing-id", hotel_id=None),
        ]
        result = search_tours(tours, HOTELS)
        self.assertIsNotNone(result["tours"][0]["hotel"])
        self.assertEqual(sum(item["hotel"] is not None for item in result["tours"]), 1)
        self.assertEqual(result["counts"]["linked_hotel_count"], 1)
        counts = linked_tour_counts([tour("good"), tour("good"), tour("bad", hotel_id="999")], HOTELS)
        self.assertEqual(counts, {"tehran:tehran-espinas-boulevard": 1})

    def test_verified_tour_only_id_links_to_other_provider_hotel(self):
        hotel = {
            "provider": "tikhotel", "hotel_id": "atlas", "canonical_id": "mashhad-atlas",
            "hotel_name": "هتل اطلس مشهد", "city": "mashhad", "stars": 4,
            "price_toman": 2_000_000, "price_basis": "per_night",
        }
        listing = tour("atlas", hotel_id="54", canonical="mashhad-atlas", hotel_name="هتل اطلس مشهد")
        listing["destination_city"] = "mashhad"
        listing["departure_city"] = "tehran"
        result = search_tours([listing], [hotel])
        self.assertEqual(result["tours"][0]["hotel"]["id"], "mashhad:mashhad-atlas")

    def test_city_intent_and_exact_jalali_checkin(self):
        tours = [tour("one"), tour("two", checkin="1405/08/20")]
        result = search_tours(tours, HOTELS, "تور تهران از مشهد", hotel_checkin_date="۱۴۰۵-۰۸-۱۶")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tours"][0]["tour_id"], "one")
        self.assertEqual(result["parsed_intent"]["departure_city"], "mashhad")
        self.assertEqual(result["parsed_intent"]["destination_city"], "tehran")
        self.assertEqual(result["filters"]["hotel_checkin_dates"], ["1405/08/16", "1405/08/20"])
        self.assertEqual(result["filters"]["departure_dates"], [])

    def test_unlinked_hotel_still_filterable_by_exact_name(self):
        tours = [tour("linked"), tour("unlinked", hotel_id="999", canonical=None, hotel_name="هتل فرضی تهران")]
        result = search_tours(tours, HOTELS, hotel_name="هتل فرضی تهران")
        self.assertEqual(result["total"], 1)
        self.assertIsNone(result["tours"][0]["hotel"])
        self.assertTrue(any(option["name"] == "هتل فرضی تهران" for option in result["filters"]["hotels"]))

    def test_numbered_hotel_name_does_not_match_other_properties(self):
        tours = [
            tour("one", hotel_id="1", canonical=None, hotel_name="هتل الماس تهران"),
            tour("two", hotel_id="2", canonical=None, hotel_name="هتل الماس ۲ تهران"),
        ]
        result = search_tours(tours, HOTELS, "هتل الماس ۲")
        self.assertEqual([item["tour_id"] for item in result["tours"]], ["two"])
        self.assertEqual(search_tours(tours, HOTELS, "تور تهران ۲ شب")["total"], 2)

    def test_coastal_destination_scope_and_conversational_query(self):
        tours = [tour("kish"), tour("anzali"), tour("rasht")]
        for listing, city in zip(tours, ("kish", "bandar_anzali", "rasht")):
            listing["destination_city"] = city
            listing["title"] = f"تور {city}"
        result = search_tours(tours, HOTELS, "می‌خوام برم کنار دریا")
        self.assertEqual({item["destination_city"] for item in result["tours"]}, {"kish", "bandar_anzali"})
        self.assertEqual(result["parsed_intent"]["destination_theme"], "coastal")
        north = search_tours(tours, HOTELS, "تور شمال ایران کنار دریا")
        self.assertEqual([item["destination_city"] for item in north["tours"]], ["bandar_anzali"])
        self.assertEqual(search_tours(tours, HOTELS, destination_city="گیلان")["total"], 2)
        alternatives = search_tours(tours, HOTELS, "ساحل شمال یا کیش")
        self.assertEqual({item["destination_city"] for item in alternatives["tours"]}, {"kish", "bandar_anzali"})
        self.assertEqual(alternatives["parsed_intent"]["destination_alternatives"], ["north", "kish"])
        self.assertIsNone(alternatives["parsed_intent"]["departure_city"])

    def test_service_means_included_not_optional(self):
        tours = [tour("one")]
        self.assertEqual(search_tours(tours, HOTELS, service="صبحانه")["total"], 1)
        self.assertEqual(search_tours(tours, HOTELS, service="گشت شهری")["total"], 0)

    def test_structured_plan_filters_name_service_and_transport(self):
        matching = tour("matching", hotel_id="999", canonical=None,
                        hotel_name="هتل الماس ۲ تهران", transport="train")
        matching["services"] = ["صبحانه بوفه رایگان"]
        other = tour("other", hotel_id="998", canonical=None,
                     hotel_name="هتل الماس تهران", transport="train")
        plan = {
            "departure_city": "mashhad", "destination_city": "tehran",
            "hotel_name": "الماس ۲", "service": "صبحانه", "transport": "train",
            "hotel_checkin_date": "1405/08/16", "max_price_toman": 13_000_000,
        }
        result = search_tours([matching, other], HOTELS, "arbitrary raw text", plan=plan)
        self.assertEqual([item["tour_id"] for item in result["tours"]], ["matching"])
        self.assertEqual(result["parsed_intent"]["hotel_name"], "الماس ۲")
        self.assertEqual(search_tours([matching, other], HOTELS, "", plan=plan,
                                      departure_city="tehran")["total"], 0)

    def test_hotel_id_and_price_sort(self):
        tours = [tour("expensive", price=15_000_000), tour("cheaper", price=10_000_000)]
        result = search_tours(tours, HOTELS, hotel_id="tehran:tehran-espinas-boulevard", sort="price")
        self.assertEqual([item["tour_id"] for item in result["tours"]], ["cheaper", "expensive"])
        self.assertEqual(search_tours(tours, HOTELS, max_price_toman=12_000_000)["total"], 1)


if __name__ == "__main__":
    unittest.main()
