"""Parser contract tests with small public-markup fixtures, no network calls."""

import unittest
from datetime import date

from .flight_crawlers import ROUTES, parse_rahig, parse_rahig_cards, parse_tikotrip


RAHIG = '''
<h1>بلیط هواپیما تهران به کیش</h1><div>۱ مسافر</div>
<p><span>ارزان‌ترین نرخ ۶۰ روز آینده</span>
<strong>۶٬۴۹۵٬۴۰۰ تومان</strong>
<a href="/flights/THR-KIH?date=2026-11-07#flight-results">شنبه ۱۶ آبان</a></p>
<button aria-label="۱۶ آبان، ۶٬۴۹۵٬۴۰۰ تومان، مشاهده پروازها">
<span>۱۶ شنبه</span><strong>۶٬۴۹۵٬۴۰۰ تومان</strong></button>
'''
TIKOTRIP = '''
<h1>بلیط هواپیما تهران به کیش</h1><p>قیمت‌ها برای یک بزرگسال است.</p>
<p>ارزان‌ترین بلیط هواپیما تهران به کیش در ۶۰ روز آینده
۶٬۱۴۱٬۰۶۹ تومان برای جمعه ۱۵ آبان است.</p>
<a data-test="blog-route-fare-day" aria-label="جمعه 15 آبان: 6,141,069 تومان"
 href="/results?origin=THR&amp;destination=KIH&amp;date=2026-11-06&amp;adults=1&amp;children=0&amp;infants=0">6,141</a>
<a data-test="blog-route-fare-day" aria-label="شنبه 16 آبان: 6,241,950 تومان"
 href="/results?origin=THR&amp;destination=KIH&amp;date=2026-11-07&amp;adults=1&amp;children=0&amp;infants=0">6,242</a>
'''
RAHIG_CALENDAR = RAHIG + '''
<details id="price-calendar"><div class="R_CMEa_calendarBody"><div>
<div class="R_CMEa_monthHeader"><h4>آبان ۱۴۰۵</h4></div>
<div class="R_CMEa_days">
<button class="R_CMEa_day" aria-label="۱۶ آبان، ۶٬۴۹۵٬۴۰۰ تومان، مشاهده پروازها"><strong>۶٬۴۹۵٬۴۰۰ تومان</strong></button>
<button class="R_CMEa_day" aria-label="۱۷ آبان، حدود ۷٬۰۰۰٬۰۰۰ تومان، مشاهده پروازها"><strong>~۷٬۰۰۰٬۰۰۰ تومان</strong></button>
<button class="R_CMEa_day" aria-label="۱۸ آبان، ۸٬۰۰۰٬۰۰۰ تومان، مشاهده پروازها"><strong>۸٬۰۰۰٬۰۰۰ تومان</strong></button>
</div></div><p class="R_CMEa_note">آخرین بروزرسانی نرخ ثبت‌شده: <span>۱۶ ساعت پیش</span></p>
</div></details>
'''
RAHIG_CARDS = '''
<h1>بلیط هواپیما تهران به کیش</h1><div>۱ مسافر</div>
<details id="price-calendar"><div class="R_CMEa_calendarBody"><div>
<div class="R_CMEa_monthHeader"><h4>آبان ۱۴۰۵</h4></div>
<div class="R_CMEa_days"><button class="R_CMEa_day" aria-current="date"
aria-label="۱۶ آبان، ۶٬۴۹۵٬۴۰۰ تومان، مشاهده پروازها"><strong>۶٬۴۹۵٬۴۰۰ تومان</strong></button></div>
</div><p class="R_CMEa_note">آخرین بروزرسانی نرخ ثبت‌شده: <span>۱۶ ساعت پیش</span></p></div></details>
<section id="flight-results"><article data-compact-flight="true" data-sold-out="false">
<span class="_iRDvq_corner">چارتری</span>
<div class="_iRDvq_airlineText"><strong>مهر</strong><span dir="ltr">MEH4152</span></div>
<div class="_iRDvq_journey"><div class="_iRDvq_time"><strong>۰۸:۱۰</strong><span><bdi>THR</bdi> · خروج</span></div>
<div class="_iRDvq_time"><strong>۰۹:۵۰</strong><span><bdi>KIH</bdi> · رسیدن</span></div></div>
<div class="_iRDvq_meta"><span>۱۳ صندلی با این نرخ</span></div>
<div class="_iRDvq_amount"><strong>۶٬۴۹۵٬۴۰۰</strong></div><button disabled>در حال بروزرسانی…</button>
</article><article data-compact-flight="true" data-sold-out="true"><strong>۱ تومان</strong></article></section>
'''
TIKOTRIP_FLIGHTS = TIKOTRIP + '''
<section data-test="landing-fares-summary">
<p data-test="landing-fares-answer">فردا ۲ پرواز با صندلی خالی از ساعت ۰۳:۴۵ تا ۱۴:۳۰ هست و ارزان‌ترین آن ۶٬۲۴۱٬۹۵۰ تومان است.</p>
<p data-test="landing-fares-updated">قیمت‌ها برای یک بزرگسال است. <time datetime="2026-11-06T10:00:00Z">به‌روز</time></p>
<table data-test="landing-flights-table"><caption>پروازهای فردا تهران به کیش</caption><tbody>
<tr data-test="landing-flight-row"><td>کیش ایر</td><td>۷۰۵۳</td><td>۰۳:۴۵</td><td>سیستمی</td>
<td><a href="/results?origin=THR&amp;destination=KIH&amp;date=2026-11-07&amp;adults=1&amp;children=0&amp;infants=0">۶٬۲۴۱٬۹۵۰ تومان</a></td></tr>
<tr data-test="landing-flight-row"><td>فلای کیش</td><td>۳۱۰۰</td><td>۱۴:۳۰</td><td>چارتری</td>
<td><a href="/results?origin=THR&amp;destination=KIH&amp;date=2026-11-07&amp;adults=1&amp;children=0&amp;infants=0">۷٬۰۰۰٬۰۰۰ تومان</a></td></tr>
</tbody></table></section>
'''


