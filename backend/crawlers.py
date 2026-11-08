"""Public city-listing crawlers for indicative Iranian hotel prices.

Only the provider city catalog pages below are fetched. Room inventory and
checkout prices are deliberately outside the scope of these adapters.
"""

from __future__ import annotations

import re
import json
from math import isfinite
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .asasafar import KISH_LISTING_URL, PROVIDER_NAME as ASASAFAR_NAME, parse_asasafar


USER_AGENT = "TorobHotelResearch/0.1 (+public hotel catalog comparison)"
SOURCES = {
    "tournegar": {
        "name": "تورنگار",
        "tehran": "https://tournegar.com/hotels/tehran",
        "mashhad": "https://tournegar.com/hotels/mashhad",
        "kish": "https://tournegar.com/hotels/kish",
    },
    "tikhotel": {
        "name": "تیک هتل",
        "tehran": "https://tikhotel.com/hotels/iran/tehran",
        "mashhad": "https://tikhotel.com/hotels/iran/mashhad",
        "kish": "https://tikhotel.com/hotels/iran/kish",
        "rasht": "https://tikhotel.com/hotels/iran/rasht",
        "bandar_anzali": "https://tikhotel.com/hotels/iran/bandaranzali",
        "lahijan": "https://tikhotel.com/hotels/iran/lahijan",
        "astara": "https://tikhotel.com/hotels/iran/astara",
        "ramsar": "https://tikhotel.com/hotels/iran/ramsar",
        "chalus": "https://tikhotel.com/hotels/iran/chalus",
        "nowshahr": "https://tikhotel.com/hotels/iran/noshahr",
    },
    "iranhotelonline": {
        "name": "ایران هتل آنلاین",
        "tehran": "https://www.iranhotelonline.com/tehran-hotels/",
        "mashhad": "https://www.iranhotelonline.com/mashhad-hotels/",
        "kish": "https://www.iranhotelonline.com/kish-hotels/",
        "rasht": "https://www.iranhotelonline.com/rasht-hotels/",
        "bandar_anzali": "https://www.iranhotelonline.com/bandar-e-anzali-hotels/",
        "lahijan": "https://www.iranhotelonline.com/lahijan-hotels/",
        "astara": "https://www.iranhotelonline.com/astara-hotels/",
        "ramsar": "https://www.iranhotelonline.com/ramsar-hotels/",
        "chalus": "https://www.iranhotelonline.com/chalus-hotels/",
        "nowshahr": "https://www.iranhotelonline.com/noshahr-hotels/",
    },
    "snapptrip": {
        "name": "اسنپ‌تریپ",
        "tehran": "https://www.snapptrip.com/رزرو-هتل/تهران",
        "mashhad": "https://www.snapptrip.com/رزرو-هتل/مشهد",
        "kish": "https://www.snapptrip.com/رزرو-هتل/کیش",
        "rasht": "https://www.snapptrip.com/رزرو-هتل/رشت",
        "bandar_anzali": "https://www.snapptrip.com/رزرو-هتل/بندر-انزلی",
        "lahijan": "https://www.snapptrip.com/رزرو-هتل/لاهیجان",
        "ramsar": "https://www.snapptrip.com/رزرو-هتل/رامسر",
        "chalus": "https://www.snapptrip.com/رزرو-هتل/چالوس",
        "nowshahr": "https://www.snapptrip.com/رزرو-هتل/نوشهر",
    },
    "asasafar": {"name": ASASAFAR_NAME, "kish": KISH_LISTING_URL},
}
CITY_FA = {
    "tehran": "تهران", "mashhad": "مشهد", "kish": "کیش",
    "rasht": "رشت", "bandar_anzali": "بندر انزلی", "lahijan": "لاهیجان",
    "astara": "آستارا", "ramsar": "رامسر", "chalus": "چالوس",
    "nowshahr": "نوشهر",
}

# A provider sometimes publishes its default Tehran map point for an unrelated
# property. Keep a generous local envelope for each city, but discard that
# repeated placeholder even if it would happen to fall inside Tehran.
SNAPPTRIP_CITY_PIN_BOUNDS = {
    "tehran": (35.50, 35.90, 51.10, 51.80),
    "mashhad": (36.00, 36.50, 59.20, 59.90),
    "kish": (26.45, 26.65, 53.80, 54.20),
    "rasht": (37.10, 37.50, 49.30, 49.80),
    "bandar_anzali": (37.35, 37.65, 49.20, 49.65),
    "lahijan": (37.05, 37.50, 49.85, 50.20),
    "ramsar": (36.75, 37.05, 50.40, 50.90),
    "chalus": (36.45, 36.85, 51.20, 51.65),
    "nowshahr": (36.20, 36.80, 51.35, 51.95),
}
SNAPPTRIP_PLACEHOLDER_PIN = (35.696814, 51.3498186)


def valid_snapptrip_property_pin(city: str, latitude: object, longitude: object) -> bool:
    """Accept finite, local coordinates except the known generic map point."""
    if (not isinstance(latitude, (int, float)) or isinstance(latitude, bool)
            or not isinstance(longitude, (int, float)) or isinstance(longitude, bool)
            or not isfinite(latitude) or not isfinite(longitude)):
        return False
    bounds = SNAPPTRIP_CITY_PIN_BOUNDS.get(city)
    if not bounds or (latitude, longitude) == SNAPPTRIP_PLACEHOLDER_PIN:
        return False
    min_lat, max_lat, min_lon, max_lon = bounds
    return min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon

