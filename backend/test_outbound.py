from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from fastapi.testclient import TestClient

from .app import app
from .outbound import ClickCounter, cta_url


class OutboundClickTests(unittest.TestCase):
    def test_redirect_counts_repeated_visits_and_preserves_destination(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "analytics.sqlite3"
            with patch("backend.app.CLICK_COUNTER", ClickCounter(db)), TestClient(app) as client:
                hotel = client.get("/api/search", params={"limit": 1}).json()["hotels"][0]["offers"][0]
                tour = client.get("/api/tours", params={"limit": 1}).json()["tours"][0]
                self.assertEqual(client.get("/api/analytics/outbound").json()["total"], 0)
                for record in (hotel, hotel, tour):
                    response = client.get(record["outbound_url"], follow_redirects=False)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(unquote(response.headers["location"]), unquote(record["source_url"]))
                    self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(client.get(hotel["outbound_url"], headers={"Sec-Purpose": "prefetch"}).status_code, 204)
                self.assertEqual(client.get("/go/tour/unknown", follow_redirects=False).status_code, 404)
                stats = client.get("/api/analytics/outbound").json()
                self.assertEqual(stats["total"], 3)
                self.assertEqual(stats["by_kind"], {"hotel": 2, "tour": 1})
                self.assertEqual(len(stats["links"]), 2)
                self.assertEqual(sum(item["clicks"] for item in stats["providers"]), 3)
            self.assertEqual(ClickCounter(db).summary()["total"], 3)

    def test_provider_links_only(self):
        base = {"provider": "tournegar", "tour_id": "sample", "title": "تور نمونه"}
        for url in (
            "https://tournegar.com.example.org/tour",
            "http://tournegar.com/tour",
            "https://evil.example@tournegar.com/tour",
            "https://tournegar.com:5000/tour",
        ):
            with self.subTest(url=url):
                self.assertIsNone(cta_url("tour", {**base, "source_url": url}))