class FlightCrawlerTests(unittest.TestCase):
    def test_rahig_route_floor_and_linked_date(self) -> None:
        url = ROUTES["rahig"][("tehran", "kish")]
        offers = parse_rahig(RAHIG, "tehran", "kish", url, "now", today=date(2026, 11, 6))
        self.assertEqual([(o["departure_date"], o["price_toman"]) for o in offers],
                         [(None, 6_495_400), ("2026-11-07", 6_495_400)])
        self.assertTrue(all(o["mode"] == "flight" for o in offers))

    def test_rahig_estimated_or_unverified_day_is_not_a_dated_fare(self) -> None:
        url = ROUTES["rahig"][("tehran", "kish")]
        estimated = RAHIG.replace("<span>۱۶ شنبه</span>", "<span>۱۶ شنبه ~</span>")
        offers = parse_rahig(estimated, "tehran", "kish", url, "now", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)
        self.assertIsNone(offers[0]["departure_date"])
        self.assertIn("تخمینی", offers[0]["price_note"])
        unverified = RAHIG.replace("<strong>۶٬۴۹۵٬۴۰۰ تومان</strong></button>",
                                  "<strong>۶٬۵۰۰٬۰۰۰ تومان</strong></button>")
        offers = parse_rahig(unverified, "tehran", "kish", url, "now", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)
        self.assertIn("تأیید نشد", offers[0]["price_note"])

    def test_tikotrip_full_toman_aria_price_and_one_adult_link(self) -> None:
        url = ROUTES["tikotrip"][("tehran", "kish")]
        offers = parse_tikotrip(TIKOTRIP, "tehran", "kish", url, "now",
                                today=date(2026, 11, 6), max_dated_days=1)
        self.assertEqual([(o["departure_date"], o["price_toman"]) for o in offers],
                         [(None, 6_141_069), ("2026-11-06", 6_141_069)])
        self.assertEqual(len(parse_tikotrip(TIKOTRIP, "tehran", "kish", url, "now",
                                             today=date(2026, 11, 6), max_dated_days=0)), 1)

    def test_route_mismatch_and_non_adult_link_fail_closed(self) -> None:
        url = ROUTES["tikotrip"][("tehran", "kish")]
        with self.assertRaises(ValueError):
            parse_tikotrip(TIKOTRIP, "kish", "tehran", url, "now", today=date(2026, 11, 6))
        changed = TIKOTRIP.replace("adults=1", "adults=2")
        offers = parse_tikotrip(changed, "tehran", "kish", url, "now", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)

    def test_verified_sari_route_is_link_only_without_published_fare(self) -> None:
        url = ROUTES["rahig"][("tehran", "sari")]
        html = '<h1>بلیط هواپیما تهران به ساری</h1><div>۱ مسافر</div>'
        offers = parse_rahig(html, "tehran", "sari", url, "now", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)
        self.assertIsNone(offers[0]["price_toman"])
        self.assertIsNone(offers[0]["departure_date"])
        self.assertEqual(offers[0]["source_url"], url)

    def test_rahig_calendar_excludes_estimates_and_uses_published_age(self) -> None:
        url = ROUTES["rahig"][("tehran", "kish")]
        offers = parse_rahig(RAHIG_CALENDAR, "tehran", "kish", url,
                             "2026-11-06T18:00:00+00:00", today=date(2026, 11, 6),
                             max_dated_days=60)
        self.assertEqual([offer["departure_date"] for offer in offers],
                         [None, "2026-11-07", "2026-11-09"])
        self.assertEqual(offers[1]["price_toman"], 6_495_400)
        self.assertEqual(offers[1]["observed_at"], "2026-11-06T02:00:00+00:00")

    def test_rahig_dated_card_keeps_published_seat_count_but_not_availability(self) -> None:
        url = ROUTES["rahig"][("tehran", "kish")]
        dated_url = f"{url}?date=2026-11-07#flight-results"
        offers = parse_rahig_cards(RAHIG_CARDS, "tehran", "kish", url, dated_url,
                                   "2026-11-06T18:00:00+00:00", today=date(2026, 11, 6))
        self.assertEqual(len(offers), 1)
        self.assertEqual((offers[0]["price_toman"], offers[0]["seats_remaining"]),
                         (6_495_400, 13))
        self.assertEqual((offers[0]["departure_time"], offers[0]["service_number"]),
                         ("08:10", "MEH4152"))
        self.assertEqual(offers[0]["availability"], "unknown")
        with self.assertRaisesRegex(ValueError, "selected day"):
            parse_rahig_cards(RAHIG_CARDS, "tehran", "kish", url,
                              f"{url}?date=2026-11-08#flight-results", "now",
                              today=date(2026, 11, 6))

    def test_tikotrip_tomorrow_table_replaces_calendar_floor_when_confirmed(self) -> None:
        url = ROUTES["tikotrip"][("tehran", "kish")]
        offers = parse_tikotrip(TIKOTRIP_FLIGHTS, "tehran", "kish", url,
                                "2026-11-06T12:00:00+00:00", today=date(2026, 11, 6),
                                max_dated_days=60)
        tomorrow = [offer for offer in offers if offer["departure_date"] == "2026-11-07"]
        self.assertEqual(len(tomorrow), 2)
        self.assertEqual([offer["price_toman"] for offer in tomorrow], [6_241_950, 7_000_000])
        self.assertEqual(tomorrow[0]["service_number"], "7053")
        self.assertEqual(tomorrow[0]["availability"], "available")
        self.assertNotIn("seats_remaining", tomorrow[0])
        self.assertEqual(tomorrow[0]["observed_at"], "2026-11-06T10:00:00+00:00")
        altered = TIKOTRIP_FLIGHTS.replace("ارزان‌ترین آن ۶٬۲۴۱٬۹۵۰", "ارزان‌ترین آن ۶٬۱۰۰٬۰۰۰")
        unconfirmed = parse_tikotrip(altered, "tehran", "kish", url,
                                     "2026-11-06T12:00:00+00:00", today=date(2026, 11, 6),
                                     max_dated_days=60)
        self.assertEqual(len([o for o in unconfirmed if o["departure_date"] == "2026-11-07"]), 1)


if __name__ == "__main__":
    unittest.main()
