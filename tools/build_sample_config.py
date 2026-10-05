#!/usr/bin/env python3
"""Builds the API's content: data/catalog.json (GET /api/v1/config) and data/release.json
(GET /api/v1/app/version). See README.md.

The catalog is data, not code: edit the tables below (or the JSON directly) and the app
picks the change up on its next refresh. Kept as a script so the sample stays readable
and consistent (ids, ordering, shared defaults).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
STORE_PACKAGE = "io.celin.super.app"

CATEGORIES = [
    # id, en, fa, color
    ("transport", "Transportation", "حمل‌ونقل", "#2F9E44"),
    ("food", "Food", "غذا", "#E8590C"),
    ("shopping", "Shopping", "خرید", "#D6336C"),
    ("classifieds", "Classifieds", "نیازمندی‌ها", "#7048E8"),
    ("travel", "Travel", "سفر", "#1C7ED6"),
    ("maps", "Maps", "نقشه و مسیریابی", "#0CA678"),
    ("entertainment", "Entertainment", "سرگرمی", "#AE3EC9"),
    ("health", "Health", "سلامت", "#F03E3E"),
    ("finance", "Finance", "مالی", "#1098AD"),
    ("utilities", "Telecom & bills", "اپراتور و قبوض", "#4C6EF5"),
    ("government", "Government", "خدمات دولتی", "#495057"),
    ("messaging", "Messaging", "پیام‌رسان", "#15AABF"),
]

LOCATION = {"location": True, "camera": False, "microphone": False}
CAMERA = {"location": False, "camera": True, "microphone": False}
MEDIA = {"location": False, "camera": True, "microphone": True}
NONE = {"location": False, "camera": False, "microphone": False}

# id, category, url, en name, fa name, en description, fa description, brand color,
# allowed domains, permissions, keep-alive, extra (dict merged into the service)
SERVICES = [
    ("snapp", "transport", "https://app.snapp.taxi/", "Snapp", "اسنپ",
     "Cars, bikes and couriers on demand", "درخواست خودرو، موتور و پیک",
     "#00D170", ["snapp.taxi", "snapp.ir"], LOCATION, "HIGH",
     {"featured": True, "keywords": ["snap", "taxi", "ride", "تاکسی", "تاکسی اینترنتی", "ماشین"]}),
    ("tapsi", "transport", "https://app.tapsi.cab/", "Tapsi", "تپسی",
     "Ride hailing across Iran", "تاکسی اینترنتی در سراسر ایران",
     "#FF6A00", ["tapsi.cab", "tapsi.ir"], LOCATION, "HIGH",
     {"featured": True, "keywords": ["tap30", "taxi", "ride", "تاکسی", "تپ سی"]}),
    ("snappbox", "transport", "https://app.snapp-box.com/", "Snapp Box", "اسنپ‌باکس",
     "Parcel delivery", "ارسال مرسوله",
     "#00B862", ["snapp-box.com"], LOCATION, "NORMAL",
     {"enabled": False}),
    ("snappfood", "food", "https://snappfood.ir/", "SnappFood", "اسنپ‌فود",
     "Restaurants and groceries delivered", "سفارش غذا و سوپرمارکت",
     "#FF00A6", ["snappfood.ir"], LOCATION, "NORMAL",
     {"featured": True, "keywords": ["food", "restaurant", "delivery", "رستوران", "غذا", "زودفود"]}),
    ("tapsifood", "food", "https://tapsi.food/", "Tapsi Food", "تپسی‌فود",
     "Food delivery from nearby restaurants", "سفارش غذا از رستوران‌های نزدیک",
     "#FF6A00", ["tapsi.food"], LOCATION, "NORMAL",
     {"keywords": ["food", "رستوران", "غذا"]}),
    ("digikala", "shopping", "https://www.digikala.com/", "Digikala", "دیجی‌کالا",
     "Iran's largest online store", "بزرگ‌ترین فروشگاه اینترنتی ایران",
     "#EF394E", ["digikala.com"], NONE, "NORMAL",
     {"featured": True, "keywords": ["digi", "shop", "store", "دیجی", "فروشگاه", "خرید"]}),
    ("torob", "shopping", "https://torob.com/", "Torob", "ترب",
     "Compare prices before you buy", "مقایسه قیمت پیش از خرید",
     "#E03131", ["torob.com"], NONE, "LOW",
     {"keywords": ["price", "compare", "قیمت", "مقایسه"]}),
    ("basalam", "shopping", "https://basalam.com/", "Basalam", "باسلام",
     "Marketplace of local sellers", "بازار فروشندگان محلی",
     "#FF6431", ["basalam.com"], NONE, "LOW",
     {"keywords": ["handmade", "بازار", "محلی"]}),
    ("digistyle", "shopping", "https://www.digistyle.com/", "Digistyle", "دیجی‌استایل",
     "Fashion and clothing", "پوشاک و مد",
     "#212529", ["digistyle.com"], NONE, "LOW",
     {"keywords": ["fashion", "clothes", "لباس", "پوشاک"]}),
    ("divar", "classifieds", "https://divar.ir/", "Divar", "دیوار",
     "Buy and sell anything locally", "خرید و فروش بی‌واسطه",
     "#A62626", ["divar.ir"], LOCATION, "NORMAL",
     {"featured": True, "keywords": ["classifieds", "ads", "آگهی", "نیازمندی"]}),
    ("sheypoor", "classifieds", "https://www.sheypoor.com/", "Sheypoor", "شیپور",
     "Classified ads", "آگهی‌های نیازمندی",
     "#0076CE", ["sheypoor.com"], LOCATION, "LOW",
     {"keywords": ["ads", "آگهی"]}),
    ("alibaba", "travel", "https://www.alibaba.ir/", "Alibaba", "علی‌بابا",
     "Flights, trains, buses and hotels", "بلیط هواپیما، قطار، اتوبوس و هتل",
     "#FDB713", ["alibaba.ir"], NONE, "NORMAL",
     {"keywords": ["flight", "ticket", "hotel", "بلیط", "پرواز", "هتل"]}),
    ("snapptrip", "travel", "https://www.snapptrip.com/", "SnappTrip", "اسنپ‌تریپ",
     "Hotels and flights", "رزرو هتل و بلیط",
     "#00A884", ["snapptrip.com"], NONE, "NORMAL",
     {"keywords": ["hotel", "flight", "هتل", "بلیط"]}),
    ("jabama", "travel", "https://www.jabama.com/", "Jabama", "جاباما",
     "Villas and stays", "اجاره ویلا و اقامتگاه",
     "#F59F00", ["jabama.com"], NONE, "LOW",
     {"keywords": ["villa", "stay", "ویلا", "اقامتگاه"]}),
    ("balad", "maps", "https://balad.ir/", "Balad", "بلد",
     "Maps, places and live traffic", "نقشه، مکان‌ها و ترافیک زنده",
     "#00A86B", ["balad.ir"], LOCATION, "NORMAL",
     {"keywords": ["map", "navigation", "traffic", "نقشه", "مسیریاب", "ترافیک"]}),
    ("neshan", "maps", "https://neshan.org/maps", "Neshan", "نشان",
     "Maps and navigation", "نقشه و مسیریابی",
     "#2A6AF6", ["neshan.org"], LOCATION, "NORMAL",
     {"keywords": ["map", "navigation", "نقشه", "مسیریاب"]}),
    ("filimo", "entertainment", "https://www.filimo.com/", "Filimo", "فیلیمو",
     "Movies and series", "فیلم و سریال",
     "#F9A800", ["filimo.com"], NONE, "LOW",
     {"keywords": ["movie", "series", "vod", "فیلم", "سریال"]}),
    ("namava", "entertainment", "https://www.namava.ir/", "Namava", "نماوا",
     "Stream films and shows", "تماشای آنلاین فیلم و سریال",
     "#1D8CF8", ["namava.ir"], NONE, "LOW",
     {"keywords": ["movie", "series", "vod", "فیلم", "سریال"]}),
    ("aparat", "entertainment", "https://www.aparat.com/", "Aparat", "آپارات",
     "Videos and live streams", "ویدیو و پخش زنده",
     "#DF0F50", ["aparat.com"], NONE, "LOW",
     {"keywords": ["video", "live", "ویدیو"]}),
    ("paziresh24", "health", "https://www.paziresh24.com/", "Paziresh24", "پذیرش۲۴",
     "Book doctor appointments", "نوبت‌دهی پزشک",
     "#3861FB", ["paziresh24.com"], NONE, "NORMAL",
     {"keywords": ["doctor", "appointment", "پزشک", "نوبت", "دکتر"]}),
    ("doctoreto", "health", "https://doctoreto.com/", "Doctoreto", "دکترتو",
     "Online consultations", "مشاوره آنلاین پزشکی",
     "#00A3C4", ["doctoreto.com"], MEDIA, "NORMAL",
     {"keywords": ["doctor", "consult", "پزشک", "مشاوره"]}),
    ("nobitex", "finance", "https://nobitex.ir/", "Nobitex", "نوبیتکس",
     "Crypto exchange", "بازار رمزارز",
     "#1E58C4", ["nobitex.ir"], CAMERA, "NORMAL",
     {"keywords": ["crypto", "bitcoin", "رمزارز", "بیت کوین"]}),
    ("easytrader", "finance", "https://easytrader.ir/", "EasyTrader", "ایزی‌تریدر",
     "Stock trading by Mofid", "معاملات بورس مفید",
     "#0B7285", ["easytrader.ir", "emofid.com"], NONE, "NORMAL",
     {"compatibility": "EXPERIMENTAL", "keywords": ["stock", "bourse", "بورس", "سهام", "مفید"]}),
    ("myirancell", "utilities", "https://my.irancell.ir/", "My Irancell", "ایرانسل من",
     "Plans, top-ups and bills", "بسته، شارژ و قبض",
     "#FFC300", ["irancell.ir"], NONE, "NORMAL",
     {"keywords": ["irancell", "sim", "charge", "بسته", "شارژ", "ایرانسل"]}),
    ("hamrahman", "utilities", "https://my.mci.ir/", "Hamrah-e Man", "همراه من",
     "MCI services and bills", "خدمات و قبض همراه اول",
     "#00A0E3", ["mci.ir"], NONE, "NORMAL",
     {"keywords": ["mci", "hamrah aval", "همراه اول", "شارژ", "قبض"]}),
    ("mygov", "government", "https://my.gov.ir/", "My Gov", "دولت من",
     "Government e-services", "خدمات الکترونیک دولت",
     "#2B8A3E", ["my.gov.ir"], NONE, "NORMAL",
     {"keywords": ["government", "دولت", "یارانه"]}),
    ("bale", "messaging", "https://web.bale.ai/", "Bale", "بله",
     "Messenger and banking", "پیام‌رسان و خدمات بانکی",
     "#00A693", ["bale.ai"], MEDIA, "NORMAL",
     {"compatibility": "EXPERIMENTAL", "keywords": ["chat", "messenger", "پیام", "بله"]}),
    ("eitaa", "messaging", "https://web.eitaa.com/", "Eitaa", "ایتا",
     "Messenger", "پیام‌رسان",
     "#F28C28", ["eitaa.com"], MEDIA, "NORMAL",
     {"keywords": ["chat", "messenger", "پیام"]}),
    ("rubika", "messaging", "https://web.rubika.ir/", "Rubika", "روبیکا",
     "Messenger and media", "پیام‌رسان و رسانه",
     "#7B2CBF", ["rubika.ir"], MEDIA, "NORMAL",
     {"keywords": ["chat", "messenger", "پیام"]}),
]

PAYMENT_DOMAINS = [
    "shaparak.ir", "sep.ir", "sadadpsp.ir", "pec.ir", "pep.co.ir", "asanpardakht.ir", "ap.ir",
    "irankish.com", "zarinpal.com", "payping.ir", "idpay.ir", "zibal.ir", "nextpay.org",
    "vandar.io", "jibit.ir", "bitpay.ir", "pay.ir", "digipay.ir", "mydigipay.com",
]

COMPARE_GROUPS = [
    ("ride-hailing", "Ride hailing", "تاکسی اینترنتی", ["snapp", "tapsi"]),
    ("food-delivery", "Food delivery", "سفارش غذا", ["snappfood", "tapsifood"]),
    ("maps", "Maps", "نقشه", ["balad", "neshan"]),
    ("travel", "Travel booking", "رزرو سفر", ["alibaba", "snapptrip", "jabama"]),
    ("streaming", "Streaming", "فیلم و سریال", ["filimo", "namava"]),
    ("shopping", "Shopping", "خرید", ["digikala", "torob", "basalam"]),
]


def service(entry, order):
    sid, cat, url, en, fa, en_desc, fa_desc, color, domains, perms, keep, extra = entry
    item = {
        "id": sid,
        "name": {"en": en, "fa": fa},
        "description": {"en": en_desc, "fa": fa_desc},
        "categoryId": cat,
        "url": url,
        "logo": f"logos/{sid}.png",
        "brandColor": color,
        "enabled": True,
        "order": order,
        "featured": False,
        "compatibility": "SUPPORTED",
        "web": {
            "allowedDomains": domains,
            "javascript": True,
            "domStorage": True,
            "permissions": perms,
            "fileUpload": True,
            "downloads": True,
            "popupPolicy": "NEW_TAB",
            "offDomainNavigation": "STAY_IN_TAB",
            "thirdPartyCookies": True,
            "cacheMode": "DEFAULT",
            "keepAlive": keep,
            "restoreLastUrl": True,
        },
    }
    item.update(extra)
    return item


def main():
    config = {
        "schemaVersion": 1,
        "configVersion": "2026-10-05.1",
        "refreshIntervalSeconds": 3600,
        "features": {
            "search": True,
            "favorites": True,
            "multiProfile": True,
            "compareMode": True,
            "downloads": True,
            "storageManager": True,
        },
        "web": {
            "paymentDomains": PAYMENT_DOMAINS,
            "externalSchemes": ["tel", "mailto", "sms", "smsto", "geo", "market", "bazaar", "myket", "intent", "tg", "whatsapp"],
        },
        "links": {
            "privacyPolicyUrl": "https://daricheh.example/privacy",
            "supportUrl": "https://daricheh.example/support",
        },
        "categories": [
            {
                "id": cid,
                "title": {"en": en, "fa": fa},
                "icon": f"icons/categories/{cid}.png",
                "color": color,
                "order": index + 1,
                "enabled": True,
            }
            for index, (cid, en, fa, color) in enumerate(CATEGORIES)
        ],
        "services": [service(entry, (index + 1) * 10) for index, entry in enumerate(SERVICES)],
        "compareGroups": [
            {"id": gid, "title": {"en": en, "fa": fa}, "serviceIds": ids}
            for gid, en, fa, ids in COMPARE_GROUPS
        ],
    }
    release = {
        # Applies to every build unless its store overrides a field below. Keep it at the
        # version that is live in every store; raise a store's minimum only once the release
        # is live in that store (docs/RELEASING.md in the app repository).
        "default": {
            "minimumSupportedVersion": 1,
            "latestVersion": 1,
            "forceUpdate": False,
            "message": {
                "en": "This version is no longer supported. Update to keep using your services.",
                "fa": "این نسخه دیگر پشتیبانی نمی‌شود. برای ادامه استفاده، برنامه را به‌روز کنید.",
            },
            "optionalMessage": {
                "en": "A new version with faster switching between services is ready.",
                "fa": "نسخه جدید با جابه‌جایی سریع‌تر بین سرویس‌ها آماده است.",
            },
        },
        # Per store (the app's build channel). updateUrl is the store page the app opens.
        "channels": {
            "bazaar": {
                "updateUrl": f"https://cafebazaar.ir/app/{STORE_PACKAGE}",
                "minimumSupportedVersion": 1,
                "latestVersion": 1,
            },
            "myket": {
                "updateUrl": f"https://myket.ir/app/{STORE_PACKAGE}",
                "minimumSupportedVersion": 1,
                "latestVersion": 1,
            },
        },
    }
    os.makedirs(DATA, exist_ok=True)
    for name, document in (("catalog.json", config), ("release.json", release)):
        with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
            json.dump(document, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"wrote data/catalog.json ({len(config['categories'])} categories, {len(config['services'])} services) and data/release.json")


if __name__ == "__main__":
    main()
