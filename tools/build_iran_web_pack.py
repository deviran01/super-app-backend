#!/usr/bin/env python3
"""Builds app/packs/iran-web.json: Iranian websites with no app of their own on Myket, for an
app mode of their own. The pack replaces the catalog while it's on (`exclusive`): the app
shows only these sites. See README.md → Packs.

Every site here passed three checks (evidence from tools/vet_iran_web.py, decisions in the
tables below):

  reachable  hosted in Iran: the addresses an Iranian resolver gives are on Iranian networks,
             so the site stays up on the national network when international internet is cut.
             Also left out: dead domains and expired certificates. Some government sites only
             answer Iranian resolvers or use intranet addresses: those were checked from the
             server in Iran.
  web only   no app of the site's own on Myket (MYKET_APPS lists the ones left out, with the
             package). Unofficial wrappers and readers by other developers don't count.
  lawful     nothing prohibited under Iranian law. Sites whose business is that never were
             candidates: film download sites (unlicensed films), VPN sellers, gambling,
             foreign Persian media. Copyright alone isn't a criterion: software download sites
             are in, by the owner's decision (P30Download, Downloadha and Download.ir also
             have film sections; Vala Music and UpMusics are music download sites).

Candidates are the catalog's services, the Iran-access pack's (tools/build_iran_access_pack.py)
and tools/iran_web_candidates.py. Ids get a "web-" prefix: the pack's entries are copies,
next to the originals in the same catalog. Logos are the originals' files.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_iran_access_pack as access  # noqa: E402
from iran_web_candidates import EXTRA_SERVICES  # noqa: E402

OUT = os.path.join(HERE, "..", "app", "packs", "iran-web.json")
CATALOG = os.path.join(HERE, "..", "data", "catalog.json")
LOGOS = os.path.join(HERE, "..", "public", "logos")
PREFIX = "web-"

PACK = {
    "id": "iran-web",
    "title": {"fa": "سایت‌های داخلی بدون اپلیکیشن", "en": "Iranian sites without an app"},
    "description": {
        "fa": "فقط سایت‌های ایرانی در دسترس روی شبکه ملی که اپلیکیشن خودشان را در مایکت ندارند: دانلود، خبر، دولت، دانشگاه و… . روشن که باشد، کاتالوگ فعلی پنهان می‌شود.",
        "en": "Only Iranian sites reachable on the national network that have no app of their own on Myket — downloads, news, government, universities and more. While it's on, the current catalog is hidden.",
    },
    "exclusive": True,
}

# The pack's categories, in order: id (without the prefix), en, fa, color, icon. Candidates'
# categories map onto these (CATEGORY_OF); a category without sites is left out.
CATEGORIES = [
    ("downloads", "Downloads", "دانلود نرم‌افزار", "#2B8A3E", "appstores"),
    ("news", "News", "اخبار", "#C92A2A", "news"),
    ("government", "Government", "خدمات دولتی", "#495057", "government"),
    ("universities", "Universities", "دانشگاه‌ها", "#364FC7", "universities"),
    ("education", "Learning & research", "آموزش و پژوهش", "#3B5BDB", "education"),
    ("finance", "Markets & prices", "بورس و قیمت‌ها", "#1098AD", "finance"),
    ("tools", "Tools", "ابزارهای کاربردی", "#E67700", "tools"),
    ("health", "Health", "سلامت", "#F03E3E", "health"),
    ("travel", "Travel", "سفر", "#1C7ED6", "travel"),
    ("transport", "Transport & maps", "حمل‌ونقل و نقشه", "#2F9E44", "transport"),
    ("shopping", "Shopping", "خرید", "#D6336C", "shopping"),
    ("cars", "Cars", "خودرو", "#F08C00", "cars"),
    ("classifieds", "Homes & classifieds", "ملک و نیازمندی‌ها", "#7048E8", "classifieds"),
    ("jobs", "Jobs", "کاریابی", "#5C940D", "jobs"),
    ("utilities", "Internet & bills", "اینترنت و قبوض", "#4C6EF5", "utilities"),
    ("insurance", "Insurance", "بیمه", "#0B7285", "insurance"),
    ("banks", "Banks & payments", "بانک و پرداخت", "#1864AB", "banks"),
    ("sports", "Sports", "ورزش", "#2F9E44", "sports"),
    ("tech", "Tech & games", "فناوری و بازی", "#495057", "tech"),
    ("lifestyle", "Lifestyle", "سبک زندگی", "#D6336C", "lifestyle"),
    ("music", "Music", "موسیقی", "#E64980", "music"),
    ("entertainment", "Entertainment", "سرگرمی", "#AE3EC9", "entertainment"),
    ("books", "Books", "کتاب", "#A0522D", "books"),
    ("cloud", "Blogs & uploads", "وبلاگ و آپلود", "#1971C2", "cloud"),
]

# A candidate's category (catalog or Iran-access) → the pack's, where they differ.
CATEGORY_OF = {"appstores": "downloads", "payments": "banks", "maps": "transport", "search": "tools",
               "home-services": "classifieds", "messaging": "tools", "food": "shopping"}

# Left out: the site's own app is on Myket (package as found there; checked 2026-10-11).
MYKET_APPS = {
    # The catalog's own services: most have one.
    "snapp": "cab.snapp.passenger", "tapsi": "taxi.tap30.passenger", "snappbox": "com.snapp_box.android",
    "snappfood": "com.zoodfood.android", "tapsifood": "com.tapsi.tapsifood", "digikala": "com.digikala",
    "torob": "ir.torob", "basalam": "ir.basalam.app", "technolife": "com.technolife", "banimode": "com.banimode.www.twa",
    "sheypoor": "com.sheypoor.mobile", "kilid": "com.kilid.portal", "alibaba": "ir.alibaba",
    "snapptrip": "com.pintapin.pintapin", "jabama": "com.jabamaguest", "mrbilit": "com.mrbilit.app",
    "flytoday": "ir.flytoday", "otaghak": "ir.otaghak.app", "balad": "ir.balad",
    "neshan": "org.rajman.neshan.traffic.tehran.navigator", "filimo": "com.aparat.filimo",
    "namava": "com.shatelland.namava.mobile", "aparat": "com.aparat", "filmnet": "ir.filmnet.android",
    "cinematicket": "com.hampardaz.cinematicket", "navaar": "ir.navaar.android", "taaghche": "ir.mservices.mybook",
    "faradars": "org.faradars.cafebazaar", "jobvision": "com.jobvision.app", "paziresh24": "com.paziresh24.paziresh24",
    "doctoreto": "ir.hivatec.doctoreto", "snappdoctor": "doctor.snapp.app", "bimebazar": "com.bimebazar.bimebazar",
    "azki": "com.nar.bimito", "bimeh": "com.bimeh.pwa.twa", "nobitex": "market.nobitex",
    "easytrader": "ir.easytrader.orbis.m.twa", "milli": "gold.milli.app", "myirancell": "com.myirancell",
    "hamrahman": "ir.mci.ecareapp", "mygov": "ir.gov.mygov", "bale": "ir.nasim", "eitaa": "ir.eitaa.messenger",
    "rubika": "app.rbmain.a", "bama": "com.bama.consumer", "karnameh": "com.karnameh", "khodro45": "com.khodro45.c2c",
    "hamrahmechanic": "com.hamrah_mechanic.hamrah_mechanic",
    # The Iran-access pack's.
    "irna": "com.irna.newsapp", "farsnews": "ir.farsnews.app", "yjc": "ir.iransamaneh.yjc",
    "khabaronline": "com.khabar_online.rss_app", "bartarinha": "co.sharang.bartarinha",
    "akharinkhabar": "com.khorasannews.latestnews",
    # Every commercial bank has a mobile bank (the Central Bank, a regulator, doesn't).
    "bmi": "ir.bmi.bam.nativeweb", "banksepah": "com.tosan.dara.sepah", "bankmellat": "com.pmb.mobile",
    "tejaratbank": "ir.tejaratbank.tata.mobile.android.tejarat", "bsi": "com.isc.bsinew",
    "bki": "com.gostaresh.mobilebank.boilerplate", "bankmaskan": "com.maskanmobilebank", "postbank": "com.tosan.dara.postbank",
    "refahbank": "com.refahbank.dpi.android", "bim": "com.tosan.dara.bim", "edbi": "com.isc.tosenew",
    "ttbank": "mob.banking.android.taavon", "sb24": "com.tosan.mobile.otpapp.saman", "bpi": "mob.banking.android.pasargad",
    "parsianbank": "com.parsmobapp", "enbank": "com.farazpardazan.enbank", "karafarinbank": "ir.karafarinbank.digital.mb",
    "sinabank": "com.tosan.dara.sina", "sbank": "com.tosan.dara.sarmayeh", "shahrbank": "co.redbank.app",
    "bankday": "com.tosan.dara.day", "middleeastbank": "ir.middleeastbank.www.meb_bank", "izbank": "ir.izbank.omnichannel",
    "tourismbank": "mob.banking.android.gardesh", "rqbank": "mob.banking.android.resalat", "qmb": "com.ada.mbank.mehr",
    "melalbank": "com.melal", "blubank": "com.samanpr.blu", "wepod": "com.dotin.wepod", "bankino": "digital.neobank",
    "ap": "com.sibche.aspardproject.app", "hafhashtad": "ir.hafhashtad.android780", "ewano": "com.ebcom.ewano",
    "setareyek": "setare_app.ymz.yma.setareyek", "digipay": "com.mydigipay.app.android", "tomanpay": "org.qbitpay",
    "tara": "com.tara360.tara.production", "wallex": "ir.wallex.app", "bitpin": "io.bitpin.app",
    "ramzinex": "com.ramzinex.app", "tabdeal": "com.tabdeal", "abantether": "ir.aban.th", "talasea": "com.novin.talasea",
    "sahamyab": "ir.sahamyab", "tamin": "com.tamin.taminhamrah",
    # Police Man (NAJA's) covers the police's e-services.
    "policeman": "com.nrdc.android.pyh", "epolice": "com.nrdc.android.pyh",
    "shamim": "ir.sfara.fara", "mytehran": "com.mytehran", "rightel": "ir.rightel.myrightel", "tci": "ir.mytci",
    "shatel": "com.Shatel.myshatel", "mobinnet": "ir.mobinnet.my", "asiatech": "com.asiatech.android",
    "hiweb": "ir.hiweb.app.my", "bargheman": "com.pdpsoft.android.saapa", "alopeyk": "com.alopeyk.customer",
    "maxim": "com.taxsee.taxsee", "tipax": "ir.tipax.mytipax", "safarmarket": "com.safarmarket.app",
    "sepehr360": "ir.sepehr360.app", "ghasedak24": "com.ghasedk24.ghasedak24train", "eghamat24": "app.eghamat24.com",
    "shab": "travel.shab", "snappmarket": "com.snappmarket", "okala": "com.okala", "digikalajet": "com.digikala.firebolt",
    "emalls": "ir.emalls.app", "modiseh": "com.golestanec.modiseh.bazarapp", "khanoumi": "com.khanoumi.app",
    "telewebion": "net.telewebion", "anten": "com.farakav.anten", "sepehrtv": "ir.IRIB.jk.MediaIRIB",
    "digitoon": "com.yaramobile.digitoon", "shad": "ir.medu.shad", "gaj": "ir.gajino.myket",
    "daneshjooyar": "ir.daneshjoyar.app", "drdr": "app.drdr.android", "axon": "me.axon.phr.twa",
    "danainsurance": "ir.insurance.dana.android", "alborzinsurance": "alborz.insurance.app",
    "parsianinsurance": "com.asanapps.parsian412810", "eestekhdam": "com.e_estekhdam.android.app",
    "iranestekhdam": "com.iranestekhdam.iranestekhdam", "igap": "net.iGap", "splus": "mobi.mmdt.ottplus",
    "zarebin": "com.zarebin.browser", "gerdoo": "me.gerdoo.browser_plus", "myket": "ir.mservices.market",
    "timeir": "co.radcom.time", "abrehamrahi": "ir.sharif.drive", "varzesh3": "com.farakav.varzesh3",
    "footballi": "com.piccolo.footballi.server", "achareh": "com.sanags.a4f3client", "sanjagh": "pro.sanjagh.client",
    # tools/iran_web_candidates.py's.
    "musicdel": "ir.musicdel.app", "khabarban": "khabarban.app", "arzdigital": "com.arzdigitalnew",
    "nigc": "qabzegas.newbilling.nigc.ir", "tavanir": "com.pdpsoft.android.saapa", "kermanmotor": "com.kmc.b2c_khodro_new_version",
    "mvm": "ir.mvmco", "kojaro": "hsp.kojaro", "karboom": "ir.karbom.app", "sabanet": "ir.sabanet.mysabanet",
    "parsonline": "com.parsonline.app.my", "niniban": "com.bartarinha.niniban",
}

# Left out: not reachable on the national network (checked 2026-10-11, from Iran too).
NOT_REACHABLE = {
    "tasnim": "hosted abroad (DIGITURUNC, TR)", "ghabzino": "hosted abroad (WORLDSTREAM, NL)",
    "tgju": "hosted abroad (Cloudflare)", "lastsecond": "hosted abroad (NL)", "payaneh": "hosted abroad (BITCOMMAND, AM)",
    "magiran": "hosted abroad (Cloudflare)", "vajehyab": "hosted abroad (Cloudflare)", "ganjoor": "hosted abroad (BITCOMMAND, AM)",
    "shahrsakhtafzar": "hosted abroad (GREENHOST, DK)", "beytoote": "hosted abroad (Hetzner, DE)",
    "virgool": "hosted abroad (Cloudflare)", "blogfa": "hosted abroad (Cloudflare)", "musicfa": "hosted abroad (Hetzner, DE)",
    "nex1music": "hosted abroad (Cloudflare)", "alanchand": "hosted abroad (Cloudflare)", "taghvim": "hosted abroad (Cloudflare)",
    "mobileir": "hosted abroad (OVH, FR)", "caspian": "hosted abroad (RU)", "hidoctor": "hosted abroad (Hetzner, DE)",
    "sakhtafzarmag": "hosted abroad (OVH, FR)", "itresan": "hosted abroad (Cloudflare)", "barnamenevis": "hosted abroad (Hetzner, DE)",
    "persiantools": "hosted abroad (CA)", "majidonline": "hosted abroad (Hetzner, DE)", "seemorgh": "hosted abroad (Hetzner, DE)",
    # An intranet address works on the national network (medu.gov.ir does, from the server in
    # Iran); this one didn't answer from there either.
    "ircfda": "an intranet address that didn't answer from Iran",
    "targoman": "the domain doesn't resolve", "faraazin": "the domain doesn't resolve",
    "blogir": "the domain doesn't resolve", "saleauto": "the domain doesn't resolve", "zagros": "the domain doesn't resolve",
    "bazinama": "the domain doesn't resolve", "akairan": "the domain doesn't resolve",
    "khorasannews": "its HTTPS certificate has expired (the app refuses it)",
    "ffiri": "its HTTPS certificate has expired (the app refuses it)",
}

# Left out for other reasons.
OTHER = {
    "mihandownload": "mostly film and series downloads now (see the docstring)",
    "ba24": "Ayandeh Bank no longer operates on its own: its customers moved to Bank Melli",
    "cafebazaar": "another Android store, in a version meant not to duplicate Myket",
    "sibapp": "an iPhone app store: no use on Android", "iapps": "an iPhone app store: no use on Android",
    "anardoni": "an iPhone app store: no use on Android", "sibche": "an iPhone app store: no use on Android",
}

# Fixes to a candidate's texts for this pack: id → {field: value}.
OVERRIDES = {}

# Members are candidate ids (without the prefix): a group shows while two of its sites are in.
COMPARE_GROUPS = [
    ("software-downloads", "Software downloads", "دانلود نرم‌افزار",
     ["soft98", "p30download", "downloadha", "yasdl", "sarzamindownload", "downloadir", "mihandownload", "downloadly"]),
    ("headlines", "Headlines", "تیتر اخبار", ["shahrekhabar", "akharinkhabar", "khabarban", "ghatreh"]),
    ("dictionaries", "Dictionaries", "دیکشنری", ["abadis", "vajehyab", "fastdic"]),
    ("stock-market", "Stock market data", "اطلاعات بورس", ["tsetmc", "rahavard365", "fipiran", "codal"]),
    ("courses", "Online courses", "آموزش آنلاین", ["maktabkhooneh", "sevenlearn", "roocket", "mongard", "codeyad", "toplearn", "sabzlearn"]),
    ("job-boards", "Job listings", "آگهی استخدام", ["jobinja", "irantalent"]),
    ("freelancing", "Freelancing", "دورکاری و فریلنس", ["ponisha", "karlancer", "parscoders"]),
    ("ebooks", "E-books", "کتاب الکترونیک", ["fidibo", "ketabrah"]),
    ("bookstores", "Bookstores", "کتاب‌فروشی", ["iranketab", "sibook", "shahreketab"]),
    ("isps", "Home internet", "اینترنت خانگی", ["pishgaman", "respina", "afranet"]),
    ("game-news", "Game news", "اخبار بازی", ["zoomg", "vigiato", "gamefa", "bazinama"]),
    ("tech-news", "Tech news", "اخبار فناوری", ["zoomit", "digiato", "techrato", "itresan"]),
    ("airlines", "Airlines", "هواپیمایی", ["iranair", "mahan", "iaa", "qeshmair", "kishair", "caspian", "zagros", "iranairtour"]),
    ("music-downloads", "Music downloads", "دانلود موسیقی", ["vmusic", "musicfa", "nex1music", "musicdel", "upmusics"]),
    ("blogs", "Blogs", "وبلاگ", ["blogfa", "blogir", "mihanblog", "blogsky", "parsiblog", "virgool"]),
]


# Main colors of the logos the Iran-access pack has none for (tools/build_iran_access_pack.py
# BRAND_COLORS has the rest): behind the logo while it loads.
BRAND_COLORS = {
    "alef": "#040404", "alldigitall": "#DC0C1C", "asiainsurance": "#3C3C3C", "asriran": "#949494",
    "bimehma": "#E4746C", "birjand": "#344C94", "blogsky": "#2C5494", "chmail": "#1464C4",
    "codal": "#0484C4", "codeyad": "#2C6CBC", "cra195": "#2C54AC", "darmankade": "#5CC4F4",
    "delgarm": "#3464D4", "didbaniran": "#3C2454", "downloadir": "#04D48C",
    "eghtesadonline": "#D41C24", "esam": "#2CDC04", "fadak": "#D4B444", "farabi": "#343464",
    "fardanews": "#FC0404", "farsroid": "#4CBC24", "fids": "#6CA414", "gamefa": "#EC244C",
    "gisoom": "#3C8C34", "haftesobh": "#2C54FC", "hamrahacademy": "#14140C", "ihio": "#043464",
    "irangov": "#1C0C54", "iranjib": "#347CF4", "irantvto": "#044C9C", "iut": "#040404",
    "jamaran": "#0474BC", "lu": "#CCCC04", "medu": "#040404", "mehrabad": "#244454",
    "mehrnews": "#BC0404", "melkana": "#3C3C3C", "miare": "#8C2CAC", "mojnews": "#0C64AC",
    "mongard": "#CCFC04", "mui": "#E4E4EC", "namatek": "#048C64", "nobat": "#04B4CC",
    "noormags": "#DC643C", "nournews": "#0C7474", "p30download": "#1C3C7C", "pana": "#3C3C5C",
    "pedal": "#FC8C04", "qeshmair": "#FC0404", "raja": "#FCC404", "sabteahval": "#DCDCDC",
    "sahamedalat": "#1C346C", "sbu": "#3C648C", "setare": "#740454", "sevenlearn": "#1C94F4",
    "shahed": "#CC241C", "sibook": "#04BCD4", "sid": "#ACACAC", "snappshop": "#B404AC",
    "soft98": "#447494", "techrato": "#44C404", "tehrantimes": "#FC0404", "tejaratnews": "#E40414",
    "theater": "#D4D4D4", "upmusics": "#143C4C", "urmia": "#040C5C", "ut": "#0494FC",
    "vigiato": "#E40424", "yasdl": "#040404", "zoomg": "#EC2C5C", "zoomit": "#E40C2C",
}


def candidates():
    """(id, row or catalog service): every candidate, in the order the pack lists them."""
    catalog = json.load(open(CATALOG, encoding="utf-8"))
    rows = [(s["id"], s) for s in catalog["services"] if "pack" not in s]
    return rows + [(e[0], e) for e in access.SERVICES] + [(e[0], e) for e in EXTRA_SERVICES]


def category_of(original):
    return CATEGORY_OF.get(original, original)


def from_row(row, colors):
    sid, cat, url, fa, en, fa_desc, en_desc, opts = row
    cat = category_of(cat)
    host = url.split("/")[2]
    keywords = list(dict.fromkeys(opts.get("kw", []) + access.CATEGORY_KEYWORDS.get(cat, [])))[:30]
    return {
        "id": PREFIX + sid,
        "name": {"fa": fa, "en": en},
        "description": {"fa": fa_desc, "en": en_desc},
        "categoryId": PREFIX + cat,
        "url": url,
        **({"logo": f"logos/{sid}.png"} if os.path.exists(os.path.join(LOGOS, f"{sid}.png")) else {}),
        "brandColor": access.BRAND_COLORS.get(sid) or BRAND_COLORS.get(sid) or colors[cat],
        "enabled": True,
        "featured": False,
        "compatibility": "SUPPORTED",
        "keywords": keywords,
        "web": {
            "allowedDomains": opts.get("domains") or [access.registrable(host)],
            "javascript": True,
            "domStorage": True,
            "permissions": opts.get("perms", access.NONE),
            "fileUpload": True,
            "downloads": True,
            "popupPolicy": "NEW_TAB",
            "offDomainNavigation": "STAY_IN_TAB",
            "externalDomains": [],
            "externalSchemes": [],
            "thirdPartyCookies": True,
            "cacheMode": "DEFAULT",
            "keepAlive": opts.get("keep", access.KEEP_ALIVE.get(cat, "NORMAL")),
            "restoreLastUrl": True,
        },
    }


def from_catalog(service):
    """A copy of one of the catalog's own services."""
    copy = json.loads(json.dumps(service))
    copy.update(id=PREFIX + service["id"], categoryId=PREFIX + category_of(service["categoryId"]), featured=False)
    copy.pop("order", None)
    return copy