# These are hand-checked hotel identities on the providers' city pages. All
# other listings remain provider-specific, avoiding an accidental fuzzy merge.
MATCHED_HOTELS = {
    "tehran-espinas-boulevard": {
        ("tournegar", "423"), ("tikhotel", "espinas"),
        ("iranhotelonline", "هتل-اسپیناس-بلوار"),
    },
    "tehran-parsian-azadi": {
        ("tournegar", "424"), ("iranhotelonline", "هتل-پارسیان-آزادی"),
    },
    "tehran-parsian-esteghlal": {
        ("tournegar", "426"), ("iranhotelonline", "هتل-استقلال"),
    },
    "tehran-espinas-palace": {
        ("tournegar", "428"), ("iranhotelonline", "هتل-اسپیناس-پالاس"),
    },
    "tehran-roxan": {
        ("tournegar", "433"), ("tikhotel", "novotel"),
        ("iranhotelonline", "هتل-رکسان-(نووتل-سابق)"),
    },
    "tehran-homa": {
        ("tournegar", "434"), ("tikhotel", "homa"),
    },
    "tehran-aramis": {
        ("tournegar", "439"), ("tikhotel", "aramis"),
    },
    "tehran-taj-mahal": {
        ("tikhotel", "tajmahal"), ("iranhotelonline", "هتل-آپارتمان-تاج-محل"),
    },
    "tehran-eskan-alvand": {
        ("tikhotel", "eskanalvand"), ("iranhotelonline", "هتل-اسکان-الوند"),
    },
    "tehran-atana": {
        ("tikhotel", "atana"), ("iranhotelonline", "هتل-آتانا"),
    },
    "mashhad-almas-2": {
        ("tournegar", "42"), ("tikhotel", "almas-2"),
        ("iranhotelonline", "هتل-الماس-2"),
    },
    "mashhad-sinoor": {
        ("tournegar", "47"), ("tikhotel", "sinoor"),
        ("iranhotelonline", "هتل-سی-نور"),
    },
    "mashhad-madineh-alreza": {
        ("tournegar", "53"), ("tikhotel", "madinehalreza"),
        ("iranhotelonline", "هتل-مدینه-الرضا"),
    },
    "mashhad-park-hayat": {
        ("tournegar", "183"), ("tikhotel", "bozorgtorqabe"),
        ("iranhotelonline", "هتل-بزرگ-پارک-حیات"),
    },
    "mashhad-golden-palace": {
        ("tournegar", "46"), ("iranhotelonline", "هتل-گلدن-پالاس"),
    },
    "mashhad-homa-1": {
        ("tournegar", "45"), ("iranhotelonline", "هتل-هما-1"),
    },
    "mashhad-atlas": {
        ("tikhotel", "atlas"), ("iranhotelonline", "هتل-اطلس"),
    },
    "mashhad-parsis": {
        ("tikhotel", "parsis"), ("iranhotelonline", "هتل-پارسیس"),
    },
    "mashhad-khaneh-sabz": {
        ("tikhotel", "khanehsabz"), ("iranhotelonline", "هتل-خانه-سبز"),
    },
    "mashhad-rezvan": {
        ("tikhotel", "rezvan"), ("iranhotelonline", "هتل-رضوان"),
    },
    "mashhad-qasr-international": {
        ("tikhotel", "qasralmas"), ("iranhotelonline", "هتل-قصر-بین-المللی"),
    },
}
MATCHED_HOTELS.update({
    # Kish: card names and provider slugs identify the same named property.
    "kish-panorama": {("tournegar", "340"), ("tikhotel", "panaroma"), ("iranhotelonline", "هتل-پانوراما")},
    "kish-aramis-plus": {("tournegar", "342"), ("tikhotel", "aramisplus"), ("iranhotelonline", "هتل-آرامیس-پلاس")},
    "kish-parmis": {("tournegar", "216"), ("tikhotel", "parmis"), ("iranhotelonline", "هتل-پارمیس")},
    "kish-aramis": {("tikhotel", "aramis"), ("iranhotelonline", "هتل-آرامیس")},
    "kish-vida": {("tournegar", "375"), ("tikhotel", "vida"), ("iranhotelonline", "هتل-ویدا")},
    "kish-lilium": {("tikhotel", "lilium"), ("iranhotelonline", "هتل-لیلیوم")},
    "kish-helya": {("tikhotel", "helya"), ("iranhotelonline", "هتل-هلیا")},
    "kish-dariush": {("tournegar", "376"), ("tikhotel", "daryosh"), ("iranhotelonline", "هتل-داریوش")},
    "kish-kourosh": {("tournegar", "343"), ("tikhotel", "kourosh"), ("iranhotelonline", "هتل-کوروش")},
    "kish-international": {("tournegar", "344"), ("tikhotel", "kish"), ("iranhotelonline", "هتل-بین-المللی")},
    "kish-amirkabir": {("tournegar", "346"), ("tikhotel", "amirkabir"), ("iranhotelonline", "هتل-امیرکبیر")},
    "kish-panorama-plus": {("tikhotel", "panorama-plus"), ("iranhotelonline", "هتل-پانوراما-پلاس")},
    "kish-shabaviz": {("tikhotel", "shabaviz"), ("iranhotelonline", "هتل-شباویز")},
    "kish-marina-park": {("tournegar", "231"), ("tikhotel", "marinapark"), ("iranhotelonline", "هتل-مارینا-پارک")},
    "kish-toranj": {("tournegar", "339"), ("tikhotel", "toranj"), ("iranhotelonline", "هتل-ترنج")},
    "kish-excelsior": {("tikhotel", "excelsior"), ("tikhotel", "akslsyor"), ("iranhotelonline", "هتل-اکسلسیور")},
    # Gilan cities: no fuzzy merging beyond these checked names.
    "rasht-sabouri": {("tikhotel", "sabouri"), ("iranhotelonline", "هتل-آپارتمان-صبوری")},
    "rasht-shabestan": {("tikhotel", "shabestan"), ("iranhotelonline", "هتل-شبستان")},
    "rasht-pamchal": {("tikhotel", "pamchal"), ("iranhotelonline", "هتل-پامچال")},
    "rasht-kacha": {("tikhotel", "kacha"), ("iranhotelonline", "هتل-بوتیک-کچا")},
    "rasht-khan-sabouri": {("tikhotel", "khan-sabouri"), ("tikhotel", "khan-sbory"), ("iranhotelonline", "هتل-خان-صبوری")},
    "rasht-sepidroud": {("tikhotel", "sepiedrood"), ("iranhotelonline", "اقامتگاه-بوم-گردی-سپیدرود")},
    "rasht-iran": {("tikhotel", "iran"), ("iranhotelonline", "هتل-ایران")},
    "bandar_anzali-sefid-kenar": {("tikhotel", "sefidkenar"), ("iranhotelonline", "هتل-سفید-کنار")},
    "bandar_anzali-almas": {("tikhotel", "almas"), ("iranhotelonline", "هتل-الماس")},
    "bandar_anzali-persian": {("tikhotel", "persian"), ("iranhotelonline", "هتل-پرشین")},
    "bandar_anzali-kadosan": {("tikhotel", "bozorgkadosan"), ("iranhotelonline", "هتل-بزرگ-کادوسان")},
    "bandar_anzali-madaen": {("tikhotel", "madaen"), ("iranhotelonline", "هتل-مدائن")},
    "bandar_anzali-deniz": {("tikhotel", "deniz"), ("iranhotelonline", "هتل-دنیز")},
    "bandar_anzali-arka": {("tikhotel", "arka"), ("iranhotelonline", "هتل-آرکا")},
    "bandar_anzali-orkideh": {("tikhotel", "orkideh"), ("iranhotelonline", "هتل-ارکیده")},
    "bandar_anzali-shayan": {("tikhotel", "shayan"), ("iranhotelonline", "هتل-آپارتمان-شایان")},
    "bandar_anzali-ahmad": {("tikhotel", "ahmad"), ("iranhotelonline", "هتل-احمد")},
    "bandar_anzali-melorin": {("tikhotel", "melorin"), ("iranhotelonline", "هتل-ملورین")},
    "bandar_anzali-kambadan": {("tikhotel", "kambadan"), ("tikhotel", "kambaden"), ("iranhotelonline", "هتل-کامبادن")},
    "bandar_anzali-pouya": {("tikhotel", "pouya"), ("tikhotel", "poya"), ("iranhotelonline", "هتل-آپارتمان-پویا")},
    "lahijan-alborz": {("tikhotel", "alborz"), ("iranhotelonline", "هتل-البرز")},
    "lahijan-shahrzad": {("tikhotel", "shahrzad"), ("iranhotelonline", "هتل-شهرزاد")},
    "lahijan-tatilat": {("tikhotel", "tatilat"), ("iranhotelonline", "هتل-آپارتمان-تعطیلات")},
    "lahijan-jahangardi": {("tikhotel", "jahangardi"), ("iranhotelonline", "هتل-جهانگردی")},
    "astara-shindan": {("tikhotel", "shindan"), ("iranhotelonline", "هتل-شیندان")},
    "astara-heyran": {("tikhotel", "heyran"), ("iranhotelonline", "هتل-حیران")},
    "astara-persian-rose": {("tikhotel", "persianroz"), ("iranhotelonline", "هتل-پرشین-رز")},
    "astara-olympic": {("tikhotel", "olympic"), ("iranhotelonline", "هتل-المپیک")},
    # Mazandaran cities.
    "ramsar-lido": {("tikhotel", "lido"), ("iranhotelonline", "هتل-لیدو")},
    "ramsar-neyestan": {("tikhotel", "neyestan"), ("iranhotelonline", "هتل-آپارتمان-نیستان")},
    "ramsar-fallah": {("tikhotel", "fallah"), ("iranhotelonline", "هتل-فلاح")},
    "ramsar-shahrzad": {("tikhotel", "shahrzad"), ("iranhotelonline", "هتل-آپارتمان-شهرزاد")},
    "ramsar-parsian": {("tikhotel", "parsianazadi"), ("iranhotelonline", "هتل-پارسیان")},
    "ramsar-bam-sabz": {("tikhotel", "bame-sabz"), ("iranhotelonline", "هتل-بام-سبز")},
    "ramsar-rose": {("tikhotel", "rose"), ("iranhotelonline", "هتل-رز")},
    "ramsar-tak": {("tikhotel", "tak"), ("iranhotelonline", "خانه-مسافر-تک")},
    "chalus-kooshal": {("tikhotel", "kooshal"), ("iranhotelonline", "هتل-آپارتمان-کوشال")},
    "chalus-narin": {("tikhotel", "sahelinarin"), ("iranhotelonline", "هتل-نارین")},
    "chalus-flamingo": {("tikhotel", "felamingo"), ("iranhotelonline", "هتل-آپارتمان-فلامینگو")},
    "chalus-venus-plus": {("tikhotel", "venusplus"), ("iranhotelonline", "هتل-ونوس-پلاس")},
    "chalus-malek": {("tikhotel", "malek"), ("iranhotelonline", "هتل-ملک")},
    "chalus-golsar": {("tikhotel", "golsar"), ("tikhotel", "glsar"), ("iranhotelonline", "هتل-گلسار")},
    "nowshahr-persia-3": {("tikhotel", "persia3"), ("iranhotelonline", "هتل-پرشیا-3")},
    "nowshahr-arsh": {("tikhotel", "arsh"), ("iranhotelonline", "هتل-عرش")},
    "nowshahr-araz": {("tikhotel", "araz"), ("iranhotelonline", "هتل-آراز")},
})
IDENTITIES = {
    (provider, canonical_id.split("-", 1)[0], hotel_id): canonical_id
    for canonical_id, aliases in MATCHED_HOTELS.items()
    for provider, hotel_id in aliases
}
IDENTITIES.update({
    # Checked exact hotel names in each Snapptrip city card against existing
    # provider listings. Unmatched names retain provider-specific identities.
    ("snapptrip", "tehran", "هتل-هویزه"): "tikhotel:tehran:hovezeh",
    ("snapptrip", "tehran", "هتل-پارسیان-آزادی"): "tehran-parsian-azadi",
    ("snapptrip", "tehran", "هتل-اسپیناس-بلوار"): "tehran-espinas-boulevard",
    ("snapptrip", "tehran", "هتل-پامچال"): "tikhotel:tehran:pamchal",
    ("snapptrip", "tehran", "هتل-هرمزان"): "iranhotelonline:tehran:هتل-هرمزان",
    ("snapptrip", "tehran", "هتل-پارسیان-اوین"): "tikhotel:tehran:parsianevin",
    ("snapptrip", "tehran", "هتل-نور-حیات"): "iranhotelonline:tehran:هتل-نور-حیات",
    ("snapptrip", "tehran", "هتل-پارسیان-استقلال"): "tehran-parsian-esteghlal",
    ("snapptrip", "tehran", "هتل-آرامیس"): "tehran-aramis",
    ("snapptrip", "tehran", "هتل-لاله"): "iranhotelonline:tehran:هتل-لاله",
    ("snapptrip", "mashhad", "هتل-الماس-2"): "mashhad-almas-2",
    ("snapptrip", "mashhad", "هتل-مجلل-درویشی"): "tournegar:mashhad:43",
    ("snapptrip", "mashhad", "هتل-آریو"): "iranhotelonline:mashhad:هتل-آریو",
    ("snapptrip", "mashhad", "هتل-مدینه-الرضا"): "mashhad-madineh-alreza",
    ("snapptrip", "mashhad", "هتل-خانه-سبز"): "mashhad-khaneh-sabz",
    ("snapptrip", "mashhad", "هتل-تارا"): "tikhotel:mashhad:tara",
    ("snapptrip", "mashhad", "هتل-میامی"): "tikhotel:mashhad:mayamey",
    ("snapptrip", "mashhad", "هتل-فردوس"): "iranhotelonline:mashhad:هتل-فردوس",
    ("snapptrip", "kish", "هتل-پانوراما"): "kish-panorama",
    ("snapptrip", "kish", "هتل-کوروش"): "kish-kourosh",
    ("snapptrip", "kish", "هتل-گلدیس"): "tikhotel:kish:goldis",
    ("snapptrip", "kish", "هتل-پالاس"): "iranhotelonline:kish:هتل-پالاس",
    ("snapptrip", "kish", "هتل-امیرکبیر"): "kish-amirkabir",
    ("snapptrip", "kish", "هتل-هلیا"): "kish-helya",
    ("snapptrip", "kish", "هتل-اکسلسیور"): "kish-excelsior",
    ("snapptrip", "kish", "هتل-پارمیس"): "kish-parmis",
    ("snapptrip", "kish", "هتل-ترنج"): "kish-toranj",
    ("snapptrip", "kish", "هتل-ایران"): "tikhotel:kish:iran",
    ("snapptrip", "kish", "هتل-پارمیدا"): "tikhotel:kish:parmida",
    ("snapptrip", "kish", "هتل-پانوراما-پلاس"): "kish-panorama-plus",
    ("snapptrip", "kish", "هتل-بین-المللی"): "kish-international",
    ("snapptrip", "kish", "هتل-گامبرون"): "tikhotel:kish:gamberon",
    ("snapptrip", "kish", "هتل-سان-رایز"): "tikhotel:kish:sanrise",
    ("snapptrip", "kish", "هتل-لیلیوم"): "kish-lilium",
    ("snapptrip", "kish", "هتل-آرامیس-پلاس"): "kish-aramis-plus",
    ("snapptrip", "kish", "هتل-آرامیس"): "kish-aramis",
    ("snapptrip", "kish", "هتل-مارینا-پارک"): "kish-marina-park",
    ("snapptrip", "rasht", "هتل-خان-صبوری"): "rasht-khan-sabouri",
    ("snapptrip", "rasht", "هتل-آپارتمان-صبوری"): "rasht-sabouri",
    ("snapptrip", "rasht", "هتل-خزر-ماسال"): "tikhotel:rasht:khazarmasal",
    ("snapptrip", "rasht", "خانه-مسافر-الهیه"): "iranhotelonline:rasht:خانه-مسافر-الهیه",
    ("snapptrip", "bandar_anzali", "هتل-سفیدکنار"): "bandar_anzali-sefid-kenar",
    ("snapptrip", "bandar_anzali", "هتل-احمد"): "bandar_anzali-ahmad",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-پویا"): "bandar_anzali-pouya",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-شایان"): "bandar_anzali-shayan",
    ("snapptrip", "bandar_anzali", "هتل-مادر"): "iranhotelonline:bandar_anzali:هتل-مادر",
    ("snapptrip", "bandar_anzali", "هتل-الماس"): "bandar_anzali-almas",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-ملل"): "tikhotel:bandar_anzali:melal",
    ("snapptrip", "bandar_anzali", "هتل-دنیز"): "bandar_anzali-deniz",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-گل-نرگس"): "tikhotel:bandar_anzali:gol-narges",
    ("snapptrip", "bandar_anzali", "هتل-مدائن"): "bandar_anzali-madaen",
    ("snapptrip", "bandar_anzali", "هتل-ملورین"): "bandar_anzali-melorin",
    ("snapptrip", "bandar_anzali", "هتل-کامبادن"): "bandar_anzali-kambadan",
    ("snapptrip", "bandar_anzali", "هتل-بزرگ-کادوسان"): "bandar_anzali-kadosan",
    ("snapptrip", "bandar_anzali", "هتل-ارکیده"): "bandar_anzali-orkideh",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-سفیر"): "tikhotel:bandar_anzali:safiran",
    ("snapptrip", "bandar_anzali", "هتل-آپارتمان-ناز-خزر"): "tikhotel:bandar_anzali:nazekhazar",
    ("snapptrip", "lahijan", "هتل-بزرگ-ملک"): "tikhotel:lahijan:nationalmalek",
    ("snapptrip", "lahijan", "هتل-آپارتمان-تعطیلات"): "lahijan-tatilat",
    ("snapptrip", "lahijan", "هتل-ابریشمی"): "tikhotel:lahijan:abrishami",
    ("snapptrip", "lahijan", "هتل-هیتا"): "tikhotel:lahijan:hita",
    ("snapptrip", "lahijan", "هتل-البرز"): "lahijan-alborz",
    ("snapptrip", "ramsar", "هتل-بام-سبز"): "ramsar-bam-sabz",
    ("snapptrip", "ramsar", "هتل-لیدو"): "ramsar-lido",
    ("snapptrip", "ramsar", "خانه-مسافر-تک"): "ramsar-tak",
    ("snapptrip", "ramsar", "هتل-آپارتمان-شهرزاد"): "ramsar-shahrzad",
    ("snapptrip", "ramsar", "هتل-آپارتمان-آرامسر"): "iranhotelonline:ramsar:هتل-آپارتمان-آرامسر",
    ("snapptrip", "ramsar", "هتل-آپارتمان-نیستان"): "ramsar-neyestan",
    ("snapptrip", "ramsar", "هتل-فلاح"): "ramsar-fallah",
    ("snapptrip", "ramsar", "هتل-آپارتمان-متین-ترنج"): "tikhotel:ramsar:matin-toranj",
    ("snapptrip", "ramsar", "هتل-آپارتمان-اسکان"): "iranhotelonline:ramsar:هتل-آپارتمان-اسکان",
    ("snapptrip", "ramsar", "هتل-آپارتمان-کارن"): "iranhotelonline:ramsar:هتل-آپارتمان-کارن",
    ("snapptrip", "chalus", "هتل-گلسار"): "chalus-golsar",
    ("snapptrip", "chalus", "هتل-آپارتمان-کوشال"): "chalus-kooshal",
    ("snapptrip", "chalus", "هتل-آپارتمان-هیرکانی"): "tikhotel:chalus:hyrcani",
    ("snapptrip", "chalus", "هتل-نارین"): "chalus-narin",
    ("snapptrip", "chalus", "هتل-ملک"): "chalus-malek",
    ("snapptrip", "chalus", "هتل-آپارتمان-فلامینگو"): "chalus-flamingo",
    ("snapptrip", "nowshahr", "هتل-پرشیا-3"): "nowshahr-persia-3",
    ("snapptrip", "nowshahr", "هتل-عرش"): "nowshahr-arsh",
    ("snapptrip", "nowshahr", "هتل-آپارتمان-ساینا"): "tikhotel:nowshahr:sayna",
    ("snapptrip", "nowshahr", "هتل-آپارتمان-پرشیا"): "iranhotelonline:nowshahr:هتل-آپارتمان-پرشیا",
})

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _integer(value: str | None) -> int | None:
    if not value:
        return None
    value = value.translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    return int(value) if value.isdecimal() else None


