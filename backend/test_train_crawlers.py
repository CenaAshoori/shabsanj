"""Regression checks for public train route page validation."""

import unittest

from backend.train_crawlers import _route_confirmed


class TrainRouteValidationTests(unittest.TestCase):
    def test_generated_orienttrips_heading_alone_is_not_route_evidence(self):
        html = "<h1>Tehran To Mashhad Train Tickets</h1><p>Choose a date</p>"
        self.assertFalse(_route_confirmed(html, "orienttrips", "tehran", "mashhad"))

    def test_orienttrips_route_article_confirms_link(self):
        html = "<h1>Tehran To Mashhad Train Tickets</h1><h2>Train From Tehran To Mashhad</h2>"
        self.assertTrue(_route_confirmed(html, "orienttrips", "tehran", "mashhad"))

    def test_persian_heading_must_match_both_cities(self):
        html = "<h1>بلیط  قطار تهران به ساری</h1>"
        self.assertTrue(_route_confirmed(html, "mrbilit", "tehran", "sari"))
        self.assertFalse(_route_confirmed(html, "mrbilit", "mashhad", "sari"))


if __name__ == "__main__":
    unittest.main()
