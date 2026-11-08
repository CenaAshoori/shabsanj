"""Contract checks for the public AsaSafar city-card parser."""

import unittest

from .asasafar import KISH_LISTING_URL, parse_asasafar


class AsaSafarParserTests(unittest.TestCase):
    def test_one_night_price_and_unverified_date(self) -> None:
        html = '''<a href="/fa/hotels/toranj?from=1405-08-14&amp;to=1">
            <h3>هتل ترنج کیش</h3><div>شروع قیمت از</div>
            <div>23,100,000 <b>/ 1 شب</b></div><span>تومان</span>
            <span>508,200 تومان بازگشت وجه</span></a>'''
        offers = parse_asasafar(html, "kish", KISH_LISTING_URL, "2026-11-05T00:00:00Z")
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer["price_toman"], 23_100_000)
        self.assertEqual(offer["canonical_id"], "kish-toranj")
        self.assertEqual((offer["price_basis"], offer["stay_nights"]), ("per_night", 1))
        self.assertIsNone(offer["checkin"])
        self.assertEqual(offer["availability"], "unknown")
        self.assertEqual(offer["source_url"], "https://www.asasafar.com/fa/hotels/toranj")

    def test_rejects_unpriced_and_wrong_origin(self) -> None:
        html = '<a href="/fa/hotels/unknown"><h3>هتل نمونه کیش</h3><div>شروع قیمت از 0 / 1 شب تومان</div></a>'
        self.assertEqual(parse_asasafar(html, "kish", KISH_LISTING_URL, "now"), [])
        with self.assertRaises(ValueError):
            parse_asasafar(html, "kish", "https://example.com/hotels/kish", "now")

    def test_uses_matching_hotel_photo_not_cashback_icon(self) -> None:
        html = '''<div><img src="/image/hotel/square/e_images/2816/Kish-Mirazh-44.jpg"
            alt="هتل میراژ کیش"><div><a href="/fa/hotels/mirage">
            <h3>هتل میراژ کیش</h3><div>شروع قیمت از 6,999,300 / 1 شب تومان</div>
            <img src="https://cdn.karnaval.ir/cashback.png" alt="cashback">
            </a></div></div>'''
        offers = parse_asasafar(html, "kish", KISH_LISTING_URL, "now")
        self.assertEqual(offers[0]["image_url"],
                         "https://www.asasafar.com/image/hotel/square/e_images/2816/Kish-Mirazh-44.jpg")
        no_photo = html.replace('alt="هتل میراژ کیش"', 'alt="دیگر"')
        self.assertNotIn("image_url", parse_asasafar(no_photo, "kish", KISH_LISTING_URL, "now")[0])


if __name__ == "__main__":
    unittest.main()