def _hotel_id(url: str) -> str:
    return unquote(urlsplit(url).path.rstrip("/").split("/")[-1])


def _canonical(provider: str, city: str, hotel_id: str) -> str:
    return IDENTITIES.get((provider, city, hotel_id), f"{provider}:{city}:{hotel_id}")


IMAGE_HOSTS = {
    "tournegar": frozenset({"tournegar.com"}),
    "tikhotel": frozenset({"cdn.grschannel.com", "cdn.tikhotel.ir"}),
    "iranhotelonline": frozenset({"cdn.iranhotelonline.com"}),
    "snapptrip": frozenset({"store.snapptrip.com"}),
}


def _public_image_url(provider: str, raw: str | None, listing_url: str) -> str | None:
    """Keep only the seller's displayed public image URL; never fetch it."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if provider == "tikhotel" and value.startswith("/_ipx/"):
        # Tikhotel puts the original CDN URL inside its Nuxt image-proxy path.
        # Store that source URL, not the low-resolution blurred proxy variant.
        marker = next((f"/https://{host}/" for host in IMAGE_HOSTS["tikhotel"]
                       if f"/https://{host}/" in value), None)
        if marker is None:
            return None
        value = marker[1:] + value.split(marker, 1)[1]
    elif provider == "snapptrip" and value.startswith("/domestic-hotel/"):
        value = urljoin("https://store.snapptrip.com/", value)
    else:
        value = urljoin(listing_url, value)
    try:
        parts = urlsplit(value)
        valid_origin = (parts.scheme == "https"
                        and parts.hostname in IMAGE_HOSTS.get(provider, ())
                        and not parts.username and not parts.password and not parts.port)
    except ValueError:
        return None
    if not valid_origin or not re.search(r"\.(?:jpe?g|png|webp|avif)$", parts.path, re.I):
        return None
    return value


def _card_image_url(provider: str, card, listing_url: str, selector: str = "img[src]") -> str | None:
    for image in card.select(selector):
        url = _public_image_url(provider, image.get("src"), listing_url)
        if url:
            return url
    return None


def _offer(
    provider: str, city: str, hotel_id: str, hotel_name: str,
    source_url: str, listing_url: str, observed_at: str,
    price_toman: int, price_note: str, *, stars: int | None = None,
    stay_nights: int | None = None, checkin: str | None = None,
    checkout: str | None = None, occupancy: int | None = None,
    offer_type: str = "hotel_listing",
) -> dict:
    return {
        "provider": provider,
        "provider_name": SOURCES[provider]["name"],
        "hotel_name": hotel_name,
        "hotel_id": hotel_id,
        "canonical_id": _canonical(provider, city, hotel_id),
        "city": city,
        "stars": stars,
        "price_toman": price_toman,
        "price_basis": "per_night",
        "stay_nights": stay_nights,
        "checkin": checkin,
        "checkout": checkout,
        "occupancy": occupancy,
        "room_type": None,
        "board": None,
        "availability": "unknown",
        "offer_type": offer_type,
        "price_note": price_note,
        "source_url": source_url,
        "listing_url": listing_url,
        "observed_at": observed_at,
    }


def parse_tournegar(html: str, city: str, listing_url: str, observed_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    for card in soup.select(".package-block-two[data-hotel-id]"):
        nightly = _integer(card.get("data-base-nightly"))
        total = _integer(card.get("data-base-price"))
        if not nightly or nightly <= 0 or not total or total <= 0:
            continue
        link = card.select_one('a[href*="/hotel/"]')
        if not link or not link.get("href"):
            continue
        source_url = urljoin(listing_url, link["href"])
        params = parse_qs(urlsplit(source_url).query)
        hotel_id = str(card["data-hotel-id"])
        name = card.get("data-hotel-title", "").strip()
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
        name = re.sub(r"^هتل تهران هتل\s+", "هتل ", name)
        city_fa = CITY_FA[city]
        if city_fa not in name:
            name += f" {city_fa}"
        nights = _integer(params.get("nights", [None])[0])
        guests = _integer(params.get("adultCount", [None])[0])
        note = "معادل هر شب از بستهٔ اقامت تورنگار"
        if nights and guests:
            note += f"؛ جمع {total:,} تومان برای {nights} شب و {guests} نفر"
        note += "؛ مزایای بسته و نوع اتاق ممکن است متفاوت باشد."
        offers.append(_offer(
            "tournegar", city, hotel_id, name, source_url, listing_url,
            observed_at, nightly, note,
            stars=_integer(card.get("data-star")), stay_nights=nights,
            checkin=params.get("checkIn", [None])[0],
            checkout=params.get("checkOut", [None])[0],
            occupancy=guests, offer_type="stay_package",
        ))
        image_url = _card_image_url("tournegar", card, listing_url)
        if image_url:
            offers[-1]["image_url"] = image_url
    return offers


def parse_tikhotel(html: str, city: str, listing_url: str, observed_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    # The public catalog sometimes repeats an identical hotel name under two
    # slugs with different starting prices. Keep the cheapest visible card and
    # its actual outbound URL; do not present both as separate properties.
    offers_by_name: dict[str, dict] = {}
    for title in soup.select("h2"):
        link = title.find_parent("a", href=True)
        provider_prefix = urlsplit(listing_url).path.rstrip("/") + "/"
        if not link or not link["href"].startswith(provider_prefix):
            continue
        card = title.find_parent("div", class_="grid-cols-12")
        if not card:
            continue
        text = card.get_text(" ", strip=True)
        price_match = re.search(r"(?:شروع قیمت از|قیمت با تخفیف از)\s*([\d۰-۹٠-٩,٬]+)\s*تومان\s*/\s*[1۱۱]\s*شب", text)
        if not price_match:
            continue
        price = _integer(price_match.group(1))
        if not price or price <= 0:
            continue
        hotel_id = _hotel_id(link["href"])
        stars_match = re.search(r"هتل\s*([1-5۱-۵])\s*ستاره", text)
        offer = _offer(
            "tikhotel", city, hotel_id, title.get_text(" ", strip=True),
            urljoin(listing_url, link["href"]), listing_url, observed_at,
            price, "قیمت شروع یک شب در فهرست عمومی تیک هتل؛ نوع اتاق و ظرفیت مشخص نیست.",
            stars=_integer(stars_match.group(1)) if stars_match else None,
            stay_nights=1,
        )
        image_url = _card_image_url("tikhotel", card, listing_url, "img[data-nuxt-img][src]")
        if image_url:
            offer["image_url"] = image_url
        previous = offers_by_name.get(offer["hotel_name"])
        if previous is None or offer["price_toman"] < previous["price_toman"]:
            offers_by_name[offer["hotel_name"]] = offer
    return list(offers_by_name.values())


def parse_iranhotelonline(html: str, city: str, listing_url: str, observed_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    for card in soup.select("iho-card article.card"):
        title = card.select_one("h2.card__title")
        link = title.find_parent("a", href=True) if title else None
        price_tag = card.select_one("span.price")
        if not title or not link or not price_tag:
            continue
        price = _integer(price_tag.get_text(" ", strip=True))
        if not price or price <= 0:
            continue
        source_url = urljoin(listing_url, link["href"])
        hotel_id = _hotel_id(source_url)
        params = parse_qs(urlsplit(source_url).query)
        text = card.get_text(" ", strip=True)
        stars_match = re.search(r"([1-5۱-۵])\s*ستاره", text)
        offer = _offer(
            "iranhotelonline", city, hotel_id,
            title.get_text(" ", strip=True), source_url, listing_url,
            observed_at, price,
            "قیمت شروع یک شب در فهرست عمومی ایران هتل آنلاین؛ نوع اتاق و ظرفیت مشخص نیست.",
            stars=_integer(stars_match.group(1)) if stars_match else None,
            stay_nights=_integer(params.get("span", [None])[0]),
            checkin=params.get("date", [None])[0],
            checkout=params.get("endDate", [None])[0],
        )
        image_url = _card_image_url("iranhotelonline", card, listing_url, "img.distance__image[src]")
        if image_url:
            offer["image_url"] = image_url
        offers.append(offer)
    return offers


def _snapptrip_name(value: str) -> str:
    return " ".join(value.translate(_DIGITS).replace("\u200c", " ").split())


def _snapptrip_properties(soup: BeautifulSoup, city: str, listing_url: str) -> dict[str, dict]:
    """Join public SSR hotel IDs and property pins to their exact hotel slug."""
    script = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if not script:
        return {}
    try:
        data = json.loads(script.string or script.get_text())
        rows = data["props"]["pageProps"]["hotelsData"]
    except (ValueError, TypeError, KeyError):
        return {}
    if not isinstance(rows, list):
        return {}
    expected_city_slug = unquote(urlsplit(listing_url).path.rstrip("/").split("/")[-1])
    found: dict[str, dict] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        details = row.get("hotelDetail")
        if not isinstance(details, dict) or details.get("cityTitle") != CITY_FA[city]:
            continue
        page_url = details.get("hotelPageUrl")
        query = page_url.get("query") if isinstance(page_url, dict) else None
        slug = query.get("hotelTitle") if isinstance(query, dict) else None
        numeric_id = row.get("id")
        if (not isinstance(slug, str) or not slug or not isinstance(numeric_id, int)
                or isinstance(numeric_id, bool) or numeric_id <= 0
                or details.get("hotelId") != numeric_id or query.get("cityTitle") != expected_city_slug):
            continue
        if slug in found:
            duplicates.add(slug)
            continue
        property_data = {"name": details.get("hotelTitle"), "numeric_id": numeric_id}
        thumbnail = row.get("thumbnail")
        image_url = _public_image_url(
            "snapptrip", thumbnail.get("url") if isinstance(thumbnail, dict) else None,
            listing_url,
        )
        if image_url and str(numeric_id) in urlsplit(image_url).path.split("/"):
            property_data["image_url"] = image_url
        location = row.get("location")
        lat = location.get("lat") if isinstance(location, dict) else None
        lon = location.get("lng") if isinstance(location, dict) else None
        if valid_snapptrip_property_pin(city, lat, lon):
            property_data["latitude"] = float(lat)
            property_data["longitude"] = float(lon)
        found[slug] = property_data
    for slug in duplicates:
        found.pop(slug, None)
    pin_owners: dict[tuple[float, float], set[int]] = {}
    for property_data in found.values():
        if "latitude" in property_data:
            pin = (property_data["latitude"], property_data["longitude"])
            pin_owners.setdefault(pin, set()).add(property_data["numeric_id"])
    for property_data in found.values():
        if "latitude" in property_data:
            pin = (property_data["latitude"], property_data["longitude"])
            if len(pin_owners[pin]) > 1:
                property_data.pop("latitude")
                property_data.pop("longitude")
    return found


def parse_snapptrip(html: str, city: str, listing_url: str, observed_at: str) -> list[dict]:
    """Read SSR one-night room offers; never infer a stay date or occupancy."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if not heading or CITY_FA[city] not in heading.get_text(" ", strip=True):
        raise ValueError("Snapptrip page does not confirm the requested city")
    expected_prefix = unquote(urlsplit(listing_url).path).rstrip("/") + "/"
    ssr_properties = _snapptrip_properties(soup, city, listing_url)
    offers = []
    seen = set()
    for card in soup.select("article.w-full"):
        title = card.select_one("h3")
        link = title.find_parent("a", href=True) if title else None
        pricing = card.select_one(".hotel-card-pricing")
        room = pricing.select_one('[data-testid="hotel_card_room_title"]') if pricing else None
        amount = pricing.select_one("span.text-headline-6") if pricing else None
        if not title or not link or not pricing or not room or not amount:
            continue
        if not re.search(r"[1۱١]\s*شب", pricing.get_text(" ", strip=True)):
            continue
        room_type = room.get_text(" ", strip=True)
        if not room_type or "ساعته" in room_type:
            # A few pages show an hourly room beneath a generic «۱ شب» label.
            continue
        price_match = re.search(r"([\d۰-۹٠-٩,٬]+)\s*تومان", amount.get_text(" ", strip=True))
        price = _integer(price_match.group(1)) if price_match else None
        if not price or price <= 0:
            continue
        source_url = urljoin(listing_url, link["href"])
        parts = urlsplit(source_url)
        if parts.netloc != "www.snapptrip.com" or parts.query or not unquote(parts.path).startswith(expected_prefix):
            continue
        hotel_id = _hotel_id(source_url)
        if hotel_id in seen:
            continue
        seen.add(hotel_id)
        name = title.get_text(" ", strip=True)
        stars_match = re.search(r"([1-5۱-۵])\s*ستاره", card.get_text(" ", strip=True))
        board = "بدون صبحانه" if "بدون صبحانه" in room_type else "با صبحانه" if "صبحانه" in room_type else None
        offer = _offer(
            "snapptrip", city, hotel_id, name, source_url, listing_url,
            observed_at, price,
            "نرخ یک شبِ اتاق نام‌برده در فهرست عمومی اسنپ‌تریپ؛ تاریخ، تعداد مهمان و موجودی قطعی مشخص نیست.",
            stars=_integer(stars_match.group(1)) if stars_match else None,
            stay_nights=1,
        )
        offer["room_type"] = room_type
        offer["board"] = board
        property_data = ssr_properties.get(hotel_id)
        if property_data and _snapptrip_name(str(property_data.get("name") or "")) == _snapptrip_name(name):
            offer["provider_numeric_id"] = property_data["numeric_id"]
            if "image_url" in property_data:
                offer["image_url"] = property_data["image_url"]
            if "latitude" in property_data and "longitude" in property_data:
                offer["latitude"] = property_data["latitude"]
                offer["longitude"] = property_data["longitude"]
                offer["location_accuracy"] = "property"
        offers.append(offer)
    return offers


