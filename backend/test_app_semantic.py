"""HTTP contract for optional semantic planning and filter precedence."""

import importlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


backend_app = importlib.import_module("backend.app")


class SemanticRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend_app.app)

    def test_hotel_route_uses_plan_but_explicit_filters_win(self):
        plan = {"city_id": "mashhad", "sort": "price"}
        with patch.object(backend_app, "_query_plan", return_value=(plan, "openrouter")):
            response = self.client.get("/api/search", params={"q": "opaque query", "city": "tehran", "sort": "stars"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["interpretation_source"], "openrouter")
        self.assertEqual(payload["parsed_intent"]["city_id"], "tehran")
        self.assertEqual(payload["sort"], "stars")
        self.assertTrue(all(hotel["city_id"] == "tehran" for hotel in payload["hotels"]))

    def test_tour_route_uses_plan_and_fallback_is_visible(self):
        plan = {"departure_city": "mashhad", "destination_city": "tehran", "service": "صبحانه", "sort": "price"}
        with patch.object(backend_app, "_query_plan", return_value=(plan, "openrouter")):
            response = self.client.get("/api/tours", params={"q": "opaque query", "departure_city": "shiraz"})
            explicit_sort = self.client.get("/api/tours", params={"q": "opaque query", "sort": "best"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["interpretation_source"], "openrouter")
        self.assertEqual(payload["parsed_intent"]["departure_city"], "shiraz")
        self.assertEqual(payload["sort"], "price")
        self.assertEqual(explicit_sort.json()["sort"], "best")
        self.assertTrue(all(tour["departure_city"] == "shiraz" for tour in payload["tours"]))

        with patch.object(backend_app, "_query_plan", return_value=(None, "fallback")):
            fallback = self.client.get("/api/search", params={"q": "sea under 8 million"})
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.json()["interpretation_source"], "fallback")
        self.assertEqual(fallback.json()["parsed_intent"]["destination_theme"], "coastal")
        self.assertEqual(fallback.json()["parsed_intent"]["max_price_toman"], 8_000_000)
        with patch("backend.semantic.plan_query", return_value=({}, "openrouter")):
            empty_plan = self.client.get("/api/search", params={"q": "sea under 8 million"})
        self.assertEqual(empty_plan.json()["interpretation_source"], "fallback")

    def test_has_tours_filter_uses_verified_links_and_explicit_false(self):
        with patch.object(backend_app, "_query_plan", return_value=(None, "fallback")):
            filtered = self.client.get("/api/search", params={"q": "هتل با تور", "has_tours": "true", "limit": 1})
            second = self.client.get("/api/search", params={"has_tours": "true", "offset": 1, "limit": 1})
            unfiltered = self.client.get("/api/search", params={"q": "هتل با تور", "has_tours": "false"})
        self.assertEqual((filtered.status_code, second.status_code, unfiltered.status_code), (200, 200, 200))
        result = filtered.json()
        self.assertGreater(result["total"], 1)
        self.assertGreater(result["hotels"][0]["tour_count"], 0)
        self.assertEqual(second.json()["total"], result["total"])
        self.assertNotEqual(second.json()["hotels"][0]["id"], result["hotels"][0]["id"])
        self.assertFalse(unfiltered.json()["parsed_intent"]["has_tours"])
        self.assertGreater(unfiltered.json()["total"], result["total"])


if __name__ == "__main__":
    unittest.main()