def build():
    colors = {cid: color for cid, _, _, color, _ in CATEGORIES}
    left_out = set(MYKET_APPS) | set(NOT_REACHABLE) | set(OTHER)
    services = []
    for sid, source in candidates():
        if sid in left_out:
            continue
        service = from_catalog(source) if isinstance(source, dict) else from_row(source, colors)
        for field, value in OVERRIDES.get(sid, {}).items():
            service[field] = value
        services.append(service)
    used = {s["categoryId"] for s in services}
    categories = [
        {"id": PREFIX + cid, "title": {"fa": fa, "en": en}, "icon": f"icons/categories/{icon}.png",
         "color": color, "enabled": True}
        for cid, en, fa, color, icon in CATEGORIES if PREFIX + cid in used
    ]
    unknown = used - {c["id"] for c in categories}
    assert not unknown, f"categories missing from CATEGORIES: {sorted(unknown)}"
    # Grouped by category, in the categories' order; the candidates' order within each.
    rank = {c["id"]: i for i, c in enumerate(categories)}
    services.sort(key=lambda s: rank[s["categoryId"]])
    for index, category in enumerate(categories):
        category["order"] = 1000 + index
    for index, service in enumerate(services, 1):
        service["order"] = index * 10
        service["pack"] = PACK["id"]
    for category in categories:
        category["pack"] = PACK["id"]
    included = {s["id"] for s in services}
    groups = []
    for gid, en, fa, members in COMPARE_GROUPS:
        members = [PREFIX + m for m in members if PREFIX + m in included]
        if len(members) >= 2:
            groups.append({"id": PREFIX + gid, "title": {"fa": fa, "en": en}, "serviceIds": members, "pack": PACK["id"]})
    return {**PACK, "categories": categories, "services": services, "compareGroups": groups}


def main():
    pack = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote app/packs/{PACK['id']}.json ({len(pack['categories'])} categories, {len(pack['services'])} services, "
          f"{len(pack['compareGroups'])} compare groups)")


if __name__ == "__main__":
    main()