PARSERS = {
    "tournegar": parse_tournegar,
    "tikhotel": parse_tikhotel,
    "iranhotelonline": parse_iranhotelonline,
    "snapptrip": parse_snapptrip,
    "asasafar": parse_asasafar,
}


def crawl(max_per_city: int = 40, providers: set[str] | None = None) -> dict:
    """Fetch bounded public catalogs after checking each origin's robots.txt."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    offers: list[dict] = []
    source_status: list[dict] = []
    robots_cache: dict[str, RobotFileParser] = {}
    with httpx.Client(
        follow_redirects=True, timeout=35.0,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        for provider, source in SOURCES.items():
            if providers is not None and provider not in providers:
                continue
            for city, url in source.items():
                if city == "name":
                    continue
                status = {"provider": provider, "city": city, "url": url,
                          "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                try:
                    parts = urlsplit(url)
                    origin = f"{parts.scheme}://{parts.netloc}"
                    if origin not in robots_cache:
                        response = client.get(
                            urljoin(origin, "/robots.txt"),
                            headers={"Accept": "text/plain"},
                        )
                        response.raise_for_status()
                        parser = RobotFileParser()
                        parser.parse(response.text.splitlines())
                        robots_cache[origin] = parser
                    if not robots_cache[origin].can_fetch(USER_AGENT, url):
                        raise PermissionError("robots.txt does not allow this catalog page")
                    response = client.get(url)
                    response.raise_for_status()
                    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    parsed = PARSERS[provider](response.text, city, url, observed_at)
                    parsed = parsed[:max_per_city]
                    if not parsed:
                        raise ValueError("No priced hotel cards found; provider markup may have changed")
                    offers.extend(parsed)
                    status.update({"status": "ok", "http_status": response.status_code,
                                   "offer_count": len(parsed), "observed_at": observed_at})
                except (httpx.HTTPError, PermissionError, ValueError) as exc:
                    status.update({"status": "error", "offer_count": 0, "error": str(exc)})
                source_status.append(status)
    return {"generated_at": now, "source_status": source_status, "offers": offers}
