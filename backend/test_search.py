"""Focused tests for intent extraction and safe offer comparison."""

import unittest

from .search import normalized_nightly_price, parse_intent, search_catalog


def offer(provider, name, city, price, *, canonical=None, stars=5, basis="per_night"):
    return {
        "provider": provider,
        "provider_name": provider,
        "hotel_name": name,
        "hotel_id": f"{provider}-{name}",
        "canonical_id": canonical,
        "city": city,
        "stars": stars,
        "price_toman": price,
        "price_basis": basis,
        "stay_nights": None,
        "source_url": f"https://example.org/{provider}/{name}",
        "observed_at": "2026-11-05T08:00:00Z",
    }


class HotelSearchTests(unittest.TestCase):
    def test_provider_photo_is_available_even_when_its_rate_is_filtered_out(self):
        published = "https://store.snapptrip.com/domestic-hotel/123/front.jpg"
        rows = [
            {**offer("snapptrip", "هتل نمونه", "kish", 3_000_000, canonical="sample"),
             "image_url": published},
            {**offer("tournegar", "هتل نمونه", "kish", 2_000_000, canonical="sample"),
             "image_url": "https://tournegar.com.example.org/unsafe.jpg"},
        ]
        hotel = search_catalog(rows, max_price_toman=2_500_000)["hotels"][0]
        self.assertEqual(hotel["image_url"], published)
        self.assertEqual(len(hotel["offers"]), 1)
        self.assertIsNone(hotel["offers"][0]["image_url"])

    def test_persian_intent_with_digits_and_budget(self):
        intent = parse_intent("هتل ۵ ستاره مشهد زیر ۳ میلیون")
        self.assertEqual((intent.city, intent.stars, intent.max_price_toman), ("mashhad", 5, 3_000_000))
        self.assertEqual(intent.name_terms, ())
        separator_intent = parse_intent("هتل تهران زیر ۳٬۵۰۰٬۰۰۰ تومان")
        self.assertEqual(separator_intent.max_price_toman, 3_500_000)
        self.assertEqual(separator_intent.name_terms, ())
        self.assertEqual(parse_intent("بالای ۴ ستاره تهران").min_stars, 5)

    def test_word_budget_and_grouped_sources(self):
        listings = [
            offer("a", "هتل مجلل درویشی", "mashhad", 2_700_000, canonical="darvishi"),
            offer("b", "هتل درویشی مشهد", "mashhad", 2_900_000, canonical="darvishi"),
            offer("c", "هتل اسپیناس پالاس", "tehran", 2_000_000, canonical="espinas"),
        ]
        result = search_catalog(listings, "درویشی مشهد زیر سه میلیون")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["hotels"][0]["provider_count"], 2)
        self.assertEqual(result["hotels"][0]["best_offer"]["price_toman"], 2_700_000)
        self.assertEqual(result["hotels"][0]["city"], "مشهد")
        self.assertIn("درویشی", result["hotels"][0]["match_explanation"])

    def test_no_fuzzy_merging_without_verified_canonical_id(self):
        listings = [
            offer("a", "هتل هما", "tehran", 4_000_000),
            offer("b", "هتل هما", "tehran", 4_100_000),
        ]
        result = search_catalog(listings, "هتل هما تهران")
        self.assertEqual(result["total"], 2)
        self.assertTrue(all(hotel["provider_count"] == 1 for hotel in result["hotels"]))

    def test_known_price_basis_only(self):
        self.assertEqual(normalized_nightly_price({"price_toman": 5_000_000, "price_basis": "per_night"}), 5_000_000)
        self.assertEqual(normalized_nightly_price({"price_toman": 5_000_000, "price_basis": "stay_total", "stay_nights": 2}), 2_500_000)
        self.assertIsNone(normalized_nightly_price({"price_toman": 5_000_000, "price_basis": "unknown"}))

    def test_price_filter_and_sort(self):
        listings = [
            offer("a", "هتل ارغوان", "tehran", 6_000_000, canonical="arghavan", stars=4),
            offer("b", "هتل لاله", "tehran", 3_000_000, canonical="laleh", stars=5),
            offer("c", "هتل هما", "tehran", 2_000_000, canonical="homa", stars=3),
        ]
        result = search_catalog(listings, city="تهران", min_stars=4, max_price_toman=5_000_000, sort="best_price")
        self.assertEqual([hotel["name"] for hotel in result["hotels"]], ["هتل لاله"])

    def test_coastal_travel_intent_is_city_level_and_intersects_regions(self):
        cities = ["kish", "rasht", "bandar_anzali", "lahijan", "astara", "ramsar", "chalus", "nowshahr", "tehran"]
        listings = [offer("a", f"هتل نمونه {city}", city,
                          4_000_000 if city == "astara" else 2_000_000, canonical=city) for city in cities]
        sea = search_catalog(listings, "می‌خوام برم کنار دریا")
        self.assertEqual({hotel["city_id"] for hotel in sea["hotels"]},
                         {"kish", "bandar_anzali", "astara", "ramsar", "chalus", "nowshahr"})
        self.assertEqual(sea["parsed_intent"]["destination_theme"], "coastal")
        self.assertIn("فاصلهٔ هتل تا ساحل بررسی نشده", sea["location_disclaimer"])
        self.assertEqual(search_catalog(listings, "دوست دارم برم جایی که دریا داشته باشه")["total"], 6)
        conversational_budget = search_catalog(listings, "می‌خوام برم کنار دریا تا ۸ میلیون")
        self.assertEqual(conversational_budget["total"], 6)
        self.assertEqual(conversational_budget["parsed_intent"]["max_price_toman"], 8_000_000)
        alternatives = search_catalog(listings, "ساحل شمال یا کیش")
        self.assertEqual(alternatives["total"], 6)
        self.assertEqual(alternatives["parsed_intent"]["destination_alternatives"], ["north", "kish"])
        gilan = search_catalog(listings, "هتل‌های گیلان کنار دریا")
        self.assertEqual({hotel["city_id"] for hotel in gilan["hotels"]}, {"bandar_anzali", "astara"})
        affordable = search_catalog(listings, "می‌خوام برم گیلان کنار دریا زیر ۳ میلیون")
        self.assertEqual([hotel["city_id"] for hotel in affordable["hotels"]], ["bandar_anzali"])
        self.assertEqual(search_catalog(listings, "کنار دریا", city="تهران")["total"], 0)
        self.assertEqual(search_catalog(listings, "شمال ایران کنار دریا")["total"], 5)
        self.assertEqual(search_catalog(listings, "ساحل جنوب")["hotels"][0]["city_id"], "kish")

    def test_joined_split_city_and_hotel_name_disambiguation(self):
        listings = [
            offer("a", "هتل باران", "bandar_anzali", 2_000_000, canonical="baran"),
            offer("b", "هتل تهران مشهد", "mashhad", 2_000_000, canonical="tehran-mashhad"),
            offer("c", "هتل دریا تهران", "tehran", 2_000_000, canonical="darya-tehran"),
        ]
        for query in ("هتل باران بندرانزلی", "هتل باران بندر انزلی", "hotel in Bandar Anzali باران"):
            self.assertEqual(search_catalog(listings, query)["hotels"][0]["city_id"], "bandar_anzali")
        self.assertEqual(search_catalog(listings, "هتل تهران در مشهد")["hotels"][0]["id"], "mashhad:tehran-mashhad")
        self.assertEqual(search_catalog(listings, "هتل دریا تهران")["hotels"][0]["id"], "tehran:darya-tehran")
        self.assertEqual(parse_intent("هتل دوست کنار دریا").name_terms, ("دوست",))

    def test_offset_preserves_total(self):
        listings = [offer("a", f"هتل {number}", "tehran", 2_000_000, canonical=str(number)) for number in range(5)]
        first = search_catalog(listings, city="tehran", limit=2, offset=0)
        second = search_catalog(listings, city="tehran", limit=2, offset=2)
        self.assertEqual((first["total"], second["total"]), (5, 5))
        self.assertFalse({hotel["id"] for hotel in first["hotels"]} & {hotel["id"] for hotel in second["hotels"]})

    def test_structured_plan_preserves_numbered_hotel_and_ui_filters(self):
        listings = [
            offer("a", "هتل الماس مشهد", "mashhad", 3_000_000, canonical="almas"),
            offer("a", "هتل الماس ۲ مشهد", "mashhad", 4_000_000, canonical="almas-2"),
            offer("a", "هتل الماس ۲ تهران", "tehran", 5_000_000, canonical="almas-2-tehran"),
        ]
        plan = {"city_id": "mashhad", "hotel_name": "الماس ۲", "sort": "price"}
        result = search_catalog(listings, "query text ignored by data filter", plan=plan)
        self.assertEqual([hotel["id"] for hotel in result["hotels"]], ["mashhad:almas-2"])
        self.assertEqual(result["parsed_intent"]["hotel_name"], "الماس ۲")
        explicit = search_catalog(listings, "", city="تهران", plan=plan)
        self.assertEqual([hotel["id"] for hotel in explicit["hotels"]], ["tehran:almas-2-tehran"])
        self.assertEqual(parse_intent("هتل الماس ۲ مشهد").name_terms, ("الماس", "2"))

    def test_english_coastal_budget_fallback(self):
        intent = parse_intent("sea under 8 million")
        self.assertEqual(intent.destination_theme, "coastal")
        self.assertEqual(intent.max_price_toman, 8_000_000)
        self.assertEqual(intent.name_terms, ())

    def test_verified_tour_filter_precedes_pagination_and_false_overrides_prompt(self):
        listings = [
            offer("a", "هتل اول مشهد", "mashhad", 2_000_000, canonical="one"),
            offer("a", "هتل دوم مشهد", "mashhad", 3_000_000, canonical="two"),
        ]
        counts = {"mashhad:two": 2}
        result = search_catalog(listings, "هتل با تور مشهد", tour_counts=counts, limit=1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["hotels"][0]["id"], "mashhad:two")
        self.assertEqual(result["hotels"][0]["tour_count"], 2)
        self.assertEqual(result["parsed_intent"]["name_terms"], [])
        self.assertEqual(search_catalog(listings, "هتل با تور مشهد", tour_counts=counts,
                                        has_tours=False)["total"], 2)
        self.assertFalse(search_catalog(listings, "", tour_counts=counts, plan={"has_tours": True},
                                        has_tours=False)["parsed_intent"]["has_tours"])

    def test_property_pin_requires_local_non_placeholder_coordinate(self):
        valid = offer("snapptrip", "هتل پانوراما کیش", "kish", 5_000_000)
        valid.update({
            "provider_numeric_id": 2347,
            "latitude": 26.543316,
            "longitude": 54.015818,
            "location_accuracy": "property",
            "source_url": "https://www.snapptrip.com/رزرو-هتل/کیش/هتل-پانوراما",
        })
        hotel = search_catalog([valid], city="kish")["hotels"][0]
        self.assertEqual(hotel["location"]["latitude"], 26.543316)
        self.assertEqual(hotel["location"]["provider"], "snapptrip")
        self.assertNotIn("latitude", hotel["offers"][0])

        invalid = dict(valid, city="mashhad", latitude=35.696814, longitude=51.3498186)
        self.assertIsNone(search_catalog([invalid], city="mashhad")["hotels"][0]["location"])


if __name__ == "__main__":
    unittest.main()
